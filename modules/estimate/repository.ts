// Repository смет (v0.4) — тем же паттерном, что projects (ADR-0008): jsonb-агрегат за
// интерфейсом. DATABASE_URL → Postgres, иначе in-memory. + лог кликов /go/ (приоритет реф-регистраций).

import { eq, desc } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { db } from "@/lib/db";
import { estimates, linkClicks, linkRoutes } from "@/db/schema";
import { estimate as estimateSchema, type Estimate } from "@/contracts/estimate";
import type { LinkRoute } from "@/lib/estimate/links";

export interface EstimateRepository {
  create(e: Estimate): Promise<Estimate>;
  get(id: string): Promise<Estimate | null>;
  update(id: string, patch: Partial<Estimate>): Promise<Estimate | null>;
  listBySession(sessionId: string): Promise<Estimate[]>;
  logClick(c: { estimateId: string; itemId: string; domain: string | null; targetUrl: string; sessionId: string | null }): Promise<void>;
  activeRoutes(): Promise<LinkRoute[]>;
}

class MemoryEstimateRepository implements EstimateRepository {
  private readonly byId = new Map<string, Estimate>();
  async create(e: Estimate) { this.byId.set(e.id, e); return e; }
  async get(id: string) { return this.byId.get(id) ?? null; }
  async update(id: string, patch: Partial<Estimate>) {
    const cur = this.byId.get(id);
    if (!cur) return null;
    const next = { ...cur, ...patch, updatedAt: new Date().toISOString() };
    this.byId.set(id, next);
    return next;
  }
  async listBySession(sessionId: string) {
    return [...this.byId.values()].filter((e) => e.sessionId === sessionId).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }
  async logClick() { /* in-memory: клики не храним (только прод) */ }
  async activeRoutes() { return []; }
}

class PgEstimateRepository implements EstimateRepository {
  async create(e: Estimate) {
    await db().insert(estimates).values({ id: e.id, sessionId: e.sessionId, data: e });
    return e;
  }
  async get(id: string) {
    const rows = await db().select().from(estimates).where(eq(estimates.id, id)).limit(1);
    return rows[0] ? estimateSchema.parse(rows[0].data) : null;
  }
  async update(id: string, patch: Partial<Estimate>) {
    const cur = await this.get(id);
    if (!cur) return null;
    const next = { ...cur, ...patch, updatedAt: new Date().toISOString() };
    await db().update(estimates).set({ data: next, updatedAt: new Date() }).where(eq(estimates.id, id));
    return next;
  }
  async listBySession(sessionId: string) {
    const rows = await db().select().from(estimates).where(eq(estimates.sessionId, sessionId)).orderBy(desc(estimates.createdAt));
    return rows.map((r) => estimateSchema.parse(r.data));
  }
  async logClick(c: { estimateId: string; itemId: string; domain: string | null; targetUrl: string; sessionId: string | null }) {
    await db().insert(linkClicks).values({
      id: randomUUID(), estimateId: c.estimateId, itemId: c.itemId,
      domain: c.domain, targetUrl: c.targetUrl, sessionId: c.sessionId,
    });
  }
  async activeRoutes(): Promise<LinkRoute[]> {
    const rows = await db().select().from(linkRoutes).where(eq(linkRoutes.active, true));
    return rows.map((r) => ({ domain: r.domain, network: r.network, urlTemplate: r.urlTemplate, priority: r.priority ?? 0, active: r.active }));
  }
}

const g = globalThis as unknown as { __remlabEstimateRepo?: EstimateRepository };
export function estimateRepo(): EstimateRepository {
  if (!g.__remlabEstimateRepo) {
    g.__remlabEstimateRepo = process.env.DATABASE_URL ? new PgEstimateRepository() : new MemoryEstimateRepository();
  }
  return g.__remlabEstimateRepo;
}
