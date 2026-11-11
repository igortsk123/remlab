import { guard } from "@/lib/ratelimit/http";
import { fail, trialJson, validId } from "@/lib/trial/http";
import { editKeyParam } from "@/lib/trial/edit-key";
import { rebuildStatus } from "@/lib/trial/repo-plan-status";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Ход пересборки тура для страницы агента (план trial-confirm-plan-01, п. 4; T-20261111-16), лёгкий опрос: `?k=` — ключ правки. Последняя
// пересборка задания: статус, комнаты «в очереди / считаем / готово», «N из M», оценка времени (`etaS`, `roomEtaS`) и сколько прошло
// (`elapsedS`) — обратный отсчёт страница ведёт сама. 403 — нет права, 404 — нет задания, 410 — срок вышел. Ручка из списка песочницы тура.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const k = editKeyParam(req);
  if (k === null) return fail(403, "forbidden");
  const r = await rebuildStatus(id, k);
  return r.ok ? trialJson(r) : fail(r.status, r.error);
}
