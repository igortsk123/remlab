// Версия комментария на /lab/mesh-check (T-20261112-118). Каждая версия — строка журнала навсегда; текущий текст карточки
// меняется, только если версия новее принятой (client_seq) и модель та же. Иначе строка с applied=false: поздний пакет старой
// вкладки или маяк по уже заменённой модели сохранены, но текущий текст не затирают. Повтор op_id — без новой строки.

import { eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditItems, meshAuditNotes } from "@/db/schema";
import { lockItem } from "./repo-decisions-tx";

export interface NoteIn {
  itemId: number;
  generationKey: string;
  body: string;
  seq: number;
  opId: string;
  editorId: string;
  reviewer: string;
}

export type NoteResult =
  | { http: 200; body: { ok: true; applied: boolean; reason?: "stale" | "older"; duplicate?: true } }
  | { http: 404; body: { error: string; code: "not_found" } };

/** Чистое правило: принять версию или только записать в журнал. */
export function noteVerdict(item: { generationKey: string; noteSeq: number | null }, n: { generationKey: string; seq: number }): "apply" | "stale" | "older" {
  if (item.generationKey !== n.generationKey) return "stale";
  if (item.noteSeq !== null && n.seq <= item.noteSeq) return "older";
  return "apply";
}

export async function saveNote(n: NoteIn): Promise<NoteResult> {
  return db().transaction(async (tx) => {
    const item = await lockItem(tx, n.itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ applied: meshAuditNotes.applied }).from(meshAuditNotes).where(eq(meshAuditNotes.opId, n.opId));
    if (dup[0]) return { http: 200, body: { ok: true, applied: dup[0].applied, duplicate: true } };

    const v = noteVerdict(item, n);
    await tx.insert(meshAuditNotes).values({
      itemId: item.id,
      sku: item.sku,
      generationKey: n.generationKey,
      body: n.body,
      reviewer: n.reviewer,
      editorId: n.editorId,
      clientSeq: n.seq,
      opId: n.opId,
      applied: v === "apply",
      reason: v === "apply" ? null : v,
    });
    if (v !== "apply") return { http: 200, body: { ok: true, applied: false, reason: v } };
    await tx.update(meshAuditItems).set({ note: n.body, noteSeq: n.seq, updatedAt: new Date() }).where(eq(meshAuditItems.id, item.id));
    return { http: 200, body: { ok: true, applied: true } };
  });
}
