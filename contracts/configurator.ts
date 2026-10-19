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
  /**
   * Откуда фактура. Три разных происхождения, и их нельзя путать:
   * `photo` — снята с карточки ТОВАРА (есть магазин, ссылка, цена);
   * `photo-material` — снята с фотографии МАТЕРИАЛА, которую дал застройщик (ADR-0226):
   *   товара за ней нет, зато есть источник фото, лицензия и физический размер;
   * `procedural` — нарисована программой, фотографии под неё не было.
   */
  source: z
    .object({
      kind: z.enum(["photo", "photo-material", "procedural"]),
      productSid: z.string().optional(),
      productName: z.string().optional(),
      shop: z.string().optional(),
      productUrl: z.string().optional(),
      imageUrl: z.string().optional(),
      sourceUrl: z.string().optional(),
      licence: z.string().optional(),
      note: z.string().optional(),
      method: z.string().optional(),
      realCm: z.array(z.number()).optional(),
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
  /**
   * Размер плиты ковра товара (demo-18 п.2): замена ковра меняет не только фото, но и размер на полу (`resolve.fitPlacement`
   * кладёт его вдоль длинной стороны места). Нет — размер места.
   */
  wCm: z.number().positive().optional(),
  dCm: z.number().positive().optional(),
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
  /**
   * Акцентная стена (demo-07): одна стена в другом материале. Хранится смыслом — «за диваном»; сторону считает
   * `lib/configurator/accent.ts:resolveAccentSide` при расчёте сцены.
   */
  accent: z.object({ materialId: z.string(), anchor: z.literal("behind-sofa") }).optional(),
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
  price: z.number().nonnegative().default(0),
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
  listPrice: z.number().nonnegative().optional(),
  /**
   * Упаковка (demo-05 п.9, разбор Codex): товар продаётся по `pack` штук, места с одним `packKey` считаются вместе —
   * `resolveScene` берёт ceil(мест/pack) покупок по цене `price` и пишет их одной строкой (первому месту), остальным 0.
   * «2 шт.» на 2 стула — одна покупка; убрал один стул — упаковку всё равно покупать.
   */
  pack: z.number().int().positive().optional(),
  packKey: z.string().optional(),
  /**
   * Куда идёт доплата (demo-06, `lib/configurator/settlement.ts`): нет поля — в мебельный сертификат; отделка застройщика —
   * `developer_surcharge` (RF, вне сертификата) или `property_price` (UK, в цену квартиры).
   */
  settlement: z.enum(["allowance", "developer_surcharge", "property_price"]).optional(),
  /** Совместимость: нужны эти опции / несовместимо с этими. */
  requires: z.array(z.string()).default([]),
  excludes: z.array(z.string()).default([]),
});
export type Option = z.infer<typeof option>;

export const catalogue = z.object({
  developerId: z.string(),
  titleRu: z.string(),
  titleEn: z.string(),
  /** Валюта цен каталога = валюта застройщика (`data/partners`, ADR-0258). */
  currency: z.enum(["GBP", "RUB"]).default("GBP"),
  options: z.array(option),
  materials: z.array(material),
});
export type Catalogue = z.infer<typeof catalogue>;

/** Куда покупатель передвинул предмет. Габариты сюда НЕ пишем — они у выбранной модели. */
export const placementOverride = z.object({
  x: z.number(),
  y: z.number(),
  rot: z.number(),
});
export type PlacementOverride = z.infer<typeof placementOverride>;

/**
 * Выбор покупателя: что выбрано и что передвинуто. Цен и габаритов здесь нет — они выводятся.
 *
 * Версия 2 добавила `placements`: без них передвинутую мебель некуда сохранять, и 3D разошлось бы
 * с планом, фото и сохранённой ссылкой (находка советника 30.09). Старые подборы (версия 1)
 * читаются и поднимаются до версии 2 функцией `upgradeConfiguration`.
 */
export const configuration = z.object({
  version: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  /** id квартиры из реестра застройщиков (`data/partners`), не id сборки. */
  apartmentId: z.string(),
  developerId: z.string(),
  /**
   * Версия 3 (b2b-06): исходный набор мебели витрины (`?demo=set16`) — отдельно от квартиры.
   * Раньше он был зашит в id квартиры (`demo-set16`) и терялся смысл «чья это квартира».
   */
  baseVariant: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/).optional(),
  /** Снимок «место → модель» исходного набора на момент сохранения: ночная пересборка витрины
   *  может сменить мебель — тогда покажем «набор обновился», а не подменим молча (ADR-0254 п.6). */
  baseSnapshot: z.record(z.string(), z.string()).optional(),
  selections: z.record(z.string(), z.string()), // slotId → optionId
  placements: z.record(z.string(), placementOverride).default({}), // slotId → куда передвинули
  /** Предметы, которые покупатель убрал из комнаты (кнопка «Убрать», flat3d-sims-ux): нет ни в сцене, ни в цене.
   *  Только мебель — встроенное и отделку убрать нельзя. Необязательное поле: старые ссылки читаются как есть. */
  hidden: z.array(z.string().max(80)).max(200).optional(),
  /** Коллекция покупателя, из которой открыт 3D (`/flat?coll=`, b2b-05): по ссылке подбор откроется на её расстановке. */
  collectionId: z.string().regex(/^[A-Za-z0-9_-]{22}$/).optional(),
  updatedAt: z.string().optional(),
});
export type Configuration = z.infer<typeof configuration>;

/** Поднять старый подбор до версии 3 — ссылки, выданные раньше, продолжают читаться. */
export function upgradeConfiguration(cfg: Configuration): Configuration {
  if (cfg.version === 3) return cfg;
  return { ...cfg, version: 3, placements: cfg.placements ?? {} };
}

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
