// Postgres-реализация ProjectRepository (Drizzle). Активна, когда задан DATABASE_URL (прод).
// Заменяет MemoryRepository без правок вызывающего кода.

import { eq, desc } from "drizzle-orm";
import { db } from "@/lib/db";
import { projects } from "@/db/schema";
import { project as projectSchema, type Project } from "@/contracts/project";
import type { ProjectRepository } from "@/modules/store/repository";

export class PgRepository implements ProjectRepository {
  async create(p: Project): Promise<Project> {
    await db().insert(projects).values({ id: p.id, sessionId: p.sessionId, data: p });
    return p;
  }

  async get(id: string): Promise<Project | null> {
    const rows = await db().select().from(projects).where(eq(projects.id, id)).limit(1);
    const row = rows[0];
    return row ? projectSchema.parse(row.data) : null;
  }

  async update(id: string, patch: Partial<Project>): Promise<Project | null> {
    const cur = await this.get(id);
    if (!cur) return null;
    const next: Project = { ...cur, ...patch, updatedAt: new Date().toISOString() };
    await db().update(projects).set({ data: next, updatedAt: new Date() }).where(eq(projects.id, id));
    return next;
  }

  async listBySession(sessionId: string): Promise<Project[]> {
    const rows = await db()
      .select()
      .from(projects)
      .where(eq(projects.sessionId, sessionId))
      .orderBy(desc(projects.createdAt));
    return rows.map((r) => projectSchema.parse(r.data));
  }
}
