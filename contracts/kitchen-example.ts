// Пример кухни из магазина (план onb-08, ADR-0330 п.8): паспорт товара и его перевод в параметры нашего
// набора `lib/viewer3d/kits/kitchen.ts`. Это демонстрация, не продаваемая кухня: цена гарнитура ≠ «под ключ»,
// поэтому что входит в цену и что нет — обязательные списки. Картинка в демо — фото с ясным правом или наш
// 3D-кадр (по умолчанию — 3D-кадр и ссылка на источник). Данные — `data/partners/kitchen-examples/{ru,uk}.json`.

import { z } from "zod";

import { currency, market } from "@/contracts/partner";

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const hex = z.string().regex(/^#[0-9a-f]{6}$/);
const publicPath = z.string().regex(/^\/[a-zA-Z0-9/_.-]+$/);

/** Части кухни, о которых спорят «входит ли в цену». */
export const kitchenPart = z.enum([
  "cabinets", "fronts", "worktop", "plinth", "handles", "dish-rack", "sink", "tap",
  "appliances", "splashback", "lighting", "delivery", "installation",
]);

/** Признаки, которые понимает `buildKitchen` (`has("…")` в наборе). */
export const kitchenFeature = z.enum([
  "dishwasher", "oven", "wine-cooler", "hob", "uppers", "hood", "fridge", "microwave", "island", "tall-unit",
]);

/** Параметры набора — та же форма, что `KitchenSpec`; ширина и глубина — паспортные. */
export const kitchenKitSpec = z.object({
  level: z.enum(["base", "practical", "comfort", "premium"]),
  features: z.array(kitchenFeature),
  doorMaterialId: z.string().min(1),
  worktopMaterialId: z.string().min(1),
  splashbackMaterialId: z.string().min(1).optional(),
  widthCm: z.number().int().min(240).max(330),
  depthCm: z.number().int().min(50).max(70),
  columnsAt: z.enum(["start", "end"]).optional(),
}).strict();

/** Цвет слота: замер по фото → ближайший наш материал; далеко (ΔE > 10) — предложение нового. */
const colorSlot = z.object({
  measuredHex: hex,
  materialId: z.string().min(1),
  deltaE: z.number().nonnegative(),
  proposed: z.object({ id: z.string().regex(/^[a-z0-9-]+$/), hex }).strict().optional(),
  note: z.string().optional(),
}).strict();

const photo = z.object({
  url: z.string().url(),
  /** `link-only` — показывать нельзя, только ссылка; `partner-feed` — фото из фида партнёрки (право — условия программы). */
  license: z.enum(["link-only", "partner-feed", "CC0-1.0", "CC-BY-4.0"]),
  licenseVersion: z.string().nullable(),
  rightsNote: z.string().min(1),
  showAllowed: z.boolean(),
  /** Копия в `public/` — только при `showAllowed`. */
  path: publicPath.optional(),
}).strict();

const model = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("none"), note: z.string().min(1) }).strict(),
  z.object({
    kind: z.literal("cc0"), url: z.string().url(), author: z.string().min(1),
    license: z.literal("CC0-1.0"), checkedAt: isoDate,
  }).strict(),
  z.object({
    kind: z.literal("cc-by"), url: z.string().url(), author: z.string().min(1),
    license: z.enum(["CC-BY-3.0", "CC-BY-4.0"]), attribution: z.string().min(1), checkedAt: isoDate,
  }).strict(),
]);

export const kitchenExample = z.object({
  id: z.string().regex(/^[a-z0-9-]+$/),
  market,
  nameRu: z.string().min(1),
  nameEn: z.string().min(1),
  sourceUrl: z.string().url(),
  seller: z.string().min(1),
  affiliate: z.object({ network: z.literal("gdeslon"), mid: z.number().int(), article: z.string() }).strict().nullable(),
  price: z.number().int().positive(),
  currency,
  /** `from` — цена «от» за типовой набор модулей, не за показанный на фото. */
  priceKind: z.enum(["fixed", "from"]),
  priceAsOf: isoDate,
  priceSource: z.enum(["partner-feed", "shop-page"]),
  priceIncludes: z.array(kitchenPart).min(1),
  priceExcludes: z.array(kitchenPart).min(1),
  priceNote: z.string().optional(),
  lengthCm: z.number().int().min(240).max(330),
  depthCm: z.number().int().positive(),
  heightCm: z.number().int().positive(),
  /** Какие размеры не из карточки, а оценка по фото/чертежу. */
  estimated: z.array(z.enum(["length", "depth", "height"])),
  shape: z.enum(["straight", "corner"]),
  island: z.boolean(),
  /** Ширины модулей, см; пусто — карточка ширин не даёт. */
  modules: z.object({ base: z.array(z.number()), upper: z.array(z.number()), tall: z.array(z.number()) }).strict(),
  /** Техника, видимая на фото источника (в цену не входит, если не сказано иное). */
  appliancesInPhoto: z.array(kitchenFeature),
  colors: z.object({
    front: colorSlot, frontUpper: colorSlot.optional(), worktop: colorSlot, splashback: colorSlot.optional(),
  }).strict(),
  colorFrom: z.string().min(1),
  photo,
  displayImage: z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("our3d") }).strict(),
    z.object({ kind: z.literal("photo"), path: publicPath }).strict(),
  ]),
  model,
  kitSpec: kitchenKitSpec,
  /** Чем кадр нашего набора отличается от фото — честно, для onb-09. */
  kitFit: z.string().min(1),
  checkedAt: isoDate,
}).strict();
export type KitchenExample = z.infer<typeof kitchenExample>;

export const kitchenExamplesFile = z.object({
  _about: z.string(),
  market,
  examples: z.array(kitchenExample).min(3),
}).strict();
export type KitchenExamplesFile = z.infer<typeof kitchenExamplesFile>;
