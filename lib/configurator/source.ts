// Откуда берётся квартира 3D (план b2b-06, ADR-0258) — ОДНО место для страницы `/flat` и для
// сохранения подбора, чтобы они не расходились. Квартира ищется в реестре застройщиков:
//   • `sources.flat3d`   — готовая квартира конфигуратора (`data/flat3d`), цена — из реестра;
//   • `sources.demoData` — квартира собирается из живого demo-data.json витрины по набору `baseVariant`.
// Адрес витрины берётся ТОЛЬКО из реестра, не из запроса. Витрина не ответила — `unavailable`
// (страница честно скажет «попробуйте позже»), а не тихая подмена другой квартирой.

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import { loadFlat3d } from "@/lib/configurator/data";
import { collectionAsVariant, finishOptionId, fromDemoVariant, resolveVariantId, type DemoContext, type DemoData, type DemoFloorChoice } from "@/lib/configurator/fromDemo";
import { settlementOf } from "@/lib/configurator/settlement";
import { currentPrices, priceIndex } from "@/lib/collections/prices";
import { collectionRepo } from "@/modules/collections/repository";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { apartmentCard, findApartment, partners, type ApartmentHit } from "@/lib/partners/registry";

export type FlatResolved =
  | {
      ok: true;
      apartment: Apartment;
      catalogue: Catalogue;
      hit: ApartmentHit;
      /** Ссылка вела на вариант, которого больше нет: открыт текущий (того же стиля, если он есть) — demo-05 п.10. */
      replaced?: { from: string; style?: string };
      /** Выбор опций застройщика из коллекции (demo-06, v2) — страница переводит его в выбор мест (`developerSelections`). */
      developerOptions?: Record<string, string>;
    }
  | { ok: false; reason: "unknown" | "unavailable" };

export type DemoLoader = (src: string) => Promise<unknown | null>;

/** Квартира по умолчанию для адреса без `?flat=`: с витриной (если пришли с `?demo=`) или из 3D. */
export function defaultApartmentId(kind: "demo" | "flat3d"): string | null {
  for (const p of partners()) for (const a of p.apartments) if (kind === "demo" ? a.sources.demoData : a.sources.flat3d) return a.id;
  return null;
}

/**
 * Пол на выбор из карточки квартиры (demo-06): включённая группа со слотом `floor`. Варианты «цена по запросу» в 3D не
 * идут — их сумму нельзя показать в итоге честно (там они 0), покупатель видит их в окне демо со своей пометкой.
 */
export function floorChoiceOf(hit: ApartmentHit): DemoFloorChoice | undefined {
  return finishChoiceOf(hit, "floor");
}

/** Отделка на выбор из карточки для места `floor` или `wall` (demo-06/07): включённая группа с этим слотом. */
export function finishChoiceOf(hit: ApartmentHit, slot: "floor" | "wall"): DemoFloorChoice | undefined {
  const ru = apartmentCard(hit, "ru").options.find((o) => o.slotIds.includes(slot));
  if (!ru) return undefined;
  const en = apartmentCard(hit, "en").options.find((o) => o.id === ru.id);
  const variants = ru.variants.filter((v) => v.material && v.price.type !== "on_request").map((v) => ({
    id: v.id, titleRu: v.name, titleEn: en?.variants.find((x) => x.id === v.id)?.name ?? v.name,
    price: v.price.type === "surcharge" ? v.price.amount ?? 0 : 0, material: v.material as Record<string, unknown> & { id: string },
    ...(v.accent ? { accent: { material: v.accent.material as Record<string, unknown> & { id: string }, anchor: v.accent.anchor } } : {}),
  }));
  return variants.length ? { groupId: ru.id, defaultVariantId: ru.defaultVariantId, settlement: ru.settlement, variants } : undefined;
}

/** Курс показа рублёвой витрины в валюте застройщика (британский демо-двойник, ADR-0298). */
function fxOf(hit: ApartmentHit): { fxRate?: number } {
  const fx = hit.partner.fx;
  return fx && fx.from === "RUB" && fx.to === hit.partner.currency ? { fxRate: fx.rate } : {};
}

/** Выбор опций застройщика → выбор мест квартиры (пол, стены). Неизвестное молча не применяется (вариант по умолчанию). */
export function developerSelections(hit: ApartmentHit, apartment: Apartment, opts: Record<string, string> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const surface of ["floor", "wall"] as const) {
    const fc = finishChoiceOf(hit, surface);
    const vid = fc && opts?.[fc.groupId];
    const slot = apartment.slots.find((x) => x.id === surface);
    if (vid && slot?.optionIds.includes(finishOptionId(surface, vid))) out[surface] = finishOptionId(surface, vid);
  }
  return out;
}

