// Drizzle-схема. Каркас Stage 1: один агрегат Project хранится как jsonb (ADR-0008);
// session_id вынесен колонкой для выборок workspace. Расширение на нормальные таблицы — позже.

import { pgTable, text, jsonb, timestamp, index } from "drizzle-orm/pg-core";
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
