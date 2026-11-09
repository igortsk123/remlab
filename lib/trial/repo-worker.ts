// Мост прод ↔ воркер DEV (план agent-trial-01, T-A; поправки Codex 09.11). ОГРАЖДЕНИЕ: claim → attempt+1 и новый
// случайный lease_token; heartbeat/result — одним UPDATE с проверкой status/attempt/lease_token/lease_until>now(),
// fail — тем же условием под блокировкой строки. Просроченная аренда не продлевается; claim берёт только
// attempt < max_attempts, исчерпанные с истёкшей арендой — отдельным UPDATE в failed/lease_lost.

import { sql } from "drizzle-orm";
import type { TrialClaimed, TrialFailIn, TrialHeartbeatIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { TRIAL_LEASE_SEC } from "@/lib/trial/config";
import { claimable, iso, rows, terminalSet } from "@/lib/trial/sql";

const NOW_ISO = iso(sql`now()`);
export const fence = (f: { id: string; attempt: number; leaseToken: string }) => sql`id = ${f.id} and status = 'running'
  and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and lease_until > now()`;
export const spentSet = (v?: number) => sql`spent_usd = greatest(spent_usd, ${v ?? 0}::numeric)`;
const stagePush = (stage: string) => sql`stages || jsonb_build_array(jsonb_build_object('stage', ${stage}::text, 'at', ${NOW_ISO}))`;

/** «Воркер жив» — на каждом опросе, в том числе когда он сам себя притормозил. */
export async function touchWorker(id: string, version?: string): Promise<void> {
  await db().execute(sql`insert into trial_workers (id, last_seen, version) values (${id}, now(), ${version ?? null})
    on conflict (id) do update set last_seen = now(), version = excluded.version`);
}

/** Исчерпанные попытки с истёкшей арендой → failed/lease_lost (иначе висели бы «running» навсегда). */
export async function exhaustExpired(): Promise<number> {
  const r = await rows<{ id: string }>(sql`update trial_jobs set status = 'failed', error_code = 'lease_lost', ${terminalSet()}
    where status = 'running' and lease_until < now() and attempt >= max_attempts returning id`);
  return r.length;
}

type ClaimRow = {
  id: string; kind: string; attempt: number; lease_token: string; lease_until: string; input_mime: string;
  input_bytes: number; input_hash: string | null; listing_text: string | null; budget_usd: string;
};

export async function claim(workerId: string): Promise<TrialClaimed | null> {
  await exhaustExpired();
  const token = randomToken(24);
  const [r] = await rows<ClaimRow>(sql`update trial_jobs j set status = 'running', attempt = j.attempt + 1,
      lease_token = ${token}, lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int), worker_id = ${workerId},
      heartbeat_at = now(), started_at = coalesce(j.started_at, now())
    from (select id from trial_jobs t where ${claimable(sql.raw("t"))} order by created_at, id for update skip locked limit 1) c
    where j.id = c.id
    returning j.id, j.kind, j.attempt, j.lease_token, ${iso(sql`j.lease_until`)} as lease_until, j.input_mime, j.input_bytes,
      j.input_hash, j.listing_text, j.budget_usd`);
  if (!r) return null;
  return {
    id: r.id, kind: r.kind, attempt: r.attempt, leaseToken: r.lease_token, leaseUntil: r.lease_until, inputMime: r.input_mime,
    inputBytes: r.input_bytes, inputHash: r.input_hash, listingText: r.listing_text, budgetUsd: Number(r.budget_usd),
  };
}

/** Продлить аренду и отметить шаг. null — аренда потеряна (истекла или задание забрал другой). */
export async function heartbeat(h: TrialHeartbeatIn): Promise<{ leaseUntil: string } | null> {
  const [r] = await rows<{ lease_until: string }>(sql`update trial_jobs set
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int), heartbeat_at = now(),
      stages = case when stage = ${h.stage} then stages else ${stagePush(h.stage)} end, stage = ${h.stage}, ${spentSet(h.spentUsd)}
    where ${fence(h)} returning ${iso(sql`lease_until`)} as lease_until`);
  return r ? { leaseUntil: r.lease_until } : null;
}

/** Принять результат. "again" — тот же результат той же аренды пришёл повторно (ответ потерялся) — тоже успех. */
export async function acceptResult(
  f: { id: string; attempt: number; leaseToken: string; spentUsd?: number }, json: string, hash: string,
): Promise<"ok" | "again" | "lease_lost"> {
  const done = await rows<{ id: string }>(sql`update trial_jobs set status = 'done', stage = 'done', stages = ${stagePush("done")},
      result = ${json}::jsonb, result_hash = ${hash}, result_version = result_version + 1, error_code = null,
      ${spentSet(f.spentUsd)}, ${terminalSet()}
    where ${fence(f)} returning id`);
  if (done.length) return "ok";
  const same = await rows<{ id: string }>(sql`select id from trial_jobs where id = ${f.id} and status = 'done'
    and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and result_hash = ${hash}`);
  return same.length ? "again" : "lease_lost";
}

/** Сбой у воркера: повторяемый и попытки есть → снова в очередь; иначе failed. `waiting_capacity` попытку не тратит. */
export async function failJob(f: TrialFailIn): Promise<"queued" | "failed" | "lease_lost"> {
  return db().transaction(async (tx) => {
    const got = (await tx.execute(sql`select attempt, max_attempts from trial_jobs where ${fence(f)} for update`)) as unknown as
      { attempt: number; max_attempts: number }[];
    const cur = got[0];
    if (!cur) return "lease_lost";
    const refund = f.code === "waiting_capacity";
    const attempt = refund ? cur.attempt - 1 : cur.attempt;
    const requeue = (refund || f.retryable) && attempt < cur.max_attempts;
    const code = refund ? null : f.code;
    const detail = f.detail?.slice(0, 2000) ?? null;
    await tx.execute(requeue
      ? sql`update trial_jobs set status = 'queued', attempt = ${attempt}, lease_token = null, lease_until = null,
          next_run_at = now() + make_interval(secs => ${f.retryAfterSec ?? 30}::int), error_code = ${code},
          error_detail = ${detail}, ${spentSet(f.spentUsd)} where id = ${f.id}`
      : sql`update trial_jobs set status = 'failed', error_code = ${f.code === "waiting_capacity" ? "timeout" : f.code},
          error_detail = ${detail}, ${spentSet(f.spentUsd)}, ${terminalSet()} where id = ${f.id}`);
    return requeue ? "queued" : "failed";
  });
}

/** Имя файла задания для ТЕКУЩЕЙ аренды; undefined — аренды нет, null — файл уже удалён по сроку. */
export async function leasedInput(f: { id: string; attempt: number; leaseToken: string }): Promise<{ name: string | null; mime: string } | undefined> {
  const [r] = await rows<{ input_path: string | null; input_mime: string }>(sql`select input_path, input_mime from trial_jobs where ${fence(f)}`);
  return r ? { name: r.input_path, mime: r.input_mime } : undefined;
}
