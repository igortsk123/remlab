// Пересборка готового тура «как есть» (план agent-trial-08; T-20261110-05) — ставит ОПЕРАТОР скриптом `tools/floorplan/reissue.py`
// (воркерный ключ), не агент. Отдельный путь, а не строка очереди `trial_rebuilds`: сборка без стадий мебели — секунды, оператор ждёт
// ответ по каждому туру; поэтому ни аренды, ни миграции вида: защита — сверка версии под замком строки задания.
// Скрипт: список живых туров → исходник (результат + последняя версия) → сборка на DEV → публикация: под `for update` задание всё ещё
// `done`, версия та же, что взяли (иначе `stale` — агент успел пересобрать), нет идущей пересборки агента (`busy`) → новая версия
// данных страницы → закрепление ТЕКУЩЕЙ витрины (`repinJobRelease`): страница тура тоже на новом коде.

import { sql, type SQL } from "drizzle-orm";
import { db } from "@/lib/db";
import { pruneBundles, readBundle, writeBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";
import { validId } from "@/lib/trial/http";
import { KEEP_VERSIONS } from "@/lib/trial/repo-bundle";
import { iso, jsonOf, rows } from "@/lib/trial/sql";
import { repinJobRelease } from "@/lib/trial/tour-bundle";

export const REISSUE_DAYS_MAX = 60;

type Refusal = "not_found" | "expired" | "not_ready" | "busy";
type JobRow = { status: string; bundle_version: number; result_version: number; bundle_hash: string | null; past_term: boolean; busy: boolean };

const ACTIVE = sql`exists (select 1 from trial_rebuilds r where r.job_id = trial_jobs.id and r.status in ('queued', 'running'))`;
const jobRow = (id: string, tail: SQL = sql``, extra: SQL = sql``): SQL => sql`select status, bundle_version, result_version, bundle_hash,
    coalesce(result_expires_at < now(), false) as past_term, ${ACTIVE} as busy ${extra} from trial_jobs where id = ${id} ${tail}`;

function refusal(j: JobRow): Refusal | null {
  if (j.status === "expired" || j.past_term) return "expired";
  if (j.status !== "done" || j.bundle_version < 1) return "not_ready";
  return j.busy ? "busy" : null;
}

/** Готовые туры (есть версия данных и результат, срок не вышел) младше `days` дней — по порядку создания. */
export async function reissueList(days: number): Promise<{ id: string; version: number; createdAt: string }[]> {
  const got = await rows<{ id: string; version: number; created_at: string }>(sql`select id, bundle_version as version,
      ${iso(sql`created_at`)} as created_at from trial_jobs where status = 'done' and bundle_version > 0 and result is not null
      and coalesce(result_expires_at > now(), true) and created_at > now() - make_interval(days => ${days}::int) order by created_at, id`);
  return got.map((r) => ({ id: r.id, version: r.version, createdAt: r.created_at }));
}

export type ReissueSource = { jobId: string; version: number; result: unknown; bundle: string };

/** Что пересобирать: сохранённый `result` и ТОЧНЫЕ байты последней версии данных страницы. */
export async function reissueSource(id: string, dir = trialDir()): Promise<ReissueSource | Refusal> {
  if (!validId(id)) return "not_found";
  const [j] = await rows<JobRow & { result: unknown }>(jobRow(id, sql``, sql`, result`));
  if (!j) return "not_found";
  const no = refusal(j);
  if (no) return no;
  if (j.result === null) return "not_ready";
  const bundle = await readBundle(dir, id, j.bundle_version);
  return bundle === null ? "not_ready" : { jobId: id, version: j.bundle_version, result: jsonOf(j.result), bundle };
}

export type Reissued = { version: number; repeated: boolean; release: string | "failed"; previous: string | null };

/** Новая версия данных страницы от версии `base` + закрепление текущей витрины. Те же байты — без новой версии, но витрина — новая. */
export async function publishReissue(
  id: string, base: number, json: string, hash: string, dir = trialDir(), repin = repinJobRelease,
): Promise<Reissued | Refusal | "stale"> {
  if (!validId(id)) return "not_found";
  const out = await db().transaction(async (tx): Promise<{ version: number; repeated: boolean } | Refusal | "stale"> => {
    const [j] = (await tx.execute(jobRow(id, sql`for update`))) as unknown as JobRow[];
    if (!j) return "not_found";
    const no = refusal(j);
    if (no) return no;
    if (j.bundle_version !== base) return "stale";
    if (j.bundle_hash === hash) return { version: j.bundle_version, repeated: true };
    const next = j.result_version + 1;
    await writeBundle(dir, id, next, json);
    await tx.execute(sql`update trial_jobs set result_version = ${next}, bundle_version = ${next}, bundle_hash = ${hash} where id = ${id}`);
    return { version: next, repeated: false };
  });
  if (typeof out === "string") return out;
  if (!out.repeated) await pruneBundles(dir, id, out.version - KEEP_VERSIONS + 1).catch(() => undefined);
  try {
    const pin = await repin(id, dir);
    return { ...out, release: pin.release, previous: pin.previous };
  } catch (e) {
    console.error(`trial ${id}: reissue_pin_failed ${e instanceof Error ? e.message : String(e)}`.slice(0, 500));
    return { ...out, release: "failed", previous: null };
  }
}
