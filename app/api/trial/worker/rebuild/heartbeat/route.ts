import { trialRebuildLeaseIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { heartbeatRebuild } from "@/lib/trial/repo-rebuild-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Продление аренды пересборки «Обустроить» (раз в 10 с, +60 с). 409 — аренда потеряна: воркер снимает процессы стадий и ничего не публикует.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialRebuildLeaseIn);
  if (body instanceof Response) return body;
  const r = await heartbeatRebuild(body);
  return r ? trialJson({ ok: true, leaseUntil: r.leaseUntil }) : fail(409, "lease_lost");
}
