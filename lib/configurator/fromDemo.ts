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

import { alternatives, feedForStyle, placeOf, type FeedItem } from "@/lib/configurator/demo-feeds";
import { finishPassport } from "@/lib/viewer3d/finish-passport";
import { apartment as apartmentSchema, type Apartment, type CropWindow, type Opening } from "@/contracts/apartment";
import { catalogue as catalogueSchema, type Catalogue, type Configuration } from "@/contracts/configurator";

/** Чья квартира и в какой валюте: из реестра застройщиков (b2b-06), не из файла витрины. */
export type DemoContext = {
  apartmentId: string;
  partnerId: string;
  currency: "RUB" | "GBP";
  basePrice: number;
  /** Адрес витрины (страница или её demo-data.json): от него считаются относительные картинки товаров (`img/…`). */
  assetBase?: string;
  /** Пол застройщика (demo-06): материал вместо ровного цвета паспорта отделки — фактура ламината/паркета. */
  floorMaterial?: Record<string, unknown> & { id: string };
  /** Пол на выбор (demo-06, группа «пол» карточки квартиры): варианты — опциями поверхности пола `opt:floor:<вариант>`. */
  floorChoice?: DemoFloorChoice;
  /**
   * Курс рубль → валюта застройщика (ADR-0298): цены витрины — рубли фидов; у британского двойника каталог в £ — пересчёт здесь,
   * ОДИН раз на цену, с округлением до целого. Нет — цены как есть. Пол из карточки (`floorChoice`) уже в валюте застройщика.
   */
  fxRate?: number;
  /** Стены на выбор (demo-07) — тем же видом, что пол. */
  wallChoice?: DemoFloorChoice;
  /** Стены живой сцены окна (выбранный вариант): материал и акцент. */
  wallMaterial?: { material: Record<string, unknown> & { id: string }; accent?: { material: Record<string, unknown> & { id: string }; anchor: "behind-sofa" } };
};

/** Варианты пола застройщика для `/flat`: цена — доплата, куда идёт — `settlement` группы (RF — застройщику). */
export type DemoFloorChoice = {
  groupId: string;
  defaultVariantId: string;
  settlement: "allowance" | "developer_surcharge" | "property_price";
  variants: { id: string; titleRu: string; titleEn: string; price: number; material: Record<string, unknown> & { id: string };
    /** Акцентная стена варианта стен (demo-07). */
    accent?: { material: Record<string, unknown> & { id: string }; anchor: "behind-sofa" } }[];
};

/** Подкраска из данных витрины — только три разумных множителя (чужим данным не доверяем). */
export function tintOf(t: unknown): { tintRgb: [number, number, number] } | Record<string, never> {
  if (!Array.isArray(t) || t.length !== 3 || !t.every((x) => typeof x === "number" && x >= 0.2 && x <= 3)) return {};
  return { tintRgb: [t[0], t[1], t[2]] as [number, number, number] };
}

/** Опция отделки варианта группы — одно имя у моста, страницы и ссылки `?opt=` (`opt:floor:<в>`, `opt:wall:<в>`). */
export const finishOptionId = (surface: "floor" | "wall", variantId: string): string => `opt:${surface}:${variantId}`;
export const floorOptionId = (variantId: string): string => finishOptionId("floor", variantId);

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
    // ковёр — фото товара в материале: смена ковра тоже «набор обновился» (Codex 15.10)
    else if (o?.asset.kind === "kit" && o.asset.kit === "rug") out[s.id] = `rug:${o.asset.materials.body ?? ""}`;
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
  sku?: { name?: string; price?: number; url?: string; shop?: string; msid?: string; sid?: string; pack?: number; yaw?: number; img?: string;
    /** Подкраска цветового варианта на модели семейства (`flat215_demo.annotate_tint`): множитель цвета по каналу. */
    tint?: number[] };
};
/** Настольный декор варианта (`flat215_demo`: ваза) — габариты в карточке товара, места нет: его даёт опора. */
type DemoDecor = { role?: string; sku?: DemoItem["sku"] & { w?: number; d?: number; h?: number } };
type DemoVariant = { id?: string; title?: string; style?: string; items?: DemoItem[]; decor?: DemoDecor[];
  /** Ракурсы окна (`tools/flat3d/demo-cams.mjs`) — режим «Фото» в /flat снимает ими (demo-05 п.8). */
  cams?: { name?: string; x?: number; y?: number; rot?: number; fov?: number; pose?: number; pshift?: number; crop?: Record<string, CropWindow> }[] };

