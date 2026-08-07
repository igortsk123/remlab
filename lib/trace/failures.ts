// Счётчик сбоев записи трейса (T0 truth-first, замечание рефери §40): best-effort не значит
// «молча» — сбой лога не валит пайплайн, но обязан быть виден (иначе самые неприятные падения
// оказываются ровно без трейсов, как класс багов «0 ассетов» до traces-init).
// Секреты и содержимое не логируем — только этап и message ошибки.

let failures = 0;

export function traceWriteFailed(where: string, e: unknown): void {
  failures += 1;
  const msg = e instanceof Error ? e.message : String(e);
  console.warn(`[trace-fail #${failures}] ${where}: ${msg}`);
}

// Счётчик с момента старта процесса — отдаётся в /api/health как traceWriteFailures.
export function traceWriteFailures(): number {
  return failures;
}
