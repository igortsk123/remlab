// Пересборки «Обустроить» для воркера DEV (план agent-trial-08, Р1). Аренда и ограждение — как у заданий (`repo-worker.ts`): claim →
// attempt+1 и новый lease_token; heartbeat/publish/fail — с проверкой status/attempt/lease_token/lease_until>now(). Публикация —
// транзакция: строка пересборки и строка задания под замком → `base_version` ещё текущая (иначе `stale`, ничего не пишем) → файл
// новой версии → манифест задания (+ накопленные снятые комнаты) → пересборка `done`. Повтор того же тела той же аренды — успех без
// новой версии. Приоритет над новыми загрузками — с квотой (`rebuildFirst`).

import { sql, type SQL } from "drizzle-orm";
import type { TrialRebuildClaimed, TrialRebuildFailIn, TrialRebuildLease } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { pruneBundles, writeBundle } from "@/lib/trial/bundle";
import { TRIAL_LEASE_SEC, trialDir, trialRebuildQuota } from "@/lib/trial/config";
import { KEEP_VERSIONS, pinAfterPublish, type Published } from "@/lib/trial/repo-bundle";
import { claimable, iso, jsonOf, rows } from "@/lib/trial/sql";
import { ensureJobRelease } from "@/lib/trial/tour-bundle";

const fenceR = (f: TrialRebuildLease) => sql`id = ${f.id} and status = 'running'
  and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and lease_until > now()`;
// конец пересборки: текст агента (`listing`) больше не нужен — не храним
const doneSet = sql`finished_at = now(), lease_until = null, listing_text = null`;
const union = (a: unknown, b: unknown): string[] => [...new Set([...jsonOf<string[]>(a ?? []), ...jsonOf<string[]>(b ?? [])])];

/** Исчерпанные попытки с истёкшей арендой → failed/lease_lost; ждущие пересборки снятого (не `done`) задания → failed/stale. Текст агента
 *  (`listing`) ждёт `done` задания штатно (принят на v1) — снимаем его, только когда задание уже не станет `done`. */
export async function exhaustRebuilds(): Promise<void> {
  await db().execute(sql`update trial_rebuilds set status = 'failed', error_code = 'lease_lost', ${doneSet}
    where status = 'running' and lease_until < now() and attempt >= max_attempts`);
  await db().execute(sql`update trial_rebuilds r set status = 'failed', error_code = 'stale', ${doneSet}
    from trial_jobs j where j.id = r.job_id and r.status in ('queued', 'running') and j.status <> 'done'
      and (r.kind <> 'listing' or j.status in ('failed', 'cancelled', 'expired'))`);
}

/** Пересборку раньше загрузки? Да, пока новая загрузка не ждёт или с её появления взято меньше `TRIAL_REBUILD_QUOTA` пересборок. */
export async function rebuildFirst(env = process.env): Promise<boolean> {
  const [r] = await rows<{ waiting: boolean; since: number }>(sql`with w as (select min(created_at) as oldest from trial_jobs t
      where ${claimable(sql.raw("t"))})
    select w.oldest is not null as waiting, (select count(*)::int from trial_rebuilds r where r.started_at >= w.oldest) as since from w`);
  return !r?.waiting || r.since < trialRebuildQuota(env);
}

type ClaimRow = {
  id: string; job_id: string; attempt: number; lease_token: string; lease_until: string; rooms: unknown; base_version: number;
  kind: "furnish" | "listing"; listing_text: string | null;
};

/** Одна пересборка под аренду — скалярным подзапросом, как `repo-worker.ts:claim` (почему не `from (…) c` — там).
 *  `listing` — воркер умеет пересборки по тексту агента (Р2-текст); старый воркер их не получает. У `listing` база версии при claim —
 *  ТЕКУЩАЯ версия данных (поколение после `done`): текст приняли на v1, задание дошло до v3 — это не «устарело». */
export async function claimRebuild(workerId: string, listing = false): Promise<TrialRebuildClaimed | null> {
  await exhaustRebuilds();
  const token = randomToken(24);
  const [r] = await rows<ClaimRow>(sql`update trial_rebuilds r set status = 'running', attempt = r.attempt + 1, lease_token = ${token},
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int), worker_id = ${workerId}, heartbeat_at = now(),
      started_at = coalesce(r.started_at, now()),
      base_version = case when r.kind = 'listing' then (select j.bundle_version from trial_jobs j where j.id = r.job_id) else r.base_version end
    where r.id = (select x.id from trial_rebuilds x join trial_jobs j on j.id = x.job_id
      where (x.status = 'queued' or (x.status = 'running' and x.lease_until < now())) and x.attempt < x.max_attempts and j.status = 'done'
        and (x.kind = 'furnish' or ${listing})
      order by x.created_at, x.id for update of x skip locked limit 1)
    returning r.id, r.job_id, r.attempt, r.lease_token, ${iso(sql`r.lease_until`)} as lease_until, r.rooms, r.base_version, r.kind,
      r.listing_text`);
  if (!r) return null;
  const [j] = await rows<{ result: unknown; released_rooms: unknown }>(sql`select result, released_rooms from trial_jobs where id = ${r.job_id}`);
  return {
    id: r.id, jobId: r.job_id, attempt: r.attempt, leaseToken: r.lease_token, leaseUntil: r.lease_until,
    rooms: union(j?.released_rooms, r.rooms), baseVersion: r.base_version, result: j ? jsonOf(j.result) : null, kind: r.kind,
    ...(r.kind === "listing" ? { listingText: r.listing_text ?? "" } : {}),
  };
}

