import { createHash } from "node:crypto";
import { bundleProblem, trialBundle, trialBundleIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { TRIAL_BUNDLE_MAX_BYTES } from "@/lib/trial/config";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { publishBundle } from "@/lib/trial/repo-bundle";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Промежуточная версия данных страницы (пустые комнаты, потом мебель; план agent-trial-08): Bearer воркера и текущая аренда, потолок размера,
// хеш байтов от воркера. Кривые данные — 422, чужая/просроченная аренда — 409; тот же файл повторно — 200 без новой версии.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialBundleIn, TRIAL_BUNDLE_MAX_BYTES * 2 + 4096); // строка в JSON: экранирование раздувает до 2 раз
  if (body instanceof Response) return body;
  if (!validId(body.id)) return fail(404, "not_found");
  if (Buffer.byteLength(body.bundle) > TRIAL_BUNDLE_MAX_BYTES) return fail(413, "too_large");
  const hash = createHash("sha256").update(body.bundle).digest("hex");
  if (hash !== body.sha256) return fail(422, "hash_mismatch");
  let raw: unknown;
  try { raw = JSON.parse(body.bundle); } catch { return fail(422, "bad_json"); }
  const parsed = trialBundle.safeParse(raw);
  if (!parsed.success) return trialJson({ ok: false, error: "invalid_bundle", issues: parsed.error.issues.slice(0, 5) }, 422);
  const problem = bundleProblem(parsed.data, body.id);
  if (problem) return fail(422, problem);
  const r = await publishBundle(body, body.bundle, hash);
  return r === "lease_lost" ? fail(409, "lease_lost") : trialJson({ ok: true, version: r.version, repeated: r.repeated });
}
