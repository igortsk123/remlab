// Пересборки «Обустроить» для воркера DEV (план agent-trial-08, Р1). Аренда и ограждение — как у заданий (`repo-worker.ts`): claim →
// attempt+1 и новый lease_token; heartbeat/publish/fail — с проверкой status/attempt/lease_token/lease_until>now(). Публикация —
// транзакция: строка пересборки и строка задания под замком → `base_version` ещё текущая (иначе `stale`, ничего не пишем) → файл
// новой версии → манифест задания (+ накопленные снятые комнаты) → пересборка `done`. Повтор того же тела той же аренды — успех без
// новой версии. Приоритет над новыми загрузками — с квотой (`rebuildFirst`).

import { sql, type SQL } from "drizzle-orm";
import type {
  TrialOpeningEdit, TrialRebuildClaimed, TrialRebuildFailIn, TrialRebuildLease, TrialRebuildProgressIn, TrialRoomEdit,
} from "@/contracts/trial";
import type { TrialReparseMap } from "@/contracts/trial-bundle";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { enqueueAutoPhotosSafe } from "@/lib/trial/auto-photos-queue";
import { pruneBundles, readBundle, writeBundle } from "@/lib/trial/bundle";
import { TRIAL_LEASE_SEC, trialDir, trialRebuildQuota } from "@/lib/trial/config";
import { KEEP_VERSIONS, pinAfterPublish, type Published } from "@/lib/trial/repo-bundle";
import { applyReparseMap } from "@/lib/trial/repo-reparse-map";
import { claimable, iso, jsonOf, rows } from "@/lib/trial/sql";
import { repinCurrentRelease } from "@/lib/trial/tour-bundle";

const fenceR = (f: TrialRebuildLease) => sql`id = ${f.id} and status = 'running'
  and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and lease_until > now()`;
// конец пересборки: текст агента (`listing`) больше не нужен — не храним
const doneSet = sql`finished_at = now(), lease_until = null, listing_text = null`;
/** Ход на публикации: все комнаты хода посчитаны (`done = total`), замеры стадий — для оценки следующих пересборок (`rebuild-eta.ts`). */
const progressDone = (timings?: Record<string, number>): SQL => sql`(select p || jsonb_build_object('done', coalesce(p->'total', '0'::jsonb),
    'rooms', coalesce((select jsonb_object_agg(k, to_jsonb('ready'::text)) from jsonb_object_keys(coalesce(p->'rooms', '{}'::jsonb)) k), '{}'::jsonb))
    ${timings ? sql`|| jsonb_build_object('timings', ${JSON.stringify(timings)}::jsonb)` : sql``}
  from (select coalesce(progress, '{}'::jsonb) as p) x)`;
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
  kind: "furnish" | "listing" | "edit" | "reparse"; listing_text: string | null; confirm: boolean;
};
type EditRow = { panel: string; src_id: string; anchor: unknown; name: string; kind: string; w_cm: number | null; d_cm: number | null; built: boolean;
  dims_ok: boolean };
/** Что умеет воркер: `listing` — пересборки по тексту агента (Р2-текст), `edit` — правки комнат (T-20261110-36), `reparse` — перечитать
 *  планировку по оператору (T-20261111-02; только вместе с `edit`: правки агента к ней обязательны). `true` — старая форма: listing. */
export type RebuildSkills = boolean | { listing?: boolean; edit?: boolean; reparse?: boolean };

/** Правки комнат задания — воркеру, который их умеет: он накладывает их на копию `result` перед любой сборкой. ТОЛЬКО подтверждённые
 *  (T-20261111-16): строка-черновик (`confirmed_at` null) не едет ни в одну сборку, у подтверждённой с черновиком — её подтверждённые
 *  значения (черновик лежит в `draft`). `drafts` — наоборот, только строки-черновики: их получает `reparse`, чтобы перевести на новые
 *  номера той же картой (T-20261111-16/2), в сборку они не идут. */
