// Проект комнаты — агрегат всего пути одной комнаты (упрощённая модель для каркаса Stage 1).
// Источник правды по форме данных. Хранилище — за интерфейсом Repository (in-memory сейчас).

import { z } from "zod";
import { roomType, goal, interventionLevel, budgetBand, keepItem, constraint } from "@/contracts/enums";
import { styleProfile } from "@/contracts/style";

export const photo = z.object({
  id: z.string(),
  mimeType: z.string(),
  dataUrl: z.string(), // data:...;base64,... — для каркаса храним инлайн
});
export type Photo = z.infer<typeof photo>;

// Действие над объектом: оставить / поменять / убрать. Легаси-значение "suggest_change" (старые прогоны)
// приводим к "change", чтобы уже сохранённые проекты продолжали читаться.
export const objectAction = z.enum(["keep", "change", "remove"]);
export type ObjectAction = z.infer<typeof objectAction>;

export const detectedObject = z.object({
  label: z.string(),
  action: z.preprocess((v) => (v === "suggest_change" ? "change" : v), objectAction),
});
export type DetectedObject = z.infer<typeof detectedObject>;

export const analysis = z.object({
  summary: z.string(),
  objects: z.array(detectedObject),
});
export type Analysis = z.infer<typeof analysis>;

export const idea = z.object({ title: z.string(), detail: z.string() });
export type Idea = z.infer<typeof idea>;

export const catalogItem = z.object({
  kind: z.enum(["product", "material"]),
  category: z.string(),
  title: z.string(),
  priceRub: z.number().int().nonnegative(),
  locked: z.boolean().default(false),
});
export type CatalogItem = z.infer<typeof catalogItem>;

export const budgetRange = z.object({
  minRub: z.number().int().nonnegative(),
  maxRub: z.number().int().nonnegative(),
  confidence: z.enum(["low", "medium", "high"]),
});
export type BudgetRange = z.infer<typeof budgetRange>;

export const briefSchema = z.object({
  roomType,
  goal,
  interventionLevel,
  city: z.string().default(""),
  budgetBand,
  keep: z.array(keepItem).default([]),
  constraints: z.array(constraint).default([]),
});
export type Brief = z.infer<typeof briefSchema>;

export const projectStatus = z.enum([
  "started", "brief_done", "analyzed", "selection_done", "style_done", "preview_ready", "paid",
]);
export type ProjectStatus = z.infer<typeof projectStatus>;

export const project = z.object({
  id: z.string(),
  sessionId: z.string(),
  title: z.string(),
  status: projectStatus,
  brief: briefSchema.partial().default({}),
  photos: z.array(photo).default([]),
  styleProfile: styleProfile.optional(),
  analysis: analysis.optional(), // предложение модели (что она увидела)
  objectChoices: z.array(detectedObject).default([]), // финальный выбор ПОЛЬЗОВАТЕЛЯ по объектам
  wish: z.string().default(""), // одно общее поле-пожелание пользователя (свободный текст)
  previewImage: photo.optional(),
  ideas: z.array(idea).default([]),
  items: z.array(catalogItem).default([]),
  budget: budgetRange.optional(),
  paid: z.boolean().default(false),
  generationSeq: z.number().int().optional(), // «номер генерации» для показа/разбора (ADR-0013)
  traceRunId: z.string().optional(), // id прогона в трейсе (для разбора по номеру)
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type Project = z.infer<typeof project>;
