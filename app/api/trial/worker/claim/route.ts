import { trialClaimIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { parseBody, trialJson } from "@/lib/trial/http";
import { claim, touchWorker } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Опрос воркера DEV (раз в 2 с): отметиться «жив» и забрать следующее задание (SKIP LOCKED, аренда 60 с).
// `paused: true` — воркер сам себя притормозил (память, очередь тяжёлых): только отметка, задание не берём.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialClaimIn);
  if (body instanceof Response) return body;
  await touchWorker(body.workerId, body.version);
  if (body.paused) return trialJson({ ok: true, job: null });
  return trialJson({ ok: true, job: await claim(body.workerId) });
}
