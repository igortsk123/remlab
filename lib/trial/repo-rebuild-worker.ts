// Пересборки «Обустроить» для воркера DEV (план agent-trial-08, Р1). Аренда и ограждение — как у заданий (`repo-worker.ts`): claim →
// attempt+1 и новый lease_token; heartbeat/publish/fail — с проверкой status/attempt/lease_token/lease_until>now(). Публикация —
// транзакция: строка пересборки и строка задания под замком → `base_version` ещё текущая (иначе `stale`, ничего не пишем) → файл
// новой версии → манифест задания (+ накопленные снятые комнаты) → пересборка `done`. Повтор того же тела той же аренды — успех без
// новой версии. Приоритет над новыми загрузками — с квотой (`rebuildFirst`).

import { sql, type SQL } from "drizzle-orm";
import type { TrialRebuildClaimed, TrialRebuildFailIn, TrialRebuildLease, TrialRoomEdit } from "@/contracts/trial";
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
  kind: "furnish" | "listing" | "edit"; listing_text: string | null;
};
type EditRow = { panel: string; src_id: string; anchor: unknown; name: string; kind: string; w_cm: number | null; d_cm: number | null; built: boolean };
/** Что умеет воркер: `listing` — пересборки по тексту агента (Р2-текст), `edit` — правки комнат (T-20261110-36). `true` — старая форма: listing. */
export type RebuildSkills = boolean | { listing?: boolean; edit?: boolean };

/** Правки комнат задания — воркеру, который их умеет: он накладывает их на копию `result` перед любой сборкой. */
export async function editsOf(jobId: string): Promise<TrialRoomEdit[]> {
  const got = await rows<EditRow>(sql`select panel, src_id, anchor, name, kind, w_cm, d_cm, built from trial_room_edits
    where job_id = ${jobId} order by created_at, room_key`);
  return got.map((e) => ({ panel: e.panel, srcId: e.src_id, anchor: jsonOf<{ x: number; y: number }>(e.anchor), name: e.name, kind: e.kind,
    wCm: e.w_cm, dCm: e.d_cm, built: e.built }));
}

/** Одна пересборка под аренду — скалярным подзапросом, как `repo-worker.ts:claim` (почему не `from (…) c` — там).
 *  Старый воркер пересборок по тексту и правок не получает. У `listing` и `edit` база версии при claim — ТЕКУЩАЯ версия данных
 *  (поколение после `done`): текст приняли на v1, задание дошло до v3 — это не «устарело». */
export async function claimRebuild(workerId: string, skills: RebuildSkills = false): Promise<TrialRebuildClaimed | null> {
  const listing = skills === true || (typeof skills === "object" && skills.listing === true);
  const edit = typeof skills === "object" && skills.edit === true;
  await exhaustRebuilds();
  const token = randomToken(24);
  const [r] = await rows<ClaimRow>(sql`update trial_rebuilds r set status = 'running', attempt = r.attempt + 1, lease_token = ${token},
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int), worker_id = ${workerId}, heartbeat_at = now(),
      started_at = coalesce(r.started_at, now()),
      base_version = case when r.kind in ('listing', 'edit') then (select j.bundle_version from trial_jobs j where j.id = r.job_id)
        else r.base_version end
    where r.id = (select x.id from trial_rebuilds x join trial_jobs j on j.id = x.job_id
      where (x.status = 'queued' or (x.status = 'running' and x.lease_until < now())) and x.attempt < x.max_attempts and j.status = 'done'
        and (x.kind = 'furnish' or (x.kind = 'listing' and ${listing}) or (x.kind = 'edit' and ${edit}))
      order by x.created_at, x.id for update of x skip locked limit 1)
    returning r.id, r.job_id, r.attempt, r.lease_token, ${iso(sql`r.lease_until`)} as lease_until, r.rooms, r.base_version, r.kind,
      r.listing_text`);
  if (!r) return null;
  const [j] = await rows<{ result: unknown; released_rooms: unknown; input_mime: string }>(sql`select result, released_rooms, input_mime
    from trial_jobs where id = ${r.job_id}`);
  return {
    id: r.id, jobId: r.job_id, attempt: r.attempt, leaseToken: r.lease_token, leaseUntil: r.lease_until,
    rooms: union(j?.released_rooms, r.rooms), baseVersion: r.base_version, result: j ? jsonOf(j.result) : null, kind: r.kind,
    ...(r.kind === "listing" ? { listingText: r.listing_text ?? "", inputMime: j?.input_mime ?? "" } : {}),
    ...(edit ? { edits: await editsOf(r.job_id) } : {}),
  };
}

