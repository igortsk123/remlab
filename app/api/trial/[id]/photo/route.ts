import { trialPhotoIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { clientIp, guard } from "@/lib/ratelimit/http";
import type { PhotoSource } from "@/contracts/trial-photos";
import { agentOnly, requestGate } from "@/lib/trial/buyer-gate";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askPhoto } from "@/lib/trial/repo-photo";

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
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialPhotoIn, 256 * 1024);
  if (body instanceof Response) return body;
  const ip = clientIp(req.headers);
  const r = await askPhoto(id, body, ip === "local" ? "" : ip, undefined, undefined, undefined, await sourceOf(req, id));
  if (!r.ok) return trialJson({ ok: false, error: r.message ?? r.error, code: r.error }, r.status);
  return trialJson({ ok: true, job: r.job });
}
