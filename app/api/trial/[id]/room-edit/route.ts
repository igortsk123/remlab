import { trialRoomEditIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askRoomEdit } from "@/lib/trial/repo-room-edit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Правка комнаты в туре пробы (план trial-room-edit-01, Е3; T-20261110-36): агент со своей ссылкой (`k`) меняет название и/или габариты
// комнаты на плане тура → воркер пересобирает её 3D и мебель сам (`kind: edit`). 202 — принято (или тот же `request_id`, или правка
// поехала с ещё не взятой пересборкой правок), 200 `unchanged` — ничего не изменилось (порог 10 см), 403 — нет права, 409 — `not_ready` /
// `stale` (страница устарела — перечитать) / `busy` (идёт другая пересборка), 422 — нет такой комнаты, 429 — лимит правок в сутки.
// Ручка `/api/*`, которую пропускает песочница тура (`lib/trial/tour-page.ts:roomEditPath`).
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialRoomEditIn, 4 * 1024);
  if (body instanceof Response) return body;
  const r = await askRoomEdit(id, body);
  if (!r.ok) return trialJson({ ok: false, error: r.error, ...(r.version !== undefined ? { version: r.version } : {}) }, r.status);
  return trialJson({ ok: true, repeated: r.repeated, unchanged: r.unchanged, edit: r.edit }, r.unchanged ? 200 : 202);
}
