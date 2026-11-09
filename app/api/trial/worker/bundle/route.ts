import { trialBundleIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { BUNDLE_BODY_MAX, checkBundle } from "@/lib/trial/bundle-check";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { publishBundle } from "@/lib/trial/repo-bundle";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Промежуточная версия данных страницы (пустые комнаты, потом мебель; план agent-trial-08): Bearer воркера и текущая аренда, потолок размера,
// хеш байтов от воркера. Кривые данные — 422, чужая/просроченная аренда — 409; тот же файл повторно — 200 без новой версии.
// Принятая версия закрепляет за заданием страницу тура, если её ещё нет (`ensureJobRelease`); сбой — `warning`, версия не теряется.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialBundleIn, BUNDLE_BODY_MAX);
  if (body instanceof Response) return body;
  if (!validId(body.id)) return fail(404, "not_found");
  const checked = checkBundle(body.bundle, body.sha256, body.id);
  if (checked instanceof Response) return checked;
  const r = await publishBundle(body, body.bundle, checked.hash);
  if (r === "lease_lost") return fail(409, "lease_lost");
  return trialJson({ ok: true, version: r.version, repeated: r.repeated, ...(r.release === "failed" ? { warning: "release_pin_failed" } : {}) });
}
