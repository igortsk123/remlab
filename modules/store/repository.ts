// Repository — хранилище проектов за интерфейсом. Реализация сейчас in-memory (каркас Stage 1);
// на деплое заменяется на Postgres/Drizzle без правок вызывающего кода (см. decisions ADR-0008).

import type { Project } from "@/contracts/project";
import { PgRepository } from "@/modules/store/pg-repository";

export interface ProjectRepository {
  create(p: Project): Promise<Project>;
  get(id: string): Promise<Project | null>;
  update(id: string, patch: Partial<Project>): Promise<Project | null>;
  listBySession(sessionId: string): Promise<Project[]>;
}

class MemoryRepository implements ProjectRepository {
  private readonly byId = new Map<string, Project>();

  async create(p: Project): Promise<Project> {
    this.byId.set(p.id, p);
    return p;
  }
  async get(id: string): Promise<Project | null> {
    return this.byId.get(id) ?? null;
  }
  async update(id: string, patch: Partial<Project>): Promise<Project | null> {
    const cur = this.byId.get(id);
    if (!cur) return null;
    const next: Project = { ...cur, ...patch, updatedAt: new Date().toISOString() };
    this.byId.set(id, next);
    return next;
  }
  async listBySession(sessionId: string): Promise<Project[]> {
    return [...this.byId.values()]
      .filter((p) => p.sessionId === sessionId)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }
}

// Синглтон переживает HMR в dev через globalThis.
// DATABASE_URL задан → Postgres (прод), иначе in-memory (локально/тесты/e2e).
const g = globalThis as unknown as { __remlabRepo?: ProjectRepository };
export function repo(): ProjectRepository {
  if (!g.__remlabRepo) {
    g.__remlabRepo = process.env.DATABASE_URL ? new PgRepository() : new MemoryRepository();
  }
  return g.__remlabRepo;
}
