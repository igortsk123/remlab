// Исполнитель автофото на DEV ↔ очередь (T-20261112-115 Ф2; `db/init/036-trial-auto-photos.sql`). Аренда партии — как у пересборок
// (`repo-rebuild-worker.ts`): claim скалярным подзапросом `skip locked` (урок devops-deploy: иначе одним запросом уходят несколько), attempt+1,
// новый lease_token; каждая отметка — под ограждением (leased, попытка, токен, аренда не истекла) и продлевает аренду. Версия данных тура
// сменилась после постановки — партия не снимается (`stale_version`): исполнитель снял бы другую расстановку. Сорвавшееся до заказа
// (`photo_id` пуст) возвращает резерв; место в UNIQUE остаётся занятым — та же расстановка не ставится снова (деньги важнее, Codex § 2).

import { sql, type SQL } from "drizzle-orm";
import type { AutoBatchClaimed, AutoFinishIn, AutoLease, AutoReleaseIn, AutoTaskIn, AutoTaskView } from "@/contracts/trial-auto-photos";
import type { PhotoCam } from "@/contracts/trial-photos";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { AUTO_RULES } from "@/lib/trial/auto-photos-pick";
import { iso, jsonOf, rows } from "@/lib/trial/sql";

const OPEN = sql`status in ('reserved', 'shooting')`;
const fence = (f: AutoLease): SQL => sql`id = ${f.batchId} and status = 'leased' and lease_token = ${f.leaseToken} and lease_until > now()`;
const renew = (): SQL => sql`lease_until = now() + make_interval(secs => ${AUTO_RULES.lease_s}::int)`;
const closeOpen = (batch: SQL, code: string, status: "failed" | "skipped" = "failed"): SQL => sql`update trial_photo_tasks
  set status = ${status}, fail_code = ${code}, updated_at = now() where batch_id in (${batch}) and ${OPEN}`;

/** Истёкшие аренды без попыток → партия failed, её открытые задачи → failed/lease_lost (резерв вернулся). */
export async function exhaustAutoBatches(): Promise<void> {
  const dead = sql`select id from trial_photo_batches where status = 'leased' and lease_until < now() and attempt >= max_attempts`;
  await db().execute(closeOpen(dead, "lease_lost"));
  await db().execute(sql`update trial_photo_batches set status = 'failed', finished_at = now(), lease_until = null, note = 'lease_lost'
    where status = 'leased' and lease_until < now() and attempt >= max_attempts`);
}

type ClaimRow = { id: string; job_id: string; bundle_version: number; attempt: number; lease_token: string; lease_until: string;
  current: number | null; alive: boolean; urgent: boolean };
type TaskRow = { id: string; room_id: string; variant_id: string; style: string; ord: number; cams: unknown; cams_sig: string; variant_sig: string;
  status: AutoTaskView["status"] };

/** Следующая партия под аренду или null. Устаревшую (версия тура ушла дальше, тур снят по сроку) закрывает сама и берёт следующую. */
export async function claimAutoBatch(workerId: string): Promise<AutoBatchClaimed | null> {
  await exhaustAutoBatches();
  for (let guard = 0; guard < 20; guard++) {
    const token = randomToken(24);
    const [b] = await rows<ClaimRow>(sql`update trial_photo_batches b set status = 'leased', attempt = b.attempt + 1, lease_token = ${token},
        ${renew()}, worker_id = ${workerId}
      where b.id = (select x.id from trial_photo_batches x join trial_jobs j on j.id = x.job_id
        where ((x.status = 'queued' and x.next_run_at <= now()) or (x.status = 'leased' and x.lease_until < now()))
          and x.attempt < x.max_attempts and j.status = 'done'
        order by x.created_at, x.id for update of x skip locked limit 1)
      returning b.id, b.job_id, b.bundle_version, b.attempt, b.lease_token, ${iso(sql`b.lease_until`)} as lease_until,
        (select j.bundle_version from trial_jobs j where j.id = b.job_id) as current,
        (select coalesce(j.result_expires_at > now(), true) from trial_jobs j where j.id = b.job_id) as alive,
        (b.attempt = 1 and b.created_at > now() - make_interval(secs => ${AUTO_RULES.urgent_window_s}::int)) as urgent`);
    if (!b) return null;
    const why = !b.alive ? "expired" : b.current !== b.bundle_version ? "stale_version" : null;
    if (why) {
      await db().execute(closeOpen(sql`${b.id}`, why, "skipped"));
      await db().execute(sql`update trial_photo_batches set status = 'done', finished_at = now(), lease_until = null, note = ${why}
        where id = ${b.id}`);
      continue;
    }
    const tasks = await rows<TaskRow>(sql`select id, room_id, variant_id, style, ord, cams, cams_sig, variant_sig, status
      from trial_photo_tasks where batch_id = ${b.id} and ${OPEN} order by ord`);
    return { batchId: b.id, leaseToken: b.lease_token, leaseUntil: b.lease_until, attempt: b.attempt, jobId: b.job_id,
      bundleVersion: b.bundle_version, tourPath: `/try/${b.job_id}/tour`, urgency: b.urgent ? "urgent" : "catchup",
      tasks: tasks.map((t) => ({ id: t.id, roomId: t.room_id, variantId: t.variant_id, style: t.style, ord: t.ord, cams: jsonOf<PhotoCam[]>(t.cams),
        camsSig: t.cams_sig, variantSig: t.variant_sig, status: t.status })) };
  }
  return null;
}

