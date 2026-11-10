import { trialReissueIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { BUNDLE_BODY_MAX, checkBundle } from "@/lib/trial/bundle-check";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { publishReissue, reissueSource } from "@/lib/trial/repo-reissue";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Пересборка готового тура «как есть» (оператор, T-20261110-05; `lib/trial/repo-reissue.ts`). GET — исходник: `result` и точные байты
// последней версии. POST — новая версия от `baseVersion` (те же проверки, что у версий воркера, `checkBundle`) и закрепление текущей
// витрины. 404 нет задания · 410 срок вышел · 409 `not_ready` / `busy` (идёт пересборка агента) / `stale` (версия сменилась) /
// `no_bundle` (файла версии нет в TRIAL_DIR).
const STATUS = { not_found: 404, expired: 410, not_ready: 409, busy: 409, stale: 409, no_bundle: 409 } as const;

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const src = await reissueSource(id);
  if (typeof src === "string") return fail(STATUS[src], src);
  return trialJson({ ok: true, ...src });
}

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialReissueIn, BUNDLE_BODY_MAX);
  if (body instanceof Response) return body;
  const checked = checkBundle(body.bundle, body.sha256, id);
  if (checked instanceof Response) return checked;
  const r = await publishReissue(id, body.baseVersion, body.bundle, checked.hash);
  if (typeof r === "string") return fail(STATUS[r], r);
  return trialJson({ ok: true, ...r, ...(r.release === "failed" ? { warning: "release_pin_failed" } : {}) });
}
