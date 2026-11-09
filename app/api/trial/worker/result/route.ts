import { createHash } from "node:crypto";
import { floorplanResult, trialResultIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { TRIAL_RESULT_MAX_BYTES } from "@/lib/trial/config";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { acceptResult } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Результат задания: JSON по `contracts/trial.ts:floorplanResult` (≤ 2 МБ), только с текущей арендой. Повтор того же
// результата (ответ потерялся в сети) — 200; другой результат или чужая/истёкшая аренда — 409; кривой JSON — 422.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialResultIn, TRIAL_RESULT_MAX_BYTES + 4096);
  if (body instanceof Response) return body;
  const json = JSON.stringify(body.result ?? null);
  if (Buffer.byteLength(json) > TRIAL_RESULT_MAX_BYTES) return fail(413, "too_large");
  const parsed = floorplanResult.safeParse(body.result);
  if (!parsed.success) return trialJson({ ok: false, error: "invalid_result", issues: parsed.error.issues.slice(0, 5) }, 422);
  const hash = createHash("sha256").update(json).digest("hex");
  const r = await acceptResult(body, json, hash);
  return r === "lease_lost" ? fail(409, "lease_lost") : trialJson({ ok: true, repeated: r === "again" });
}
