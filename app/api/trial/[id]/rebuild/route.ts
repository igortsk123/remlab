import { trialRebuildIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askRebuild } from "@/lib/trial/repo-rebuild";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// «Обустроить» / «Обустроить всё» из тура пробы (план agent-trial-08, Р1): ключ правки агента `k` (из его ссылки), `request_id` — повтор
// нажатия возвращает ту же пересборку, `base_version` — версия данных на странице, `rooms` — комнаты или "all". 202 — поставлена (или та же),
// 403 — нет права, 409 — `not_ready` / `stale` (+ текущая версия) / `busy` / `nothing_to_furnish`, 422 — `bad_rooms`, 429 — лимит в сутки.
// Ключ в ответ не возвращается. Единственная ручка `/api/*`, которую пропускает песочница тура (`lib/trial/tour-page.ts`).
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialRebuildIn, 4096);
  if (body instanceof Response) return body;
  const r = await askRebuild(id, body);
  if (!r.ok) return trialJson({ ok: false, error: r.error, ...(r.version !== undefined ? { version: r.version } : {}) }, r.status);
  return trialJson({ ok: true, repeated: r.repeated, rebuild: r.rebuild }, 202);
}
