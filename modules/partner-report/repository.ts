// Данные отчёта застройщику и анонимные счётчики (план b2b-03, ADR-0265): DATABASE_URL → Postgres,
// иначе память процесса (тесты). Каждый запрос отчёта фильтруется partner_id, взятым ТОЛЬКО из ключа.

import { createHash } from "node:crypto";
import { and, eq, gte, inArray, isNotNull, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { collections, pageCounters, partnerKeys, sendEvents, sends } from "@/db/schema";
import type { ReportInput } from "@/modules/partner-report/report";

export const keyHash = (key: string) => createHash("sha256").update(key).digest("hex");

export type CounterHit = { day: string; partnerId: string; apartmentId: string; kind: string; lang: string };
export type ReportRows = Omit<ReportInput, "timezone" | "now">;

export interface ReportRepo {
  partnerByKey(key: string): Promise<string | null>;
  bump(h: CounterHit): Promise<void>;
  rows(partnerId: string, since: Date, sinceDay: string): Promise<ReportRows>;
}

export class MemoryReportRepo implements ReportRepo {
  readonly keys = new Map<string, string>(); // hash → partner
  readonly counters = new Map<string, number>();
  data: ReportRows = { sends: [], events: [], savedSendIds: [], counters: [] };
  async partnerByKey(key: string) { return this.keys.get(keyHash(key)) ?? null; }
  async bump(h: CounterHit) {
    const k = [h.day, h.partnerId, h.apartmentId, h.kind, h.lang].join("|");
    this.counters.set(k, (this.counters.get(k) ?? 0) + 1);
  }
  async rows() { return this.data; }
}

class PgReportRepo implements ReportRepo {
  async partnerByKey(key: string) {
    const r = await db().select({ p: partnerKeys.partnerId }).from(partnerKeys)
      .where(and(eq(partnerKeys.keyHash, keyHash(key)), eq(partnerKeys.active, true))).limit(1);
    return r[0]?.p ?? null;
  }
  async bump(h: CounterHit) {
    await db().insert(pageCounters).values({ ...h, n: 1 })
      .onConflictDoUpdate({ target: [pageCounters.day, pageCounters.partnerId, pageCounters.apartmentId, pageCounters.kind, pageCounters.lang], set: { n: sql`${pageCounters.n} + 1` } });
  }
  async rows(partnerId: string, since: Date, sinceDay: string): Promise<ReportRows> {
    const ss = await db().select({ id: sends.id, apartmentId: sends.apartmentId, createdAt: sends.createdAt, openedAt: sends.openedAt, status: sends.status })
      .from(sends).where(and(eq(sends.partnerId, partnerId), gte(sends.createdAt, since)));
    const ids = ss.map((s) => s.id);
    const events = ids.length
      ? await db().selectDistinct({ sendId: sendEvents.sendId, kind: sendEvents.kind }).from(sendEvents).where(inArray(sendEvents.sendId, ids))
      : [];
    const saved = ids.length
      ? await db().selectDistinct({ sendId: collections.sendId }).from(collections)
        .where(and(eq(collections.partnerId, partnerId), isNotNull(collections.sendId), inArray(collections.sendId, ids)))
      : [];
    const counters = await db().select({ day: pageCounters.day, apartmentId: pageCounters.apartmentId, kind: pageCounters.kind, n: pageCounters.n })
      .from(pageCounters).where(and(eq(pageCounters.partnerId, partnerId), gte(pageCounters.day, sinceDay)));
    return { sends: ss, events, savedSendIds: saved.map((r) => r.sendId!).filter(Boolean), counters };
  }
}

const g = globalThis as unknown as { __remlabReport?: ReportRepo };
export function reportRepo(): ReportRepo {
  g.__remlabReport ??= process.env.DATABASE_URL ? new PgReportRepo() : new MemoryReportRepo();
  return g.__remlabReport;
}
