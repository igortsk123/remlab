import { autoReleaseIn } from "@/contracts/trial-auto-photos";
import { workerGuard } from "@/lib/trial/auth";
import { releaseAutoBatch } from "@/lib/trial/auto-photos-lease";
import { fail, parseBody, trialJson } from "@/lib/trial/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Тур ещё не готов к съёмке (съёмщик Ф3: exit 3, TOUR_READY) — партия автофото обратно в очередь (T-20261112-115 Ф2): попытка не
// тратится, следующая выдача — не раньше `retry_s` правила; слишком много возвратов — `failed` (резерв вернулся).
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, autoReleaseIn);
  if (body instanceof Response) return body;
  const r = await releaseAutoBatch(body);
  if (!r.ok) return fail(409, r.error);
  return trialJson({ ok: true, status: r.status });
}
