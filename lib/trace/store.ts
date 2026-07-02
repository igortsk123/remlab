// Хранилище трейсов. DATABASE_URL задан → Postgres (Drizzle), иначе in-memory (dev/тесты).
// Тот же паттерн, что modules/store/repository.ts. Ошибки записи глушим на уровне рекордера —
// логирование не должно валить пайплайн.

import { sql, eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { generationRuns, generationSteps, generationAssets } from "@/db/schema";
import type { RunRow, StepRow, AssetRow } from "@/lib/trace/types";

export interface TraceStore {
  allocSeq(): Promise<number>;
  insertRun(run: RunRow): Promise<void>;
  finishRun(id: string, patch: Partial<Pick<RunRow, "status" | "error" | "totalLatencyMs" | "totalCostUsd" | "finishedAt">>): Promise<void>;
  insertStep(step: StepRow): Promise<void>;
  insertAsset(asset: AssetRow): Promise<void>;
  annotateRun(runId: string, meta: Record<string, unknown>): Promise<void>;
  getRunBySeq(seq: number): Promise<RunRow | null>;
  getStepsByRun(runId: string): Promise<StepRow[]>;
  getAssetsByRun(runId: string): Promise<AssetRow[]>;
  getAssetById(id: string): Promise<AssetRow | null>;
}

class PgTraceStore implements TraceStore {
  async allocSeq(): Promise<number> {
    const rows = await db().execute<{ seq: number }>(sql`select nextval('generation_seq')::int as seq`);
    return Number((rows as unknown as Array<{ seq: number }>)[0]?.seq ?? 0);
  }
  async insertRun(r: RunRow): Promise<void> {
    await db().insert(generationRuns).values({
      id: r.id, seq: r.seq, projectId: r.projectId, sessionId: r.sessionId,
      pipelineId: r.pipelineId, pipelineVersion: r.pipelineVersion, status: r.status,
      error: r.error, totalLatencyMs: r.totalLatencyMs, totalCostUsd: r.totalCostUsd, meta: r.meta,
    });
  }
  async finishRun(id: string, patch: Partial<RunRow>): Promise<void> {
    await db().update(generationRuns).set({
      status: patch.status, error: patch.error, totalLatencyMs: patch.totalLatencyMs,
      totalCostUsd: patch.totalCostUsd, finishedAt: patch.finishedAt ?? new Date(),
    }).where(eq(generationRuns.id, id));
  }
  async insertStep(s: StepRow): Promise<void> {
    await db().insert(generationSteps).values(s);
  }
  async insertAsset(a: AssetRow): Promise<void> {
    await db().insert(generationAssets).values(a);
  }
  async annotateRun(runId: string, meta: Record<string, unknown>): Promise<void> {
    const rows = await db().select().from(generationRuns).where(eq(generationRuns.id, runId)).limit(1);
    const cur = (rows[0]?.meta as Record<string, unknown> | null) ?? {};
    await db().update(generationRuns).set({ meta: { ...cur, ...meta } }).where(eq(generationRuns.id, runId));
  }
  async getRunBySeq(seq: number): Promise<RunRow | null> {
    const rows = await db().select().from(generationRuns).where(eq(generationRuns.seq, seq)).limit(1);
    return (rows[0] as RunRow) ?? null;
  }
  async getStepsByRun(runId: string): Promise<StepRow[]> {
    return (await db().select().from(generationSteps).where(eq(generationSteps.runId, runId)).orderBy(generationSteps.idx)) as StepRow[];
  }
  async getAssetsByRun(runId: string): Promise<AssetRow[]> {
    return (await db().select().from(generationAssets).where(eq(generationAssets.runId, runId))) as AssetRow[];
  }
  async getAssetById(id: string): Promise<AssetRow | null> {
    const rows = await db().select().from(generationAssets).where(eq(generationAssets.id, id)).limit(1);
    return (rows[0] as AssetRow) ?? null;
  }
}

// In-memory: держит последние прогоны в globalThis (переживает HMR). Для dev/тестов без БД.
type MemState = { seq: number; runs: Map<string, RunRow>; steps: StepRow[]; assets: AssetRow[] };
const g = globalThis as unknown as { __remlabTrace?: MemState; __remlabTraceStore?: TraceStore };
function mem(): MemState {
  if (!g.__remlabTrace) g.__remlabTrace = { seq: 0, runs: new Map(), steps: [], assets: [] };
  return g.__remlabTrace;
}

class MemoryTraceStore implements TraceStore {
  async allocSeq(): Promise<number> { return ++mem().seq; }
  async insertRun(r: RunRow): Promise<void> { mem().runs.set(r.id, r); }
  async finishRun(id: string, patch: Partial<RunRow>): Promise<void> {
    const cur = mem().runs.get(id);
    if (cur) mem().runs.set(id, { ...cur, ...patch, finishedAt: patch.finishedAt ?? new Date() });
  }
  async insertStep(s: StepRow): Promise<void> { mem().steps.push(s); }
  async insertAsset(a: AssetRow): Promise<void> { mem().assets.push(a); }
  async annotateRun(runId: string, meta: Record<string, unknown>): Promise<void> {
    const cur = mem().runs.get(runId);
    if (cur) mem().runs.set(runId, { ...cur, meta: { ...(cur.meta ?? {}), ...meta } });
  }
  async getRunBySeq(seq: number): Promise<RunRow | null> {
    return [...mem().runs.values()].find((r) => r.seq === seq) ?? null;
  }
  async getStepsByRun(runId: string): Promise<StepRow[]> {
    return mem().steps.filter((s) => s.runId === runId).sort((a, b) => a.idx - b.idx);
  }
  async getAssetsByRun(runId: string): Promise<AssetRow[]> {
    return mem().assets.filter((a) => a.runId === runId);
  }
  async getAssetById(id: string): Promise<AssetRow | null> {
    return mem().assets.find((a) => a.id === id) ?? null;
  }
}

export function traceStore(): TraceStore {
  if (!g.__remlabTraceStore) {
    g.__remlabTraceStore = process.env.DATABASE_URL ? new PgTraceStore() : new MemoryTraceStore();
  }
  return g.__remlabTraceStore;
}
