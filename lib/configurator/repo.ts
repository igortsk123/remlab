// Хранение подборов конфигуратора. Как у сметы (`modules/estimate/repository.ts`): есть БД —
// пишем в неё, нет (локально, e2e) — в память процесса. Наружу отдаём БЕЗ контакта.

import { randomUUID } from "node:crypto";

import { eq } from "drizzle-orm";

import type { Configuration } from "@/contracts/configurator";
import { db } from "@/lib/db";
import { flatConfigs } from "@/db/schema";

export interface QuoteLine {
  slotId: string;
  optionId: string;
  titleRu: string;
  roomId: string;
  priceGbp: number;
}

export interface Quote {
  basePriceGbp: number;
  upgradesGbp: number;
  totalGbp: number;
  currency: "GBP";
  lines: QuoteLine[];
  computedAt: string;
}

export interface SavedConfig {
  id: string;
  configuration: Configuration;
  quote: Quote;
  createdAt: string;
}

export interface SaveInput {
  configuration: Configuration;
  quote: Quote;
  apartmentRevision: string;
  catalogueRevision: string;
  contact?: Record<string, unknown>;
}

/** Публичный токен: 22 символа из uuid — не перебирается и не несёт смысла. */
function newToken(): string {
  return randomUUID().replace(/-/g, "").slice(0, 22);
}

const memory = new Map<string, SavedConfig>();
const hasDb = (): boolean => Boolean(process.env.DATABASE_URL);

export async function saveConfig(input: SaveInput): Promise<string> {
  const id = newToken();
  const record: SavedConfig = {
    id,
    configuration: input.configuration,
    quote: input.quote,
    createdAt: new Date().toISOString(),
  };
  if (!hasDb()) {
    memory.set(id, record);
    return id;
  }
  await db()
    .insert(flatConfigs)
    .values({
      id,
      apartmentId: input.configuration.apartmentId,
      developerId: input.configuration.developerId,
      schemaVersion: 2,
      apartmentRevision: input.apartmentRevision,
      catalogueRevision: input.catalogueRevision,
      selections: input.configuration.selections,
      placements: input.configuration.placements ?? {},
      quote: input.quote as unknown as Record<string, unknown>,
      contact: input.contact ?? null,
    });
  return id;
}

export async function readConfig(id: string): Promise<SavedConfig | null> {
  if (!hasDb()) return memory.get(id) ?? null;
  const rows = await db().select().from(flatConfigs).where(eq(flatConfigs.id, id)).limit(1);
  const row = rows[0];
  if (!row) return null;
  return {
    id: row.id,
    configuration: {
      // старые записи (до 30.09) хранят только выбор — поднимаем до версии 2 с пустыми
      // перемещениями, иначе выданные раньше ссылки перестали бы открываться
      version: 2,
      apartmentId: row.apartmentId,
      developerId: row.developerId,
      selections: row.selections,
      placements: (row.placements as Record<string, { x: number; y: number; rot: number }>) ?? {},
      updatedAt: row.updatedAt.toISOString(),
    },
    quote: row.quote as unknown as Quote,
    createdAt: row.createdAt.toISOString(),
  };
}
