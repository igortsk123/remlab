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
import { catalogue as catalogueSchema, type Catalogue } from "@/contracts/configurator";

type DemoItem = {
  role?: string;
  x?: number;
  y?: number;
  rot?: number;
  w?: number;
  d?: number;
  h?: number;
  elev?: number;
  sku?: { name?: string; price?: number; url?: string; shop?: string; msid?: string; sid?: string };
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
export function fromDemoVariant(data: DemoData, variantId: string): { apartment: Apartment; catalogue: Catalogue } | null {
  const room = data.room;
  const v = (data.variants ?? []).find((x) => x.id === variantId);
  if (!room?.w || !room?.d || !v) return null;

  const items = (v.items ?? []).filter((it) => it.w && it.d && it.h && it.sku?.msid);
  if (!items.length) return null;

  const title = v.style ? v.style.charAt(0).toUpperCase() + v.style.slice(1) : (v.title ?? "Вариант");
  const slots = items.map((it, i) => ({
    id: `demo-${i}`,
    roomId: "living",
    category: "furniture" as const,
    kind: "furniture" as const,
    titleRu: it.role ?? "Предмет",
    titleEn: it.role ?? "Item",
    photoRole: it.role,
    defaultOptionId: `demo-opt-${i}`,
    optionIds: [`demo-opt-${i}`],
    placement: {
      x: it.x ?? 0,
      y: it.y ?? 0,
      rot: it.rot ?? 0,
      wCm: it.w as number,
      dCm: it.d as number,
      hCm: it.h as number,
      elevCm: Math.max(0, it.elev ?? 0),
    },
  }));

  const apartment = apartmentSchema.parse({
    id: `demo-${variantId}`,
    titleRu: `${title} — ${room.title ?? "гостиная"}`,
    titleEn: `${title} — living room`,
    areaM2: Math.round(((room.w * room.d) / 10000) * 10) / 10,
    developerId: "demo",
    basePriceGbp: 0,
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
    developerId: "demo",
    titleRu: `Набор «${title}»`,
    titleEn: `${title} set`,
    currency: "GBP",
    materials: [],
    options: items.map((it, i) => ({
      id: `demo-opt-${i}`,
      category: "furniture" as const,
      titleRu: it.sku?.name ?? it.role ?? "Предмет",
      titleEn: it.sku?.name ?? it.role ?? "Item",
      descRu: `${Math.round(it.w as number)}×${Math.round(it.d as number)}×${Math.round(it.h as number)} см`,
      tier: "base" as const,
      priceGbp: 0,
      availability: "available" as const,
      roomKinds: ["living" as const],
      asset: {
        kind: "mesh" as const,
        // Ссылку не кладём: `meshUrl()` сам возьмёт лёгкую runtime-копию, а её нет — исходник
        // галереи по meshId. Своя ссылка отключила бы этот выбор.
        meshId: it.sku?.msid as string,
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
