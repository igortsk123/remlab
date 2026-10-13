// Удаление по срокам хранения (план b2b-04, ADR-0268). Срок каждого вида данных — из env; НЕ задан → ничего
// не удаляем и пишем в журнал «срок не задан» (сроки заявок и контактов — решение владельца, не код).
// Трейсы ИИ — по TRACE_RETENTION_DAYS (90 по умолчанию, как `tools/trace-prune.mjs`). Каждое выполнение —
// строка в `retention_runs`: видно, что и сколько удалено.
//
// Разбор Codex 13.10: всё — в ОДНОЙ транзакции под advisory-замком (второй одновременный запуск пропускается,
// а не пишет в журнал чужие числа); заявка удаляется вместе с перепиской атомарно (сначала переписка);
// строка трейса удаляется ТОЛЬКО после успешного удаления его файлов — иначе фото осталось бы на диске без
// записи, по которой его можно найти.

import { promises as fs } from "node:fs";
import path from "node:path";
import { and, inArray, isNotNull, lt, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { flatConfigs, generationAssets, generationRuns, generationSteps, leadMessages, leads, retentionRuns } from "@/db/schema";
import { TRACE_DIR } from "@/lib/trace/assets";

export type RetentionResult = { kind: string; days: number | null; deleted: number; kept?: number };
type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];

const LOCK_KEY = 2026101304; // advisory-замок удаления по срокам (любое постоянное число)

/** Срок в днях из env: целое > 0, иначе null («не задан»). */
export function daysFrom(v: string | undefined): number | null {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : null;
}

const cutoff = (now: Date, days: number) => new Date(now.getTime() - days * 86_400_000);

/** Удалить файлы прогонов; вернуть те, чьи файлы удалены (строки остальных остаются до следующего раза). */
export async function removeRunFiles(ids: string[], dir = TRACE_DIR, rm = fs.rm): Promise<string[]> {
  const ok: string[] = [];
  for (const id of ids) {
    try {
      await rm(path.join(dir, id), { recursive: true, force: true });
      ok.push(id);
    } catch {
      // нет прав / занят — строку не трогаем, повторим завтра
    }
  }
  return ok;
}

async function traces(tx: Tx, now: Date, days: number): Promise<{ deleted: number; kept: number }> {
  const old = await tx.select({ id: generationRuns.id }).from(generationRuns).where(lt(generationRuns.startedAt, cutoff(now, days)));
  const ids = await removeRunFiles(old.map((r) => r.id));
  if (ids.length) {
    await tx.delete(generationAssets).where(inArray(generationAssets.runId, ids));
    await tx.delete(generationSteps).where(inArray(generationSteps.runId, ids));
    await tx.delete(generationRuns).where(inArray(generationRuns.id, ids));
  }
  // временные оригиналы сжатия старше суток (свежие может держать идущее сжатие)
  const tmp = path.join(TRACE_DIR, "_tmp");
  for (const f of await fs.readdir(tmp).catch(() => [] as string[])) {
    const p = path.join(tmp, f);
    const st = await fs.stat(p).catch(() => null);
    if (st && st.mtimeMs < now.getTime() - 86_400_000) await fs.rm(p, { recursive: true, force: true }).catch(() => undefined);
  }
  return { deleted: ids.length, kept: old.length - ids.length };
}

async function oldLeads(tx: Tx, now: Date, days: number): Promise<number> {
  const old = await tx.select({ id: leads.id }).from(leads).where(lt(leads.createdAt, cutoff(now, days))).for("update");
  const ids = old.map((r) => r.id);
  if (!ids.length) return 0;
  await tx.delete(leadMessages).where(inArray(leadMessages.leadId, ids)); // сначала переписка — сирот не остаётся
  await tx.delete(leads).where(inArray(leads.id, ids));
  return ids.length;
}

async function flatContacts(tx: Tx, now: Date, days: number): Promise<number> {
  const r = await tx.update(flatConfigs).set({ contact: null })
    .where(and(isNotNull(flatConfigs.contact), lt(flatConfigs.createdAt, cutoff(now, days)))).returning({ id: flatConfigs.id });
  return r.length;
}

/** null — другой запуск уже идёт (замок занят), ничего не делали. */
export async function runRetention(now = new Date(), env = process.env): Promise<RetentionResult[] | null> {
  return db().transaction(async (tx) => {
    const got = await tx.execute(sql`select pg_try_advisory_xact_lock(${LOCK_KEY}) as ok`);
    const row = (got as unknown as { ok: boolean }[])[0];
    if (!row?.ok) return null;
    const out: RetentionResult[] = [];
    const tDays = daysFrom(env.TRACE_RETENTION_DAYS) ?? 90;
    const t = await traces(tx, now, tDays);
    out.push({ kind: "traces", days: tDays, deleted: t.deleted, kept: t.kept });
    const lDays = daysFrom(env.LEADS_RETENTION_DAYS);
    out.push({ kind: "leads", days: lDays, deleted: lDays ? await oldLeads(tx, now, lDays) : 0 });
    const cDays = daysFrom(env.CONTACT_RETENTION_DAYS);
    out.push({ kind: "flat_contacts", days: cDays, deleted: cDays ? await flatContacts(tx, now, cDays) : 0 });
    for (const r of out) await tx.insert(retentionRuns).values({ kind: r.kind, days: r.days, deleted: r.deleted, ranAt: now });
    return out;
  });
}