export async function heartbeatRebuild(f: TrialRebuildLease): Promise<{ leaseUntil: string } | null> {
  const [r] = await rows<{ lease_until: string }>(sql`update trial_rebuilds set heartbeat_at = now(),
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int) where ${fenceR(f)} returning ${iso(sql`lease_until`)} as lease_until`);
  return r ? { leaseUntil: r.lease_until } : null;
}

type JobRow = { status: string; bundle_version: number; result_version: number; bundle_hash: string | null; released_rooms: unknown };

/** Итог пересборки → одна новая версия данных страницы. "stale" — пока шла сборка, страница успела смениться: не публикуем. */
export async function publishRebuild(
  f: TrialRebuildLease & { jobId: string }, json: string, hash: string, dir = trialDir(), pin = ensureJobRelease,
): Promise<Published | "lease_lost" | "stale"> {
  const out = await db().transaction(async (tx): Promise<Published | "lease_lost" | "stale"> => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [cur] = await ex<{ job_id: string; base_version: number; rooms: unknown }>(sql`select job_id, base_version, rooms
        from trial_rebuilds where ${fenceR(f)} for update`);
    if (!cur || cur.job_id !== f.jobId) {
      const [again] = await ex<{ result_version: number }>(sql`select result_version from trial_rebuilds where id = ${f.id}
          and job_id = ${f.jobId} and status = 'done' and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and bundle_hash = ${hash}`);
      return again ? { version: again.result_version, repeated: true } : "lease_lost";
    }
    const [job] = await ex<JobRow>(sql`select status, bundle_version, result_version, bundle_hash, released_rooms
        from trial_jobs where id = ${cur.job_id} for update`);
    if (!job || job.status !== "done" || job.bundle_version !== cur.base_version) {
      await tx.execute(sql`update trial_rebuilds set status = 'failed', error_code = 'stale', ${doneSet} where id = ${f.id}`);
      return "stale";
    }
    const released = JSON.stringify(union(job.released_rooms, cur.rooms));
    const same = job.bundle_hash === hash;
    const next = same ? job.bundle_version : job.result_version + 1;
    if (!same) await writeBundle(dir, cur.job_id, next, json);
    await tx.execute(sql`update trial_jobs set released_rooms = ${released}::jsonb
        ${same ? sql`` : sql`, result_version = ${next}, bundle_version = ${next}, bundle_hash = ${hash}`} where id = ${cur.job_id}`);
    await tx.execute(sql`update trial_rebuilds set status = 'done', bundle_hash = ${hash}, result_version = ${next}, ${doneSet}
        where id = ${f.id}`);
    return { version: next, repeated: same };
  });
  if (out === "lease_lost" || out === "stale") return out;
  if (!out.repeated) await pruneBundles(dir, f.jobId, out.version - KEEP_VERSIONS + 1).catch(() => undefined);
  return { ...out, release: await pinAfterPublish(f.jobId, dir, pin) };
}

/** Сбой у воркера: повторяемый и попытки есть → снова в очередь; `waiting_capacity` попытку не тратит; иначе failed с кодом. */
export async function failRebuild(f: TrialRebuildFailIn): Promise<"queued" | "failed" | "lease_lost"> {
  return db().transaction(async (tx) => {
    const got = (await tx.execute(sql`select attempt, max_attempts from trial_rebuilds where ${fenceR(f)} for update`)) as unknown as
      { attempt: number; max_attempts: number }[];
    const cur = got[0];
    if (!cur) return "lease_lost";
    const refund = f.code === "waiting_capacity";
    const attempt = refund ? cur.attempt - 1 : cur.attempt;
    const requeue = (refund || f.retryable) && attempt < cur.max_attempts;
    const detail = f.detail?.slice(0, 2000) ?? null;
    await tx.execute(requeue
      ? sql`update trial_rebuilds set status = 'queued', attempt = ${attempt}, lease_token = null, lease_until = null,
          error_detail = ${detail} where id = ${f.id}`
      : sql`update trial_rebuilds set status = 'failed', error_code = ${refund ? "timeout" : f.code}, error_detail = ${detail}, ${doneSet}
          where id = ${f.id}`);
    return requeue ? "queued" : "failed";
  });
}
