// Типы трейсинга пайплайна. Ряды (RunRow/StepRow/AssetRow) — форма записей в хранилище;
// TracedMeta — то, что вызывающий код кладёт в вызов провайдера для обогащения лога.

export type AssetRole = "input" | "intermediate" | "output";
export type StepKind = "vision" | "image" | "text";
export type RunStatus = "running" | "ok" | "error";

// Обогащение вызова провайдера (провайдер игнорирует; читает инструментированная обёртка).
export type TracedMeta = {
  stepName?: string;
  promptId?: string;
  promptVersion?: string;
  params?: Record<string, unknown>;
};

export type RunRow = {
  id: string;
  seq: number;
  projectId: string | null;
  sessionId: string | null;
  pipelineId: string;
  pipelineVersion: string;
  status: RunStatus;
  error: string | null;
  totalLatencyMs: number | null;
  totalCostUsd: number | null;
  meta: Record<string, unknown> | null;
  startedAt: Date;
  finishedAt: Date | null;
};

export type StepRow = {
  id: string;
  runId: string;
  idx: number;
  stepName: string;
  kind: StepKind;
  provider: string;
  model: string;
  promptId: string | null;
  promptVersion: string | null;
  promptText: string | null;
  params: Record<string, unknown> | null;
  inputText: string | null;
  outputText: string | null;
  status: "ok" | "error";
  errorKind: string | null;
  errorMessage: string | null;
  latencyMs: number | null;
  costUsd: number | null;
  startedAt: Date;
  finishedAt: Date | null;
};

// Ссылка на сохранённый ассет, которую отдаём вызывающему коду (для показа/логов).
export type AssetRef = {
  id: string;
  url: string;
  storageKey: string;
  mimeType: string;
  sizeBytes: number;
};

export type AssetRow = {
  id: string;
  runId: string;
  stepId: string | null;
  role: AssetRole;
  mimeType: string;
  storageKey: string;
  sizeBytes: number | null;
  createdAt: Date;
};
