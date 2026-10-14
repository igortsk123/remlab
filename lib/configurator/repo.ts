import { upgradeConfiguration } from "@/contracts/configurator";
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
  price: number;
}

export interface Quote {
  basePrice: number;
  upgrades: number;
  total: number;
  currency: "GBP" | "RUB";
  lines: QuoteLine[];
  /** Против какого лимита выбирали (снимок на момент сохранения, для отчёта застройщику). */
  certificate?: { amount: number; share: number };
  computedAt: string;
}

/** Старые снимки цены (до 13.10) писали поля с суффиксом Gbp — читаем их тем же видом. */
export function upgradeQuote(raw: Record<string, unknown>): Quote {
  const n = (k: string) => Number(raw[k] ?? raw[`${k}Gbp`] ?? 0);
  const lines = ((raw.lines as Record<string, unknown>[] | undefined) ?? []).map((l) => ({
    slotId: String(l.slotId), optionId: String(l.optionId), titleRu: String(l.titleRu ?? ""), roomId: String(l.roomId ?? ""),
    price: Number(l.price ?? l.priceGbp ?? 0),
  }));
  return {
    basePrice: n("basePrice"), upgrades: n("upgrades"), total: n("total"),
    currency: raw.currency === "RUB" ? "RUB" : "GBP", lines,
    ...(raw.certificate ? { certificate: raw.certificate as Quote["certificate"] } : {}),
    computedAt: String(raw.computedAt ?? ""),
  };
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
      schemaVersion: 3,
      apartmentRevision: input.apartmentRevision,
      catalogueRevision: input.catalogueRevision,
      selections: input.configuration.selections,
      placements: input.configuration.placements ?? {},
      baseVariant: input.configuration.baseVariant ?? null,
      baseSnapshot: input.configuration.baseSnapshot ?? null,
      quote: input.quote as unknown as Record<string, unknown>,
      contact: input.contact ?? null,
      hidden: input.configuration.hidden ?? null,
      collectionId: input.configuration.collectionId ?? null,
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
    // Старые записи (до 30.09) хранят только выбор — поднимаем до версии 2 ОДНОЙ функцией,
    // общей с браузерным черновиком: два разных подъёма рано или поздно разойдутся.
    configuration: upgradeConfiguration({
      version: 1,
      apartmentId: row.apartmentId,
      developerId: row.developerId,
      selections: row.selections,
      placements: (row.placements as Record<string, { x: number; y: number; rot: number }>) ?? {},
      ...(row.baseVariant ? { baseVariant: row.baseVariant } : {}),
      ...(row.baseSnapshot ? { baseSnapshot: row.baseSnapshot } : {}),
      ...(row.hidden ? { hidden: row.hidden } : {}),
      ...(row.collectionId ? { collectionId: row.collectionId } : {}),
      updatedAt: row.updatedAt.toISOString(),
    }),
    quote: upgradeQuote(row.quote),
    createdAt: row.createdAt.toISOString(),
  };
}
