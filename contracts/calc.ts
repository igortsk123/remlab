// Контракты калькулятора материалов v2 (роадмап calc-materials). Рабочее состояние — КЛИЕНТСКОЕ
// (локально в сессии, localStorage); в серверную смету (contracts/estimate.ts) материализуется в К3.
// Один расчёт = один вид материала (kind на уровне проекта); смета копит несколько расчётов.

import { z } from "zod";

export const calcKind = z.enum(["oboi", "plitka", "kraska", "laminat"]);
export type CalcKind = z.infer<typeof calcKind>;

// Проём (окно/дверь/прочее исключаемое), вычитается из площади стены (К1).
export const opening = z.object({
  id: z.string(),
  kind: z.enum(["window", "door", "other"]),
  widthM: z.number().nonnegative(),
  heightM: z.number().nonnegative(),
  count: z.number().int().positive(),
});
export type Opening = z.infer<typeof opening>;

// Стена/поверхность (обои/плитка/краска).
export const surface = z.object({
  id: z.string(),
  label: z.string(),
  lengthM: z.number().nonnegative(),
  heightM: z.number().nonnegative(),
  openings: z.array(opening),
});
export type Surface = z.infer<typeof surface>;

// Зона пола (ламинат) — дополнительная или исключаемая.
export const zone = z.object({
  id: z.string(),
  label: z.string(),
  lengthM: z.number().nonnegative(),
  widthM: z.number().nonnegative(),
});
export type Zone = z.infer<typeof zone>;

export const floor = z.object({
  lengthM: z.number().nonnegative(),
  widthM: z.number().nonnegative(),
  extraZones: z.array(zone),
  excludedZones: z.array(zone),
});
export type Floor = z.infer<typeof floor>;

// Параметры материала — плоский набор, все опциональны; заполняются по виду в К2.
export const materialSpec = z.object({
  // обои
  rollWidthM: z.number().positive().optional(),
  rollLengthM: z.number().positive().optional(),
  rapportM: z.number().nonnegative().optional(),
  offset: z.boolean().optional(),
  pricePerRollRub: z.number().nonnegative().optional(),
  // плитка
  tileLengthMm: z.number().positive().optional(),
  tileWidthMm: z.number().positive().optional(),
  seamMm: z.number().nonnegative().optional(),
  tilesPerPack: z.number().int().positive().optional(),
  // краска
  surfaceType: z.string().optional(),
  paintType: z.string().optional(),
  consumptionM2PerL: z.number().positive().optional(),
  coats: z.number().int().positive().optional(),
  packVolumeL: z.number().positive().optional(),
  // ламинат
  panelLengthMm: z.number().positive().optional(),
  panelWidthMm: z.number().positive().optional(),
  thicknessMm: z.number().positive().optional(),
  panelsPerPack: z.number().int().positive().optional(),
  rowOffset: z.enum(["random", "half", "third"]).optional(),
  minCutMm: z.number().nonnegative().optional(),
  wallGapMm: z.number().nonnegative().optional(),
  direction: z.enum(["length", "width", "diag45", "diag135"]).optional(),
  // общее
  reservePct: z.number().nonnegative().optional(),
  pricePerM2Rub: z.number().nonnegative().optional(),
  pricePerPackRub: z.number().nonnegative().optional(),
});
export type MaterialSpec = z.infer<typeof materialSpec>;

export const room = z.object({
  id: z.string(),
  name: z.string().min(1),
  surfaces: z.array(surface),
  floor: floor.optional(),
  material: materialSpec,
  productUrl: z.string().optional(),
});
export type Room = z.infer<typeof room>;

export const calcProject = z.object({
  version: z.literal(1),
  kind: calcKind,
  rooms: z.array(room),
  updatedAt: z.string(),
});
export type CalcProject = z.infer<typeof calcProject>;
