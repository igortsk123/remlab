// Выгрузка отметок /lab/cutout-check списком (T-20261119-104): что владелец нажал и написал по текущей вырезке каждого товара.

import { and, asc, eq, isNotNull, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { cutoutCheckItems, cutoutCheckMarks } from "@/db/schema";
import { currentRun } from "./repo-items";

export interface ExportRow {
  sku: string;
  role: string | null;
  name: string | null;
  mark: "ok" | "bad";
  note: string | null;
  by: string | null;
  at: string | null; // ISO
  generationKey: string;
}

export interface ExportData {
  run: string;
  total: number;
  ok: number;
  bad: number;
  journal: number; // строк журнала (нажатия + версии текста) по прогону
  marks: ExportRow[];
}

/** Только карточки с отметкой (ок / не ок) либо с текстом: «не ок» первыми — это и есть список для разбора. */
export async function exportMarks(run?: string): Promise<ExportData | null> {
  const r = run ?? (await currentRun());
  if (!r) return null;
  const rows = await db()
    .select()
    .from(cutoutCheckItems)
    .where(and(eq(cutoutCheckItems.run, r), isNotNull(cutoutCheckItems.mark)))
    .orderBy(asc(cutoutCheckItems.mark), asc(cutoutCheckItems.position));
  const [t] = await db().select({ n: sql<number>`count(*)::int` }).from(cutoutCheckItems).where(eq(cutoutCheckItems.run, r));
  if (!t || t.n === 0) return null;
  const [j] = await db().select({ n: sql<number>`count(*)::int` }).from(cutoutCheckMarks).where(eq(cutoutCheckMarks.run, r));
  const marks: ExportRow[] = rows.map((x) => ({
    sku: x.sku,
    role: x.role,
    name: x.name,
    mark: x.mark === "bad" ? "bad" : "ok",
    note: x.note && x.note.trim() ? x.note : null,
    by: x.markBy,
    at: x.markAt ? x.markAt.toISOString() : null,
    generationKey: x.generationKey,
  }));
  return { run: r, total: t.n, ok: marks.filter((m) => m.mark === "ok").length, bad: marks.filter((m) => m.mark === "bad").length, journal: j?.n ?? 0, marks };
}
