// Смета-лист (v0.4, ADR-0016) — агрегат, аналогичный Project (jsonb за repository).
// Позиция несёт исходную ссылку; внешний переход всегда через /go/ (late-binding реф).

import { z } from "zod";

export const estimateItem = z.object({
  id: z.string(),
  title: z.string().min(1),
  qty: z.number().nonnegative(),
  unit: z.string().min(1), // рулон / м² / упаковка / л / шт
  unitPriceRub: z.number().nonnegative().optional(),
  url: z.string().url().optional(), // ссылка магазина (пользователя или наша)
  domain: z.string().optional(), // хост из url (для маршрутизации реф)
  source: z.enum(["calc", "user_link", "our_pick"]),
  note: z.string().optional(), // «с запасом 10%», «сопутствующее»
});
export type EstimateItem = z.infer<typeof estimateItem>;

export const estimate = z.object({
  id: z.string(),
  sessionId: z.string(),
  title: z.string().min(1),
  source: z.enum(["calc", "remont", "manual"]),
  items: z.array(estimateItem).default([]),
  meta: z.record(z.string(), z.unknown()).optional(), // площадь, глубина ремонта и т.п.
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type Estimate = z.infer<typeof estimate>;

export function itemTotal(i: EstimateItem): number | undefined {
  return i.unitPriceRub === undefined ? undefined : Math.round(i.unitPriceRub * i.qty);
}

export function estimateTotal(e: Estimate): number {
  return e.items.reduce((s, i) => s + (itemTotal(i) ?? 0), 0);
}
