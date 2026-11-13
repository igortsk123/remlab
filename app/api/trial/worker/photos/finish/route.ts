import { autoFinishIn } from "@/contracts/trial-auto-photos";
import { workerGuard } from "@/lib/trial/auth";
import { finishAutoBatch } from "@/lib/trial/auto-photos-lease";
import { fail, parseBody, trialJson } from "@/lib/trial/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Закрыть партию автофото (T-20261112-115 Ф2): незаказанные задачи → failed/abandoned (резерв вернулся), партия → done.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, autoFinishIn);
  if (body instanceof Response) return body;
  const r = await finishAutoBatch(body);
  if (!r.ok) return fail(409, r.error);
  return trialJson({ ok: true, abandoned: r.abandoned });
}
