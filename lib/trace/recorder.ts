// Рекордер прогонов: открыть прогон (выделить seq, вставить строку), выполнить fn в ambient-контексте,
// закрыть (статус + итоги). recordStep пишет один шаг. Все записи best-effort: ошибка лога не валит
// пайплайн (guardrail) — оборачиваем в .catch.

import { randomUUID } from "node:crypto";
import { traceStore } from "@/lib/trace/store";
import { runInContext, type RunContext } from "@/lib/trace/context";
import type { RunStatus, StepRow } from "@/lib/trace/types";

export type RunMeta = {
  pipelineId: string;
  pipelineVersion: string;
  projectId?: string | null;
  sessionId?: string | null;
  meta?: Record<string, unknown>;
};

export async function runWithTrace<T>(
  runMeta: RunMeta,
  fn: (ctx: RunContext) => Promise<T>,
): Promise<{ result: T; ctx: RunContext }> {
  const store = traceStore();
  const seq = await store.allocSeq().catch(() => 0);
  const ctx: RunContext = {
    runId: randomUUID(), seq,
    projectId: runMeta.projectId ?? null, sessionId: runMeta.sessionId ?? null,
    stepCounter: 0, totalCostUsd: 0, totalLatencyMs: 0,
  };
  await store.insertRun({
    id: ctx.runId, seq, projectId: ctx.projectId, sessionId: ctx.sessionId,
    pipelineId: runMeta.pipelineId, pipelineVersion: runMeta.pipelineVersion,
    status: "running", error: null, totalLatencyMs: null, totalCostUsd: null,
    meta: runMeta.meta ?? null, startedAt: new Date(), finishedAt: null,
  }).catch(() => {});

  let status: RunStatus = "ok";
  let error: string | null = null;
  try {
    const result = await runInContext(ctx, () => fn(ctx));
    return { result, ctx };
  } catch (e) {
    status = "error";
    error = e instanceof Error ? e.message : String(e);
    throw e;
  } finally {
    await store.finishRun(ctx.runId, {
      status, error, totalLatencyMs: ctx.totalLatencyMs, totalCostUsd: ctx.totalCostUsd, finishedAt: new Date(),
    }).catch(() => {});
  }
}

// Записать шаг. id можно задать заранее (чтобы привязать ассеты до вставки). Аккумулирует итоги в ctx.
export async function recordStep(
  ctx: RunContext,
  step: Omit<StepRow, "runId" | "idx"> & { id: string },
): Promise<void> {
  const idx = ctx.stepCounter++;
  ctx.totalCostUsd += step.costUsd ?? 0;
  ctx.totalLatencyMs += step.latencyMs ?? 0;
  await traceStore().insertStep({ ...step, runId: ctx.runId, idx }).catch(() => {});
}
