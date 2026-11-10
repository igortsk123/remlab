import { workerGuard } from "@/lib/trial/auth";
import { fail, trialJson } from "@/lib/trial/http";
import { REISSUE_DAYS_MAX, reissueList } from "@/lib/trial/repo-reissue";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Пересборка «как есть» (оператор, T-20261110-05; `lib/trial/repo-reissue.ts`): готовые туры младше `days` дней — кого пересобрать пачкой.
export async function GET(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const raw = new URL(req.url).searchParams.get("days") ?? "";
  const days = /^\d{1,3}$/.test(raw) ? Number(raw) : NaN;
  if (!(days >= 1 && days <= REISSUE_DAYS_MAX)) return fail(400, "bad_days");
  return trialJson({ ok: true, jobs: await reissueList(days) });
}
