// Чтение задания для страницы `/try/<id>` (план agent-trial-01, T-A). Наружу — только `trialJobView`: ни пути файла,
// ни текста объявления, ни аренды, ни воркера, ни деталей ошибки (поправки Codex 09.11).

import { sql } from "drizzle-orm";
import { trialErrorCode, trialJobView, type TrialJobView } from "@/contracts/trial";
import { TRIAL_WORKER_ALIVE_SEC } from "@/lib/trial/config";
import { claimable, iso, jsonOf, rows } from "@/lib/trial/sql";

type ViewRow = {
  id: string; status: string; stage: string; stages: unknown; created_at: string; finished_at: string | null;
  elapsed_sec: number; error_code: string | null; result_version: number; queue_ahead: number | null; worker_alive: boolean;
};

/** undefined — нет такого задания; "expired" — результат снят по сроку (410). */
export async function jobView(id: string): Promise<TrialJobView | "expired" | undefined> {
  const [r] = await rows<ViewRow>(sql`select j.id, j.status, j.stage, j.stages, ${iso(sql`j.created_at`)} as created_at,
      ${iso(sql`j.finished_at`)} as finished_at,
      greatest(0, floor(extract(epoch from coalesce(j.finished_at, now()) - j.created_at)))::int as elapsed_sec,
      j.error_code, j.result_version,
      case when j.status = 'queued' then (select count(*)::int from trial_jobs o
        where ${claimable(sql.raw("o"))} and (o.created_at, o.id) < (j.created_at, j.id)) end as queue_ahead,
      exists (select 1 from trial_workers w where w.last_seen > now() - make_interval(secs => ${TRIAL_WORKER_ALIVE_SEC}::int)) as worker_alive
    from trial_jobs j where j.id = ${id}`);
  if (!r) return undefined;
  if (r.status === "expired") return "expired";
  const code = trialErrorCode.safeParse(r.error_code);
  return trialJobView.parse({
    id: r.id, status: r.status, stage: r.stage, stages: jsonOf(r.stages), createdAt: r.created_at, finishedAt: r.finished_at,
    elapsedSec: r.elapsed_sec, queueAhead: r.queue_ahead, workerAlive: r.worker_alive,
    errorCode: r.status === "failed" ? (code.success ? code.data : "internal") : null, resultVersion: r.result_version,
  });
}

/** Результат готового задания. "expired" — снят по сроку; "not_ready" — ещё нет (или задание не удалось). */
export async function jobResult(id: string): Promise<{ result: unknown; version: number } | "expired" | "not_ready" | undefined> {
  const [r] = await rows<{ status: string; result: unknown; result_version: number }>(
    sql`select status, result, result_version from trial_jobs where id = ${id}`);
  if (!r) return undefined;
  if (r.status === "expired") return "expired";
  if (r.status !== "done" || r.result == null) return "not_ready";
  return { result: jsonOf(r.result), version: r.result_version };
}
