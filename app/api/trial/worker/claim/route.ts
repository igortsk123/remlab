import { trialClaimIn } from "@/contracts/trial";
import { workerGuard } from "@/lib/trial/auth";
import { parseBody, trialJson } from "@/lib/trial/http";
import { claimRebuild, rebuildFirst } from "@/lib/trial/repo-rebuild-worker";
import { claim, touchWorker } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Опрос воркера DEV (раз в 2 с): отметиться «жив» и забрать следующее задание (SKIP LOCKED, аренда 60 с).
// `paused: true` — воркер сам себя притормозил: только отметка, задание не берём.
// `rebuilds: true` — воркер умеет «Обустроить»: пересборка (агент ждёт на странице) идёт раньше новой загрузки, но пока загрузка ждёт —
// не больше `TRIAL_REBUILD_QUOTA` пересборок подряд (`rebuildFirst`). Ответ — `job` ИЛИ `rebuild`.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialClaimIn);
  if (body instanceof Response) return body;
  await touchWorker(body.workerId, body.version);
  if (body.paused) return trialJson({ ok: true, job: null });
  if (!body.rebuilds) return trialJson({ ok: true, job: await claim(body.workerId) });
  const first = await rebuildFirst();
  const listing = body.listing === true; // пересборки по тексту агента (Р2-текст) — только воркеру, который их умеет
  if (first) {
    const rebuild = await claimRebuild(body.workerId, listing);
    if (rebuild) return trialJson({ ok: true, job: null, rebuild });
  }
  const job = await claim(body.workerId);
  if (job || first) return trialJson({ ok: true, job });
  const rebuild = await claimRebuild(body.workerId, listing);
  return trialJson({ ok: true, job: null, rebuild });
}
