// Хранилище коллекций (план b2b-05): DATABASE_URL → Postgres, иначе память процесса (тесты).

import { createHash } from "node:crypto";
import { and, eq, gt, sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { collections } from "@/db/schema";
import { randomToken } from "@/lib/token";
import type { CollectionIn } from "@/contracts/collection";

export type StoredCollection = { id: string; partnerId: string; payload: CollectionIn; createdAt: Date };

export interface CollectionRepo {
  create(partnerId: string, c: CollectionIn, now?: Date): Promise<StoredCollection>;
  get(id: string, now?: Date): Promise<StoredCollection | null>;
  /** Картинка снята после сохранения: ставится ОДИН раз и только в первые SHOT_WINDOW_MS (иначе — false). */
  setShot(id: string, shot: string, now?: Date): Promise<boolean>;
}

// Окно, в которое можно прикрепить кадр: фоновый черновик снимается за минуту-две; дольше — снимок уже не «этот».
export const SHOT_WINDOW_MS = 30 * 60_000;

const hashOf = (c: CollectionIn) => createHash("sha256").update(JSON.stringify(c)).digest("hex").slice(0, 16);

export class MemoryCollectionRepo implements CollectionRepo {
  readonly rows = new Map<string, StoredCollection & { expiresAt: Date }>();
  async create(partnerId: string, c: CollectionIn, now = new Date()) {
    const row = { id: randomToken(), partnerId, payload: c, createdAt: now, expiresAt: new Date(now.getTime() + 365 * 86_400_000) };
    this.rows.set(row.id, row);
    return row;
  }
  async get(id: string, now = new Date()) {
    const r = this.rows.get(id);
    return r && r.expiresAt > now ? r : null;
  }
  async setShot(id: string, shot: string, now = new Date()) {
    const r = this.rows.get(id);
    if (!r || r.payload.shot || now.getTime() - r.createdAt.getTime() > SHOT_WINDOW_MS) return false;
    r.payload = { ...r.payload, shot };
    return true;
  }
}

class PgCollectionRepo implements CollectionRepo {
  async create(partnerId: string, c: CollectionIn, now = new Date()) {
    const id = randomToken();
    await db().insert(collections).values({
      id, partnerId, apartmentId: c.apartmentId, baseVariant: c.baseVariant, sendId: c.sendId ?? null, lang: c.lang,
      payload: c as unknown as Record<string, unknown>, contentHash: hashOf(c), createdAt: now,
    });
    return { id, partnerId, payload: c, createdAt: now };
  }
  async get(id: string, now = new Date()) {
    const r = (await db().select().from(collections).where(eq(collections.id, id)).limit(1))[0];
    if (!r || r.expiresAt <= now) return null;
    return { id: r.id, partnerId: r.partnerId, payload: r.payload as unknown as CollectionIn, createdAt: r.createdAt };
  }
  async setShot(id: string, shot: string, now = new Date()) {
    // одно условие в одном UPDATE: нет картинки И коллекция свежая — гонка двух запросов даёт одну запись
    const res = await db().update(collections)
      .set({ payload: sql`jsonb_set(${collections.payload}, '{shot}', to_jsonb(${shot}::text))` })
      .where(and(eq(collections.id, id), sql`(${collections.payload} -> 'shot') is null`,
        gt(collections.createdAt, new Date(now.getTime() - SHOT_WINDOW_MS))))
      .returning({ id: collections.id });
    return res.length > 0;
  }
}

const g = globalThis as unknown as { __remlabCollections?: CollectionRepo };
export function collectionRepo(): CollectionRepo {
  g.__remlabCollections ??= process.env.DATABASE_URL ? new PgCollectionRepo() : new MemoryCollectionRepo();
  return g.__remlabCollections;
}
