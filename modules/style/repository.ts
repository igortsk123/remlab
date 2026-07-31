// Repository результата игры «узнай свой вкус» — тем же паттерном, что estimates/projects:
// DATABASE_URL → Postgres, иначе in-memory. Один стиль на сессию (upsert по session_id).

import { eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { styleResults } from "@/db/schema";
import type { StyleId } from "@/lib/styles/quiz";

export interface StyleResult {
  sessionId: string;
  style: StyleId;
  updatedAt: string; // ISO
}

export interface StyleResultRepository {
  get(sessionId: string): Promise<StyleResult | null>;
  upsert(sessionId: string, style: StyleId): Promise<StyleResult>;
}

class MemoryStyleResultRepository implements StyleResultRepository {
  private readonly bySession = new Map<string, StyleResult>();
  async get(sessionId: string) {
    return this.bySession.get(sessionId) ?? null;
  }
  async upsert(sessionId: string, style: StyleId) {
    const next: StyleResult = { sessionId, style, updatedAt: new Date().toISOString() };
    this.bySession.set(sessionId, next);
    return next;
  }
}

class PgStyleResultRepository implements StyleResultRepository {
  async get(sessionId: string) {
    const rows = await db().select().from(styleResults).where(eq(styleResults.sessionId, sessionId)).limit(1);
    const r = rows[0];
    return r ? { sessionId: r.sessionId, style: r.style as StyleId, updatedAt: r.updatedAt.toISOString() } : null;
  }
  async upsert(sessionId: string, style: StyleId) {
    const now = new Date();
    await db()
      .insert(styleResults)
      .values({ sessionId, style, updatedAt: now })
      .onConflictDoUpdate({ target: styleResults.sessionId, set: { style, updatedAt: now } });
    return { sessionId, style, updatedAt: now.toISOString() };
  }
}

const g = globalThis as unknown as { __remlabStyleRepo?: StyleResultRepository };
export function styleResultRepo(): StyleResultRepository {
  if (!g.__remlabStyleRepo) {
    g.__remlabStyleRepo = process.env.DATABASE_URL ? new PgStyleResultRepository() : new MemoryStyleResultRepository();
  }
  return g.__remlabStyleRepo;
}
