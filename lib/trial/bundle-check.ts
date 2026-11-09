// Проверка присланной версии данных страницы — одна на обе ручки публикации (версии задания `worker/bundle` и пересборки
// `worker/rebuild/publish`): потолок размера, хеш байтов от воркера, форма (`trialBundle`) и связи (`bundleProblem`).

import { createHash } from "node:crypto";
import { bundleProblem, trialBundle } from "@/contracts/trial-bundle";
import { TRIAL_BUNDLE_MAX_BYTES } from "@/lib/trial/config";
import { fail, trialJson } from "@/lib/trial/http";

/** Потолок тела JSON: строка версии в JSON экранируется — до 2 раз больше. */
export const BUNDLE_BODY_MAX = TRIAL_BUNDLE_MAX_BYTES * 2 + 4096;

/** → { hash } или готовый отказ (413/422). `jobId` — чьё задание: версия про чужое — `wrong_job`. */
export function checkBundle(bundle: string, sha256: string, jobId: string): { hash: string } | Response {
  if (Buffer.byteLength(bundle) > TRIAL_BUNDLE_MAX_BYTES) return fail(413, "too_large");
  const hash = createHash("sha256").update(bundle).digest("hex");
  if (hash !== sha256) return fail(422, "hash_mismatch");
  let raw: unknown;
  try { raw = JSON.parse(bundle); } catch { return fail(422, "bad_json"); }
  const parsed = trialBundle.safeParse(raw);
  if (!parsed.success) return trialJson({ ok: false, error: "invalid_bundle", issues: parsed.error.issues.slice(0, 5) }, 422);
  const problem = bundleProblem(parsed.data, jobId);
  return problem ? fail(422, problem) : { hash };
}
