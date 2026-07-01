// Перечисления домена Stage 1 (единый источник — Zod-схемы, тип через z.infer).

import { z } from "zod";

export const roomType = z.enum(["living_room", "bedroom"]);
export type RoomType = z.infer<typeof roomType>;

export const goal = z.enum(["refresh", "estimate_cost"]);
export type Goal = z.infer<typeof goal>;

// 1 освежить · 2 недорого обновить · 3 лёгкий косметический (CJM §5)
export const interventionLevel = z.enum(["refresh", "budget_update", "light_cosmetic"]);
export type InterventionLevel = z.infer<typeof interventionLevel>;

export const budgetBand = z.enum(["u30", "30_70", "70_150", "150_300", "300p", "unknown"]);
export type BudgetBand = z.infer<typeof budgetBand>;

export const keepItem = z.enum([
  "floor", "walls", "sofa_bed", "wardrobe", "curtains", "light", "all_changeable", "unknown",
]);
export type KeepItem = z.infer<typeof keepItem>;

export const constraint = z.enum([
  "kids", "pets", "for_rent", "no_drilling", "no_painting", "easy_remove", "small", "low_light",
]);
export type Constraint = z.infer<typeof constraint>;
