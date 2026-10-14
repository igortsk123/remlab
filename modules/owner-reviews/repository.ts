// Отметки владельца (ADR-0275): DATABASE_URL → Postgres, иначе память процесса (тесты).

import { and, eq, gt, asc } from "drizzle-orm";
import { db } from "@/lib/db";
import { ownerReviews } from "@/db/schema";

export type Review = { id: number; kind: string; itemKey: string; verdict: string; comment: string | null; createdAt: Date };
export type ReviewIn = Omit<Review, "id" | "createdAt">;

export interface ReviewRepo {
  add(r: ReviewIn): Promise<Review>;
  list(kind: string, afterId: number, limit: number): Promise<Review[]>;
}

export class MemoryReviewRepo implements ReviewRepo {
  readonly rows: Review[] = [];
  async add(r: ReviewIn) { const row = { ...r, id: this.rows.length + 1, createdAt: new Date() }; this.rows.push(row); return row; }
  async list(kind: string, afterId: number, limit: number) { return this.rows.filter((x) => x.kind === kind && x.id > afterId).slice(0, limit); }
}

class PgReviewRepo implements ReviewRepo {
  async add(r: ReviewIn) {
    const [row] = await db().insert(ownerReviews).values(r).returning();
    return row as Review;
  }
  async list(kind: string, afterId: number, limit: number) {
    return (await db().select().from(ownerReviews).where(and(eq(ownerReviews.kind, kind), gt(ownerReviews.id, afterId)))
      .orderBy(asc(ownerReviews.id)).limit(limit)) as Review[];
  }
}

const g = globalThis as unknown as { __remlabReviews?: ReviewRepo };
export function reviewRepo(): ReviewRepo {
  g.__remlabReviews ??= process.env.DATABASE_URL ? new PgReviewRepo() : new MemoryReviewRepo();
  return g.__remlabReviews;
}
