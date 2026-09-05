// Решения владельца по мешам: одна транзакция на клик (актуальность поколения → лимит → запись →
// смена состояния) и курсор для конвейера. Две вкладки разом: строка карточки берётся
// `for update`, плюс уникальность (sku, manual_attempt_no) в схеме — третьей «первой» не будет.

import { asc, desc, eq, gt } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditCancellations, meshAuditDecisions, meshAuditItems } from "@/db/schema";
import { checkCancel, checkDecision, type Verdict } from "./rules";
import { toView } from "./repo-items";
import type { AuditItemView } from "./types";

export type DecideResult =
  | { http: 200; body: { ok: true; duplicate?: true; item: AuditItemView } }
  | { http: 400 | 404 | 409; body: { error: string; code: string } };

export async function decide(itemId: number, generationKey: string, verdict: Verdict, idemKey: string): Promise<DecideResult> {
  return db().transaction(async (tx) => {
    const [item] = await tx.select().from(meshAuditItems).where(eq(meshAuditItems.id, itemId)).for("update");
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ id: meshAuditDecisions.id }).from(meshAuditDecisions).where(eq(meshAuditDecisions.idemKey, idemKey));
    if (dup.length > 0) return { http: 200, body: { ok: true, duplicate: true, item: toView(item) } };
    const chk = checkDecision(item, generationKey, verdict);
    if (!chk.ok) return { http: chk.http as 400 | 409, body: { error: chk.message, code: chk.code } };
    await tx.insert(meshAuditDecisions).values({
      itemId: item.id,
      sku: item.sku,
      generationKey,
      verdict,
      manualAttemptNo: chk.attemptNo,
      idemKey,
    });
    const [upd] = await tx
      .update(meshAuditItems)
      .set({ manualAttempts: chk.manualAttempts, status: chk.status, reworkStatus: "requested", reworkError: null, updatedAt: new Date() })
      .where(eq(meshAuditItems.id, item.id))
      .returning();
    if (!upd) return { http: 404, body: { error: "карточка исчезла во время записи", code: "not_found" } };
    return { http: 200, body: { ok: true, item: toView(upd) } };
  });
}

// Отмена случайного клика: последнее решение по этому поколению удаляется из журнала, факт
// отмены пишется append-only (конвейер откатит у себя), карточка возвращается в open и попытка
// возвращается владельцу. Только пока переделка не ушла в снимок очереди.
export async function cancel(itemId: number, generationKey: string): Promise<DecideResult> {
  return db().transaction(async (tx) => {
    const [item] = await tx.select().from(meshAuditItems).where(eq(meshAuditItems.id, itemId)).for("update");
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const [last] = await tx
      .select()
      .from(meshAuditDecisions)
      .where(eq(meshAuditDecisions.itemId, item.id))
      .orderBy(desc(meshAuditDecisions.id))
      .limit(1);
    if (!last || last.generationKey !== generationKey) return { http: 409, body: { error: "нечего отменять", code: "not_pending" } };
    const chk = checkCancel(item, generationKey, last.verdict);
    if (!chk.ok) return { http: chk.http, body: { error: chk.message, code: chk.code } };
    await tx.insert(meshAuditCancellations).values({
      decisionId: last.id,
      itemId: item.id,
      sku: item.sku,
      generationKey,
      verdict: last.verdict,
      manualAttemptNo: last.manualAttemptNo,
    });
    await tx.delete(meshAuditDecisions).where(eq(meshAuditDecisions.id, last.id));
    const [upd] = await tx
      .update(meshAuditItems)
      .set({ manualAttempts: chk.manualAttempts, status: "open", reworkStatus: null, reworkError: null, updatedAt: new Date() })
      .where(eq(meshAuditItems.id, item.id))
      .returning();
    if (!upd) return { http: 404, body: { error: "карточка исчезла во время записи", code: "not_found" } };
    return { http: 200, body: { ok: true, item: toView(upd) } };
  });
}

export async function listCancellations(afterId: number, limit = 200) {
  return db()
    .select()
    .from(meshAuditCancellations)
    .where(gt(meshAuditCancellations.id, afterId))
    .orderBy(asc(meshAuditCancellations.id))
    .limit(limit);
}

// Курсор для DEV: решения по возрастанию id после after_id; курсор двигает конвейер у себя и
// только после применения (правило mesh-review, Codex q25).
export async function listDecisions(afterId: number, limit = 200) {
  return db()
    .select({
      id: meshAuditDecisions.id,
      itemId: meshAuditDecisions.itemId,
      sku: meshAuditDecisions.sku,
      generationKey: meshAuditDecisions.generationKey,
      verdict: meshAuditDecisions.verdict,
      manualAttemptNo: meshAuditDecisions.manualAttemptNo,
      reviewer: meshAuditDecisions.reviewer,
      createdAt: meshAuditDecisions.createdAt,
    })
    .from(meshAuditDecisions)
    .where(gt(meshAuditDecisions.id, afterId))
    .orderBy(asc(meshAuditDecisions.id))
    .limit(limit);
}
