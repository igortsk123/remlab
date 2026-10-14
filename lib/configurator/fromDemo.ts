// Мост «витрина → конфигуратор»: вариант со страницы /demo открывается в 3D той же мебелью.
//
// ЗАЧЕМ (владелец 13.10: «3D должен открываться по кнопке конкретного варианта»). До этого
// кнопка вела на абстрактную демо-квартиру: человек смотрел джапанди, нажимал «в 3D» и попадал
// в другую комнату с другой мебелью. Теперь берём РОВНО тот набор, который он видит на карточке.
//
// ИСТОЧНИК — ЖИВОЙ `demo-data.json` ВИТРИНЫ, а не копия. Ночная пересборка меняет наборы, и
// любая копия на нашей стороне назавтра показывала бы не то, что на странице. Берём текущий файл
// и собираем квартиру из него: расхождение между фото и 3D становится невозможным по построению.
//
// КООРДИНАТЫ СОВПАДАЮТ. Витрина отдаёт `x`/`y` как ЦЕНТР footprint в сантиметрах от юго-западного
// угла комнаты — та же конвенция, что у конфигуратора (`contracts/apartment.ts`). Проверено на
// данных: диван 162 см шириной стоит в x=166 при комнате 439 см, то есть 85…247 — у стены.
// Поворот витрины — градусы по часовой, 0 — «лицом на +y», тоже как у нас.

import { apartment as apartmentSchema, type Apartment, type Opening } from "@/contracts/apartment";
import { catalogue as catalogueSchema, type Catalogue, type Configuration } from "@/contracts/configurator";

/** Чья квартира и в какой валюте: из реестра застройщиков (b2b-06), не из файла витрины. */
export type DemoContext = { apartmentId: string; partnerId: string; currency: "RUB" | "GBP"; basePrice: number };

/**
 * Имя места — роль + номер внутри роли («диван#0», «стул#2»), а не порядковый номер в файле.
 * Ночная пересборка меняет состав набора; при сквозной нумерации сохранённый выбор «места 3»
 * переехал бы на другой предмет (рецензия 13.10, P0).
 */
export function stableSlotIds(items: DemoItem[]): string[] {
  const seen = new Map<string, number>();
  return items.map((it) => {
    const role = (it.role ?? "предмет").trim().toLowerCase();
    const k = seen.get(role) ?? 0;
    seen.set(role, k + 1);
    return `${role}#${k}`;
  });
}

/** Снимок «место → модель» исходного набора: пишется в сохранение, сверяется при открытии. */
export function baseSnapshotOf(a: Apartment, c: Catalogue): Record<string, string> {
  const out: Record<string, string> = {};
  for (const s of a.slots) {
    const o = c.options.find((x) => x.id === s.defaultOptionId);
    if (o?.asset.kind === "mesh") out[s.id] = o.asset.meshId;
  }
  return out;
}

/** Какие места сохранённого подбора больше не совпадают с набором витрины (товар сменился/пропал). */
export function staleSlots(saved: Configuration, current: Record<string, string>): string[] {
  if (!saved.baseSnapshot) return [];
  return Object.entries(saved.baseSnapshot).filter(([slot, mesh]) => current[slot] !== mesh).map(([slot]) => slot);
}

type DemoItem = {
  role?: string;
  x?: number;
  y?: number;
  rot?: number;
  w?: number;
  d?: number;
  h?: number;
  elev?: number;
  corner?: boolean;
  corner_left?: boolean;
  sku?: { name?: string; price?: number; url?: string; shop?: string; msid?: string; sid?: string; pack?: number; yaw?: number };
};
type DemoVariant = { id?: string; title?: string; style?: string; items?: DemoItem[] };
type DemoRoom = {
  w?: number;
  d?: number;
  title?: string;
  height_cm?: number;
  openings?: { kind?: string; wall?: string; offset_cm?: number; width_cm?: number; sill_cm?: number; height_cm?: number }[];
};
export type DemoData = { room?: DemoRoom; variants?: DemoVariant[] };

