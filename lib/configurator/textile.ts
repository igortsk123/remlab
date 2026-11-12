// УСЛОВНЫЕ ШТОРЫ И ПЛЕД (T-20261112-74, владелец TG 953): из фото магазина ткань чисто не вырезать (разбор T-73: годных вырезок
// у штор 1 из 8, у пледов 0 из 8), поэтому в 3D — простая форма ЦВЕТОМ ТОВАРА, с ценой и карточкой, как у прочего декора. Место и
// цвет даёт сборка витрины (`tools/scout/textile_abstract.py`: решатель паспорта `dependents.resolve`, цвет — по названию товара);
// здесь — только перевод строки декора в место, опцию и материал каталога. Без места или цвета — строка остаётся только в списке.

import type { Opening } from "@/contracts/apartment";

export const TEXTILE_STRATEGY = "textile_abstract";
/** Пометка в карточке: форма не по фото товара. */
export const TEXTILE_NOTE_RU = "вид условный";

export type TextileShape = "curtain" | "throw";
export type TextilePlace = {
  x?: number; y?: number; rot?: number; elev_cm?: number; slot_instance_id?: string; parent?: string | null;
  kind?: string; opening?: number | null; wall?: string | null; edge?: string | null; w?: number; d?: number; h?: number;
};
/** `of` — товар, для которого посчитан цвет (`lookKey`): замена на странице меняет `sku`, а цвет — нет. */
export type TextileLook = { hex?: string; from?: string; sheer?: boolean; of?: string };
export type TextileDecor = {
  role?: string; list_only?: boolean; strategy?: string; place?: TextilePlace; look?: TextileLook;
  sku?: { name?: string; name_en?: string; price?: number; url?: string; shop?: string; sid?: string; img?: string; w?: number; d?: number; h?: number };
};

const HEX = /^#[0-9a-fA-F]{6}$/;
const shapeOf = (p?: TextilePlace): TextileShape | null => (p?.kind === "curtain" || p?.kind === "throw" ? p.kind : null);

/** Ключ товара для `look.of`: артикул, иначе название (то же — `tools/scout/textile_abstract.py:look_key`). */
export const lookKey = (sku?: { sid?: string | null; name?: string }): string => String(sku?.sid || sku?.name || "");

/**
 * Строка декора — условная ткань с местом и цветом СВОЕГО товара (иначе — только список, как было): покупатель заменил штору —
 * цвета новой у сцены нет, она уходит из 3D; вернул (история) — штора снова там.
 */
export const isTextileDecor = (x: TextileDecor): boolean =>
  !x.list_only && x.strategy === TEXTILE_STRATEGY && !!x.sku?.name && !!shapeOf(x.place) && HEX.test(x.look?.hex ?? "")
  && x.look?.of === lookKey(x.sku)
  && Number.isFinite(x.place?.x) && Number.isFinite(x.place?.y) && Number.isFinite(x.place?.elev_cm)
  && (x.place?.kind !== "curtain" || Number.isInteger(x.place?.opening));

/** Толщина шторы и пледа в месте сцены — коробка выбора и рамка; форму строит сцена (`viewer.ts`). */
const CURTAIN_D_CM = 6;
const THROW_DEF = { w: 36, d: 55, h: 5 };

/**
 * Номер проёма шторы в проёмах комнаты моста (`fromDemo.ts:openings` выбрасывает проёмы без ширины): решатель считает по сырому
 * списку геометрии — ищем тот же проём по стене и отступу.
 */
export function openingIndex(raw: { wall?: string; offset_cm?: number; width_cm?: number }[] | undefined, ops: Opening[], i: number): number {
  const o = raw?.[i];
  if (!o) return -1;
  return ops.findIndex((p) => p.offsetCm === Math.max(0, o.offset_cm ?? 0) && p.widthCm === o.width_cm
    && (p.kind === "window" || p.kind === "balcony"));
}

export interface TextilePart {
  material: Record<string, unknown> & { id: string };
  option: Record<string, unknown> & { id: string };
  slot: Record<string, unknown> & { id: string };
}

/**
 * Место, опция и материал условной ткани комнаты. `id` — места моста (`textile:<роль>#k`), `ox/oy` — угол комнаты в квартире.
 * Штора — место у окна (центр проёма на стене, `rot` — нормаль внутрь), высота — до штанги; плед — брусок на подлокотнике.
 */
export function textilePart(x: TextileDecor, id: string, k: number, at: { id: string; prefix: string; ox: number; oy: number },
  ops: Opening[], rawOpenings: { wall?: string; offset_cm?: number; width_cm?: number }[] | undefined,
  opt: { kinds: string[]; price: number; titleEn: string; previewUrl?: string; shop: object }): TextilePart | null {
  const p = x.place!, sk = x.sku!, shape = shapeOf(p)!;
  const opening = shape === "curtain" ? openingIndex(rawOpenings, ops, p.opening!) : undefined;
  if (opening !== undefined && opening < 0) return null;
  const o = opening !== undefined ? ops[opening]! : undefined;
  const size = shape === "curtain"
    ? { w: o!.widthCm + 2 * 55, d: CURTAIN_D_CM, h: Math.max(1, p.elev_cm!), elev: 0 }
    : { w: p.w ?? THROW_DEF.w, d: p.d ?? THROW_DEF.d, h: p.h ?? THROW_DEF.h, elev: Math.max(0, p.elev_cm!) };
  const mat = `textile:${at.prefix}${k}:${sk.sid ?? sk.name}`;
  const sheer = !!x.look?.sheer;
  const dims = shape === "curtain" && sk.w && sk.h ? `${Math.round(sk.w)}×${Math.round(sk.h)} см · ` : "";
  return {
    material: { id: mat, titleRu: shape === "curtain" ? "Штора" : "Плед", titleEn: shape === "curtain" ? "Curtain" : "Throw",
      colorHex: x.look!.hex!.toLowerCase(), roughness: 0.95, tileCm: [100, 100] },
    option: { id: `opt:${id}`, category: "furniture", titleRu: sk.name, titleEn: opt.titleEn, descRu: `${dims}${TEXTILE_NOTE_RU}`,
      tier: "standard", price: opt.price, availability: "available", roomKinds: opt.kinds,
      asset: { kind: "kit", kit: "textile", materials: { body: mat }, features: [shape, ...(sheer ? ["sheer"] : [])] },
      ...(opt.previewUrl ? { previewUrl: opt.previewUrl } : {}), ...opt.shop },
    slot: { id, roomId: at.id, category: "furniture" as const, kind: "furniture" as const, titleRu: x.role ?? "шторы",
      titleEn: shape === "curtain" ? "curtains" : "throw", photoRole: x.role, defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`],
      textile: { shape, ...(opening !== undefined ? { opening } : {}) },
      placement: { x: at.ox + p.x!, y: at.oy + p.y!, rot: p.rot ?? 0, wCm: size.w, dCm: size.d, hCm: size.h, elevCm: size.elev } },
  };
}
