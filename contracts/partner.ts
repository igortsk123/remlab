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

/** Тип помещения: общий для комнат квартиры и опций застройщика (кухня — к кухне). */
export const roomKind = z.enum(["kitchen", "bathroom", "bedroom", "living", "hall"]);
export type RoomKind = z.infer<typeof roomKind>;

/**
 * Опции квартиры от партнёров застройщика (b2b-10 этап 0, ADR-0262): группа «кухня» и её варианты.
 * Цена — явное состояние (разбор Codex 13.10: `null` читался бы как «неизвестно»): включено в цену, доплата
 * в валюте застройщика, цена уточняется у менеджера, либо берётся из 3D-каталога (один источник цены).
 * Модули, техника и размеры кухни — позже (`specRef`), когда придут настоящие кухни (этап 1).
 */
export const optionPricing = z.discriminatedUnion("type", [
  z.object({ type: z.literal("included") }),
  z.object({ type: z.literal("surcharge"), amount: z.number().int().positive() }),
  /** За квадратный метр (demo-06): площадь к оплате задаёт застройщик — автоматически из комнаты не берём (Codex 14.10). */
  z.object({ type: z.literal("per_m2"), rate: z.number().positive(), billableAreaM2: z.number().positive() }),
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
  /** Материал поверхности (`data/flat3d/materials.json`) — у отделки (пол): им красится слот `slotIds` группы (demo-06). */
  materialId: z.string().regex(/^[a-z0-9-]{2,40}$/).optional(),
  /** Акцентная стена (demo-07): одна стена другим материалом; сторона — «за диваном», считает расчёт сцены. */
  accent: z.object({ materialId: z.string().regex(/^[a-z0-9-]{2,40}$/), anchor: z.literal("behind-sofa") }).optional(),
  specRef: z.string().optional(),
});

export const optionGroup = z
  .object({
    id: z.string().regex(/^[a-z0-9-]{2,40}$/),
    kind: z.enum(["kitchen", "wardrobe", "appliances", "bathroom", "flooring", "walls"]),
    roomKind,
    /** Помещение квартиры (`apartmentRef.rooms[].id`), к которому относится группа: сумма корзины — по комнатам (demo-16). */
    roomId: z.string().optional(),
    titleRu: z.string().min(1),
    titleEn: z.string().min(1),
    defaultVariantId: z.string(),
    variants: z.array(optionVariant).min(1),
    /**
     * Выбор включён у застройщика (владелец 14.10: «предусмотри отключение кастома»): `false` — группа не показывается
     * покупателю, не считается в сумме, сцена рисует вариант по умолчанию.
     */
    enabled: z.boolean().default(true),
    /**
     * Куда идёт доплата (demo-06, ADR-0254): `allowance` — в мебельный сертификат; `developer_surcharge` — доплата застройщику
     * вне сертификата (RF пол); `property_price` — в цену квартиры (UK). Нет поля — по умолчанию из `settlementOf`.
     */
    settlement: z.enum(["allowance", "developer_surcharge", "property_price"]).optional(),
    /** Слоты квартиры, которые меняет группа (пол витрины — `floor`); выбор группы — источник, слот — проекция. */
    slotIds: z.array(z.string()).optional(),
  })
  .refine((g) => new Set(g.variants.map((v) => v.id)).size === g.variants.length, "id вариантов повторяются")
  // ровно один ассет у варианта (Codex 16.10): материал — у отделки, опция 3D — у кухни; оба сразу — ошибка данных
  .refine((g) => g.variants.every((v) => !(v.materialId && v.configuratorOptionId)), "у варианта и материал, и опция 3D")
  .refine((g) => !["flooring", "walls"].includes(g.kind) || g.variants.every((v) => v.materialId), "у варианта отделки нет материала")
  .refine((g) => g.kind === "walls" || g.variants.every((v) => !v.accent), "акцентная стена — только у группы стен")
  .refine((g) => g.variants.some((v) => v.id === g.defaultVariantId), "вариант по умолчанию не найден");
export type OptionGroup = z.infer<typeof optionGroup>;

/**
 * Помещение квартиры (demo-16, Codex 18.10 п.1): главная строит «стиль → комнаты» из этого списка, а не из заголовков чертежа.
 * Порядок массива = порядок плана (`ordinal` — тот же номер явно, с 1). `contentState`: `ready` — у комнаты есть варианты
 * обстановки, `soon` — пока единая заглушка «появится следующим шагом» (не фиктивный вариант).
 */
export const apartmentRoom = z.object({
  id: z.string().regex(/^[a-z0-9-]{2,40}$/),
  kind: roomKind,
  ordinal: z.number().int().min(1),
  titleRu: z.string().min(1),
  titleEn: z.string().min(1),
  areaM2: z.number().positive(),
  contentState: z.enum(["ready", "soon"]),
});
export type ApartmentRoom = z.infer<typeof apartmentRoom>;