const WALLS = ["north", "south", "east", "west"] as const;
type Wall = (typeof WALLS)[number];
const wallOf = (s?: string): Wall => (WALLS as readonly string[]).includes(s ?? "") ? (s as Wall) : "north";

/** Проёмы витрины → проёмы конфигуратора: другие имена полей, та же геометрия. */
function openings(room: DemoRoom): Opening[] {
  return (room.openings ?? [])
    .filter((o) => o.width_cm && o.width_cm > 0)
    .map((o) => ({
      kind: o.kind === "window" ? ("window" as const) : ("door" as const),
      wall: wallOf(o.wall),
      offsetCm: Math.max(0, o.offset_cm ?? 0),
      widthCm: o.width_cm as number,
      ...(o.sill_cm !== undefined ? { sillCm: o.sill_cm } : {}),
      ...(o.height_cm !== undefined ? { heightCm: o.height_cm } : {}),
    }));
}

/**
 * Квартира и каталог из одного варианта витрины.
 *
 * Квартира — ОДНОКОМНАТНАЯ: у витрины детально описана только гостиная (439×325), остальные
 * помещения на её чертеже — заглушки с другого плана. Обещать «та же квартира» было бы неправдой,
 * поэтому обещаем «та же комната и та же расстановка» и других дверей не открываем.
 */
export function fromDemoVariant(data: DemoData, variantId: string, ctx: DemoContext): { apartment: Apartment; catalogue: Catalogue } | null {
  const room = data.room;
  const v = (data.variants ?? []).find((x) => x.id === variantId);
  if (!room?.w || !room?.d || !v) return null;

  const items = (v.items ?? []).filter((it) => it.w && it.d && it.h && it.sku?.msid);
  // УПАКОВКА: «Стул АСТИ 2 шт.» на двух местах — ОДНА покупка (как в списке витрины, `index.html`
  // `buys = ceil(мест/упаковку)`). Цену несут первые `buys` мест товара, остальные — 0; иначе «выбрано на»
  // в 3D было бы больше суммы того же набора на витрине (verify 13.10).
  const paidSlots = new Set<number>();
  const byProduct = new Map<string, number[]>();
  items.forEach((it, i) => {
    const k = `${it.sku?.url ?? ""}|${it.sku?.name ?? ""}`;
    byProduct.set(k, [...(byProduct.get(k) ?? []), i]);
  });
  for (const [, idx] of byProduct) {
    const pack = Math.max(1, Math.round(Number(items[idx[0]!]!.sku?.pack ?? 1)) || 1);
    idx.slice(0, Math.ceil(idx.length / pack)).forEach((i) => paidSlots.add(i));
  }
  if (!items.length) return null;

  const title = v.style ? v.style.charAt(0).toUpperCase() + v.style.slice(1) : (v.title ?? "Вариант");
  const ids = stableSlotIds(items);
  const slots = items.map((it, i) => ({
    id: ids[i]!,
    roomId: "living",
    category: "furniture" as const,
    kind: "furniture" as const,
    titleRu: it.role ?? "Предмет",
    titleEn: it.role ?? "Item",
    photoRole: it.role,
    defaultOptionId: `opt:${ids[i]}`,
    optionIds: [`opt:${ids[i]}`],
    placement: {
      x: it.x ?? 0,
      y: it.y ?? 0,
      rot: it.rot ?? 0,
      wCm: it.w as number,
      dCm: it.d as number,
      hCm: it.h as number,
      elevCm: Math.max(0, it.elev ?? 0),
      // сторона оттоманки Г-дивана — как у расстановщика: движок зеркалит модель, нарисованную с другой стороны
      ...(it.corner ? { cornerLeft: !!it.corner_left } : {}),
    },
  }));

  const apartment = apartmentSchema.parse({
    id: ctx.apartmentId,
    baseVariant: variantId,
    ...(v.style ? { style: v.style } : {}),
    titleRu: `${title} — ${room.title ?? "гостиная"}`,
    titleEn: `${title} — living room`,
    areaM2: Math.round(((room.w * room.d) / 10000) * 10) / 10,
    developerId: ctx.partnerId,
    basePrice: ctx.basePrice,
    rooms: [
      {
        id: "living",
        kind: "living",
        titleRu: room.title ?? "Гостиная",
        titleEn: "Living room",
        x: 0,
        y: 0,
        w: room.w,
        d: room.d,
        heightCm: room.height_cm ?? 270,
        openings: openings(room),
      },
    ],
    slots,
    cameras: [],
    // Старт прогулки — у середины комнаты, лицом вглубь: так человек сразу видит расстановку.
    spawn: { x: room.w / 2, y: Math.min(120, room.d / 3), rot: 0 },
  });

  const catalogue = catalogueSchema.parse({
    developerId: ctx.partnerId,
    titleRu: `Набор «${title}»`,
    titleEn: `${title} set`,
    currency: ctx.currency,
    materials: [],
    options: items.map((it, i) => ({
      id: `opt:${ids[i]}`,
      category: "furniture" as const,
      titleRu: it.sku?.name ?? it.role ?? "Предмет",
      titleEn: it.sku?.name ?? it.role ?? "Item",
      descRu: `${Math.round(it.w as number)}×${Math.round(it.d as number)}×${Math.round(it.h as number)} см`,
      // Мебель витрины в цену квартиры не входит: это покупка за счёт сертификата/доплаты, поэтому
      // ступень «стандарт» и настоящая цена товара — иначе «выбрано на» в 3D было бы всегда 0.
      tier: "standard" as const,
      price: paidSlots.has(i) ? Math.max(0, Math.round(it.sku?.price ?? 0)) : 0,
      availability: "available" as const,
      roomKinds: ["living" as const],
      asset: {
        kind: "mesh" as const,
        // Ссылку не кладём: `meshUrl()` сам возьмёт лёгкую runtime-копию, а её нет — исходник
        // галереи по meshId. Своя ссылка отключила бы этот выбор.
        meshId: it.sku?.msid as string,
        // разворот фронта модели — тот же, что у 3D-сцены демо (`orient.json` + ручные поправки, `flat215_demo.annotate_yaw`)
        yawDeg: it.sku?.yaw ?? 0,
        wCm: it.w as number,
        dCm: it.d as number,
        hCm: it.h as number,
      },
      // Ссылка в магазин — ПАРТНЁРСКАЯ, прямо как на витрине: иначе теряется комиссия (ADR-0016).
      ...(it.sku?.url ? { shopUrl: it.sku.url } : {}),
      ...(it.sku?.shop ? { shopName: it.sku.shop } : {}),
    })),
  });

  return { apartment, catalogue };
}