const isRugRole = (role?: string): boolean => String(role ?? "").startsWith("ковёр");
/** Картинка товара витрины: абсолютная — как есть, относительная (`img/…`) — от адреса витрины. */
function assetUrl(img: string | undefined, base: string | undefined): string | undefined {
  if (!img || /^https?:|^\//.test(img) || !base) return img;
  // адрес страницы (с `?…#…`) — по правилам URL; путь сайта (`/demo/demo-data.json` у /flat) — до последнего «/»
  if (/^https?:/.test(base)) return new URL(img, base).toString();
  return base.replace(/[?#].*$/, "").replace(/[^/]*$/, "") + img;
}
type DemoRoom = {
  w?: number;
  d?: number;
  title?: string;
  height_cm?: number;
  /** Вид из окна по карточке квартиры (`flat215_demo.py`: `windowView` застройщика). */
  window_view?: string;
  /** Паспорт отделки — готовый, из ночной сборки (`finish-passport.ts`). */
  finish?: Record<string, { id?: string; colorHex?: string }>;
  openings?: {
    kind?: string; wall?: string; offset_cm?: number; width_cm?: number; sill_cm?: number; height_cm?: number;
    swing_cm?: number; hinge?: string; into?: boolean;
  }[];
};
/** `variant_aliases` — история номеров вариантов → стиль (`flat215_demo.merge_aliases`, demo-05 п.10). */
export type DemoData = { room?: DemoRoom; variants?: DemoVariant[]; variant_aliases?: Record<string, string>; feeds?: Record<string, FeedItem[]> };

/**
 * Какой вариант открыть по ссылке (demo-05 п.10): номер варианта меняется при пересборке витрины, а ссылки менеджеров
 * живут дольше (14.10 `?demo=set2` дал 404). Есть такой — он; нет — текущий вариант ТОГО ЖЕ СТИЛЯ по истории номеров;
 * стиля нет — первый вариант. Замена возвращается явно (`from`), страница говорит о ней покупателю.
 */
export function resolveVariantId(data: DemoData, wanted: string): { id: string; from?: string; style?: string } | null {
  const vs = data.variants ?? [];
  if (vs.some((v) => v.id === wanted)) return { id: wanted };
  const style = data.variant_aliases?.[wanted];
  const same = style ? vs.find((v) => v.style === style && v.id) : undefined;
  if (same?.id) return { id: same.id, from: wanted, style };
  const first = vs.find((v) => v.id)?.id;
  return first ? { id: first, from: wanted } : null;
}

const WALLS = ["north", "south", "east", "west"] as const;
type Wall = (typeof WALLS)[number];
const wallOf = (s?: string): Wall => (WALLS as readonly string[]).includes(s ?? "") ? (s as Wall) : "north";

/** Проёмы витрины → проёмы конфигуратора: другие имена полей, та же геометрия. */
export function openings(room: DemoRoom): Opening[] {
  return (room.openings ?? [])
    .filter((o) => o.width_cm && o.width_cm > 0)
    .map((o) => ({
      kind: o.kind === "window" || o.kind === "balcony" || o.kind === "opening" ? o.kind : ("door" as const),
      wall: wallOf(o.wall),
      offsetCm: Math.max(0, o.offset_cm ?? 0),
      widthCm: o.width_cm as number,
      ...(o.sill_cm !== undefined ? { sillCm: o.sill_cm } : {}),
      ...(o.height_cm !== undefined ? { heightCm: o.height_cm } : {}),
      // петли и створка с плана витрины (`index.html:doorGeom`: hinge start|end, into) — та же дверь в 3D и на кадре
      ...(o.hinge === "end" || o.hinge === "right" ? { hinge: "right" as const } : {}),
      ...(o.into === false || o.swing_cm === 0 ? { swingCm: 0 } : o.swing_cm !== undefined ? { swingCm: o.swing_cm } : {}),
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
  // УПАКОВКА: «Стул АСТИ 2 шт.» на двух местах — ОДНА покупка (как в списке витрины, `index.html` `buys = ceil(мест/упаковку)`).
  // Считает её расчёт сцены по фактически выбранным местам (`resolve.packPrices`: опции с одним `packKey`), а не статическая
  // раскладка цены здесь — иначе замена, убранный стул или смешанный подбор давали бы неверную сумму (разбор Codex 15.10)
  // цена витрины (рубли) → валюта каталога: одно место для товаров, лент, ковров и декора (коллекции идут сюда же)
  const rub = (v?: number): number => Math.max(0, Math.round((v ?? 0) * (ctx.fxRate ?? 1)));
  const packOf = (pack?: number): object => (Math.round(pack ?? 1) > 1 ? { pack: Math.round(pack!) } : {});
  if (!items.length) return null;

  const title = v.style ? v.style.charAt(0).toUpperCase() + v.style.slice(1) : (v.title ?? "Вариант");
  const ids = stableSlotIds(items);
  const baseOf = (role?: string): string => String(role ?? "").replace(/\s+\d+$/, "").trim();
  const keyOf = (it: DemoItem): string => `${it.sku?.url ?? ""}|${it.sku?.name ?? ""}`;
  // СТУЛЬЯ ЗА ОДНИМ СТОЛОМ МЕНЯЮТСЯ ВСЕ РАЗОМ (владелец 30.09; клиент — `useFlatConfig.choose`, сервер — `resolve.sameInGroups`):
  // у группы одна общая опция; упаковки считает `resolve.packPrices`
  const chairIdx = items.map((it, i) => ({ it, i })).filter(({ it }) => baseOf(it.role) === "стул").map(({ i }) => i);
  const chairGroup = chairIdx.length >= 2 && chairIdx.every((i) => keyOf(items[i]!) === keyOf(items[chairIdx[0]!]!)) ? chairIdx : [];
  const inGroup = new Set(chairGroup);
  const defaultOf = (i: number): string => (inGroup.has(i) ? "opt:стул" : `opt:${ids[i]}`);
  // ЛЕНТЫ ЗАМЕН (demo-05 п.9): варианты места из ленты витрины своей роли и стиля, ближайшие по размеру, разные модели раньше
  // цветов, диван — той же формы, что место (demo-18 п.1, `demo-feeds.ts`)
  const feedOptions = new Map<string, unknown>();
  const feedIdsOf = (i: number): string[] => {
    const it = items[i]!;
    const base = baseOf(it.role);
    const feed = feedForStyle(data.feeds?.[base] ?? [], v.style);
    return alternatives(feed, placeOf(it, items), new Set([it.sku?.sid ?? "", it.sku?.name ?? ""])).map((p) => {
      const id = `feed:${base}:${p.sid ?? p.name}`;
      if (!feedOptions.has(id)) {
        feedOptions.set(id, { id, category: "furniture", titleRu: p.name ?? base, titleEn: p.name ?? base,
          descRu: `${Math.round(p.w!)}×${Math.round(p.d!)}×${Math.round(p.h!)} см${(p.pack ?? 1) > 1 ? ` · ${p.pack} шт. в упаковке` : ""}`,
          tier: "standard", price: rub(p.price), ...packOf(p.pack), packKey: id,
          listPrice: rub(p.price), availability: "available", roomKinds: ["living"],
          asset: { kind: "mesh", meshId: p.msid, yawDeg: p.yaw ?? 0, wCm: p.w, dCm: p.d, hCm: p.h, ...tintOf(p.tint) },
          ...(assetUrl(p.img, ctx.assetBase) ? { previewUrl: assetUrl(p.img, ctx.assetBase) } : {}),
          ...(p.url ? { shopUrl: p.url } : {}), ...(p.shop ? { shopName: p.shop } : {}) });
      }
      return id;
    });
  };
  const slots: object[] = items.map((it, i) => ({
    id: ids[i]!,
    roomId: "living",
    category: "furniture" as const,
    kind: "furniture" as const,
    titleRu: it.role ?? "Предмет",
    titleEn: it.role ?? "Item",
    photoRole: it.role,
    defaultOptionId: defaultOf(i),
    optionIds: [defaultOf(i), ...feedIdsOf(inGroup.has(i) ? chairGroup[0]! : i)],
    ...(inGroup.has(i) ? { selectionGroup: "стул" } : {}),
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

  // КОВЁР И НАСТОЛЬНЫЙ ДЕКОР — ТОВАРЫ ВАРИАНТА (demo-05 п.9, разбор Codex): раньше мост брал только предметы с моделью и
  // высотой, и в /flat не было ни ковра, ни вазы, хотя в окне и в цене они были. Ковёр — плита с фото товара (как серверный
  // «фото-ковёр»), ваза — модель на опоре (место пересчитывает `resolve.placeTabletop`)
  const rugs = (v.items ?? []).filter((it) => isRugRole(it.role) && it.w && it.d);
  const decor = (v.decor ?? []).filter((x) => x.sku?.msid && x.sku.w && x.sku.d && x.sku.h);
  const extraOptions: unknown[] = [];
  const extraMaterials: unknown[] = [];
  // плита ковра: материал с фото товара (повтор — один на ковёр) и опция-кит с размером товара вдоль длинной стороны места
  const rugOption = (id: string, mat: string, sku: { name?: string; price?: number; url?: string; shop?: string; img?: string },
    w: number, d: number): void => {
    const img = assetUrl(sku.img, ctx.assetBase);
    extraMaterials.push({ id: mat, titleRu: "Ковёр", titleEn: "Rug", colorHex: "#b8b0a4", roughness: 0.95, tileCm: [w, d],
      surfaces: ["rug"], ...(img ? { baseColorUrl: img } : {}) });
    extraOptions.push({ id, category: "furniture", titleRu: sku.name ?? "Ковёр", titleEn: sku.name ?? "Rug",
      descRu: `${Math.round(Math.max(w, d))}×${Math.round(Math.min(w, d))} см`,
      tier: "standard", price: rub(sku.price), availability: "available", roomKinds: ["living"],
      asset: { kind: "kit", kit: "rug", materials: { body: mat }, wCm: w, dCm: d },
      ...(img ? { previewUrl: img } : {}), ...(sku.url ? { shopUrl: sku.url } : {}), ...(sku.shop ? { shopName: sku.shop } : {}) });
  };
  const rugFeed = new Set<string>();
  rugs.forEach((it, k) => {
    const id = `ковёр#${k}`;
    // материал назван по ТОВАРУ: подпись ковра в движке — по материалу, и замена ковра того же размера иначе оставила бы
    // старое фото (verify 14.10)
    rugOption(`opt:${id}`, `rug:${k}:${it.sku?.sid ?? it.sku?.img ?? ""}`, it.sku ?? {}, it.w as number, it.d as number);
    // ЗАМЕНЫ КОВРА (demo-18 п.2): лента ковров стиля, ближайшие по размеру, длинная сторона не короче дивана (`placeOf`);
    // размер плиты — товара, вдоль длинной стороны места (`resolve.fitPlacement`)
    const alts = alternatives(feedForStyle(data.feeds?.["ковёр"] ?? [], v.style), placeOf(it, v.items ?? []),
      new Set([it.sku?.sid ?? "", it.sku?.name ?? ""]));
    const along = (p: FeedItem): [number, number] => {
      const [a, b] = [Math.max(p.w!, p.d!), Math.min(p.w!, p.d!)];
      return (it.w as number) >= (it.d as number) ? [a, b] : [b, a];
    };
    const feedIds = alts.map((p) => {
      const fid = `feed:ковёр:${p.sid ?? p.name}`;
      if (!rugFeed.has(fid)) {
        rugFeed.add(fid);
        rugOption(fid, `rug:feed:${p.sid ?? p.name}`, p, ...along(p));
      }
      return fid;
    });
    slots.push({ id, roomId: "living", category: "furniture" as const, kind: "furniture" as const, titleRu: it.role ?? "ковёр",
      titleEn: "rug", photoRole: it.role, defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`, ...feedIds],
      placement: { x: it.x ?? 0, y: it.y ?? 0, rot: it.rot ?? 0, wCm: it.w as number, dCm: it.d as number, hCm: 1, elevCm: 0 } });
  });
  const decorIds = stableSlotIds(decor.map((x) => ({ role: x.role ?? "декор" })));
  decor.forEach((x, k) => {
    const id = `decor:${decorIds[k]}`;
    const sk = x.sku!;
    extraOptions.push({ id: `opt:${id}`, category: "furniture", titleRu: sk.name ?? x.role ?? "Декор", titleEn: sk.name ?? "Decor",
      descRu: `${Math.round(sk.w!)}×${Math.round(sk.d!)}×${Math.round(sk.h!)} см`, tier: "standard",
      price: rub(sk.price), availability: "available", roomKinds: ["living"],
      asset: { kind: "mesh", meshId: sk.msid, yawDeg: sk.yaw ?? 0, wCm: sk.w, dCm: sk.d, hCm: sk.h, ...tintOf((sk as { tint?: unknown }).tint) },
      ...(sk.url ? { shopUrl: sk.url } : {}), ...(sk.shop ? { shopName: sk.shop } : {}) });
    // место — заглушка: настоящее считает `resolve.placeTabletop` от текущей опоры при каждом расчёте сцены
    slots.push({ id, roomId: "living", category: "furniture" as const, kind: "furniture" as const, titleRu: x.role ?? "декор",
      titleEn: "decor", photoRole: x.role, tabletop: true, defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`],
      placement: { x: 0, y: 0, rot: 0, wCm: sk.w!, dCm: sk.d!, hCm: sk.h!, elevCm: 0 } });
  });

  // СТЕНЫ И ПОЛ — СВОИ МАТЕРИАЛЫ (живая проверка 14.10, /flat 15.10): у набора витрины своей отделки нет, и движок брал на
  // оболочку первый материал каталога — фото ковра легло на стены, пол и потолок. Цвета — из паспорта отделки
  // (`finish-passport.ts`), тем же красится серверный кадр; материалы стен и пола — ПЕРВЫМИ в каталоге
  const fp = finishPassport(room.finish);
  // ПОЛ И СТЕНЫ НА ВЫБОР (demo-06/07): варианты группы застройщика — опциями своего места (`opt:floor:<в>`, `opt:wall:<в>`),
  // доплата — по `settlement` группы; акцентная стена — составной частью опции стен (сторону считает `resolveScene`)
  type Mat = Record<string, unknown> & { id: string };
  const choiceOf = (c?: DemoFloorChoice) => (c?.variants.length ? c : undefined);
  const defOf = (c?: DemoFloorChoice) => c?.variants.find((x) => x.id === c.defaultVariantId) ?? c?.variants[0];
  const fc = choiceOf(ctx.floorChoice), wc = choiceOf(ctx.wallChoice);
  const floorMat: Mat = defOf(fc)?.material ?? ctx.floorMaterial
    ?? { id: fp.floor.id, titleRu: "Пол", titleEn: "Floor", colorHex: fp.floor.colorHex, roughness: 0.7 };
  const wallMat: Mat = defOf(wc)?.material ?? ctx.wallMaterial?.material
    ?? { id: fp.wall.id, titleRu: "Стены", titleEn: "Walls", colorHex: fp.wall.colorHex, roughness: 0.95 };
  extraMaterials.unshift(wallMat, floorMat);
  const seen = new Set([wallMat.id, floorMat.id]);
  const addMat = (m?: Mat) => { if (m && !seen.has(m.id)) { seen.add(m.id); extraMaterials.push(m); } };
  const accentOf = (a?: { material: Mat; anchor: "behind-sofa" }) => (a ? (addMat(a.material), { accent: { materialId: a.material.id, anchor: a.anchor } }) : {});
  for (const [surface, category, base, choice] of [["floor", "flooring", floorMat, fc], ["wall", "walls", wallMat, wc]] as const) {
    if (choice) {
      for (const v of choice.variants) {
        addMat(v.material);
        extraOptions.push({ id: finishOptionId(surface, v.id), category, titleRu: v.titleRu, titleEn: v.titleEn, tier: v.price > 0 ? "standard" : "base",
          price: v.price, settlement: choice.settlement, availability: "available", roomKinds: ["living"],
          asset: { kind: "material", materialId: v.material.id, ...accentOf(v.accent) },
          ...(v.material.previewUrl ? { previewUrl: String(v.material.previewUrl) } : {}) });
      }
    } else {
      const live = surface === "wall" ? accentOf(ctx.wallMaterial?.accent) : {};
      extraOptions.push({ id: `opt:${surface}`, category, titleRu: surface, titleEn: surface, tier: "standard", price: 0,
        availability: "available", roomKinds: ["living"], asset: { kind: "material", materialId: base.id, ...live } });
    }
    slots.push({ id: surface, roomId: "living", category, kind: "surface", surface, titleRu: surface === "wall" ? "Стены" : "Пол",
      titleEn: surface === "wall" ? "Walls" : "Floor",
      defaultOptionId: choice ? finishOptionId(surface, defOf(choice)!.id) : `opt:${surface}`,
      optionIds: choice ? choice.variants.map((v) => finishOptionId(surface, v.id)) : [`opt:${surface}`] });
  }

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
        ...(room.window_view && /^[a-z0-9-]{1,32}$/.test(room.window_view) ? { windowView: room.window_view } : {}),
        ...(room.finish ? { finish: finishPassport(room.finish) } : {}),
        openings: openings(room),
      },
    ],
    slots,
    cameras: (v.cams ?? []).filter((c) => c.x !== undefined && c.y !== undefined).map((c, k) => ({ id: `cam${k + 1}`, roomId: "living",
      titleRu: `Ракурс ${k + 1}`, x: c.x as number, y: c.y as number, rot: c.rot ?? 0, fov: c.fov ?? 72, ...(c.pose ? { pose: c.pose } : {}),
      ...(typeof c.pshift === "number" ? { pshift: c.pshift } : {}), ...(c.crop ? { crop: c.crop } : {}) })),
    // Старт прогулки — у середины комнаты, лицом вглубь: так человек сразу видит расстановку.
    spawn: { x: room.w / 2, y: Math.min(120, room.d / 3), rot: 0 },
  });

  const catalogue = catalogueSchema.parse({
    developerId: ctx.partnerId,
    titleRu: `Набор «${title}»`,
    titleEn: `${title} set`,
    currency: ctx.currency,
    materials: extraMaterials,
    options: [...items.map((it, i) => ({ it, i })).filter(({ i }) => !inGroup.has(i) || i === chairGroup[0]).map(({ it, i }) => ({
      id: defaultOf(i),
      category: "furniture" as const,
      titleRu: it.sku?.name ?? it.role ?? "Предмет",
      titleEn: it.sku?.name ?? it.role ?? "Item",
      descRu: `${Math.round(it.w as number)}×${Math.round(it.d as number)}×${Math.round(it.h as number)} см`,
      // Мебель витрины в цену квартиры не входит: это покупка за счёт сертификата/доплаты, поэтому
      // ступень «стандарт» и настоящая цена товара — иначе «выбрано на» в 3D было бы всегда 0.
      tier: "standard" as const,
      price: rub(it.sku?.price),
      ...packOf(it.sku?.pack),
      packKey: keyOf(it),
      ...(it.sku?.img ? { previewUrl: assetUrl(it.sku.img, ctx.assetBase) } : {}),
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
        // цветовой вариант на модели семейства — подкраской (demo-02 приёмка 16.10 п.11б)
        ...tintOf(it.sku?.tint),
      },
      // Ссылка в магазин — ПАРТНЁРСКАЯ, прямо как на витрине: иначе теряется комиссия (ADR-0016).
      ...(it.sku?.url ? { shopUrl: it.sku.url } : {}),
      ...(it.sku?.shop ? { shopName: it.sku.shop } : {}),
    })), ...extraOptions, ...feedOptions.values()],
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
