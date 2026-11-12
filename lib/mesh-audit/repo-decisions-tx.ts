// Решение и его отмена ВНУТРИ уже открытой транзакции (строка карточки взята `for update` зовущим). Нужны, чтобы нажатие «брак»
// на /lab/mesh-check писало журнал, отметку и решение одной транзакцией (T-20261112-118, Codex 12.11); `repo-decisions.ts`
// (кнопки /lab/mesh-audit) зовёт их же — правило одно.

import { desc, eq } from "drizzle-orm";
import type { db } from "@/lib/db";
import { meshAuditCancellations, meshAuditDecisions, meshAuditItems } from "@/db/schema";
import { checkCancel, checkDecision, type Verdict } from "./rules";

export type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];
export type ItemRow = typeof meshAuditItems.$inferSelect;
export type TxFail = { ok: false; http: 400 | 404 | 409; error: string; code: string };
export type TxOk = { ok: true; item: ItemRow; decisionId: number };

export async function lockItem(tx: Tx, itemId: number): Promise<ItemRow | undefined> {
  const [item] = await tx.select().from(meshAuditItems).where(eq(meshAuditItems.id, itemId)).for("update");
  return item;
}

export interface DecideArgs {
  generationKey: string;
  verdict: Verdict;
  idemKey: string;
  comment: string | null;
  reviewer?: string;
}

export async function decideTx(tx: Tx, item: ItemRow, a: DecideArgs): Promise<TxOk | TxFail> {
  const chk = checkDecision(item, a.generationKey, a.verdict);
  if (!chk.ok) return { ok: false, http: chk.http as 400 | 409, error: chk.message, code: chk.code };
  const [row] = await tx
    .insert(meshAuditDecisions)
    .values({
      itemId: item.id,
      sku: item.sku,
      generationKey: a.generationKey,
      verdict: a.verdict,
      manualAttemptNo: chk.attemptNo,
      idemKey: a.idemKey,
      comment: a.comment,
      ...(a.reviewer ? { reviewer: a.reviewer } : {}),
    })
    .returning({ id: meshAuditDecisions.id });
  const [upd] = await tx
    .update(meshAuditItems)
    .set({ manualAttempts: chk.manualAttempts, status: chk.status, reworkStatus: "requested", reworkError: null, updatedAt: new Date() })
    .where(eq(meshAuditItems.id, item.id))
    .returning();
  if (!row || !upd) return { ok: false, http: 404, error: "карточка исчезла во время записи", code: "not_found" };
  return { ok: true, item: upd, decisionId: row.id };
}

// Отмена случайного клика: последнее решение по этому поколению удаляется из журнала, факт отмены пишется append-only
// (конвейер откатит у себя), карточка возвращается в open и попытка возвращается. Только пока переделка не ушла в волну.
export async function cancelTx(tx: Tx, item: ItemRow, generationKey: string): Promise<TxOk | TxFail> {
  const [last] = await tx.select().from(meshAuditDecisions).where(eq(meshAuditDecisions.itemId, item.id)).orderBy(desc(meshAuditDecisions.id)).limit(1);
  if (!last || last.generationKey !== generationKey) return { ok: false, http: 409, error: "нечего отменять", code: "not_pending" };
  const chk = checkCancel(item, generationKey, last.verdict);
  if (!chk.ok) return { ok: false, http: chk.http, error: chk.message, code: chk.code };
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
  if (!upd) return { ok: false, http: 404, error: "карточка исчезла во время записи", code: "not_found" };
  return { ok: true, item: upd, decisionId: last.id };
}
