// Нажатия и версии комментария /lab/cutout-check (T-20261119-104): одна транзакция, карточка `for update`, журнал пишется ВСЕГДА
// (и для не применённого — applied=false). Повтор op_id — ответ без новой строки. Правила — rules.ts.

import { eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { cutoutCheckItems, cutoutCheckMarks } from "@/db/schema";
import { noteVerdict, planPress, type Mark } from "./rules";
import { toView, type ItemRow } from "./repo-items";
import type { CutoutItemView } from "./types";

type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];

async function lock(tx: Tx, id: number): Promise<ItemRow | undefined> {
  const [item] = await tx.select().from(cutoutCheckItems).where(eq(cutoutCheckItems.id, id)).for("update");
  return item;
}

export interface PressIn {
  itemId: number;
  generationKey: string;
  press: Mark;
  expected: Mark | null;
  reviewer: string;
  idemKey: string;
}

export type PressResult =
  | { http: 200; body: { ok: true; item: CutoutItemView; duplicate?: true } }
  | { http: 404 | 409; body: { error: string; code: string; item?: CutoutItemView } };

export async function pressMark(p: PressIn): Promise<PressResult> {
  return db().transaction(async (tx) => {
    const item = await lock(tx, p.itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ id: cutoutCheckMarks.id }).from(cutoutCheckMarks).where(eq(cutoutCheckMarks.opId, p.idemKey));
    if (dup.length > 0) return { http: 200, body: { ok: true, duplicate: true, item: toView(item) } };

    const row = { itemId: item.id, run: item.run, sku: item.sku, generationKey: p.generationKey, kind: "mark", expected: p.expected, reviewer: p.reviewer, opId: p.idemKey };
    const plan = planPress(item, p.generationKey, p.press, p.expected);
    if (!plan.applied) {
      await tx.insert(cutoutCheckMarks).values({ ...row, mark: p.press, applied: false, reason: plan.reason });
      return { http: 409, body: { error: plan.message, code: plan.reason, item: toView(item) } };
    }
    const now = new Date();
    const [upd] = await tx
      .update(cutoutCheckItems)
      .set({ mark: plan.next, markAt: now, markBy: plan.next ? p.reviewer : null, updatedAt: now })
      .where(eq(cutoutCheckItems.id, item.id))
      .returning();
    if (!upd) return { http: 404, body: { error: "карточка исчезла во время записи", code: "not_found" } };
    await tx.insert(cutoutCheckMarks).values({ ...row, mark: plan.log });
    return { http: 200, body: { ok: true, item: toView(upd) } };
  });
}

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

export async function saveNote(n: NoteIn): Promise<NoteResult> {
  return db().transaction(async (tx) => {
    const item = await lock(tx, n.itemId);
    if (!item) return { http: 404, body: { error: "нет карточки", code: "not_found" } };
    const dup = await tx.select({ applied: cutoutCheckMarks.applied }).from(cutoutCheckMarks).where(eq(cutoutCheckMarks.opId, n.opId));
    if (dup[0]) return { http: 200, body: { ok: true, applied: dup[0].applied, duplicate: true } };

    const v = noteVerdict(item, n);
    await tx.insert(cutoutCheckMarks).values({
      itemId: item.id,
      run: item.run,
      sku: item.sku,
      generationKey: n.generationKey,
      kind: "note",
      body: n.body,
      clientSeq: n.seq,
      reviewer: n.reviewer,
      editorId: n.editorId,
      opId: n.opId,
      applied: v === "apply",
      reason: v === "apply" ? null : v,
    });
    if (v !== "apply") return { http: 200, body: { ok: true, applied: false, reason: v } };
    await tx.update(cutoutCheckItems).set({ note: n.body, noteSeq: n.seq, updatedAt: new Date() }).where(eq(cutoutCheckItems.id, item.id));
    return { http: 200, body: { ok: true, applied: true } };
  });
}
