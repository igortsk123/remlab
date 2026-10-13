// Хранилище отправок в Postgres (план b2b-02). Смена статуса и первое открытие — одним условным
// UPDATE: два одновременных события не поставят статус «назад» и не пришлют два «открыл».

import { and, asc, desc, eq, gte, inArray, isNull, lte, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { managers, sendEvents, sends, signalOutbox, tgUpdates } from "@/db/schema";
import type { SendStatus } from "@/contracts/send";
import type { Manager, OutboxRow, Send, SendEventRow, SendPatch, SendStore } from "@/modules/sends/types";

const toSend = (r: typeof sends.$inferSelect): Send => ({ ...r, status: r.status as SendStatus, createdVia: r.createdVia as Send["createdVia"] });
const toOutbox = (r: typeof signalOutbox.$inferSelect): OutboxRow => ({ ...r, status: r.status as OutboxRow["status"] });
const one = <T,>(rows: T[]): T | null => rows[0] ?? null;

export class PgSendStore implements SendStore {
  async managerByKey(key: string): Promise<Manager | null> {
    return one(await db().select().from(managers).where(and(eq(managers.pageKey, key), eq(managers.active, true))).limit(1));
  }
  async managerById(id: string) { return one(await db().select().from(managers).where(eq(managers.id, id)).limit(1)); }
  async managerByTgUser(u: number) {
    return one(await db().select().from(managers).where(and(eq(managers.tgUserId, u), eq(managers.active, true))).limit(1));
  }
  async managersByConnectPhone(digits: string) {
    return db().select().from(managers).where(and(eq(managers.connectPhone, digits), eq(managers.active, true)));
  }
  async bindTelegram(id: string, tgUserId: number, tgChatId: number) {
    await db().update(managers).set({ tgUserId, tgChatId }).where(eq(managers.id, id));
  }
  async createSend(s: Send) { await db().insert(sends).values(s); }
  async getSend(id: string) {
    const r = one(await db().select().from(sends).where(eq(sends.id, id)).limit(1));
    return r ? toSend(r) : null;
  }
  async listSends(managerId: string, limit: number) {
    return (await db().select().from(sends).where(eq(sends.managerId, managerId)).orderBy(desc(sends.createdAt)).limit(limit)).map(toSend);
  }
  async changeStatus(id: string, from: readonly SendStatus[], to: SendStatus, at: Date) {
    const r = await db().update(sends).set({ status: to, statusAt: at })
      .where(and(eq(sends.id, id), inArray(sends.status, [...from]))).returning({ id: sends.id });
    return r.length > 0;
  }
  async updateSend(id: string, patch: SendPatch) {
    if (Object.keys(patch).length) await db().update(sends).set(patch).where(eq(sends.id, id));
  }
  async claimFirstOpen(id: string, at: Date) {
    const r = await db().update(sends).set({ openedAt: at, openSignalAt: at })
      .where(and(eq(sends.id, id), isNull(sends.openedAt))).returning({ id: sends.id });
    return r.length > 0;
  }
  async addEvent(e: SendEventRow) { await db().insert(sendEvents).values(e); }
  async events(sendId: string, limit: number) {
    return db().select({ sendId: sendEvents.sendId, kind: sendEvents.kind, payload: sendEvents.payload, createdAt: sendEvents.createdAt })
      .from(sendEvents).where(eq(sendEvents.sendId, sendId)).orderBy(desc(sendEvents.id)).limit(limit);
  }
  async enqueue(row: Omit<OutboxRow, "id" | "status" | "attempts" | "lastError">) {
    await db().insert(signalOutbox).values(row);
  }
  async queuedSince(managerId: string, since: Date) {
    const r = await db().select({ n: sql<number>`count(*)::int` }).from(signalOutbox)
      .where(and(eq(signalOutbox.managerId, managerId), gte(signalOutbox.createdAt, since)));
    return r[0]?.n ?? 0;
  }
  async dueOutbox(now: Date, limit: number) {
    return (await db().select().from(signalOutbox).where(and(eq(signalOutbox.status, "pending"), lte(signalOutbox.nextAt, now)))
      .orderBy(asc(signalOutbox.id)).limit(limit)).map(toOutbox);
  }
  async outboxFor(ids: string[]) {
    if (!ids.length) return [];
    return (await db().select().from(signalOutbox).where(inArray(signalOutbox.sendId, ids)).orderBy(asc(signalOutbox.id))).map(toOutbox);
  }
  async markOutbox(id: number, patch: Partial<Pick<OutboxRow, "status" | "attempts" | "nextAt" | "lastError">> & { sentAt?: Date }) {
    await db().update(signalOutbox).set(patch).where(eq(signalOutbox.id, id));
  }
  async dueSummaries(now: Date, limit: number) {
    return (await db().select().from(sends).where(lte(sends.summaryDueAt, now)).limit(limit)).map(toSend);
  }
  async firstSeenUpdate(updateId: number) {
    const r = await db().insert(tgUpdates).values({ updateId }).onConflictDoNothing().returning({ id: tgUpdates.updateId });
    return r.length > 0;
  }
}
