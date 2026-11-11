import { guard } from "@/lib/ratelimit/http";
import { fail, trialJson, validId } from "@/lib/trial/http";
import { editKeyParam } from "@/lib/trial/edit-key";
import { editsView } from "@/lib/trial/repo-plan-status";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Черновики правок тура агента (план trial-confirm-plan-01, п. 2; T-20261111-16): `?k=` — ключ правки из ссылки агента. Страница рисует
// черновики поверх плана с пометкой «не подтверждено» — они переживают перезагрузку; `roomsOk` — галочки «размеры верны», `confirmedAt` —
// последнее подтверждение. 403 — нет права, 404 — нет задания, 410 — срок вышел. Кэшам — no-store. Ручка из списка песочницы тура.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const k = editKeyParam(req);
  if (k === null) return fail(403, "forbidden");
  const r = await editsView(id, k);
  return r.ok ? trialJson(r) : fail(r.status, r.error);
}