/** Исходный лист задания — пересборке по тексту агента под ТЕКУЩЕЙ арендой; undefined — аренды нет, `name: null` — файл удалён по сроку. */
export async function leasedRebuildInput(f: TrialRebuildLease): Promise<{ name: string | null; mime: string } | undefined> {
  const [r] = await rows<{ input_path: string | null; input_mime: string }>(sql`select j.input_path, j.input_mime
    from trial_rebuilds r join trial_jobs j on j.id = r.job_id
    where r.id = ${f.id} and r.kind = 'listing' and r.status = 'running' and r.attempt = ${f.attempt}
      and r.lease_token = ${f.leaseToken} and r.lease_until > now()`);
  return r ? { name: r.input_path, mime: r.input_mime } : undefined;
}

export async function heartbeatRebuild(f: TrialRebuildLease): Promise<{ leaseUntil: string } | null> {
  const [r] = await rows<{ lease_until: string }>(sql`update trial_rebuilds set heartbeat_at = now(),
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int) where ${fenceR(f)} returning ${iso(sql`lease_until`)} as lease_until`);
  return r ? { leaseUntil: r.lease_until } : null;
}

type JobRow = { status: string; bundle_version: number; result_version: number; bundle_hash: string | null; released_rooms: unknown };

/** Новый `floorplanResult` задания (JSON + sha256) — только у пересборки по тексту агента (Р2-текст). */
export type NewResult = { json: string; hash: string };
type PublishOut = Published | "lease_lost" | "stale" | "result_unexpected";

/** Итог пересборки → одна новая версия данных страницы. "stale" — пока шла сборка, страница успела смениться: не публикуем.
 *  `result` (Р2-текст) пишется в задание той же транзакцией, что и версия: масштаб и комнаты страницы и `result` не расходятся. */
export async function publishRebuild(
  f: TrialRebuildLease & { jobId: string }, json: string, hash: string, dir = trialDir(), pin = ensureJobRelease, result?: NewResult,
): Promise<PublishOut> {
  const out = await db().transaction(async (tx): Promise<PublishOut> => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [cur] = await ex<{ job_id: string; base_version: number; rooms: unknown; kind: string }>(sql`select job_id, base_version, rooms,
        kind from trial_rebuilds where ${fenceR(f)} for update`);
    if (cur && result && cur.kind !== "listing") return "result_unexpected";
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
        ${same ? sql`` : sql`, result_version = ${next}, bundle_version = ${next}, bundle_hash = ${hash}`}
        ${result ? sql`, result = ${result.json}::jsonb, result_hash = ${result.hash}` : sql``} where id = ${cur.job_id}`);
    await tx.execute(sql`update trial_rebuilds set status = 'done', bundle_hash = ${hash}, result_version = ${next}, ${doneSet}
        where id = ${f.id}`);
    // правки комнат вошли в версию (воркер наложил все, что получил при claim; пока пересборка идёт, новых не принимают — `busy`)
    await tx.execute(sql`update trial_room_edits set built = true where job_id = ${cur.job_id} and not built`);
    return { version: next, repeated: same };
  });
  if (out === "lease_lost" || out === "stale" || out === "result_unexpected") return out;
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
