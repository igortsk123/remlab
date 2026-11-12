// Решения владельца по мешам: одна транзакция на клик (актуальность поколения → лимит → запись →
// смена состояния) и курсор для конвейера. Две вкладки разом: строка карточки берётся
// `for update`, плюс уникальность (sku, manual_attempt_no) в схеме — третьей «первой» не будет.

import { asc, eq, gt } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditCancellations, meshAuditDecisions } from "@/db/schema";
import type { Verdict } from "./rules";
import { cancelTx, decideTx, lockItem, type TxFail, type TxOk } from "./repo-decisions-tx";
import { toView } from "./repo-items";
import type { AuditItemView } from "./types";

export type DecideResult =
  | { http: 200; body: { ok: true; duplicate?: true; item: AuditItemView } }
  | { http: 400 | 404 | 409; body: { error: string; code: string } };

export async function decide(
  itemId: number,
  generationKey: string,
  verdict: Verdict,
  idemKey: string,
  comment: string | null = null,
): Promise<DecideResult> {
  return db().transaction(async (tx) => {
    const item = await lockItem(tx, itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ id: meshAuditDecisions.id }).from(meshAuditDecisions).where(eq(meshAuditDecisions.idemKey, idemKey));
    if (dup.length > 0) return { http: 200, body: { ok: true, duplicate: true, item: toView(item) } };
    return asResult(await decideTx(tx, item, { generationKey, verdict, idemKey, comment }));
  });
}

// Отмена случайного клика — правило в `repo-decisions-tx.cancelTx`.
export async function cancel(itemId: number, generationKey: string): Promise<DecideResult> {
  return db().transaction(async (tx) => {
    const item = await lockItem(tx, itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    return asResult(await cancelTx(tx, item, generationKey));
  });
}

function asResult(r: TxOk | TxFail): DecideResult {
  return r.ok ? { http: 200, body: { ok: true, item: toView(r.item) } } : { http: r.http, body: { error: r.error, code: r.code } };
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
      comment: meshAuditDecisions.comment,
      createdAt: meshAuditDecisions.createdAt,
    })
    .from(meshAuditDecisions)
    .where(gt(meshAuditDecisions.id, afterId))
    .orderBy(asc(meshAuditDecisions.id))
    .limit(limit);
}
