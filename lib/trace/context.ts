// Ambient-контекст прогона через AsyncLocalStorage: оркестратор открывает прогон, а вложенные
// вызовы провайдеров видят «текущий прогон» без протаскивания ctx через сигнатуры. Нет прогона →
// трейсинг молча выключен (guardrail: логирование НИКОГДА не ломает пайплайн).

import { AsyncLocalStorage } from "node:async_hooks";

export type RunContext = {
  runId: string;
  seq: number;
  projectId: string | null;
  sessionId: string | null;
  stepCounter: number; // мутируется: порядковый номер шага
  totalCostUsd: number; // мутируется: аккумулятор стоимости
  totalLatencyMs: number; // мутируется: аккумулятор времени
};

const storage = new AsyncLocalStorage<RunContext>();

export function currentRun(): RunContext | undefined {
  return storage.getStore();
}

export function runInContext<T>(ctx: RunContext, fn: () => Promise<T>): Promise<T> {
  return storage.run(ctx, fn);
}
