import { trialConfirmIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askConfirm } from "@/lib/trial/repo-confirm";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// «Подтвердить планировку» (план trial-confirm-plan-01; T-20261111-16): агент со своей ссылкой (`k`) подтверждает все черновики правок
// комнат, окон и дверей и галочки «размеры верны» (`rooms_ok`) → ОДНА пересборка `edit` (и без черновиков). 202 — поставлена (повтор того же
// `request_id` — тот же ответ, `repeated`), 403 — нет права, 409 — `not_ready` / `stale` (+ текущая версия) / `busy` (идёт пересборка),
// 422 — `bad_rooms` (галочка у комнаты не этой версии), 429 — `edit_limit`. Ход — `GET rebuild-status`. Ручка из списка песочницы тура.
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialConfirmIn, 4 * 1024);
  if (body instanceof Response) return body;
  const r = await askConfirm(id, body);
  if (!r.ok) return trialJson({ ok: false, error: r.error, ...(r.version !== undefined ? { version: r.version } : {}) }, r.status);
  return trialJson({ ok: true, repeated: r.repeated, rebuild: r.rebuild, confirmed: r.confirmed }, 202);
}
