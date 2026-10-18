// Хранилище коллекций (план b2b-05): DATABASE_URL → Postgres, иначе память процесса (тесты).

import { createHash, timingSafeEqual } from "node:crypto";
import { and, eq, gt, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { collections } from "@/db/schema";
import { randomToken } from "@/lib/token";
import type { CollectionIn } from "@/contracts/collection";

// `editHash` — sha256 секрета редактирования (demo-15): лежит в payload, наружу не отдаётся (`GET` его вырезает)
export type StoredPayload = CollectionIn & { editHash?: string };
export type StoredCollection = { id: string; partnerId: string; payload: StoredPayload; createdAt: Date };

export interface CollectionRepo {
  create(partnerId: string, c: CollectionIn, now?: Date, editHash?: string): Promise<StoredCollection>;
  get(id: string, now?: Date): Promise<StoredCollection | null>;
  /** Картинка снята после сохранения: ставится ОДИН раз и только в первые SHOT_WINDOW_MS (иначе — false). */
  setShot(id: string, shot: string, now?: Date, stateId?: string): Promise<boolean>;
  /** Новое имя — только если хеш секрета совпал с сохранённым (у коллекций до demo-15 хеша нет — false). */
  rename(id: string, displayName: string, editHash: string, now?: Date): Promise<boolean>;
}

export const editHashOf = (token: string) => createHash("sha256").update(token).digest("hex");

// Окно, в которое можно прикрепить кадр: фоновый черновик снимается за минуту-две; дольше — снимок уже не «этот».
export const SHOT_WINDOW_MS = 30 * 60_000;

const hashOf = (c: CollectionIn) => createHash("sha256").update(JSON.stringify(c)).digest("hex").slice(0, 16);

export class MemoryCollectionRepo implements CollectionRepo {
  readonly rows = new Map<string, StoredCollection & { expiresAt: Date }>();
  async create(partnerId: string, c: CollectionIn, now = new Date(), editHash?: string) {
    const payload: StoredPayload = editHash ? { ...c, editHash } : c;
    const row = { id: randomToken(), partnerId, payload, createdAt: now, expiresAt: new Date(now.getTime() + 365 * 86_400_000) };
    this.rows.set(row.id, row);
    return row;
  }
  async get(id: string, now = new Date()) {
    const r = this.rows.get(id);
    return r && r.expiresAt > now ? r : null;
  }
  async setShot(id: string, shot: string, now = new Date(), stateId?: string) {
    const r = this.rows.get(id);
    if (!r || r.payload.shot || now.getTime() - r.createdAt.getTime() > SHOT_WINDOW_MS) return false;
    if (r.payload.stateId && stateId !== r.payload.stateId) return false;   // кадр другого состояния — не картинка коллекции
    r.payload = { ...r.payload, shot };
    return true;
  }
  async rename(id: string, displayName: string, editHash: string, now = new Date()) {
    const r = this.rows.get(id);
    if (!r || r.expiresAt <= now || !r.payload.editHash || !sameHash(r.payload.editHash, editHash)) return false;
    r.payload = { ...r.payload, displayName };
    return true;
  }
}

const sameHash = (a: string, b: string) => a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));

class PgCollectionRepo implements CollectionRepo {
  async create(partnerId: string, c: CollectionIn, now = new Date(), editHash?: string) {
    const id = randomToken();
    const payload: StoredPayload = editHash ? { ...c, editHash } : c;
    await db().insert(collections).values({
      id, partnerId, apartmentId: c.apartmentId, baseVariant: c.baseVariant, sendId: c.sendId ?? null, lang: c.lang,
      payload: payload as unknown as Record<string, unknown>, contentHash: hashOf(c), createdAt: now,
    });
    return { id, partnerId, payload, createdAt: now };
  }
  async get(id: string, now = new Date()) {
    const r = (await db().select().from(collections).where(eq(collections.id, id)).limit(1))[0];
    if (!r || r.expiresAt <= now) return null;
    return { id: r.id, partnerId: r.partnerId, payload: r.payload as unknown as StoredPayload, createdAt: r.createdAt };
  }
  async setShot(id: string, shot: string, now = new Date(), stateId?: string) {
    // одно условие в одном UPDATE: нет картинки И коллекция свежая И (номер состояния не задан у коллекции ИЛИ совпал) —
    // гонка двух запросов даёт одну запись, кадр чужого состояния не прикрепляется (demo-02, Codex 14.10)
    const res = await db().update(collections)
      .set({ payload: sql`jsonb_set(${collections.payload}, '{shot}', to_jsonb(${shot}::text))` })
      .where(and(eq(collections.id, id), sql`(${collections.payload} -> 'shot') is null`,
        gt(collections.createdAt, new Date(now.getTime() - SHOT_WINDOW_MS)),
        sql`((${collections.payload} ->> 'stateId') is null or ${collections.payload} ->> 'stateId' = ${stateId ?? ""})`))
      .returning({ id: collections.id });
    return res.length > 0;
  }
  async rename(id: string, displayName: string, editHash: string, now = new Date()) {
    // одно условие в одном UPDATE: коллекция жива И хеш секрета совпал; у коллекций без хеша (до demo-15) — ничего
    const res = await db().update(collections)
      .set({ payload: sql`jsonb_set(${collections.payload}, '{displayName}', to_jsonb(${displayName}::text))` })
      .where(and(eq(collections.id, id), gt(collections.expiresAt, now), sql`${collections.payload} ->> 'editHash' = ${editHash}`))
      .returning({ id: collections.id });
    return res.length > 0;
  }
}

const g = globalThis as unknown as { __remlabCollections?: CollectionRepo };
export function collectionRepo(): CollectionRepo {
  g.__remlabCollections ??= process.env.DATABASE_URL ? new PgCollectionRepo() : new MemoryCollectionRepo();
  return g.__remlabCollections;
}
