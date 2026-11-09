import { trialRebuildFailIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { failRebuild } from "@/lib/trial/repo-rebuild-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Сбой пересборки у воркера: `retryable` и попытки есть → снова в очередь; `waiting_capacity` попытку не тратит; иначе failed с кодом
// (страница пишет понятный текст по `rebuildError`). 409 — аренда потеряна.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialRebuildFailIn);
  if (body instanceof Response) return body;
  const r = await failRebuild(body);
  return r === "lease_lost" ? fail(409, "lease_lost") : trialJson({ ok: true, status: r });
}
