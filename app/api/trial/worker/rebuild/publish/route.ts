import { trialRebuildPublishIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { BUNDLE_BODY_MAX, checkBundle } from "@/lib/trial/bundle-check";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { publishRebuild } from "@/lib/trial/repo-rebuild-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Итог пересборки «Обустроить» — ОДНА новая версия данных страницы (план agent-trial-08, Р1). Те же проверки, что у версий задания
// (`checkBundle`); `base_version` сверяется ещё раз под замком: страница успела смениться — 409 `stale`, ничего не пишем, пересборка failed.
// 409 `lease_lost` — аренда потеряна; повтор того же тела той же аренды — 200 `repeated`.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialRebuildPublishIn, BUNDLE_BODY_MAX);
  if (body instanceof Response) return body;
  if (!validId(body.jobId)) return fail(404, "not_found");
  const checked = checkBundle(body.bundle, body.sha256, body.jobId);
  if (checked instanceof Response) return checked;
  const r = await publishRebuild(body, body.bundle, checked.hash);
  if (r === "lease_lost" || r === "stale") return fail(409, r);
  return trialJson({ ok: true, version: r.version, repeated: r.repeated, ...(r.release === "failed" ? { warning: "release_pin_failed" } : {}) });
}
