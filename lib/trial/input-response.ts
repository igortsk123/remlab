// Отдача исходного листа воркеру по аренде (задания или пересборки по тексту агента): аренда — в заголовках X-Trial-Attempt и
// X-Trial-Lease (в адрес токен не кладём — адреса пишет журнал Caddy). Наружу файлы не отдаются никогда.
// 400 — кривые заголовки; 409 — аренды нет; 410 — файл удалён по сроку или пропал с диска.

import { Readable } from "node:stream";
import { workerGuard } from "@/lib/trial/auth";
import { TRIAL_HEADERS, trialDir } from "@/lib/trial/config";
import { fail, validId } from "@/lib/trial/http";
import { openInput } from "@/lib/trial/storage";

type Lease = { id: string; attempt: number; leaseToken: string };
type Lookup = (f: Lease) => Promise<{ name: string | null; mime: string } | undefined>;

export async function leasedInputResponse(req: Request, id: string, lookup: Lookup): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const attempt = Number(req.headers.get("x-trial-attempt"));
  const leaseToken = req.headers.get("x-trial-lease") ?? "";
  if (!validId(id) || !Number.isInteger(attempt) || attempt < 1 || !leaseToken) return fail(400, "bad_request");
  const row = await lookup({ id, attempt, leaseToken });
  if (!row) return fail(409, "lease_lost");
  if (!row.name) return fail(410, "input_deleted");
  const f = await openInput(trialDir(), row.name);
  if (!f) return fail(410, "input_missing");
  const body = Readable.toWeb(f.handle.createReadStream()) as unknown as ReadableStream<Uint8Array>;
  return new Response(body, {
    headers: { ...TRIAL_HEADERS, "Content-Type": row.mime, "Content-Length": String(f.size), "X-Content-Type-Options": "nosniff" },
  });
}
