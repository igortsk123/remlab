// Нажатие «ок»/«брак» на /lab/mesh-check (T-20261112-118): ОДНА транзакция — строка карточки `for update` → правило
// (`marks.planPress`) → решение/отмена переделки → текущая отметка → строка журнала. Журнал пишется и для не применённого
// нажатия (старая вкладка, модель заменена) — ни одно нажатие не теряется. Повтор того же idem_key — ответ без новой строки.

import { eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditMarks, meshAuditItems } from "@/db/schema";
import { planPress, type Mark, type Press } from "./marks";
import { cancelTx, decideTx, lockItem } from "./repo-decisions-tx";
import { toView } from "./repo-items";
import { COMMENT_MAX } from "./decision-body";
import type { AuditItemView } from "./types";

export interface PressIn {
  itemId: number;
  generationKey: string;
  press: Press;
  expected: Mark | null;
  reviewer: string;
  idemKey: string;
}

export type PressResult =
  | { http: 200; body: { ok: true; item: AuditItemView; duplicate?: true; reason?: string } }
  | { http: 404 | 409; body: { error: string; code: string; item?: AuditItemView } };

// Комментарий решения (столбец ≤ 500, 021) — начало текущего текста; полный текст и все версии — в mesh_audit_notes.
export function decisionComment(note: string | null): string | null {
  const t = note?.trim() ?? "";
  return t ? t.slice(0, COMMENT_MAX) : null;
}

export async function pressMark(p: PressIn): Promise<PressResult> {
  return db().transaction(async (tx) => {
    const item = await lockItem(tx, p.itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ id: meshAuditMarks.id }).from(meshAuditMarks).where(eq(meshAuditMarks.idemKey, p.idemKey));
    if (dup.length > 0) return { http: 200, body: { ok: true, duplicate: true, item: toView(item) } };

    const row = { itemId: item.id, sku: item.sku, generationKey: p.generationKey, expected: p.expected, reviewer: p.reviewer, idemKey: p.idemKey };
    const plan = planPress(item, p.generationKey, p.press, p.expected);
    if (!plan.applied) {
      await tx.insert(meshAuditMarks).values({ ...row, mark: p.press, applied: false, reason: plan.reason });
      return { http: 409, body: { error: plan.message, code: plan.reason, item: toView(item) } };
    }

    let cur = item;
    let reason: string | undefined = plan.reason;
    let decisionId: number | null = null;
    let cancelledDecisionId: number | null = null;
    if (plan.cancel) {
      const r = await cancelTx(tx, cur, p.generationKey);
      if (r.ok) [cur, cancelledDecisionId] = [r.item, r.decisionId];
      else reason = r.code; // решение уже не отменить — отметку всё равно снимаем, вкладка покажет состояние переделки
    }
    if (plan.decide) {
      const comment = decisionComment(cur.note);
      const r = await decideTx(tx, cur, { generationKey: p.generationKey, verdict: plan.decide, idemKey: `mark:${p.idemKey}`, comment, reviewer: p.reviewer });
      if (!r.ok) {
        await tx.insert(meshAuditMarks).values({ ...row, mark: p.press, applied: false, reason: r.code });
        return { http: 409, body: { error: r.error, code: r.code, item: toView(cur) } };
      }
      [cur, decisionId] = [r.item, r.decisionId];
    }
    const now = new Date();
    const [upd] = await tx
      .update(meshAuditItems)
      .set({ mark: plan.next, markAt: now, markBy: plan.next ? p.reviewer : null, updatedAt: now })
      .where(eq(meshAuditItems.id, cur.id))
      .returning();
    if (!upd) return { http: 404, body: { error: "карточка исчезла во время записи", code: "not_found" } };
    await tx.insert(meshAuditMarks).values({ ...row, mark: plan.log, reason: reason ?? null, decisionId, cancelledDecisionId });
    return { http: 200, body: { ok: true, item: toView(upd), ...(reason ? { reason } : {}) } };
  });
}