/**
 * Коллекция покупателя (план b2b-05) → вариант витрины для того же моста в 3D. Предметы коллекции — в той же форме,
 * что предметы варианта; цены — ТЕКУЩИЕ (`lib/collections/prices.ts`), пропавший с витрины товар остаётся на месте, но
 * в сумму не входит; разворот модели — из вариантов витрины по msid (как у `flat215_demo.annotate_yaw`).
 */
export function collectionAsVariant(
  data: DemoData,
  coll: { baseVariant: string; style?: string; items: DemoItem[] },
  prices: Record<string, { price: number | null; unavailable: boolean }>,
): DemoData {
  const yaw = new Map<string, number>();
  for (const v of data.variants ?? []) for (const it of v.items ?? []) if (it.sku?.msid && it.sku.yaw !== undefined) yaw.set(it.sku.msid, it.sku.yaw);
  const items = coll.items.map((it) => {
    if (!it.sku) return it;
    const cur = it.sku.sid ? prices[it.sku.sid] : undefined;
    const price = cur && !cur.unavailable && cur.price !== null ? cur.price : cur?.unavailable ? 0 : it.sku.price;
    const y = it.sku.msid ? yaw.get(it.sku.msid) : undefined;
    return { ...it, sku: { ...it.sku, price, ...(y !== undefined ? { yaw: y } : {}) } };
  });
  return { ...data, variants: [{ id: coll.baseVariant, title: coll.style, style: coll.style, items }] };
}
