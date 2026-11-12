// Сроки хранения пробы (план agent-trial-01, T-A; поправки Codex 09.11 — ICO storage limitation). Зовёт
// `modules/retention/run.ts:runRetention` в своей транзакции под замком. Порядок: зависшие → failed/stale; файлы по
// `expires_at` (ошибка удаления оставляет ссылку — повтор в следующий раз); результаты по `result_expires_at` →
// «надгробие» `expired` без данных (страница 410); старые надгробия — удалить; сироты `.part` и файлы без записи — удалить.

import { promises as fs } from "node:fs";
import path from "node:path";
import { sql, type SQL } from "drizzle-orm";
import type { db } from "@/lib/db";
import { TRIAL_STALE_HOURS, TRIAL_TOMBSTONE_DAYS, trialDir, trialFileHours, trialKeepSourceForTour, trialResultDays } from "@/lib/trial/config";
import { removeBundles } from "@/lib/trial/bundle";
import { terminalSet } from "@/lib/trial/sql";
import { INPUT_NAME_RE, PREVIEW_NAME_RE, previewName, previewPath, removeInput } from "@/lib/trial/storage";
import { TOKEN_RE } from "@/lib/token";

type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];
export type TrialRetention = { kind: string; days: number | null; deleted: number; kept?: number };

const ORPHAN_AGE_MS = 3_600_000; // моложе часа может быть идущая загрузка
const q = async <T>(tx: Tx, s: SQL) => (await tx.execute(s)) as unknown as T[];

async function files(tx: Tx, now: Date, dir: string, rm: typeof fs.rm, keepForTour: boolean): Promise<{ deleted: number; kept: number }> {
  const at = now.toISOString();
  // хранение исходника готового тура до конца тура (Р2-текст, `trialKeepSourceForTour`): уходит вместе с результатом
  const tour = keepForTour ? sql`and (status <> 'done' or result_expires_at < ${at})` : sql``;
  const due = await q<{ id: string; input_path: string }>(tx, sql`select id, input_path from trial_jobs
    where input_path is not null and expires_at < ${at} ${tour} for update skip locked limit 1000`);
  const ok: string[] = [];
  for (const r of due) {
    try { await removeInput(dir, r.input_path, rm); ok.push(r.id); } catch { /* нет прав / занят — повторим */ }
  }
  if (ok.length) {
    await tx.execute(sql`update trial_jobs set input_path = null, input_deleted_at = now()
      where id in (${sql.join(ok.map((id) => sql`${id}`), sql`, `)})`);
  }
  return { deleted: ok.length, kept: due.length - ok.length };
}

async function orphans(tx: Tx, now: Date, dir: string): Promise<number> {
  const names = await fs.readdir(dir).catch(() => [] as string[]);
  const old: string[] = [];
  for (const n of names) {
    if (!n.endsWith(".part") && !INPUT_NAME_RE.test(n) && !PREVIEW_NAME_RE.test(n)) continue;
    const st = await fs.lstat(path.join(dir, n)).catch(() => null);
    if (st && st.mtimeMs < now.getTime() - ORPHAN_AGE_MS) old.push(n);
  }
  const finals = old.filter((n) => INPUT_NAME_RE.test(n) || PREVIEW_NAME_RE.test(n));
  const list = sql.join(finals.map((n) => sql`${n}`), sql`, `);
  const known = finals.length
    ? new Set((await q<{ name: string }>(tx, sql`select input_path as name from trial_jobs where input_path in (${list})
        union select preview_path from trial_jobs where preview_path in (${list})`)).map((r) => r.name))
    : new Set<string>();
  let n = 0;
  for (const name of old) {
    if (known.has(name)) continue;
    if (await fs.rm(path.join(dir, name), { force: true }).then(() => true, () => false)) n++;
  }
  return n;
}

/** Папки данных страницы (`<id>/`) без живого задания старше часа: записи нет, или надгробие, а удаление в свой срок не удалось (повтор здесь). */
async function orphanBundleDirs(tx: Tx, now: Date, dir: string, rm: typeof fs.rm): Promise<number> {
  const names = (await fs.readdir(dir).catch(() => [] as string[])).filter((n) => TOKEN_RE.test(n));
  const old: string[] = [];
  for (const n of names) {
    const st = await fs.lstat(path.join(dir, n)).catch(() => null);
    if (st && st.isDirectory() && st.mtimeMs < now.getTime() - ORPHAN_AGE_MS) old.push(n);
  }
  if (!old.length) return 0;
  const alive = new Set((await q<{ id: string }>(tx, sql`select id from trial_jobs where status <> 'expired'
    and id in (${sql.join(old.map((n) => sql`${n}`), sql`, `)})`)).map((r) => r.id));
  let n = 0;
  for (const id of old) {
    if (alive.has(id)) continue;
    if (await removeBundles(dir, id, rm).then(() => true, () => false)) n++;
  }
  return n;
}

export async function trialRetention(tx: Tx, now: Date, env = process.env, rm: typeof fs.rm = fs.rm): Promise<TrialRetention[]> {
  const dir = trialDir(env);
  const stale = await q<{ id: string }>(tx, sql`update trial_jobs set status = 'failed', error_code = 'stale', ${terminalSet(env)}
    where status in ('queued', 'running') and created_at < ${new Date(now.getTime() - TRIAL_STALE_HOURS * 3_600_000).toISOString()}
    returning id`);
  const f = await files(tx, now, dir, rm, trialKeepSourceForTour(env));
  const results = await q<{ id: string }>(tx, sql`update trial_jobs set status = 'expired', result = null, result_hash = null,
      listing_text = null, preview_path = null, input_hash = null, error_detail = null, lease_token = null, bundle_version = 0, bundle_hash = null
    where status in ('done', 'failed', 'cancelled') and input_path is null and result_expires_at < ${now.toISOString()} returning id`);
  // текст агента «размеры своими словами» (Р2-текст) не переживает результат, даже если пересборка так и не дошла до воркера
  await tx.execute(sql`update trial_rebuilds r set listing_text = null from trial_jobs j
    where j.id = r.job_id and j.status = 'expired' and r.listing_text is not null`);
  let bundlesKept = 0;
  for (const r of results) { // данные страницы и превью чертежа уходят вместе с результатом; не вышло — повторят `orphanBundleDirs`/`orphans`
    await removeBundles(dir, r.id, rm).catch(() => { bundlesKept++; });
    const pv = previewPath(dir, previewName(r.id));
    if (pv) await rm(pv, { force: true }).catch(() => undefined);
  }
  const tomb = await q<{ id: string }>(tx, sql`delete from trial_jobs where status = 'expired'
    and result_expires_at < ${new Date(now.getTime() - TRIAL_TOMBSTONE_DAYS * 86_400_000).toISOString()} returning id`);
  return [
    { kind: "trial_stale", days: null, deleted: stale.length },
    { kind: "trial_files", days: Math.ceil(trialFileHours(env) / 24), deleted: f.deleted, kept: f.kept },
    { kind: "trial_results", days: trialResultDays(env), deleted: results.length },
    { kind: "trial_bundles", days: trialResultDays(env), deleted: results.length - bundlesKept, kept: bundlesKept },
    { kind: "trial_tombstones", days: TRIAL_TOMBSTONE_DAYS, deleted: tomb.length },
    { kind: "trial_orphans", days: null, deleted: (await orphans(tx, now, dir)) + (await orphanBundleDirs(tx, now, dir, rm)) },
  ];
}
