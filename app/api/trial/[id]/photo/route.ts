import { z } from "zod";
import { trialPhotoIn, trialRenderIn, type TrialPhotoIn, type TrialRenderIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { clientIp, guard } from "@/lib/ratelimit/http";
import type { PhotoSource } from "@/contracts/trial-photos";
import { agentOnly, requestGate } from "@/lib/trial/buyer-gate";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askPhoto } from "@/lib/trial/repo-photo";
import { askRender } from "@/lib/trial/repo-render";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// «Сделать реалистичнее» из тура пробы (T-20261109-34): заказ страницы (`payload()` + два кадра `views`) → сервис кадров. 200 `{job}` —
// номер задания, его опрашивает страница (`/api/job?id=`, как в `/demo`); 403 `photo_not_allowed` — комнате нет доверия к размерам,
// 409 `stale` / `not_ready`, 410 — срок вышел, 429 `photo_limit` — суточный предел задания; отказ сервиса кадров — его код и текст.
// Пропускает песочница тура (`lib/trial/tour-page.ts`) вместе с загрузкой кадров и опросом задания.
// Кто заказал — в строку фото (T-20261112-115): `?k=` ключ агента совпал — агент; Bearer воркера — `auto`; иначе покупатель. Право на
// заказ от этого не меняется (решают комната и предел).
async function sourceOf(req: Request, id: string): Promise<PhotoSource> {
  const gate = requestGate(req);
  if (await agentOnly(gate, id)) return "agent";
  return gate.creds.worker ? "auto" : "buyer";
}
// РЕНДЕР «Сделать фото» (T-20261117-19/1): тело с `mode: "render"` — снимок расстановки (`trialRenderIn`), бесплатный рендер Blender без брони и квоты
// фото нейросети; 200 `{ok, job, kind: "render", eta, eta_range, queue, scene_hash, key, cached}` — ход опрашивает страница тем же `/api/job?id=`,
// отказ — код, `error`/`error_en` и `Retry-After`. Тело без `mode` — заказ фото нейросети, как было (в том числе «Улучшить» с `render_key`).
const photoOrRender = z.union([trialRenderIn, trialPhotoIn]);
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, photoOrRender, 256 * 1024);
  if (body instanceof Response) return body;
  const ip = clientIp(req.headers);
  if ((body as { mode?: unknown }).mode === "render") {
    const rr = await askRender(id, body as TrialRenderIn, ip === "local" ? "" : ip);
    if (rr.ok) return trialJson({ ok: true, ...rr.body });
    return trialJson({ ok: false, error: rr.message ?? rr.error, error_en: rr.messageEn, code: rr.error, ...(rr.retryAfter ? { retry_after: rr.retryAfter } : {}) },
      rr.status, rr.retryAfter ? { "Retry-After": String(rr.retryAfter) } : {});
  }
  const r = await askPhoto(id, body as TrialPhotoIn, ip === "local" ? "" : ip, undefined, undefined, undefined, await sourceOf(req, id));
  if (!r.ok) return trialJson({ ok: false, error: r.message ?? r.error, code: r.error }, r.status);
  return trialJson({ ok: true, job: r.job });
}
