import { autoClaimIn } from "@/contracts/trial-auto-photos";
import { workerGuard } from "@/lib/trial/auth";
import { claimAutoBatch } from "@/lib/trial/auto-photos-lease";
import { parseBody, trialJson } from "@/lib/trial/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Автофото тура (T-20261112-115 Ф2): исполнитель DEV берёт партию «снять тур» под аренду. 200 `{batch: null}` — снимать нечего.
// Партия — тур (`tourPath`, открывать с Bearer воркера), версия данных, задачи по комнатам с вариантом и позами C1/C2.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, autoClaimIn);
  if (body instanceof Response) return body;
  return trialJson({ ok: true, batch: await claimAutoBatch(body.workerId) });
}