export async function editsOf(jobId: string, drafts = false): Promise<TrialRoomEdit[]> {
  const got = await rows<EditRow>(sql`select panel, src_id, anchor, name, kind, w_cm, d_cm, built, dims_ok from trial_room_edits
    where job_id = ${jobId} and confirmed_at is ${drafts ? sql`null` : sql`not null`} order by created_at, room_key`);
  return got.map((e) => ({ panel: e.panel, srcId: e.src_id, anchor: jsonOf<{ x: number; y: number }>(e.anchor), name: e.name, kind: e.kind,
    wCm: e.w_cm, dCm: e.d_cm, built: e.built, dimsOk: e.dims_ok }));
}

type OpeningRow = { op_key: string; panel: string; src_idx: number | null; src_c: unknown; kind: "door" | "window"; c: unknown;
  width_cm: number; removed: boolean; built: boolean };
/** Окна и двери агента (T-20261110-39) — тому же воркеру: накладываются на копию `result` после правок комнат. Только подтверждённые
 *  (`drafts` — только черновики, как у `editsOf`). */
export async function openingEditsOf(jobId: string, drafts = false): Promise<TrialOpeningEdit[]> {
  const got = await rows<OpeningRow>(sql`select op_key, panel, src_idx, src_c, kind, c, width_cm, removed, built from trial_opening_edits
    where job_id = ${jobId} and confirmed_at is ${drafts ? sql`null` : sql`not null`} order by created_at, op_key`);
  return got.map((e) => ({ panel: e.panel, key: e.op_key.slice(e.panel.length + 1), srcIdx: e.src_idx,
    srcC: e.src_c === null ? null : jsonOf<[number, number]>(e.src_c), kind: e.kind, c: jsonOf<[number, number]>(e.c), widthCm: e.width_cm,
    removed: e.removed, built: e.built }));
}

/** Одна пересборка под аренду — скалярным подзапросом, как `repo-worker.ts:claim` (почему не `from (…) c` — там).
 *  Старый воркер пересборок по тексту и правок не получает. У `listing`, `edit` и `reparse` база версии при claim — ТЕКУЩАЯ версия данных
 *  (поколение после `done`): текст приняли на v1, задание дошло до v3 — это не «устарело»; перевыпуск между постановкой `reparse` и claim —
 *  тоже не отказ (сверяет публикация). `reparse` получает ИСХОДНЫЙ текст объявления задания и точные байты версии `baseVersion`. */
export async function claimRebuild(workerId: string, skills: RebuildSkills = false, dir = trialDir()): Promise<TrialRebuildClaimed | null> {
  const listing = skills === true || (typeof skills === "object" && skills.listing === true);
  const edit = typeof skills === "object" && skills.edit === true;
  const reparse = edit && typeof skills === "object" && skills.reparse === true;
  await exhaustRebuilds();
  const token = randomToken(24);
  const [r] = await rows<ClaimRow>(sql`update trial_rebuilds r set status = 'running', attempt = r.attempt + 1, lease_token = ${token},
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int), worker_id = ${workerId}, heartbeat_at = now(),
      started_at = coalesce(r.started_at, now()),
      base_version = case when r.kind in ('listing', 'edit', 'reparse') then (select j.bundle_version from trial_jobs j where j.id = r.job_id)
        else r.base_version end
    where r.id = (select x.id from trial_rebuilds x join trial_jobs j on j.id = x.job_id
      where (x.status = 'queued' or (x.status = 'running' and x.lease_until < now())) and x.attempt < x.max_attempts and j.status = 'done'
        and (x.kind = 'furnish' or (x.kind = 'listing' and ${listing}) or (x.kind = 'edit' and ${edit}) or (x.kind = 'reparse' and ${reparse}))
      order by x.created_at, x.id for update of x skip locked limit 1)
    returning r.id, r.job_id, r.attempt, r.lease_token, ${iso(sql`r.lease_until`)} as lease_until, r.rooms, r.base_version, r.kind,
      r.listing_text, coalesce((r.progress->>'confirm')::boolean, false) as confirm`);
  if (!r) return null;
  const [j] = await rows<{ result: unknown; released_rooms: unknown; input_mime: string; listing_text: string | null }>(sql`select result,
    released_rooms, input_mime, listing_text from trial_jobs where id = ${r.job_id}`);
  return {
    id: r.id, jobId: r.job_id, attempt: r.attempt, leaseToken: r.lease_token, leaseUntil: r.lease_until,
    rooms: union(j?.released_rooms, r.rooms), baseVersion: r.base_version, result: j ? jsonOf(j.result) : null, kind: r.kind,
    ...(r.kind === "listing" ? { listingText: r.listing_text ?? "", inputMime: j?.input_mime ?? "" } : {}),
    ...(r.kind === "reparse" ? { listingText: j?.listing_text ?? "", inputMime: j?.input_mime ?? "",
      bundle: (await readBundle(dir, r.job_id, r.base_version)) ?? undefined } : {}),
    ...(edit ? { edits: await editsOf(r.job_id), openingEdits: await openingEditsOf(r.job_id) } : {}),
    ...(r.kind === "reparse" ? { draftEdits: await editsOf(r.job_id, true), draftOpeningEdits: await openingEditsOf(r.job_id, true) } : {}),
    ...(r.kind === "edit" && r.confirm ? { confirm: true } : {}),
  };
}

