import { trialReparseIn } from "@/contracts/trial-bundle";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson } from "@/lib/trial/http";
import { askReparse, reparseState } from "@/lib/trial/repo-reparse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// «Перечитать планировку» готового тура (оператор, план trial-reparse-01; T-20261111-02; `lib/trial/repo-reparse.ts`). Только ключ воркера.
// POST {jobId, requestId} → 202 строка очереди `reparse` (повтор `requestId` — та же). 404 нет тура · 410 `expired` / `source_gone`
// (исходного листа уже нет) · 409 `not_ready` / `busy` (идёт другая пересборка). GET ?id=<id пересборки> — её исход для скрипта оператора.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialReparseIn);
  if (body instanceof Response) return body;
  const r = await askReparse(body.jobId, body.requestId);
  if (!r.ok) return fail(r.status, r.error);
  return trialJson({ ok: true, repeated: r.repeated, rebuild: r.rebuild }, 202);
}

export async function GET(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const st = await reparseState(new URL(req.url).searchParams.get("id") ?? "");
  return st ? trialJson({ ok: true, ...st }) : fail(404, "not_found");
}
