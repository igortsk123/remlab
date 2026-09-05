// Партии публикации моделей. На проде одновременно живёт одна активная партия (+ предыдущая на
// grace-период). Владелец просит партию кнопкой; DEV-публикатор льёт в staging, проверяет и
// отчитывается сюда; страница опрашивает состояние.

import { randomBytes } from "node:crypto";
import { desc, eq, inArray } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditBatches } from "@/db/schema";
import type { BatchStateView, BatchView } from "./types";

type Row = typeof meshAuditBatches.$inferSelect;
const PENDING = ["requested", "uploading", "verifying"];

function view(r: Row): BatchView {
  return {
    id: r.id,
    batch: r.batch,
    token: r.token,
    status: r.status,
    filesTotal: r.filesTotal,
    filesDone: r.filesDone,
    bytesTotal: r.bytesTotal,
    error: r.error,
    activatedAt: r.activatedAt?.toISOString() ?? null,
  };
}

export async function batchState(): Promise<BatchStateView> {
  const rows = await db()
    .select()
    .from(meshAuditBatches)
    .where(inArray(meshAuditBatches.status, [...PENDING, "active", "retiring"]))
    .orderBy(desc(meshAuditBatches.id));
  const pick = (statuses: string[]) => rows.find((r) => statuses.includes(r.status));
  const active = pick(["active"]);
  const retiring = pick(["retiring"]);
  const pending = pick(PENDING);
  return { active: active ? view(active) : null, retiring: retiring ? view(retiring) : null, pending: pending ? view(pending) : null };
}

export type BatchResult = { http: 200; body: { ok: true; batch: BatchView } } | { http: 404 | 409; body: { error: string } };

export async function requestBatch(batch: number): Promise<BatchResult> {
  const st = await batchState();
  if (st.pending) return { http: 409, body: { error: `уже готовится партия ${st.pending.batch}` } };
  if (st.active?.batch === batch) return { http: 409, body: { error: "эта партия уже на сервере" } };
  const [row] = await db()
    .insert(meshAuditBatches)
    .values({ batch, token: randomBytes(8).toString("hex") })
    .returning();
  if (!row) return { http: 409, body: { error: "партия не записалась — повторите" } };
  return { http: 200, body: { ok: true, batch: view(row) } };
}

export interface BatchReport {
  status?: string;
  filesTotal?: number;
  filesDone?: number;
  bytesTotal?: number;
  error?: string;
  skus?: string[];
}

// sku, чьи модели сейчас реально отдаются (активная партия + прежняя на grace).
export async function servedSkus(state: BatchStateView): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  for (const b of [state.retiring, state.active]) {
    if (!b) continue;
    const [row] = await db().select({ skus: meshAuditBatches.skus }).from(meshAuditBatches).where(eq(meshAuditBatches.id, b.id));
    for (const sku of row?.skus ?? []) out.set(sku, b.token); // активная перекрывает уходящую
  }
  return out;
}

// Отчёт публикатора. Переход в active уводит прежнюю активную в retiring (её ещё отдаём —
// вкладка владельца могла не догрузить модель); removed ставит сам публикатор после grace.
export async function reportBatch(token: string, p: BatchReport): Promise<BatchResult> {
  const d = db();
  return d.transaction(async (tx) => {
    const [row] = await tx.select().from(meshAuditBatches).where(eq(meshAuditBatches.token, token)).for("update");
    if (!row) return { http: 404, body: { error: "нет такой партии" } };
    if (p.status === "active" && row.status !== "active") {
      await tx.update(meshAuditBatches).set({ status: "retiring", updatedAt: new Date() }).where(eq(meshAuditBatches.status, "active"));
    }
    const [upd] = await tx
      .update(meshAuditBatches)
      .set({
        ...(p.status ? { status: p.status } : {}),
        ...(p.filesTotal !== undefined ? { filesTotal: p.filesTotal } : {}),
        ...(p.filesDone !== undefined ? { filesDone: p.filesDone } : {}),
        ...(p.bytesTotal !== undefined ? { bytesTotal: p.bytesTotal } : {}),
        ...(p.skus ? { skus: p.skus } : {}),
        error: p.error ?? null,
        ...(p.status === "active" ? { activatedAt: new Date() } : {}),
        ...(p.status === "removed" ? { removedAt: new Date() } : {}),
        updatedAt: new Date(),
      })
      .where(eq(meshAuditBatches.id, row.id))
      .returning();
    if (!upd) return { http: 404, body: { error: "партия исчезла во время записи" } };
    return { http: 200, body: { ok: true, batch: view(upd) } };
  });
}
