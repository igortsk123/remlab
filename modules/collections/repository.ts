// Хранилище коллекций (план b2b-05): DATABASE_URL → Postgres, иначе память процесса (тесты).

import { createHash } from "node:crypto";
import { eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { collections } from "@/db/schema";
import { randomToken } from "@/lib/token";
import type { CollectionIn } from "@/contracts/collection";

export type StoredCollection = { id: string; partnerId: string; payload: CollectionIn; createdAt: Date };

export interface CollectionRepo {
  create(partnerId: string, c: CollectionIn, now?: Date): Promise<StoredCollection>;
  get(id: string, now?: Date): Promise<StoredCollection | null>;
}

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
}

const g = globalThis as unknown as { __remlabCollections?: CollectionRepo };
export function collectionRepo(): CollectionRepo {
  g.__remlabCollections ??= process.env.DATABASE_URL ? new PgCollectionRepo() : new MemoryCollectionRepo();
  return g.__remlabCollections;
}
