// Чтение задания для страницы `/try/<id>` (план agent-trial-01, T-A). Наружу — только `trialJobView`: ни пути файла,
// ни текста объявления, ни аренды, ни воркера, ни деталей ошибки (поправки Codex 09.11).

import { sql } from "drizzle-orm";
import { trialErrorCode, trialJobView, type TrialJobView } from "@/contracts/trial";
import { TRIAL_WORKER_ALIVE_SEC } from "@/lib/trial/config";
import { scaleAsks, sizeAsk } from "@/lib/trial/size-ask";
import { claimable, iso, jsonOf, rows } from "@/lib/trial/sql";

type ViewRow = {
  id: string; status: string; stage: string; stages: unknown; created_at: string; finished_at: string | null;
  elapsed_sec: number; error_code: string | null; result_version: number; bundle_version: number; queue_ahead: number | null;
  worker_alive: boolean; rebuild: Last | string | null; scale_status: string | null;
};
type Last = { status?: string; code?: string | null; kind?: string };
type RebuildPart = Pick<TrialJobView, "rebuild" | "rebuildError" | "listing" | "listingError" | "roomEdit" | "roomEditError" | "tourUpdate">;

const REBUILD_ERRORS = new Set(["stale", "lease_lost", "timeout", "pipeline_error", "internal"]);
const LISTING_ERRORS = new Set([...REBUILD_ERRORS, "source_gone", "no_match"]);
const NONE: RebuildPart = { rebuild: null, rebuildError: null, listing: null, listingError: null, roomEdit: null, roomEditError: null,
  tourUpdate: null };
const errOf = (r: Last, known: Set<string>) => (r.status === "failed" ? (known.has(r.code ?? "") ? r.code : "internal") : null);

/** Последняя пересборка задания → видимое состояние. «Обустроить»: `done` — уже не важно (новая версия пришла), ошибка — закрытым кодом.
 *  Текст агента (`kind: listing`, Р2-текст): ждёт, пока задание не `done`, — «принято, применим после сборки»; потом «применяем»; итог. */
function rebuildOf(raw: ViewRow["rebuild"], jobStatus: string): RebuildPart {
  const r = raw ? jsonOf<Last>(raw) : null;
  if (!r) return NONE;
  if (r.kind === "listing") {
    const listing = r.status === "queued" && jobStatus !== "done" ? "accepted"
      : r.status === "queued" || r.status === "running" ? "applying" : r.status === "done" ? "done" : r.status === "failed" ? "failed" : null;
    return { ...NONE, listing, listingError: errOf(r, LISTING_ERRORS) as TrialJobView["listingError"] };
  }
  // «перечитать планировку» оператора (T-20261111-02): нейтрально «обновляем тур»; итог виден новой версией, неудача — тур прежний (без кода)
  if (r.kind === "reparse") return { ...NONE, tourUpdate: r.status === "queued" || r.status === "running" ? "applying" : null };
  if (r.kind === "edit") {                    // правка комнаты (T-20261110-36): страница держит «Пересобираю комнату…», пока не `done`
    const roomEdit = r.status === "queued" || r.status === "running" ? "applying" : r.status === "done" ? "done" : r.status === "failed" ? "failed" : null;
    return { ...NONE, roomEdit, roomEditError: errOf(r, REBUILD_ERRORS) as TrialJobView["roomEditError"] };
  }
  if (r.status !== "queued" && r.status !== "running" && r.status !== "failed") return NONE;
  return { ...NONE, rebuild: r.status, rebuildError: errOf(r, REBUILD_ERRORS) as TrialJobView["rebuildError"] };
}

/** undefined — нет такого задания; "expired" — результат снят по сроку (410). */
export async function jobView(id: string): Promise<TrialJobView | "expired" | undefined> {
  const [r] = await rows<ViewRow>(sql`select j.id, j.status, j.stage, j.stages, ${iso(sql`j.created_at`)} as created_at,
      ${iso(sql`j.finished_at`)} as finished_at,
      greatest(0, floor(extract(epoch from coalesce(j.finished_at, now()) - j.created_at)))::int as elapsed_sec,
      j.error_code, j.result_version, j.bundle_version, j.result->'scale'->>'status' as scale_status,
      case when j.status = 'queued' then (select count(*)::int from trial_jobs o
        where ${claimable(sql.raw("o"))} and (o.created_at, o.id) < (j.created_at, j.id)) end as queue_ahead,
      exists (select 1 from trial_workers w where w.last_seen > now() - make_interval(secs => ${TRIAL_WORKER_ALIVE_SEC}::int)) as worker_alive,
      (select jsonb_build_object('status', r.status, 'code', r.error_code, 'kind', r.kind) from trial_rebuilds r where r.job_id = j.id
        order by r.created_at desc, r.id desc limit 1) as rebuild
    from trial_jobs j where j.id = ${id}`);
  if (!r) return undefined;
  if (r.status === "expired") return "expired";
  const code = trialErrorCode.safeParse(r.error_code);
  return trialJobView.parse({
    id: r.id, status: r.status, stage: r.stage, stages: jsonOf(r.stages), createdAt: r.created_at, finishedAt: r.finished_at,
    elapsedSec: r.elapsed_sec, queueAhead: r.queue_ahead, workerAlive: r.worker_alive,
    errorCode: r.status === "failed" ? (code.success ? code.data : "internal") : null, resultVersion: r.result_version,
    bundleVersion: r.bundle_version, ...rebuildOf(r.rebuild, r.status),
    // результат готов — его масштаб (данных страницы может и не быть); иначе — последняя опубликованная версия данных
    askSizes: scaleAsks(r.scale_status) || await sizeAsk(r.id, r.bundle_version),
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
