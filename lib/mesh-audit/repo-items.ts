// Серверный слой /lab/mesh-audit: список карточек, push с DEV, ACK переделок, прогресс просмотра.

import { and, asc, count, eq, inArray, isNotNull, isNull, or, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditDecisions, meshAuditItems, meshAuditMarks, meshAuditNotes } from "@/db/schema";
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
    variantsNote: i.variantsNote,
    manualAttempts: i.manualAttempts,
    status: i.status,
    reworkStatus: i.reworkStatus,
    reworkError: i.reworkError,
    redoneAt: i.redoneAt?.toISOString() ?? null,
    seenAt: i.seenAt?.toISOString() ?? null,
    posterHdUrl: i.posterHdUrl,
    mark: i.mark,
    markBy: i.markBy,
    note: i.note,
    noteSeq: i.noteSeq,
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
  posterHdUrl?: string | null;
  modelPath: string;
  seed?: number;
  attempt?: number;
  generatedAt?: string;
  photoStale?: boolean;
  variantsNote?: string | null;
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
          posterHdUrl: it.posterHdUrl ?? null,
          modelPath: it.modelPath,
          seed: it.seed ?? null,
          attempt: it.attempt ?? null,
          generatedAt: it.generatedAt ? new Date(it.generatedAt) : null,
          photoStale: it.photoStale ?? false,
          variantsNote: it.variantsNote ?? null,
        })
        .onConflictDoUpdate({
          target: meshAuditItems.sku,
          set: {
            revisionKey: sql`excluded.revision_key`,
            role: sql`excluded.role`,
            name: sql`excluded.name`,
            imageUrl: sql`excluded.image_url`,
            posterUrl: sql`excluded.poster_url`,
            // снимок 1024 рендерится ночными порциями: push без него не стирает уже опубликованный того же поколения
            posterHdUrl: sql`case when ${same} then coalesce(excluded.poster_hd_url, ${meshAuditItems.posterHdUrl}) else excluded.poster_hd_url end`,
            modelPath: sql`excluded.model_path`,
            seed: sql`excluded.seed`,
            attempt: sql`excluded.attempt`,
            generatedAt: sql`excluded.generated_at`,
            photoStale: sql`excluded.photo_stale`,
            variantsNote: sql`excluded.variants_note`,
            seenAt: sql`case when ${same} then ${meshAuditItems.seenAt} else null end`,
            redoneAt: sql`case when ${same} or ${meshAuditItems.status} = 'open' then ${meshAuditItems.redoneAt} else now() end`,
            status: sql`case when ${same} then ${meshAuditItems.status} else 'open' end`,
            reworkStatus: sql`case when ${same} then ${meshAuditItems.reworkStatus} else null end`,
            reworkError: sql`case when ${same} then ${meshAuditItems.reworkError} else null end`,
            // отметка и текст /lab/mesh-check — про конкретную модель: новая модель снова «не проверена» (журналы хранят старое)
            mark: sql`case when ${same} then ${meshAuditItems.mark} else null end`,
            markAt: sql`case when ${same} then ${meshAuditItems.markAt} else null end`,
            markBy: sql`case when ${same} then ${meshAuditItems.markBy} else null end`,
            note: sql`case when ${same} then ${meshAuditItems.note} else null end`,
            noteSeq: sql`case when ${same} then ${meshAuditItems.noteSeq} else null end`,
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
// Карточку с решениями владельца, отметками или комментариями /lab/mesh-check не удаляем — журналы ссылаются на неё.
export async function retireItems(skus: string[]): Promise<number> {
  if (skus.length === 0) return 0;
  const d = db();
  const decided = await d.selectDistinct({ sku: meshAuditDecisions.sku }).from(meshAuditDecisions).where(inArray(meshAuditDecisions.sku, skus));
  const marked = await d.selectDistinct({ sku: meshAuditMarks.sku }).from(meshAuditMarks).where(inArray(meshAuditMarks.sku, skus));
  const noted = await d.selectDistinct({ sku: meshAuditNotes.sku }).from(meshAuditNotes).where(inArray(meshAuditNotes.sku, skus));
  const keep = new Set([...decided, ...marked, ...noted].map((r) => r.sku));
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

// Поколения, ПРИНЯТЫЕ владельцем (правило — `rules.isAccepted`, условие здесь повторено в SQL,
// чтобы не тащить тысячи строк в приложение). Нужно прополке болванок формы на DEV (ADR-0233):
// `shape.glb` живёт, пока меш не принят, иначе теряется рычаг перепокраски ADR-0145.
// Лимит — предохранитель от безразмерного ответа; при упоре в него зовущий узнает об этом по
// равенству длины лимиту и может пойти страницами.
export async function acceptedGenerationKeys(limit = 20000): Promise<string[]> {
  const rows = await db()
    .select({ k: meshAuditItems.generationKey })
    .from(meshAuditItems)
    // «брак» на /lab/mesh-check снимает принятие сразу (отметка «ок» прополку НЕ запускает — Codex 12.11: прополка необратима)
    .where(and(isNotNull(meshAuditItems.seenAt), eq(meshAuditItems.status, "open"), or(isNull(meshAuditItems.mark), sql`${meshAuditItems.mark} <> 'bad'`)))
    .orderBy(asc(meshAuditItems.id))
    .limit(limit);
  return rows.map((r) => r.k);
}
