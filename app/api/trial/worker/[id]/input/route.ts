import { Readable } from "node:stream";
import { workerGuard } from "@/lib/trial/auth";
import { TRIAL_HEADERS, trialDir } from "@/lib/trial/config";
import { fail, validId } from "@/lib/trial/http";
import { leasedInput } from "@/lib/trial/repo-worker";
import { openInput } from "@/lib/trial/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Исходный файл задания — ТОЛЬКО воркеру с текущей арендой (заголовки X-Trial-Attempt, X-Trial-Lease; в адрес токен не
// кладём — адреса пишет журнал Caddy). Наружу файлы не отдаются никогда. 409 — аренды нет; 410 — файл удалён по сроку.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const attempt = Number(req.headers.get("x-trial-attempt"));
  const leaseToken = req.headers.get("x-trial-lease") ?? "";
  if (!validId(id) || !Number.isInteger(attempt) || attempt < 1 || !leaseToken) return fail(400, "bad_request");
  const row = await leasedInput({ id, attempt, leaseToken });
  if (!row) return fail(409, "lease_lost");
  if (!row.name) return fail(410, "input_deleted");
  const f = await openInput(trialDir(), row.name);
  if (!f) return fail(410, "input_missing");
  const body = Readable.toWeb(f.handle.createReadStream()) as unknown as ReadableStream<Uint8Array>;
  return new Response(body, {
    headers: { ...TRIAL_HEADERS, "Content-Type": row.mime, "Content-Length": String(f.size), "X-Content-Type-Options": "nosniff" },
  });
}