export type AutoTaskOut = { ok: true; status: AutoTaskView["status"]; leaseUntil: string }
  | { ok: false; error: "lease_lost" | "not_found" | "bad_transition" };

/** Отметка задачи под арендой партии (и продление аренды). Отметка без заказа — только у открытой задачи; `spent_rub` — только у заказанной. */
export async function markAutoTask(inp: AutoTaskIn): Promise<AutoTaskOut> {
  return db().transaction(async (tx) => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [b] = await ex<{ lease_until: string }>(sql`update trial_photo_batches set ${renew()} where ${fence(inp)}
        returning ${iso(sql`lease_until`)} as lease_until`);
    if (!b) return { ok: false, error: "lease_lost" } as const;
    const [t] = await ex<{ status: AutoTaskView["status"]; photo_id: string | null }>(sql`select status, photo_id from trial_photo_tasks
        where id = ${inp.taskId} and batch_id = ${inp.batchId} for update`);
    if (!t) return { ok: false, error: "not_found" } as const;
    let status = t.status;
    if (inp.status && inp.status !== t.status) {                 // та же отметка повторно — без изменений
      if (t.status !== "reserved" && t.status !== "shooting") return { ok: false, error: "bad_transition" } as const;
      await tx.execute(sql`update trial_photo_tasks set status = ${inp.status}, fail_code = ${inp.code ?? null}, updated_at = now()
          where id = ${inp.taskId}`);
      status = inp.status;
    }
    if (inp.spent_rub !== undefined) {
      if (!t.photo_id) return { ok: false, error: "bad_transition" } as const;
      await tx.execute(sql`update trial_photo_tasks set spent_rub = ${inp.spent_rub}, updated_at = now() where id = ${inp.taskId}`);
    }
    return { ok: true, status, leaseUntil: b.lease_until } as const;
  });
}

/** Тур ещё не готов к съёмке (съёмщик: TOUR_READY / exit 3) — партия обратно в очередь: попытка не тратится, взятые в работу задачи снова
 *  reserved, следующая выдача — не раньше `retry_s`. Возвратов больше `max_releases` — партия failed/tour_not_ready, резерв вернулся. */
export async function releaseAutoBatch(inp: AutoReleaseIn): Promise<{ ok: true; status: "queued" | "failed" } | { ok: false; error: "lease_lost" }> {
  return db().transaction(async (tx) => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [b] = await ex<{ releases: number }>(sql`select releases from trial_photo_batches where ${fence(inp)} for update`);
    if (!b) return { ok: false, error: "lease_lost" } as const;
    if (b.releases + 1 > AUTO_RULES.max_releases) {
      await tx.execute(closeOpen(sql`${inp.batchId}`, "tour_not_ready"));
      await tx.execute(sql`update trial_photo_batches set status = 'failed', finished_at = now(), lease_until = null,
          releases = releases + 1, note = 'tour_not_ready' where id = ${inp.batchId}`);
      return { ok: true, status: "failed" } as const;
    }
    await tx.execute(sql`update trial_photo_tasks set status = 'reserved', updated_at = now()
        where batch_id = ${inp.batchId} and status = 'shooting' and photo_id is null`);
    await tx.execute(sql`update trial_photo_batches set status = 'queued', attempt = greatest(attempt - 1, 0), lease_token = null,
        lease_until = null, releases = releases + 1, note = ${inp.code},
        next_run_at = now() + make_interval(secs => ${AUTO_RULES.retry_s}::int) where id = ${inp.batchId}`);
    return { ok: true, status: "queued" } as const;
  });
}

/** Закрыть партию: открытые задачи → failed/abandoned (резерв вернулся), партия → done. Повтор после закрытия — `lease_lost`. */
export async function finishAutoBatch(inp: AutoFinishIn): Promise<{ ok: true; abandoned: number } | { ok: false; error: "lease_lost" }> {
  return db().transaction(async (tx) => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [b] = await ex<{ id: string }>(sql`select id from trial_photo_batches where ${fence(inp)} for update`);
    if (!b) return { ok: false, error: "lease_lost" } as const;
    const left = await ex<{ id: string }>(sql`update trial_photo_tasks set status = 'failed', fail_code = 'abandoned', updated_at = now()
        where batch_id = ${inp.batchId} and ${OPEN} returning id`);
    await tx.execute(sql`update trial_photo_batches set status = 'done', finished_at = now(), lease_until = null, note = ${inp.note ?? null}
        where id = ${inp.batchId}`);
    return { ok: true, abandoned: left.length } as const;
  });
}
