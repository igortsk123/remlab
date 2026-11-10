import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { randomToken } from "@/lib/token";
import { trialDir } from "@/lib/trial/config";
import { newEditKey } from "@/lib/trial/edit-key";
import { fail, trialJson } from "@/lib/trial/http";
import { isOwnMachine } from "@/lib/trial/own-key";
import { admissionPrecheck, commitUpload, type Admission } from "@/lib/trial/repo-create";
import { receiveUpload } from "@/lib/trial/upload";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const REFUSE: Record<Exclude<Admission, "ok">, () => Response> = {
  busy: () => fail(503, "busy", { "Retry-After": "120" }),
  daily_cap: () => fail(429, "daily_cap", { "Retry-After": "3600" }),
};

// Загрузка плана для пробы (план agent-trial-01, T-A): multipart `file` (JPEG/PNG/WebP/PDF ≤ 15 МБ), `listing` (текст
// объявления ≤ 5000), `consent=yes`. Email НЕ принимаем до T9 (минимизация ПДн). Лимит частоты и заполненность очереди —
// ДО чтения тела; тело — потоком на диск (`lib/trial/upload.ts`); окончательный допуск — под замком при записи.
// Наши машины (верный `x-trial-own-key`, `lib/trial/own-key.ts`) не упираются ни в лимит адреса, ни в суточный потолок сайта.
export async function POST(req: Request): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const own = isOwnMachine(req.headers);
  const limited = own ? null : await guard(req, "trialUpload");
  if (limited) return limited;
  const pre = await admissionPrecheck(process.env, own);
  if (pre !== "ok") return REFUSE[pre]();
  const id = randomToken();
  const dir = trialDir();
  const up = await receiveUpload(req, dir, id);
  if (!up.ok) return fail(up.status, up.error);
  const edit = newEditKey();
  let verdict: Admission;
  try {
    verdict = await commitUpload(up, id, dir, process.env, edit.hash, own);
  } catch {
    return fail(500, "internal");
  }
  if (verdict !== "ok") return REFUSE[verdict]();
  // ключ правки — ЕДИНСТВЕННЫЙ раз наружу: в ответе загрузки и в ссылке агента (`?k=`); дальше его знает только ссылка
  return trialJson({ ok: true, id, url: `/try/${id}?k=${edit.key}`, editKey: edit.key }, 201);
}
