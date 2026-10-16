// Коллекция покупателя: снимок своей расстановки, который открывается ссылкой на любом устройстве
// (план b2b-05, ADR-0264). Без ПДн. Цены в снимке — на момент сохранения; при открытии сервер отдаёт
// ТЕКУЩИЕ цены из витрины, пропавший товар помечается, а не подменяется (ADR-0254 п.6).

import { z } from "zod";

const sku = z.object({
  sid: z.string().regex(/^\d+_[\w-]{1,64}$/),
  msid: z.string().max(80).optional(),
  name: z.string().max(200),
  url: z.string().url().max(600).optional(),
  shop: z.string().max(80).optional(),
  price: z.number().nonnegative().max(100_000_000).optional(),
  pack: z.number().int().positive().max(100).optional(),
});

const item = z.object({
  role: z.string().min(1).max(40),
  x: z.number().min(-100).max(5000),
  y: z.number().min(-100).max(5000),
  rot: z.number().min(-360).max(720),
  w: z.number().positive().max(2000),
  d: z.number().positive().max(2000),
  h: z.number().nonnegative().max(1000).optional(),
  elev: z.number().nonnegative().max(500).optional(),
  sku: sku.optional(),
});

// КАРТИНКА КОЛЛЕКЦИИ (план demo-03, карта сценариев 2.13): путь к НАШЕМУ кадру (папка кадров демо), без домена —
// чужую картинку (пиксель-трекер) на карточку не поставить. Ставится при сохранении или один раз после (`PATCH`).
export const SHOT_PATH_RE = /^\/test\/share\/frames\/[\w.-]{1,120}\.(?:jpg|jpeg|png|webp)$/;
/** Номер состояния расстановки (demo-02): считает страница демо, `tools/scout/flat215-demo/index.html` блок STATEID. */
// s1 — расстановка без опций застройщика; s2 — с выбранными опциями (пол, demo-06). Старые s1 читаются как прежде.
export const STATE_ID_RE = /^s[12]-[0-9a-f]{32}$/;
export const collectionShotIn = z.object({ shot: z.string().regex(SHOT_PATH_RE), stateId: z.string().regex(STATE_ID_RE).optional() });

const optId = z.string().regex(/^[a-z0-9-]{2,40}$/);

// v2 (demo-06): + `developerOptions` — выбор в группах опций застройщика (группа → вариант; пол). v1 читается как v2 без
// выбора: апгрейд — умолчание `{}`. Что группы и варианты существуют у квартиры, проверяет ручка сохранения.
export const collectionIn = z.object({
  schemaVersion: z.union([z.literal(1), z.literal(2)]).default(1),
  apartmentId: z.string().regex(/^[a-z0-9-]{2,40}$/),
  roomId: z.string().max(40).default("living"),
  baseVariant: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/),
  style: z.string().max(40).optional(),
  sendId: z.string().regex(/^[A-Za-z0-9_-]{22}$/).optional(),
  lang: z.enum(["ru", "en"]).default("ru"),
  items: z.array(item).min(1).max(60),
  decor: z.array(z.object({ role: z.string().max(40), sku })).max(30).default([]),
  cams: z.array(z.object({ x: z.number(), y: z.number(), rot: z.number(), fov: z.number().optional() })).max(4).default([]),
  shot: z.string().regex(SHOT_PATH_RE).optional(),
  stateId: z.string().regex(STATE_ID_RE).optional(),
  developerOptions: z.record(optId, optId).refine((o) => Object.keys(o).length <= 10, "слишком много опций").default({}),
});
export type CollectionIn = z.infer<typeof collectionIn>;

/** Текущая цена товара при открытии коллекции: из витрины; нет в витрине — `unavailable`. */
export type CurrentPrice = {
  price: number | null; priceAt: string | null; unavailable: boolean; temporarilyUnavailable?: boolean;
  name?: string; url?: string | null; shop?: string | null; img?: string | null;
};

export type CollectionOut = CollectionIn & {
  id: string;
  partnerId: string;
  createdAt: string;
  expiresAt: string;
  current: Record<string, CurrentPrice>; // sid → текущая цена
};
