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
  sources: apartmentSources,
});
export type ApartmentRef = z.infer<typeof apartmentRef>;

export const partner = z.object({
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
  /** Домены, которым разрешено встраивать нас рамкой (`b2b-07`, Caddy frame-ancestors). */
  frameDomains: z.array(z.string().url()).default([]),
  /** Демонстрационный застройщик: можно переключать рынок на странице (ADR-0254). */
  demo: z.boolean().default(false),
  complexes: z.array(complex).min(1),
  apartments: z.array(apartmentRef).min(1),
});
export type Partner = z.infer<typeof partner>;

/** Публичная карточка квартиры для шапки витрины и 3D — всё уже посчитано сервером. */
export type ApartmentCard = {
  id: string;
  partnerId: string;
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
  certificate: { amount: number; title: string; text: string } | null;
  sources: { demoData?: string; flat3d?: string };
};