/** Исходный лист задания — пересборке по тексту агента (и «перечитать планировку») под ТЕКУЩЕЙ арендой; undefined — аренды нет,
 *  `name: null` — файл удалён по сроку. */
export async function leasedRebuildInput(f: TrialRebuildLease): Promise<{ name: string | null; mime: string } | undefined> {
  const [r] = await rows<{ input_path: string | null; input_mime: string }>(sql`select j.input_path, j.input_mime
    from trial_rebuilds r join trial_jobs j on j.id = r.job_id
    where r.id = ${f.id} and r.kind in ('listing', 'reparse') and r.status = 'running' and r.attempt = ${f.attempt}
      and r.lease_token = ${f.leaseToken} and r.lease_until > now()`);
  return r ? { name: r.input_path, mime: r.input_mime } : undefined;
}

/** Продление аренды; `progress` (T-20261111-16) — ход по комнатам от воркера: поверх хода строки (оценку времени сервера не трогает). */
export async function heartbeatRebuild(f: TrialRebuildLease & { progress?: TrialRebuildProgressIn }): Promise<{ leaseUntil: string } | null> {
  const p = f.progress ? sql`, progress = coalesce(progress, '{}'::jsonb) || ${JSON.stringify(f.progress)}::jsonb` : sql``;
  const [r] = await rows<{ lease_until: string }>(sql`update trial_rebuilds set heartbeat_at = now(),
      lease_until = now() + make_interval(secs => ${TRIAL_LEASE_SEC}::int) ${p} where ${fenceR(f)}
      returning ${iso(sql`lease_until`)} as lease_until`);
  return r ? { leaseUntil: r.lease_until } : null;
}

type JobRow = { status: string; bundle_version: number; result_version: number; bundle_hash: string | null; released_rooms: unknown;
  result_hash: string | null };

/** Новый `floorplanResult` задания (JSON + sha256) — только у пересборки по тексту агента (Р2-текст) и «перечитать планировку». */
export type NewResult = { json: string; hash: string };
type PublishOut = Published | "lease_lost" | "stale" | "result_unexpected";

/** Итог пересборки → одна новая версия данных страницы. "stale" — пока шла сборка, страница успела смениться: не публикуем.
 *  `result` (Р2-текст, `reparse`) пишется в задание той же транзакцией, что и версия: масштаб и комнаты страницы и `result` не расходятся.
 *  «Та же версия» — только если совпали ОБА хэша (страница и `result`): новый канон при тех же байтах страницы — всё равно новая версия.
 *  `map` (только `reparse`): снятые комнаты новыми id страницы (заменяют накопленные) и правки агента на новые номера комнат/проёмов. */
