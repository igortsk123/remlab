// Промежуточные версии данных страницы (план agent-trial-08, задача А; поправки Codex 09.11). Публикация — транзакция под блокировкой строки:
// проверка аренды → файл новой версии (целиком, подменой) → одним огороженным UPDATE манифест `bundle_version` + `result_version`. Читатель
// видит только версию из строки, поэтому файл без записи никому не виден; чужой или просроченный воркер не доходит до записи файла.
// Повтор того же содержимого — без новой версии. Задание не завершается: `acceptResult` остаётся единственным путём в `done`.

import { sql } from "drizzle-orm";
import type { TrialBundleIn } from "@/contracts/trial-bundle";
import { db } from "@/lib/db";
import { pruneBundles, readBundle, writeBundle } from "@/lib/trial/bundle";
import { validId } from "@/lib/trial/http";
import { fence, spentSet } from "@/lib/trial/repo-worker";
import { rows } from "@/lib/trial/sql";
import { trialDir } from "@/lib/trial/config";

const KEEP_VERSIONS = 2; // предыдущая остаётся: страница могла только что узнать её номер

type Published = { version: number; repeated: boolean };
type Row = { bundle_version: number; bundle_hash: string | null; result_version: number };

export async function publishBundle(
  f: Pick<TrialBundleIn, "id" | "attempt" | "leaseToken" | "spentUsd">, json: string, hash: string, dir = trialDir(),
): Promise<Published | "lease_lost"> {
  const out = await db().transaction(async (tx): Promise<Published | "lease_lost"> => {
    const got = (await tx.execute(sql`select bundle_version, bundle_hash, result_version from trial_jobs where ${fence(f)} for update`)) as unknown as Row[];
    const cur = got[0];
    if (!cur) return "lease_lost";
    if (cur.bundle_version > 0 && cur.bundle_hash === hash) return { version: cur.bundle_version, repeated: true };
    const next = cur.result_version + 1;
    await writeBundle(dir, f.id, next, json);
    // строка под замком: claim (skip locked) и heartbeat ждут запись файла; неудача UPDATE/коммита — файл без записи никому не виден
    const done = (await tx.execute(sql`update trial_jobs set result_version = ${next}, bundle_version = ${next}, bundle_hash = ${hash},
        ${spentSet(f.spentUsd)} where ${fence(f)} returning id`)) as unknown as { id: string }[];
    return done.length ? { version: next, repeated: false } : "lease_lost";
  });
  if (out !== "lease_lost" && !out.repeated) await pruneBundles(dir, f.id, out.version - KEEP_VERSIONS + 1).catch(() => undefined);
  return out;
}

type Info = { status: string; bundle_version: number; past_term: boolean };

/** Версия для опроса: undefined — нет задания; "expired" — снято по сроку (410); "not_ready" — ещё не публиковалось. */
export async function bundleInfo(id: string): Promise<{ version: number } | "expired" | "not_ready" | undefined> {
  const [r] = await rows<Info>(sql`select status, bundle_version, coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id}`);
  if (!r) return undefined;
  if (r.status === "expired" || r.past_term) return "expired";
  return r.bundle_version > 0 ? { version: r.bundle_version } : "not_ready";
}

export type LatestBundle = { version: number; json: string } | "not_ready" | "expired";

/** ЕДИНСТВЕННОЕ чтение данных страницы: последняя опубликованная версия задания. Страница получает `json` как `demo-data.json`, путь наружу не нужен.
 *  Неверный id, нет задания, нет публикации — `not_ready` (наружу 404); снято по сроку — `expired` (410). Файл мог смениться между строкой и чтением — один повтор. */
export async function latestBundle(id: string, dir = trialDir()): Promise<LatestBundle> {
  if (!validId(id)) return "not_ready";
  for (let tries = 0; tries < 2; tries++) {
    const info = await bundleInfo(id);
    if (!info || info === "not_ready") return "not_ready";
    if (info === "expired") return "expired";
    const json = await readBundle(dir, id, info.version);
    if (json !== null) return { version: info.version, json };
  }
  return "not_ready";
}
