// Каталог опций застройщика и выбор покупателя (план apartment-3d-configurator, ADR-0211).
//
// Разделение намеренное: КВАРТИРА (`contracts/apartment.ts`) знает геометрию и слоты,
// КАТАЛОГ знает, что в эти слоты можно поставить, а КОНФИГУРАЦИЯ — только выбор
// {slotId: optionId}. Поэтому один и тот же выбор рисуется тремя способами (3D, план, фото),
// а каталог можно заменить на каталог конкретного застройщика, не трогая квартиру.

import { z } from "zod";
import { slotCategory, roomKind } from "@/contracts/apartment";

/** Ступень апгрейда: базовая (входит в цену), стандарт, премиум. */
export const optionTier = z.enum(["base", "standard", "premium"]);
export type OptionTier = z.infer<typeof optionTier>;

/** Доступность у застройщика: сразу / под заказ со сроком / по запросу. */
export const availability = z.enum(["available", "lead_time", "on_request"]);
export type Availability = z.infer<typeof availability>;

/** Материал покрытия: карты + физический размер тайла (см) — иначе текстура «плывёт». */
export const material = z.object({
  id: z.string(),
  titleRu: z.string(),
  titleEn: z.string(),
  /** Базовый цвет — файл (webp/ktx2) или сплошной цвет как честный фолбэк. */
  baseColorUrl: z.string().optional(),
  normalUrl: z.string().optional(),
  roughnessUrl: z.string().optional(),
  aoUrl: z.string().optional(),
  colorHex: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  roughness: z.number().min(0).max(1).default(0.8),
  metalness: z.number().min(0).max(1).default(0),
  /** Размер одного повтора текстуры в сантиметрах: [ширина, высота]. */
  tileCm: z.tuple([z.number().positive(), z.number().positive()]).default([100, 100]),
  previewUrl: z.string().optional(),
  /**
   * Где материал ПРИМЕНИМ. Доска пола не надевается на фасад шкафа, а плитка — на диван
   * (владелец 29.09: «не все поверхности применимы»). Пусто = ограничений нет.
   */
  surfaces: z.array(z.enum(["floor", "wall", "worktop", "splashback", "front", "rug"])).default([]),
  /** Откуда фактура: фото товара (с провенансом) или процедурная генерация. */
  source: z
    .object({
      kind: z.enum(["photo", "procedural"]),
      productSid: z.string().optional(),
      productName: z.string().optional(),
      shop: z.string().optional(),
      productUrl: z.string().optional(),
      imageUrl: z.string().optional(),
      seamError: z.number().optional(),
      patch: z.record(z.string(), z.unknown()).optional(),
    })
    .optional(),
});
export type Material = z.infer<typeof material>;

/** Параметрический комплект: кухня/санузел/кровать/шкаф собираются кодом, а не мешем. */
export const kitAsset = z.object({
  kind: z.literal("kit"),
  kit: z.enum(["kitchen", "bathroom", "bed", "wardrobe", "rug"]),
  /** Уровень исполнения — им кит решает, что показать (например, встроенную технику). */
  level: z.enum(["base", "practical", "comfort", "premium"]).default("base"),
  materials: z.record(z.string(), z.string()).default({}), // слот кита → id материала
  features: z.array(z.string()).default([]), // integrated-oven, wine-cooler, …
});

/** Меш из нашего конвейера: ключ — msid (представитель семейства, ADR-0196). */
export const meshAsset = z.object({
  kind: z.literal("mesh"),
  meshId: z.string(),
  /** Готовый лёгкий GLB; пусто — берём исходный по meshId из галереи. */
  runtimeUrl: z.string().optional(),
  yawDeg: z.number().default(0), // канонический разворот фронта (orient.json)
  /**
   * Поправка цвета по фото товара: множитель на канал. У части моделей конвейера текстура
   * почти серая (замер 29.09: «жёлтое» кресло имело насыщенность 21 из 255), и покупатель
   * видел не тот цвет, который выбрал. Считает `tools/flat3d/mesh_tint.py`.
   */
  tintRgb: z.tuple([z.number(), z.number(), z.number()]).optional(),
  tintFrom: z.record(z.string(), z.unknown()).optional(),
  wCm: z.number().positive(),
  dCm: z.number().positive(),
  hCm: z.number().positive(),
});

export const materialAsset = z.object({
  kind: z.literal("material"),
  materialId: z.string(),
});

export const optionAsset = z.discriminatedUnion("kind", [meshAsset, materialAsset, kitAsset]);
export type OptionAsset = z.infer<typeof optionAsset>;

export const option = z.object({
  id: z.string(),
  category: slotCategory,
  titleRu: z.string(),
  titleEn: z.string(),
  descRu: z.string().default(""),
  tier: optionTier,
  /** Имя пакета застройщика: Base / Practical / Comfort / Premium. */
  packageName: z.string().optional(),
  /** Доплата к базе, £. У базовой опции — 0. */
  priceGbp: z.number().nonnegative().default(0),
  availability: availability.default("available"),
  roomKinds: z.array(roomKind).default([]),
  asset: optionAsset,
  previewUrl: z.string().optional(),
  /**
   * Товарная часть — для карточки в 3D: цена магазина и ПАРТНЁРСКАЯ ссылка (Гдеслон).
   * Прямую ссылку сюда класть нельзя — потеряем комиссию (ADR-0016).
   */
  shopUrl: z.string().optional(),
  shopName: z.string().optional(),
  listPriceGbp: z.number().nonnegative().optional(),
  /** Совместимость: нужны эти опции / несовместимо с этими. */
  requires: z.array(z.string()).default([]),
  excludes: z.array(z.string()).default([]),
});
export type Option = z.infer<typeof option>;

export const catalogue = z.object({
  developerId: z.string(),
  titleRu: z.string(),
  titleEn: z.string(),
  currency: z.literal("GBP").default("GBP"),
  options: z.array(option),
  materials: z.array(material),
});
export type Catalogue = z.infer<typeof catalogue>;

/** Выбор покупателя. Только id — никакой геометрии и цен, они выводятся. */
export const configuration = z.object({
  version: z.literal(1),
  apartmentId: z.string(),
  developerId: z.string(),
  selections: z.record(z.string(), z.string()), // slotId → optionId
  updatedAt: z.string().optional(),
});
export type Configuration = z.infer<typeof configuration>;

/** Заявка менеджеру: конфигурация + контакт. Контакт валидируем мягко — это демо. */
export const configSaveIn = z.object({
  configuration,
  name: z.string().max(120).optional(),
  contact: z.string().max(200).optional(),
  note: z.string().max(1000).optional(),
});
export type ConfigSaveIn = z.infer<typeof configSaveIn>;

export function optionById(c: Catalogue, id: string): Option | undefined {
  return c.options.find((o) => o.id === id);
}

export function materialById(c: Catalogue, id: string): Material | undefined {
  return c.materials.find((m) => m.id === id);
}