export async function publishRebuild(
  f: TrialRebuildLease & { jobId: string; timings?: Record<string, number> }, json: string, hash: string, dir = trialDir(),
  pin = repinCurrentRelease, result?: NewResult, map?: TrialReparseMap,
): Promise<PublishOut> {
  const out = await db().transaction(async (tx): Promise<PublishOut> => {
    const ex = async <T>(q: SQL) => (await tx.execute(q)) as unknown as T[];
    const [cur] = await ex<{ job_id: string; base_version: number; rooms: unknown; kind: string; confirm: boolean }>(sql`select job_id,
        base_version, rooms, kind, coalesce((progress->>'confirm')::boolean, false) as confirm from trial_rebuilds where ${fenceR(f)} for update`);
    if (cur && ((result && cur.kind !== "listing" && cur.kind !== "reparse") || (map && cur.kind !== "reparse"))) return "result_unexpected";
    if (!cur || cur.job_id !== f.jobId) {
      const [again] = await ex<{ result_version: number }>(sql`select result_version from trial_rebuilds where id = ${f.id}
          and job_id = ${f.jobId} and status = 'done' and attempt = ${f.attempt} and lease_token = ${f.leaseToken} and bundle_hash = ${hash}`);
      return again ? { version: again.result_version, repeated: true } : "lease_lost";
    }
    const [job] = await ex<JobRow>(sql`select status, bundle_version, result_version, bundle_hash, released_rooms, result_hash
        from trial_jobs where id = ${cur.job_id} for update`);
    if (!job || job.status !== "done" || job.bundle_version !== cur.base_version) {
      await tx.execute(sql`update trial_rebuilds set status = 'failed', error_code = 'stale', ${doneSet} where id = ${f.id}`);
      return "stale";
    }
    const released = JSON.stringify(map ? [...new Set(map.released)] : union(job.released_rooms, cur.rooms));
    const same = job.bundle_hash === hash && (!result || job.result_hash === result.hash);
    const next = same ? job.bundle_version : job.result_version + 1;
    if (!same) await writeBundle(dir, cur.job_id, next, json);
    await tx.execute(sql`update trial_jobs set released_rooms = ${released}::jsonb
        ${same ? sql`` : sql`, result_version = ${next}, bundle_version = ${next}, bundle_hash = ${hash}`}
        ${result ? sql`, result = ${result.json}::jsonb, result_hash = ${result.hash}` : sql``} where id = ${cur.job_id}`);
    await tx.execute(sql`update trial_rebuilds set status = 'done', bundle_hash = ${hash}, result_version = ${next}, ${doneSet},
        progress = ${progressDone(f.timings)} where id = ${f.id}`);
    if (map) {
      const dropped = await applyReparseMap(tx, cur.job_id, map);
      if (dropped.length) {
        await tx.execute(sql`update trial_rebuilds set progress = coalesce(progress, '{}'::jsonb)
            || jsonb_build_object('dropped_drafts', ${JSON.stringify(dropped)}::jsonb) where id = ${f.id}`);
      }
    }
    // правки вошли в версию — только те, что воркер получил при claim (T-20261111-16): подтверждённые под эту пересборку (`rebuild_id`)
    // и подтверждённые до её постановки (прошлая пересборка не удалась). Черновики и правки, пришедшие во время сборки, остаются `built=false`.
    for (const t of [sql`trial_room_edits`, sql`trial_opening_edits`]) {
      await tx.execute(sql`update ${t} set built = true where job_id = ${cur.job_id} and not built and confirmed_at is not null
          and (rebuild_id = ${f.id} or confirmed_at < (select created_at from trial_rebuilds where id = ${f.id}))`);
    }
    // агент подтвердил планировку — автофото тура в очередь той же транзакцией (outbox, T-20261112-115 Ф2); сети здесь нет.
    // Своей точкой сохранения: сбой постановки не откатывает подтверждение (T-115/3)
    if (cur.kind === "edit" && cur.confirm) await enqueueAutoPhotosSafe(tx, { jobId: cur.job_id, version: next, rebuildId: f.id, json });
    return { version: next, repeated: same };
  });
  if (out === "lease_lost" || out === "stale" || out === "result_unexpected") return out;
  if (!out.repeated) await pruneBundles(dir, f.jobId, out.version - KEEP_VERSIONS + 1).catch(() => undefined);
  // витрина — ТЕКУЩАЯ (T-20261112-92): пересборка агента после выкладки не оставляет новые данные на старой странице
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
