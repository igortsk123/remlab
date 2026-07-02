// Drizzle-схема. Каркас Stage 1: один агрегат Project хранится как jsonb (ADR-0008);
// session_id вынесен колонкой для выборок workspace. Расширение на нормальные таблицы — позже.
// Трейсинг пайплайна (ADR-0013): runs/steps/assets — подробный лог каждого вызова LLM.

import { pgTable, text, jsonb, timestamp, integer, doublePrecision, index } from "drizzle-orm/pg-core";
import type { Project } from "@/contracts/project";

export const projects = pgTable(
  "projects",
  {
    id: text("id").primaryKey(),
    sessionId: text("session_id").notNull(),
    data: jsonb("data").$type<Project>().notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("projects_session_idx").on(t.sessionId)],
);

// Прогон пайплайна = один запуск (фото → превью). seq — человекочитаемый «номер генерации».
export const generationRuns = pgTable(
  "generation_runs",
  {
    id: text("id").primaryKey(),
    seq: integer("seq").notNull().unique(),
    projectId: text("project_id"),
    sessionId: text("session_id"),
    pipelineId: text("pipeline_id").notNull(),
    pipelineVersion: text("pipeline_version").notNull(),
    status: text("status").notNull(), // running | ok | error
    error: text("error"),
    totalLatencyMs: integer("total_latency_ms"),
    totalCostUsd: doublePrecision("total_cost_usd"),
    meta: jsonb("meta").$type<Record<string, unknown>>(),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
  },
  (t) => [index("gen_runs_seq_idx").on(t.seq), index("gen_runs_project_idx").on(t.projectId)],
);

// Шаг = один вызов модели внутри прогона. Хранит промпт, настройки, вход/выход текста, статус.
export const generationSteps = pgTable(
  "generation_steps",
  {
    id: text("id").primaryKey(),
    runId: text("run_id").notNull(),
    idx: integer("idx").notNull(), // порядок внутри прогона
    stepName: text("step_name").notNull(),
    kind: text("kind").notNull(), // vision | image | text
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    promptId: text("prompt_id"),
    promptVersion: text("prompt_version"),
    promptText: text("prompt_text"),
    params: jsonb("params").$type<Record<string, unknown>>(),
    inputText: text("input_text"),
    outputText: text("output_text"),
    status: text("status").notNull(), // ok | error
    errorKind: text("error_kind"),
    errorMessage: text("error_message"),
    latencyMs: integer("latency_ms"),
    costUsd: doublePrecision("cost_usd"),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
  },
  (t) => [index("gen_steps_run_idx").on(t.runId)],
);

// Ассет = картинка (вход/промежуточная/выход). Байты — на диске, тут только ссылка+метаданные.
export const generationAssets = pgTable(
  "generation_assets",
  {
    id: text("id").primaryKey(),
    runId: text("run_id").notNull(),
    stepId: text("step_id"),
    role: text("role").notNull(), // input | intermediate | output
    mimeType: text("mime_type").notNull(),
    storageKey: text("storage_key").notNull(), // относительный путь под TRACE_DIR
    sizeBytes: integer("size_bytes"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("gen_assets_run_idx").on(t.runId)],
);
