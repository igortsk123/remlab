// Серверный слой /lab/mesh-audit: список карточек, push с DEV, ACK переделок, прогресс просмотра.

import { and, asc, count, eq, inArray, isNotNull, isNull, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditDecisions, meshAuditItems } from "@/db/schema";
import { PAGE_SIZE, reworkToItemStatus } from "./rules";
import type { AuditItemView } from "./types";

export type AuditItem = typeof meshAuditItems.$inferSelect;

export function toView(i: AuditItem): AuditItemView {
  return {
    id: i.id,
    sku: i.sku,
    generationKey: i.generationKey,
    role: i.role,
    name: i.name,
    imageUrl: i.imageUrl,
    posterUrl: i.posterUrl,
    modelPath: i.modelPath,
    seed: i.seed,
    attempt: i.attempt,
    generatedAt: i.generatedAt?.toISOString() ?? null,
    photoStale: i.photoStale,
    manualAttempts: i.manualAttempts,
    status: i.status,
    reworkStatus: i.reworkStatus,
    reworkError: i.reworkError,
    redoneAt: i.redoneAt?.toISOString() ?? null,
    seenAt: i.seenAt?.toISOString() ?? null,
  };
}

export async function listPage(page: number): Promise<{ items: AuditItem[]; total: number; seen: number }> {
  const d = db();
  const total = (await d.select({ n: count() }).from(meshAuditItems))[0]?.n ?? 0;
  const seen = (await d.select({ n: count() }).from(meshAuditItems).where(isNotNull(meshAuditItems.seenAt)))[0]?.n ?? 0;
  const items = await d
    .select()
    .from(meshAuditItems)
    .orderBy(asc(meshAuditItems.id))
    .limit(PAGE_SIZE)
    .offset((page - 1) * PAGE_SIZE);
  return { items, total, seen };
}

export interface ItemIn {
  sku: string;
  generationKey: string;
  revisionKey?: string | null;
  role?: string | null;
  name?: string | null;
  imageUrl?: string | null;
  posterUrl?: string | null;
  modelPath: string;
  seed?: number;
  attempt?: number;
  generatedAt?: string;
  photoStale?: boolean;
}

// Upsert по sku. Новое поколение (другой generation_key) сбрасывает «просмотрено» и переводит
// карточку в open с пометкой redone_at — владелец должен взглянуть заново. Тот же ключ ничего
// из состояния владельца не трогает. Порядок вставки = порядок карточек, поэтому по одной строке.
export async function upsertItems(items: ItemIn[]): Promise<number> {
  const same = sql`${meshAuditItems.generationKey} = excluded.generation_key`;
  await db().transaction(async (tx) => {
    for (const it of items) {
      await tx
        .insert(meshAuditItems)
        .values({
          sku: it.sku,
          generationKey: it.generationKey,
          revisionKey: it.revisionKey ?? null,
          role: it.role ?? null,
          name: it.name ?? null,
          imageUrl: it.imageUrl ?? null,
          posterUrl: it.posterUrl ?? null,
          modelPath: it.modelPath,
          seed: it.seed ?? null,
          attempt: it.attempt ?? null,
          generatedAt: it.generatedAt ? new Date(it.generatedAt) : null,
          photoStale: it.photoStale ?? false,
        })
        .onConflictDoUpdate({
          target: meshAuditItems.sku,
          set: {
            revisionKey: sql`excluded.revision_key`,
            role: sql`excluded.role`,
            name: sql`excluded.name`,
            imageUrl: sql`excluded.image_url`,
            posterUrl: sql`excluded.poster_url`,
            modelPath: sql`excluded.model_path`,
            seed: sql`excluded.seed`,
            attempt: sql`excluded.attempt`,
            generatedAt: sql`excluded.generated_at`,
            photoStale: sql`excluded.photo_stale`,
            seenAt: sql`case when ${same} then ${meshAuditItems.seenAt} else null end`,
            redoneAt: sql`case when ${same} or ${meshAuditItems.status} = 'open' then ${meshAuditItems.redoneAt} else now() end`,
            status: sql`case when ${same} then ${meshAuditItems.status} else 'open' end`,
            reworkStatus: sql`case when ${same} then ${meshAuditItems.reworkStatus} else null end`,
            reworkError: sql`case when ${same} then ${meshAuditItems.reworkError} else null end`,
            generationKey: sql`excluded.generation_key`,
            updatedAt: sql`now()`,
          },
        });
    }
  });
  return items.length;
}

export interface AckIn {
  sku: string;
  reworkStatus: string;
  error?: string;
}

// ACK конвейера меняет статус только у карточек, которые ждут переделки: решение «нужна замена»
// или уже пришедшее новое поколение он не перебивает.
export async function applyAcks(acks: AckIn[]): Promise<number> {
  const d = db();
  let n = 0;
  for (const a of acks) {
    const status = reworkToItemStatus(a.reworkStatus);
    const rows = await d
      .update(meshAuditItems)
      .set({ reworkStatus: a.reworkStatus, reworkError: a.error ?? null, ...(status ? { status } : {}), updatedAt: new Date() })
      .where(and(eq(meshAuditItems.sku, a.sku), inArray(meshAuditItems.status, ["redo_requested", "redo_queued", "redo_blocked"])))
      .returning({ id: meshAuditItems.id });
    n += rows.length;
  }
  return n;
}

// Снятие карточек, которых на странице быть не должно (роль без меша по канону, товар исчез).
// Карточку с решениями владельца не удаляем — журнал решений ссылается на неё.
export async function retireItems(skus: string[]): Promise<number> {
  if (skus.length === 0) return 0;
  const d = db();
  const decided = await d.selectDistinct({ sku: meshAuditDecisions.sku }).from(meshAuditDecisions).where(inArray(meshAuditDecisions.sku, skus));
  const keep = new Set(decided.map((r) => r.sku));
  const victims = skus.filter((s) => !keep.has(s));
  if (victims.length === 0) return 0;
  const rows = await d.delete(meshAuditItems).where(inArray(meshAuditItems.sku, victims)).returning({ id: meshAuditItems.id });
  return rows.length;
}

export async function markSeen(ids: number[]): Promise<number> {
  if (ids.length === 0) return 0;
  const rows = await db()
    .update(meshAuditItems)
    .set({ seenAt: new Date() })
    .where(and(inArray(meshAuditItems.id, ids), isNull(meshAuditItems.seenAt)))
    .returning({ id: meshAuditItems.id });
  return rows.length;
}
