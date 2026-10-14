// Застройщик (партнёр) → ЖК → квартира: данные, а не константы в вёрстке (план b2b-06, ADR-0258).
//
// Рынок задаёт застройщик (ADR-0254): валюта, доля сертификата, язык по умолчанию. Переключатель на
// странице меняет только язык. Сертификат — одна предельная сумма = доля от цены квартиры
// (В12: РФ 5 %, UK 4 % по умолчанию), считается в одном месте — `lib/partners/registry.ts`.
// Менеджеры застройщика здесь НЕ живут: их привязка к Telegram и ключи — в базе (ADR-0257).

import { z } from "zod";

export const market = z.enum(["ru", "uk"]);
export type Market = z.infer<typeof market>;
export const lang = z.enum(["ru", "en"]);
export type Lang = z.infer<typeof lang>;
export const currency = z.enum(["RUB", "GBP"]);
export type Currency = z.infer<typeof currency>;

/** Срок сдачи: целевые квартиры — дом сдан или сдаётся в ближайшие месяцы (ADR-0252). */
export const handover = z.object({
  status: z.enum(["delivered", "planned"]),
  /** Квартал сдачи «2026-Q4»; у сданного — когда сдан (необязательно). */
  quarter: z.string().regex(/^\d{4}-Q[1-4]$/).optional(),
});
export type Handover = z.infer<typeof handover>;

export const complex = z.object({
  id: z.string().min(1),
  nameRu: z.string().min(1),
  nameEn: z.string().min(1),
  handover,
});
export type Complex = z.infer<typeof complex>;

/** Где у квартиры живые данные для витрины и 3D. Хотя бы одно — иначе показывать нечего. */
export const apartmentSources = z
  .object({
    /** demo-data.json витрины (`flat215_demo.py`): планировка, варианты мебели. */
    demoData: z.string().optional(),
    /** id квартиры 3D-конфигуратора (`data/flat3d/*.json`). */
    flat3d: z.string().optional(),
  })
  .refine((s) => s.demoData || s.flat3d, "у квартиры нет ни витрины, ни 3D");

/**
 * Опции квартиры от партнёров застройщика (b2b-10 этап 0, ADR-0262): группа «кухня» и её варианты.
 * Цена — явное состояние (разбор Codex 13.10: `null` читался бы как «неизвестно»): включено в цену, доплата
 * в валюте застройщика, цена уточняется у менеджера, либо берётся из 3D-каталога (один источник цены).
 * Модули, техника и размеры кухни — позже (`specRef`), когда придут настоящие кухни (этап 1).
 */
export const optionPricing = z.discriminatedUnion("type", [
  z.object({ type: z.literal("included") }),
  z.object({ type: z.literal("surcharge"), amount: z.number().int().positive() }),
  z.object({ type: z.literal("on_request") }),
  z.object({ type: z.literal("from_configurator") }),
]);
export type OptionPricing = z.infer<typeof optionPricing>;

export const optionVariant = z.object({
  id: z.string().regex(/^[a-z0-9-]{2,40}$/),
  nameRu: z.string().min(1),
  nameEn: z.string().min(1),
  descRu: z.string().default(""),
  descEn: z.string().default(""),
  /** Фото варианта (путь в приложении `/partners/<партнёр>/options/...`); нет фото — карточка без картинки. */
  image: z.string().regex(/^\/[a-zA-Z0-9/_.-]+$/).optional(),
  pricing: optionPricing,
  /** Демонстрационный вариант (не настоящий товар партнёра) — помечается на плитке. */
  demo: z.boolean().default(false),
  /** Та же опция в 3D-конфигураторе (`data/flat3d`): цена `from_configurator` и переход в 3D. */
  configuratorOptionId: z.string().optional(),
  specRef: z.string().optional(),
});

export const optionGroup = z
  .object({
    id: z.string().regex(/^[a-z0-9-]{2,40}$/),
    kind: z.enum(["kitchen", "bathroom", "flooring"]),
    roomKind: z.enum(["kitchen", "bathroom", "bedroom", "living", "hall"]),
    roomId: z.string().optional(),
    titleRu: z.string().min(1),
    titleEn: z.string().min(1),
    defaultVariantId: z.string(),
    variants: z.array(optionVariant).min(1),
  })
  .refine((g) => new Set(g.variants.map((v) => v.id)).size === g.variants.length, "id вариантов повторяются")
  .refine((g) => g.variants.some((v) => v.id === g.defaultVariantId), "вариант по умолчанию не найден");
