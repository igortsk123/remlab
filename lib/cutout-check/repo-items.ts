// Чтение и заливка карточек /lab/cutout-check (T-20261119-104): текущий прогон, счётчики по ролям, страница карточек, upsert от DEV.

import { and, asc, desc, eq, isNull, sql, type SQL } from "drizzle-orm";
import { db } from "@/lib/db";
import { cutoutCheckItems } from "@/db/schema";
import type { ItemInput } from "./body";
import { countMarks, PAGE_SIZE, type CheckFilter, type Counts } from "./rules";
import type { CutoutItemView, RoleCount } from "./types";

export type ItemRow = typeof cutoutCheckItems.$inferSelect;

export function toView(r: ItemRow): CutoutItemView {
  return {
    id: r.id,
    run: r.run,
    sku: r.sku,
    position: r.position,
    role: r.role,
    name: r.name,
    nameEn: r.nameEn,
    shop: r.shop,
    shopUrl: r.shopUrl,
    photoUrl: r.photoUrl,
    cutUrl: r.cutUrl,
    generationKey: r.generationKey,
    info: r.info,
    mark: r.mark,
    markBy: r.markBy,
    note: r.note,
    noteSeq: r.noteSeq,
  };
}

/** Текущий прогон — тот, в который карточки клали последним. Нет карточек — null. */
export async function currentRun(): Promise<string | null> {
  const [r] = await db().select({ run: cutoutCheckItems.run }).from(cutoutCheckItems).orderBy(desc(cutoutCheckItems.updatedAt)).limit(1);
  return r?.run ?? null;
}

export async function roleCounts(run: string): Promise<{ roles: RoleCount[]; all: Counts }> {
  const rows = await db().select({ role: cutoutCheckItems.role, mark: cutoutCheckItems.mark }).from(cutoutCheckItems).where(eq(cutoutCheckItems.run, run));
  const by = new Map<string, { mark: string | null }[]>();
  for (const r of rows) by.set(r.role ?? "—", [...(by.get(r.role ?? "—") ?? []), r]);
  const roles = [...by.entries()].map(([role, rs]) => ({ role, ...countMarks(rs) })).sort((a, b) => b.total - a.total || a.role.localeCompare(b.role, "ru"));
  return { roles, all: countMarks(rows) };
}

function where(run: string, role: string | null, filter: CheckFilter): SQL | undefined {
  const parts: (SQL | undefined)[] = [eq(cutoutCheckItems.run, run)];
  if (role) parts.push(role === "—" ? isNull(cutoutCheckItems.role) : eq(cutoutCheckItems.role, role));
  if (filter === "todo") parts.push(isNull(cutoutCheckItems.mark));
  if (filter === "bad") parts.push(eq(cutoutCheckItems.mark, "bad"));
  return and(...parts);
}

export async function listPage(run: string, role: string | null, filter: CheckFilter, page: number): Promise<{ items: ItemRow[]; total: number }> {
  const w = where(run, role, filter);
  const [c] = await db().select({ n: sql<number>`count(*)::int` }).from(cutoutCheckItems).where(w);
  const items = await db()
    .select()
    .from(cutoutCheckItems)
    .where(w)
    .orderBy(asc(cutoutCheckItems.position), asc(cutoutCheckItems.id))
    .limit(PAGE_SIZE)
    .offset((page - 1) * PAGE_SIZE);
  return { items, total: c?.n ?? 0 };
}

/** Заливка от DEV: upsert по (run, sku). Новая вырезка (другой generation_key) сбрасывает отметку и текст — журнал остаётся. */
export async function upsertItems(run: string, items: ItemInput[]): Promise<number> {
  const same = sql`${cutoutCheckItems.generationKey} = excluded.generation_key`;
  await db().transaction(async (tx) => {
    for (const it of items) {
      await tx
        .insert(cutoutCheckItems)
        .values({
          run,
          sku: it.sku,
          position: it.position,
          role: it.role ?? null,
          name: it.name ?? null,
          nameEn: it.nameEn ?? null,
          shop: it.shop ?? null,
          shopUrl: it.shopUrl ?? null,
          photoUrl: it.photoUrl ?? null,
          cutUrl: it.cutUrl ?? null,
          generationKey: it.generationKey,
          info: it.info ?? null,
        })
        .onConflictDoUpdate({
          target: [cutoutCheckItems.run, cutoutCheckItems.sku],
          set: {
            position: sql`excluded.position`,
            role: sql`excluded.role`,
            name: sql`excluded.name`,
            nameEn: sql`excluded.name_en`,
            shop: sql`excluded.shop`,
            shopUrl: sql`excluded.shop_url`,
            photoUrl: sql`excluded.photo_url`,
            cutUrl: sql`excluded.cut_url`,
            info: sql`excluded.info`,
            mark: sql`case when ${same} then ${cutoutCheckItems.mark} else null end`,
            markAt: sql`case when ${same} then ${cutoutCheckItems.markAt} else null end`,
            markBy: sql`case when ${same} then ${cutoutCheckItems.markBy} else null end`,
            note: sql`case when ${same} then ${cutoutCheckItems.note} else null end`,
            noteSeq: sql`case when ${same} then ${cutoutCheckItems.noteSeq} else null end`,
            generationKey: sql`excluded.generation_key`,
            updatedAt: sql`now()`,
          },
        });
    }
  });
  return items.length;
}
