import { trialHeartbeatIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { heartbeat } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Продление аренды (раз в 10 с, +60 с) и текущий шаг (время шага ставит прод). 409 — аренда потеряна: воркер
// бросает задание, его доделает тот, кто забрал.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialHeartbeatIn);
  if (body instanceof Response) return body;
  if (body.stage === "done" || body.stage === "queued") return fail(400, "bad_stage"); // done — только через result
  const r = await heartbeat(body);
  return r ? trialJson({ ok: true, leaseUntil: r.leaseUntil }) : fail(409, "lease_lost");
}
