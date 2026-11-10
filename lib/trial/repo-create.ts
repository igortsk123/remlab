// Постановка задания пробы (план agent-trial-01, T-A). Допуск — дважды: дешёвая проверка ДО чтения тела (не качать 15 МБ
// в полную очередь) и окончательная — под advisory-замком при записи (конкурентные загрузки не пробивают лимит очереди
// и суточный потолок). Файл переезжает из `.part` в `<id>.<ext>` ВНУТРИ транзакции: rename упал → записи нет; запись не
// закоммитилась → файл удаляется. Ни `.part`, ни сирот.

import { promises as fs } from "node:fs";
import path from "node:path";
import { sql } from "drizzle-orm";
import { trialJobs } from "@/db/schema";
import { db } from "@/lib/db";
import { POLICY_VERSION } from "@/lib/legal/policy";
import { trialDailyCap, trialQueueMax } from "@/lib/trial/config";
import { rows } from "@/lib/trial/sql";
import { inputName } from "@/lib/trial/storage";
import type { Staged } from "@/lib/trial/upload";

const LOCK_KEY = 2026110908; // advisory-замок допуска заданий пробы
export type Admission = "ok" | "busy" | "daily_cap";

const COUNTS = sql`select count(*) filter (where status = 'queued')::int as queued,
  count(*) filter (where created_at > now() - interval '24 hours')::int as day
  from trial_jobs where status = 'queued' or created_at > now() - interval '24 hours'`;

/** `own` — наша машина (`lib/trial/own-key.ts`): суточный потолок сайта не проверяем, очередь — да. */
function decide(c: { queued: number; day: number } | undefined, env: NodeJS.ProcessEnv, own: boolean): Admission {
  if (!own && (c?.day ?? 0) >= trialDailyCap(env)) return "daily_cap";
  if ((c?.queued ?? 0) >= trialQueueMax(env)) return "busy";
  return "ok";
}

/** Без замка — только чтобы не принимать тело заведомо зря. */
export async function admissionPrecheck(env = process.env, own = false): Promise<Admission> {
  const [c] = await rows<{ queued: number; day: number }>(COUNTS);
  return decide(c, env, own);
}

/** `editKeyHash` — sha256 ключа правки агента (`lib/trial/edit-key.ts`); сам ключ в базу не попадает. */
export async function commitUpload(
  staged: Staged, id: string, dir: string, env = process.env, editKeyHash: string | null = null, own = false,
): Promise<Admission> {
  const finalPath = path.join(dir, inputName(id, staged.mime));
  let renamed = false;
  try {
    const verdict = await db().transaction(async (tx) => {
      await tx.execute(sql`select pg_advisory_xact_lock(${LOCK_KEY})`);
      const c = ((await tx.execute(COUNTS)) as unknown as { queued: number; day: number }[])[0];
      const v = decide(c, env, own);
      if (v !== "ok") return v;
      await tx.insert(trialJobs).values({
        id, inputHash: staged.inputHash, inputPath: path.basename(finalPath), inputMime: staged.mime, inputBytes: staged.bytes,
        listingText: staged.listing, consentVersion: POLICY_VERSION, editKeyHash,
      });
      await fs.rename(staged.partPath, finalPath);
      renamed = true;
      return v;
    });
    if (verdict !== "ok") await fs.rm(staged.partPath, { force: true });
    return verdict;
  } catch (e) {
    await fs.rm(staged.partPath, { force: true }).catch(() => undefined);
    if (renamed) await fs.rm(finalPath, { force: true }).catch(() => undefined); // запись не закоммитилась — файл сирота
    throw e;
  }
}
