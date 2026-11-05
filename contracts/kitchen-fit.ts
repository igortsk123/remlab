// Посадка примера кухни на кухню квартиры (план onb-09 Т2–Т3, T-20261105-33): ответ солвера `planner/kitchen.py:seat_kitchen`,
// файл `data/partners/kitchen-fit/<квартира>.json` пишет `tools/scout/kitchen_fit.py` (руками не править). Набор берёт отсюда
// конец колонн, форму, глубину комнаты, вентканал, места холодильника и запреты (окно над рядом, глухой конец) —
// `kitchenSpecFromExample(e, { fit })`. Координаты — план кухни в см; `s` — путь набора от его левого конца, `out` — от задней стены.

import { z } from "zod";

import { market } from "@/contracts/partner";

const wall = z.enum(["north", "south", "west", "east"]);
const span = z.tuple([z.number(), z.number()]);
const pt = z.object({ x: z.number(), y: z.number(), h: z.number() }).strict();

export const kitchenFridgeSpot = z.object({
  /** end — у свободного конца на своей стене; leg — у торца плеча Г; corner — за углом (перед глухим концом); wall — у другой стены. */
  where: z.enum(["end", "leg", "corner", "wall"]),
  wall,
  offset_cm: z.number(),
  s: z.number(),
  out: z.number(),
  blind: span.nullable(),
}).strict();

const check = z.object({ code: z.string(), value: z.number(), need: z.number(), ok: z.boolean() }).strict();

const fitOk = z.object({
  market,
  ok: z.literal(true),
  reason: z.array(z.string()).length(0),
  wall,
  u0_cm: z.number(),
  shape: z.enum(["straight", "corner"]),
  shape_changed: z.boolean(),
  length_cm: z.number().positive(),
  columns_at: z.enum(["start", "end"]).nullable(),
  corner_at: z.enum(["start", "end"]).nullable(),
  leg_cm: z.number().nullable(),
  room_depth_cm: z.number().positive(),
  cooks: z.number().int(),
  vent_at_cm: z.number().nullable(),
  vent_distance_cm: z.number().nullable(),
  vent_assumed: z.boolean(),
  fridge_at_cm: z.array(z.number()),
  fridge: z.array(kitchenFridgeSpot),
  blind_cm: z.array(span),
  no_hob_cm: z.array(span),
  checks: z.array(check),
  pose: z.object({ x: z.number(), y: z.number(), rot: z.number() }).strict(),
  right: z.tuple([z.number(), z.number()]),
  normal: z.tuple([z.number(), z.number()]),
  kit: z.object({
    length_cm: z.number(), depth_cm: z.number(), shape: z.enum(["straight", "corner"]), tall_cm: z.number(), uppers: z.boolean(),
    fridge_in_column: z.boolean(), leg_cm: z.number().nullable(), peninsula: z.boolean(), upper_depth_cm: z.number(),
  }).strict(),
  dining: z.object({
    max_seats: z.number().int(),
    table_cm: span.nullable(),
    region_cm: span.nullable(),
    center_cm: span.nullable(),
  }).strict(),
  views: z.object({ kit: z.object({ eye: pt, target: pt }).strict(), counter: z.object({ eye: pt, target: pt }).strict() }).strict(),
}).strict();

const fitFail = z.object({ market, ok: z.literal(false), reason: z.array(z.string()).min(1), why: z.array(z.string()) }).strict();

export const kitchenFit = z.discriminatedUnion("ok", [fitOk, fitFail]);
export type KitchenFit = z.infer<typeof kitchenFit>;
export type KitchenFitOk = z.infer<typeof fitOk>;

export const kitchenFitFile = z.object({
  _about: z.string(),
  room: z.object({ source: z.string(), w: z.number(), d: z.number(), vent_assumed: z.boolean() }).strict(),
  /** Квартиры с этой геометрией кухни (RU и её английский двойник). */
  apartments: z.array(z.string().min(1)).min(1),
  fits: z.record(z.string(), kitchenFit),
}).strict();
export type KitchenFitFile = z.infer<typeof kitchenFitFile>;