export const apartmentRef = z.object({
  id: z.string().regex(/^[a-z0-9-]{2,40}$/),
  complexId: z.string(),
  kindRu: z.string().min(1), // «Трёхкомнатная»
  kindEn: z.string().min(1), // «3-bedroom flat»
  /** Короткий тип для строки квартиры на телефоне («3-комн.», demo-16 макет A); нет — полный. */
  kindShortRu: z.string().max(16).optional(),
  kindShortEn: z.string().max(16).optional(),
  areaM2: z.number().positive(),
  /**
   * Лоджия/балкон — площадь с понижающим коэффициентом, как в экспликации (у №215 — 1,3 из 2,6 м²). Комнатой не является (в корзину и
   * на главную не идёт), но входит в общую площадь: комнаты + лоджия = `areaM2` (demo-21, T-20261022-04).
   */
  loggiaM2: z.number().nonnegative().optional(),
  /** Номер квартиры в ЖК для бейджа («215»); у демо — условный. */
  number: z.string().max(12).optional(),
  floor: z.number().int().optional(),
  floorsTotal: z.number().int().optional(),
  building: z.string().optional(),
  /** Паспорт отделки квартиры: стены, пол, потолок, плинтус — id материала и цвет `#rrggbb` (`lib/viewer3d/finish-passport.ts`). */
  finish: z.record(z.enum(["wall", "floor", "ceiling", "skirting"]),
    z.object({ id: z.string().regex(/^[a-z0-9-]{1,40}$/), colorHex: z.string().regex(/^#[0-9a-fA-F]{6}$/) })).optional(),
  /** Вид из окон — id нашего набора (`lib/viewer3d/window-views.ts`: city-day, city-evening, yard, park), demo-04 п.5. */
  windowView: z.string().regex(/^[a-z0-9-]{1,32}$/).optional(),
  /** Цена в валюте партнёра, целое число. Демонстрационная — помечается `demoPrice`. */
  price: z.number().int().nonnegative(),
  demoPrice: z.boolean().default(false),
  /** На какую дату цена (ADR-0252: цены — с датой и оговоркой). */
  priceAsOf: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  sources: apartmentSources,
  /** Помещения в порядке плана (demo-16); нет — главная показывает только комнаты, у которых есть варианты. */
  rooms: z.array(apartmentRoom).default([]),
  options: z.array(optionGroup).default([]),
  /**
   * Двойник для английского ДЕМО (владелец 16.10, ADR-0298): анонимное демо витрины на английском открывает квартиру-двойника
   * британского демо-застройщика (£, allowance, «к цене квартиры»). По ссылке менеджера/партнёра — эта же квартира (ADR-0254).
   */
  enTwin: z.string().regex(/^[a-z0-9-]{2,40}$/).optional(),
})
  .refine((a) => new Set(a.rooms.map((r) => r.id)).size === a.rooms.length, "id комнат повторяются")
  .refine((a) => a.rooms.every((r, k) => r.ordinal === k + 1), "ordinal комнат — по порядку плана с 1")
  // ОДНА ИСТИНА ПЛОЩАДЕЙ (T-20261022-04): комнаты реестра + лоджия = общая площадь квартиры (±0,2 — округление экспликации)
  .refine((a) => !a.rooms.length || Math.abs(a.rooms.reduce((s, r) => s + r.areaM2, 0) + (a.loggiaM2 ?? 0) - a.areaM2) <= 0.2,
    "сумма площадей комнат и лоджии не равна площади квартиры")
  // опция с комнатой — к существующей комнате (сумма по комнатам иначе молча потеряет доплату)
  .refine((a) => !a.rooms.length || a.options.every((g) => !g.roomId || a.rooms.some((r) => r.id === g.roomId)), "roomId опции нет среди комнат")
  // кухня застройщика — к кухне: тип комнаты опции совпадает с типом помещения, к которому она привязана (Codex 18.10)
  .refine((a) => a.options.every((g) => !g.roomId || a.rooms.every((r) => r.id !== g.roomId || r.kind === g.roomKind)), "roomKind опции не совпадает с комнатой");
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
  /**
   * Курс для показа рублёвых цен витрины в валюте застройщика (ADR-0298): фиксированный, с датой и источником, правит человек.
   * Канон цен — рубли фидов; здесь только представление «≈ по курсу на дату».
   */
  fx: z.object({ from: z.literal("RUB"), to: currency, rate: z.number().positive(), asOf: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    source: z.string().min(1) }).optional(),
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
  /** «3-комн.» — строка квартиры первого экрана рядом с ценой (demo-19 Б1, без площади); нет короткого типа — полный без площади. */
  kindShort: string;
  number: string | null;
  areaM2: number;
  complex: string;
  handover: string;
  meta: string; // «ЖК … · сдан · эт. 6 из 17 · корп. 3»
  /** Короткая строка дома для первого экрана: «ЖК … · сдача 4 кв. 2026» (demo-19 Б1; этаж и корпус — в `meta`, «Подробнее»). */
  metaShort: string;
  price: number;
  demoPrice: boolean;
  priceAsOf: string | null;
  certificate: { amount: number; title: string; text: string } | null;
  /** Курс показа рублёвых цен витрины (у британского демо-двойника); нет — цены в валюте витрины. */
  fx: { from: "RUB"; to: Currency; rate: number; asOf: string; source: string } | null;
  /** Помещения в порядке плана, подписи на языке страницы (demo-16). */
  rooms: { id: string; kind: RoomKind; ordinal: number; title: string; areaM2: number; contentState: "ready" | "soon" }[];
  /** Опции квартиры в публичном виде: подписи на языке, цена уже текстом. */
  options: {
    id: string; kind: string; roomKind: string; roomId: string | null; title: string; defaultVariantId: string;
    /** Куда идёт доплата группы (`lib/configurator/settlement.ts`); выключенные группы в карточку не попадают. */
    settlement: "allowance" | "developer_surcharge" | "property_price";
    slotIds: string[];
    variants: { id: string; name: string; desc: string; image: string | null; demo: boolean;
      price: { type: OptionPricing["type"]; amount: number | null; text: string }; configuratorOptionId: string | null;
      materialId: string | null; material: Record<string, unknown> | null;
      accent: { material: Record<string, unknown>; anchor: "behind-sofa" } | null }[];
  }[];
  sources: { demoData?: string; flat3d?: string };
};
