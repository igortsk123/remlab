// Удаление по срокам хранения (план b2b-04, ADR-0268). Срок каждого вида данных — из env; НЕ задан → ничего
// не удаляем и пишем в журнал «срок не задан» (сроки заявок и контактов — решение владельца, не код).
// Трейсы ИИ — по TRACE_RETENTION_DAYS (90 по умолчанию, как `tools/trace-prune.mjs`). Каждое выполнение —
// строка в `retention_runs`: видно, что и сколько удалено.

import { promises as fs } from "node:fs";
import path from "node:path";
import { and, inArray, isNotNull, lt } from "drizzle-orm";
import { db } from "@/lib/db";
import { flatConfigs, generationAssets, generationRuns, generationSteps, leadMessages, leads, retentionRuns } from "@/db/schema";
import { TRACE_DIR } from "@/lib/trace/assets";

export type RetentionResult = { kind: string; days: number | null; deleted: number };

/** Срок в днях из env: целое > 0, иначе null («не задан»). */
export function daysFrom(v: string | undefined): number | null {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : null;
}

const cutoff = (now: Date, days: number) => new Date(now.getTime() - days * 86_400_000);

async function traces(now: Date, days: number): Promise<number> {
  const old = await db().select({ id: generationRuns.id }).from(generationRuns).where(lt(generationRuns.startedAt, cutoff(now, days)));
  const ids = old.map((r) => r.id);
  for (const id of ids) await fs.rm(path.join(TRACE_DIR, id), { recursive: true, force: true }).catch(() => undefined);
  if (!ids.length) return 0;
  await db().delete(generationAssets).where(inArray(generationAssets.runId, ids));
  await db().delete(generationSteps).where(inArray(generationSteps.runId, ids));
  await db().delete(generationRuns).where(inArray(generationRuns.id, ids));
  return ids.length;
}

async function oldLeads(now: Date, days: number): Promise<number> {
  const gone = await db().delete(leads).where(lt(leads.createdAt, cutoff(now, days))).returning({ id: leads.id });
  const ids = gone.map((r) => r.id);
  if (ids.length) await db().delete(leadMessages).where(inArray(leadMessages.leadId, ids));
  return ids.length;
}

async function flatContacts(now: Date, days: number): Promise<number> {
  const r = await db().update(flatConfigs).set({ contact: null })
    .where(and(isNotNull(flatConfigs.contact), lt(flatConfigs.createdAt, cutoff(now, days)))).returning({ id: flatConfigs.id });
  return r.length;
}

export async function runRetention(now = new Date(), env = process.env): Promise<RetentionResult[]> {
  const plan: [string, number | null, (n: Date, d: number) => Promise<number>][] = [
    ["traces", daysFrom(env.TRACE_RETENTION_DAYS) ?? 90, traces],
    ["leads", daysFrom(env.LEADS_RETENTION_DAYS), oldLeads],
    ["flat_contacts", daysFrom(env.CONTACT_RETENTION_DAYS), flatContacts],
  ];
  const out: RetentionResult[] = [];
  for (const [kind, days, fn] of plan) {
    const deleted = days ? await fn(now, days) : 0;
    out.push({ kind, days, deleted });
    await db().insert(retentionRuns).values({ kind, days, deleted, ranAt: now });
  }
  return out;
}
