import { trialOpeningEditIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askOpeningEdit } from "@/lib/trial/repo-opening-edit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Окна и двери агента на плане тура пробы (план trial-room-edit-01, Е4; T-20261110-39): агент со своей ссылкой (`k`) ставит, двигает,
// растягивает или снимает проёмы одной панели плана → воркер пересобирает 3D и мебель комнат по обе стороны задетых стен сам
// (`kind: edit`, та же очередь и лимит, что у правки комнаты). Ответы — как у `room-edit`; 422 `bad_opening` — нет такого проёма или
// центр вне плана, `too_many` — правок проёмов у задания слишком много. Черновик (`draft: true`, T-20261111-16) — как у `room-edit`:
// 200 `{draft: true}` без пересборки, 429 `draft_limit`. Ручка из списка песочницы тура (`lib/trial/tour-page.ts`).
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialOpeningEditIn, 16 * 1024);
  if (body instanceof Response) return body;
  const r = await askOpeningEdit(id, body);
  if (!r.ok) return trialJson({ ok: false, error: r.error, ...(r.version !== undefined ? { version: r.version } : {}) }, r.status);
  return trialJson({ ok: true, repeated: r.repeated, unchanged: r.unchanged, edit: r.edit, ...(r.draft ? { draft: true } : {}) },
    r.unchanged || r.draft ? 200 : 202);
}
