import { trialFailIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { failJob } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Сбой задания у воркера: `retryable` и попытки есть → снова в очередь через `retryAfterSec` (30 с); иначе failed.
// `waiting_capacity` — DEV занят дольше минуты: задание вернулось, попытка не потрачена. 409 — аренда потеряна.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialFailIn);
  if (body instanceof Response) return body;
  const r = await failJob(body);
  return r === "lease_lost" ? fail(409, "lease_lost") : trialJson({ ok: true, status: r });
}
