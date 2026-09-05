// Drizzle-схема. Каркас Stage 1: один агрегат Project хранится как jsonb (ADR-0008);
// session_id вынесен колонкой для выборок workspace. Расширение на нормальные таблицы — позже.
// Трейсинг пайплайна (ADR-0013): runs/steps/assets — подробный лог каждого вызова LLM.

import { pgTable, text, jsonb, timestamp, integer, bigint, doublePrecision, boolean, index, serial, uniqueIndex } from "drizzle-orm/pg-core";
import type { Project } from "@/contracts/project";
import type { Estimate } from "@/contracts/estimate";

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

// Смета-лист (v0.4, ADR-0016) — jsonb-агрегат, как projects.
export const estimates = pgTable(
  "estimates",
  {
    id: text("id").primaryKey(),
    sessionId: text("session_id").notNull(),
    data: jsonb("data").$type<Estimate>().notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("estimates_session_idx").on(t.sessionId)],
);

// Лог кликов через /go/ — приоритет реф-регистраций (какие магазины популярны).
export const linkClicks = pgTable(
  "link_clicks",
  {
    id: text("id").primaryKey(),
    estimateId: text("estimate_id").notNull(),
    itemId: text("item_id").notNull(),
    domain: text("domain"),
    targetUrl: text("target_url").notNull(),
    sessionId: text("session_id"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("link_clicks_domain_idx").on(t.domain)],
);

// Маршруты реф-программ: домен магазина → шаблон реф-URL (late-binding). Наполняется по мере
// регистраций владельца; пока пусто → /go/ отдаёт прямую ссылку.
export const linkRoutes = pgTable("link_routes", {
  domain: text("domain").primaryKey(),
  network: text("network").notNull(), // gdeslon | admitad | epn | direct | ...
  urlTemplate: text("url_template").notNull(), // содержит {url} — исходная ссылка (encoded)
  priority: integer("priority").default(0),
  active: boolean("active").notNull().default(true),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

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

// Результат игры «узнай свой вкус» (/styles): один стиль на сессию, повторная игра перезаписывает.
export const styleResults = pgTable("style_results", {
  sessionId: text("session_id").primaryKey(),
  style: text("style").notNull(), // StyleId из lib/styles/quiz.ts
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

// Лиды «найти дешевле» (К6). email — ПДн: собираем ТОЛЬКО по согласию (чекбокс, interim); юр. часть — TODO.
export const leads = pgTable(
  "leads",
  {
    id: text("id").primaryKey(),
    email: text("email"),
    channel: text("channel").notNull(), // email | telegram | max
    url: text("url"),
    city: text("city"),
    kind: text("kind"),
    sessionId: text("session_id"),
    // П7 лид-канал: номер заявки (sequence в SQL), регион по IP, чат мессенджера, статус.
    leadNo: integer("lead_no"),
    ipRegion: text("ip_region"),
    messengerChatId: text("messenger_chat_id"),
    status: text("status"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("leads_session_idx").on(t.sessionId)],
);

// Сообщения по заявке (П7): маппинг «сообщение в служебном TG-боте ↔ заявка» для ответов реплаем.
export const leadMessages = pgTable(
  "lead_messages",
  {
    id: text("id").primaryKey(),
    leadId: text("lead_id").notNull(),
    direction: text("direction").notNull(), // in | out
    text: text("text").notNull(),
    adminTgMessageId: bigint("admin_tg_message_id", { mode: "number" }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("lead_messages_lead_idx").on(t.leadId), index("lead_messages_admin_msg_idx").on(t.adminTgMessageId)],
);

// Проверка ориентации 3D-мешей человеком (ADR-0131, /lab/mesh-review): задачи ставит
// DEV-конвейер, решения append-only забираются курсором after_id (mesh_review_sync.py).
export const meshReviewTasks = pgTable(
  "mesh_review_tasks",
  {
    id: serial("id").primaryKey(),
    taskKey: text("task_key").notNull().unique(), // revision_key: sku|glb_sha|contract
    sku: text("sku").notNull(),
    role: text("role"),
    contract: text("contract").notNull(),
    payload: jsonb("payload").notNull(), // рендеры (data-URL), варианты кнопок, evidence
    status: text("status").notNull().default("open"), // open | decided | superseded
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("mesh_review_tasks_status_idx").on(t.status)],
);

export const meshReviewDecisions = pgTable(
  "mesh_review_decisions",
  {
    id: serial("id").primaryKey(),
    taskId: integer("task_id").notNull(),
    choice: text("choice").notNull(), // front_0|front_90|front_180|front_270|symmetric|bad_up|bad_mesh|skip
    reviewer: text("reviewer").notNull().default("owner"),
    idemKey: text("idem_key").notNull().unique(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("mesh_review_decisions_task_idx").on(t.taskId)],
);

// Ручная приёмка мешей владельцем (план mesh-owner-audit, /lab/mesh-audit). Истина по мешам живёт
// на DEV; здесь — read-model «одна строка на товар = его текущий меш» (пушит DEV по Bearer),
// журнал решений append-only (курсор after_id, как у mesh-review) и партии публикации моделей.
export const meshAuditItems = pgTable(
  "mesh_audit_items",
  {
    id: serial("id").primaryKey(), // порядок карточек = порядок регистрации: новое всегда в конце
    sku: text("sku").notNull().unique(),
    generationKey: text("generation_key").notNull(), // текущее физическое поколение — CAS при клике
    revisionKey: text("revision_key"),
    role: text("role"),
    name: text("name"),
    imageUrl: text("image_url"), // фото товара (CDN магазина) — эталон для сравнения
    posterUrl: text("poster_url"), // лёгкий рендер 320px, живёт постоянно
    modelPath: text("model_path").notNull(), // путь модели внутри каталога партии
    seed: integer("seed"),
    attempt: integer("attempt"), // порядковый номер попытки генерации у товара
    generatedAt: timestamp("generated_at", { withTimezone: true }),
    photoStale: boolean("photo_stale").notNull().default(false), // меш от старого фото — перегенерится сам
    manualAttempts: integer("manual_attempts").notNull().default(0), // ручные переделки за всё время (≤2)
    status: text("status").notNull().default("open"), // open|redo_requested|redo_queued|redo_blocked|replace_needed
    reworkStatus: text("rework_status"), // ACK с DEV: requested|applied|queued|running|done|blocked
    reworkError: text("rework_error"),
    redoneAt: timestamp("redone_at", { withTimezone: true }), // пришло новое поколение после переделки
    seenAt: timestamp("seen_at", { withTimezone: true }), // владелец открывал страницу с этой карточкой
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("mesh_audit_items_status_idx").on(t.status)],
);

export const meshAuditDecisions = pgTable(
  "mesh_audit_decisions",
  {
    id: serial("id").primaryKey(),
    itemId: integer("item_id").notNull(),
    sku: text("sku").notNull(),
    generationKey: text("generation_key").notNull(), // какой именно меш забракован
    verdict: text("verdict").notNull(), // redo | replace_needed
    manualAttemptNo: integer("manual_attempt_no").notNull(), // 1, 2 — переделки; 3 — «нужна замена»
    reviewer: text("reviewer").notNull().default("owner"),
    idemKey: text("idem_key").notNull().unique(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    index("mesh_audit_decisions_item_idx").on(t.itemId),
    // две вкладки одновременно не выдадут одному товару две «первые» переделки
    uniqueIndex("mesh_audit_decisions_sku_attempt_uq").on(t.sku, t.manualAttemptNo),
  ],
);

// Отмена случайного клика (владелец 05.09): решение удаляется из журнала, а факт отмены
// остаётся здесь append-only — конвейер забирает курсором и откатывает у себя.
export const meshAuditCancellations = pgTable(
  "mesh_audit_cancellations",
  {
    id: serial("id").primaryKey(),
    decisionId: integer("decision_id").notNull(),
    itemId: integer("item_id").notNull(),
    sku: text("sku").notNull(),
    generationKey: text("generation_key").notNull(),
    verdict: text("verdict").notNull(),
    manualAttemptNo: integer("manual_attempt_no").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("mesh_audit_cancellations_item_idx").on(t.itemId)],
);

export const meshAuditBatches = pgTable(
  "mesh_audit_batches",
  {
    id: serial("id").primaryKey(),
    batch: integer("batch").notNull(), // номер партии: страницы (b-1)*10+1 … b*10
    token: text("token").notNull().unique(), // каталог releases/<token> на проде — непредсказуемый
    status: text("status").notNull().default("requested"), // requested|uploading|verifying|active|retiring|removed|failed
    filesTotal: integer("files_total"),
    filesDone: integer("files_done"),
    bytesTotal: bigint("bytes_total", { mode: "number" }),
    error: text("error"),
    requestedAt: timestamp("requested_at", { withTimezone: true }).notNull().defaultNow(),
    activatedAt: timestamp("activated_at", { withTimezone: true }),
    removedAt: timestamp("removed_at", { withTimezone: true }),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("mesh_audit_batches_status_idx").on(t.status)],
);