/** `?opt=flooring:parquet-herringbone,…` — пары «группа:вариант» в адресе (несохранённое состояние окна демо). */
export function parseOptParam(raw: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const pair of (raw ?? "").split(",").slice(0, 10)) {
    const m = /^([a-z0-9-]{2,40}):([a-z0-9-]{2,40})$/.exec(pair);
    if (m) out[m[1]!] = m[2]!;
  }
  return out;
}

export async function resolveFlat(apartmentId: string, baseVariant?: string, load: DemoLoader = loadDemoRaw): Promise<FlatResolved> {
  const hit = findApartment(apartmentId);
  if (!hit) return { ok: false, reason: "unknown" };
  const fc = floorChoiceOf(hit), wc = finishChoiceOf(hit, "wall");
  const ctx: DemoContext = { apartmentId, partnerId: hit.partner.id, currency: hit.partner.currency, basePrice: hit.apartment.price,
    ...(fc ? { floorChoice: fc } : {}), ...(wc ? { wallChoice: wc } : {}), ...fxOf(hit) };

  const src = hit.apartment.sources.demoData;
  if (src && (baseVariant || !hit.apartment.sources.flat3d)) {
    const raw = (await load(src)) as DemoData | null;
    ctx.assetBase = src; // картинки ковров витрины (`img/…`) — рядом с её demo-data.json
    if (!raw) return { ok: false, reason: "unavailable" };
    const pick = baseVariant ? resolveVariantId(raw, baseVariant) : raw.variants?.[0]?.id ? { id: raw.variants[0].id } : null;
    const built = pick ? fromDemoVariant(raw, pick.id, ctx) : null;
    if (!built) return { ok: false, reason: "unknown" };
    return { ok: true, ...built, hit, ...(pick?.from ? { replaced: { from: pick.from, ...(pick.style ? { style: pick.style } : {}) } } : {}) };
  }

  const flat3d = hit.apartment.sources.flat3d;
  if (!flat3d || baseVariant) return { ok: false, reason: "unknown" };
  const base = loadFlat3d();
  if (base.apartment.id !== flat3d) return { ok: false, reason: "unknown" };
  if (base.catalogue.currency !== hit.partner.currency) {
    throw new Error(`валюта каталога ${base.catalogue.currency} ≠ валюте застройщика ${hit.partner.currency}`);
  }
  // ОТДЕЛКА (demo-06, ADR-0254; demo-23 шаг 3): пол квартиры 3D идёт по правилу рынка застройщика (RF — доплата застройщику вне
  // сертификата, UK — в пакет), если у опции не задано своё; мебель и встроенное — в сертификат
  // кухня UK — тоже персонализация в цене квартиры (ADR-0298); RF кухня по-прежнему в сертификате
  const options = base.catalogue.options.map((o) => (["flooring", "walls", "kitchen"].includes(o.category) && !o.settlement
    ? { ...o, settlement: settlementOf(o.category, hit.partner.market) } : o));
  return {
    ok: true,
    apartment: { ...base.apartment, basePrice: hit.apartment.price, developerId: hit.partner.id },
    catalogue: { ...base.catalogue, options, developerId: hit.partner.id },
    hit,
  };
}


/**
 * 3D из коллекции покупателя (`/flat?coll=<id>`, план b2b-05 п.5): та же квартира и комната витрины, расстановка и
 * товары — из коллекции, цены текущие. Нет коллекции/квартиры — `unknown`, витрина не ответила — `unavailable`.
 */
export async function resolveCollectionFlat(id: string, load: DemoLoader = loadDemoRaw): Promise<FlatResolved> {
  const c = await collectionRepo().get(id);
  if (!c) return { ok: false, reason: "unknown" };
  const hit = findApartment(c.payload.apartmentId);
  const src = hit?.apartment.sources.demoData;
  if (!hit || !src) return { ok: false, reason: "unknown" };
  const raw = (await load(src)) as DemoData | null;
  if (!raw) return { ok: false, reason: "unavailable" };
  const sids = c.payload.items.map((i) => i.sku?.sid).filter((x): x is string => !!x);
  const data = collectionAsVariant(raw, c.payload, currentPrices(sids, priceIndex(raw)));
  const fc = floorChoiceOf(hit), wc = finishChoiceOf(hit, "wall");
  const ctx: DemoContext = { apartmentId: hit.apartment.id, partnerId: hit.partner.id, currency: hit.partner.currency,
    basePrice: hit.apartment.price, assetBase: src, ...(fc ? { floorChoice: fc } : {}), ...(wc ? { wallChoice: wc } : {}), ...fxOf(hit) };
  const built = fromDemoVariant(data, c.payload.baseVariant, ctx);
  return built ? { ok: true, ...built, hit, developerOptions: c.payload.developerOptions ?? {} } : { ok: false, reason: "unknown" };
}
