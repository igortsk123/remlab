// Постановка автофото тура — outbox публикации подтверждённой пересборки (T-20261112-115 Ф2; Codex 12.11 § 1, 3). Вызывается ВНУТРИ
// транзакции `publishRebuild` (строка задания уже под замком — два подтверждения одного тура не пересекутся), сети не трогает: партия
// с версией данных + задачи-резервы по комнатам (`auto-photos-pick.ts`). Резерв — `INSERT … ON CONFLICT DO NOTHING` по UNIQUE задачи:
// комната, уже снятая (или снимаемая) в той же расстановке теми же ракурсами, второй раз не ставится. Деньги — до постановки: потолок тура
// (за всё время, факт `spent_rub`, пока нет — резерв) и суточный на все туры (скользящие 24 ч) — под общим замком бюджета
// (`pg_advisory_xact_lock`), чтобы два тура разом не перешли сутки. Что не встало — `refused` партии с кодом; переход порога
// предупреждения — `warn` партии и строка в журнале приложения.

import { sql } from "drizzle-orm";
import { randomToken } from "@/lib/token";
import { AUTO_RULES, pickAutoRooms, type AutoRefusal, type AutoRules } from "@/lib/trial/auto-photos-pick";
import { q, type Tx } from "@/lib/trial/repo-rebuild";

/** Сколько денег уже связано задачами: факт, пока нет — резерв; сорвавшиеся до заказа (`photo_id` пуст) — ноль. */
const COMMITTED = sql`coalesce(sum(case when t.photo_id is null and t.status in ('failed', 'skipped') then 0
  else coalesce(t.spent_rub, t.reserve_rub) end), 0)::float8`;
const BUDGET_LOCK = 7_115_036;   // номер замка бюджета автофото (T-115, миграция 036)

export type AutoQueued = { batchId: string; tasks: number; reservedRub: number; refused: (AutoRefusal | { room: string; code: string })[];
  warn: string | null } | null;

export async function enqueueAutoPhotos(tx: Tx, a: { jobId: string; version: number; rebuildId: string; json: string },
  rules: AutoRules = AUTO_RULES): Promise<AutoQueued> {
  let bundle: unknown;
  try { bundle = JSON.parse(a.json); } catch { bundle = null; }
  const { picks, refused } = bundle ? pickAutoRooms(bundle, rules) : { picks: [], refused: [{ room: "*", code: "bad_bundle" as const }] };
  const out: { room: string; code: string }[] = [...refused];
  const batchId = randomToken();
  const made = await q<{ id: string }>(tx, sql`insert into trial_photo_batches (id, job_id, rebuild_id, bundle_version)
      values (${batchId}, ${a.jobId}, ${a.rebuildId}, ${a.version}) on conflict (rebuild_id) do nothing returning id`);
  if (!made.length) return null;                                 // эта публикация уже поставила свою партию (повтор тела)
  await tx.execute(sql`select pg_advisory_xact_lock(${BUDGET_LOCK})`);
  const [tour] = await q<{ rub: number }>(tx, sql`select ${COMMITTED} as rub from trial_photo_tasks t where t.job_id = ${a.jobId}`);
  const [day] = await q<{ rub: number }>(tx, sql`select ${COMMITTED} as rub from trial_photo_tasks t
      where t.created_at > now() - interval '24 hours'`);
  let tourRub = tour?.rub ?? 0, dayRub = day?.rub ?? 0, n = 0, reserved = 0;
  for (const p of picks) {
    const taken = await q<{ id: string }>(tx, sql`select id from trial_photo_tasks where job_id = ${a.jobId} and room_id = ${p.roomId}
        and variant_sig = ${p.variantSig} and cams_sig = ${p.camsSig} and quality = ${rules.quality}`);
    if (taken.length) continue;                                  // уже снято/снимается в этой расстановке — не тратим и не отказ
    if (tourRub + rules.reserve_rub > rules.tour_cap_rub) { out.push({ room: p.roomId, code: "tour_cap" }); continue; }
    if (dayRub + rules.reserve_rub > rules.daily_cap_rub) { out.push({ room: p.roomId, code: "daily_cap" }); continue; }
    const ins = await q<{ id: string }>(tx, sql`insert into trial_photo_tasks (id, batch_id, job_id, room_id, variant_id, style, ord, area_m2,
        variant_sig, cams, cams_sig, quality, reserve_rub) values (${randomToken()}, ${batchId}, ${a.jobId}, ${p.roomId}, ${p.variantId},
        ${p.style}, ${n}, ${p.areaM2}, ${p.variantSig}, ${JSON.stringify(p.cams)}::jsonb, ${p.camsSig}, ${rules.quality}, ${rules.reserve_rub})
        on conflict (job_id, room_id, variant_sig, cams_sig, quality) do nothing returning id`);
    if (!ins.length) continue;
    n++; reserved += rules.reserve_rub; tourRub += rules.reserve_rub; dayRub += rules.reserve_rub;
  }
  const warn = n && dayRub >= rules.daily_warn_rub ? "daily_warn" : null;
  if (warn) console.warn(`[trial-auto-photos] сутки автофото ${dayRub} ₽ ≥ ${rules.daily_warn_rub} ₽ (потолок ${rules.daily_cap_rub} ₽)`);
  if (out.length) console.info(`[trial-auto-photos] ${a.jobId}: не поставлено ${out.map((r) => `${r.room}:${r.code}`).join(", ")}`);
  await tx.execute(sql`update trial_photo_batches set tasks = ${n}, reserved_rub = ${reserved}, refused = ${JSON.stringify(out)}::jsonb,
      warn = ${warn}, status = ${n ? "queued" : "empty"}, finished_at = ${n ? null : sql`now()`} where id = ${batchId}`);
  return { batchId, tasks: n, reservedRub: reserved, refused: out, warn };
}
