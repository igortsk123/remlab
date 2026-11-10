import { createHash } from "node:crypto";
import { floorplanResult } from "@/contracts/trial";
import { trialRebuildPublishIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { BUNDLE_BODY_MAX, checkBundle } from "@/lib/trial/bundle-check";
import { TRIAL_RESULT_MAX_BYTES } from "@/lib/trial/config";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { publishRebuild, type NewResult } from "@/lib/trial/repo-rebuild-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Итог пересборки «Обустроить» — ОДНА новая версия данных страницы (план agent-trial-08, Р1). Те же проверки, что у версий задания
// (`checkBundle`); `base_version` сверяется ещё раз под замком: страница успела смениться — 409 `stale`, ничего не пишем, пересборка failed.
// 409 `lease_lost` — аренда потеряна; повтор того же тела той же аренды — 200 `repeated`.
// Пересборка по тексту агента (Р2-текст) шлёт и новый `result` задания — та же схема и потолок, что у `/worker/result`.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialRebuildPublishIn, BUNDLE_BODY_MAX + TRIAL_RESULT_MAX_BYTES);
  if (body instanceof Response) return body;
  if (!validId(body.jobId)) return fail(404, "not_found");
  const checked = checkBundle(body.bundle, body.sha256, body.jobId);
  if (checked instanceof Response) return checked;
  let result: NewResult | undefined;
  if (body.result !== undefined) {
    const json = JSON.stringify(body.result);
    if (Buffer.byteLength(json) > TRIAL_RESULT_MAX_BYTES) return fail(413, "too_large");
    const parsed = floorplanResult.safeParse(body.result);
    if (!parsed.success) return trialJson({ ok: false, error: "invalid_result", issues: parsed.error.issues.slice(0, 5) }, 422);
    result = { json, hash: createHash("sha256").update(json).digest("hex") };
  }
  const r = await publishRebuild(body, body.bundle, checked.hash, undefined, undefined, result);
  if (r === "lease_lost" || r === "stale") return fail(409, r);
  if (r === "result_unexpected") return fail(422, r);
  return trialJson({ ok: true, version: r.version, repeated: r.repeated, ...(r.release === "failed" ? { warning: "release_pin_failed" } : {}) });
}