export type OptionGroup = z.infer<typeof optionGroup>;

export const apartmentRef = z.object({
  id: z.string().regex(/^[a-z0-9-]{2,40}$/),
  complexId: z.string(),
  kindRu: z.string().min(1), // «Трёхкомнатная»
  kindEn: z.string().min(1), // «3-bedroom flat»
  areaM2: z.number().positive(),
  /** Номер квартиры в ЖК для бейджа («215»); у демо — условный. */
  number: z.string().max(12).optional(),
  floor: z.number().int().optional(),
  floorsTotal: z.number().int().optional(),
  building: z.string().optional(),
  /** Цена в валюте партнёра, целое число. Демонстрационная — помечается `demoPrice`. */
  price: z.number().int().nonnegative(),
  demoPrice: z.boolean().default(false),
  /** На какую дату цена (ADR-0252: цены — с датой и оговоркой). */
  priceAsOf: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  sources: apartmentSources,
  options: z.array(optionGroup).default([]),
});
export type ApartmentRef = z.infer<typeof apartmentRef>;

export const partner = z.object({
  /** Пояснение для людей в файле данных; программа его не читает. */
  _note: z.string().optional(),
  id: z.string().regex(/^[a-z0-9-]{2,40}$/),
  nameRu: z.string().min(1),
  nameEn: z.string().min(1),
  market,
  defaultLang: lang,
  currency,
  /** Доля сертификата от цены квартиры: 0 — сертификата нет. */
  certificateShare: z.number().min(0).max(0.3),
  /** Тексты блока сертификата; пусто — стандартные. */
  certificateTextRu: z.string().optional(),
  certificateTextEn: z.string().optional(),
  /** Источники, которым разрешено встраивать нас рамкой (`b2b-07`, Caddy frame-ancestors):
   *  `https://site.ru` или `https://*.site.ru` — без пути. */
  frameDomains: z.array(z.string().regex(/^https:\/\/(\*\.)?[a-z0-9.-]+\.[a-z]{2,}(:\d+)?$/)).default([]),
  /** Логотип застройщика для экрана загрузки 3D (flat3d-sims-ux D8): свой путь (`/partners/…`) или https. */
  logoUrl: z.string().regex(/^(https:\/\/|\/)[^\s"'<>]{1,300}$/).optional(),
  /** Часовой пояс отчёта застройщику (`b2b-03`: недельный отчёт по его времени). */
  timezone: z.string().default("Europe/Moscow"),
  /** Демонстрационный застройщик: можно переключать рынок на странице (ADR-0254). */
  demo: z.boolean().default(false),
  complexes: z.array(complex).min(1),
  apartments: z.array(apartmentRef).min(1),
}).strict(); // опечатка в ключе («certificateshare») — ошибка, а не тихий пропуск (рецензия 13.10)
export type Partner = z.infer<typeof partner>;

/** Публичная карточка квартиры для шапки витрины и 3D — всё уже посчитано сервером. */
export type ApartmentCard = {
  id: string;
  partnerId: string;
  complexId: string;
  market: Market;
  lang: Lang;
  currency: Currency;
  kind: string;
  number: string | null;
  areaM2: number;
  complex: string;
  handover: string;
  meta: string; // «ЖК … · сдан · эт. 6 из 17 · корп. 3»
  price: number;
  demoPrice: boolean;
  priceAsOf: string | null;
  certificate: { amount: number; title: string; text: string } | null;
  /** Опции квартиры в публичном виде: подписи на языке, цена уже текстом. */
  options: {
    id: string; kind: string; roomKind: string; title: string; defaultVariantId: string;
    variants: { id: string; name: string; desc: string; image: string | null; demo: boolean;
      price: { type: OptionPricing["type"]; amount: number | null; text: string }; configuratorOptionId: string | null }[];
  }[];
  sources: { demoData?: string; flat3d?: string };
};
