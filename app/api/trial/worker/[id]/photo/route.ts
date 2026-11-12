import { PHOTO_MAX_BYTES, PHOTO_SHOTS_MAX, PHOTO_THUMB_MAX_BYTES, trialPhotoDoneIn } from "@/contracts/trial-photos";
import { safeEqual } from "@/lib/safe-equal";
import { workerAuth, workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { finishPhoto } from "@/lib/trial/repo-photo-done";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Готовое фото тура (T-20261112-115 Ф1): сервис кадров по готовности заказа (`tools/scout/draft_trial.py:report`, сеть remlab-net,
// внутренний ключ `x-internal-token` = INTERNAL_API_TOKEN — как заявка «отправить себе») или воркер DEV (Bearer). Тело — номер задания
// сервиса кадров и кадры (JPEG/PNG/WEBP по первым байтам) либо `failed` с кодом. Файлы — в папку тура, строка → done только после
// проверки файлов (`repo-photo-done.ts`). Повтор безвреден. Нет строки с таким номером — 404 (сервис кадров повторит позже).
const BODY_MAX = Math.ceil(((PHOTO_MAX_BYTES + PHOTO_THUMB_MAX_BYTES) * 4) / 3) * PHOTO_SHOTS_MAX + 16 * 1024;

function internalOk(req: Request): boolean {
  const token = process.env.INTERNAL_API_TOKEN;
  return Boolean(token) && safeEqual(req.headers.get("x-internal-token") ?? "", token!);
}

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (!internalOk(req) && workerAuth(req.headers) !== "ok") {
    const denied = workerGuard(req);
    if (denied) return denied;
  }
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialPhotoDoneIn, BODY_MAX);
  if (body instanceof Response) return body;
  const r = await finishPhoto(id, body);
  if (!r.ok) return fail(r.status, r.error);
  return trialJson({ ok: true, status: r.status, repeated: r.repeated });
}
