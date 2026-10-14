// Откуда берётся квартира 3D (план b2b-06, ADR-0258) — ОДНО место для страницы `/flat` и для
// сохранения подбора, чтобы они не расходились. Квартира ищется в реестре застройщиков:
//   • `sources.flat3d`   — готовая квартира конфигуратора (`data/flat3d`), цена — из реестра;
//   • `sources.demoData` — квартира собирается из живого demo-data.json витрины по набору `baseVariant`.
// Адрес витрины берётся ТОЛЬКО из реестра, не из запроса. Витрина не ответила — `unavailable`
// (страница честно скажет «попробуйте позже»), а не тихая подмена другой квартирой.

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import { loadFlat3d } from "@/lib/configurator/data";
import { collectionAsVariant, fromDemoVariant, type DemoData } from "@/lib/configurator/fromDemo";
import { currentPrices, priceIndex } from "@/lib/collections/prices";
import { collectionRepo } from "@/modules/collections/repository";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { findApartment, partners, type ApartmentHit } from "@/lib/partners/registry";

export type FlatResolved =
  | { ok: true; apartment: Apartment; catalogue: Catalogue; hit: ApartmentHit }
  | { ok: false; reason: "unknown" | "unavailable" };

export type DemoLoader = (src: string) => Promise<unknown | null>;

/** Квартира по умолчанию для адреса без `?flat=`: с витриной (если пришли с `?demo=`) или из 3D. */
export function defaultApartmentId(kind: "demo" | "flat3d"): string | null {
  for (const p of partners()) for (const a of p.apartments) if (kind === "demo" ? a.sources.demoData : a.sources.flat3d) return a.id;
  return null;
}

export async function resolveFlat(apartmentId: string, baseVariant?: string, load: DemoLoader = loadDemoRaw): Promise<FlatResolved> {
  const hit = findApartment(apartmentId);
  if (!hit) return { ok: false, reason: "unknown" };
  const ctx = { apartmentId, partnerId: hit.partner.id, currency: hit.partner.currency, basePrice: hit.apartment.price };

  const src = hit.apartment.sources.demoData;
  if (src && (baseVariant || !hit.apartment.sources.flat3d)) {
    const raw = (await load(src)) as DemoData | null;
    if (!raw) return { ok: false, reason: "unavailable" };
    const variant = baseVariant ?? raw.variants?.[0]?.id;
    const built = variant ? fromDemoVariant(raw, variant, ctx) : null;
    return built ? { ok: true, ...built, hit } : { ok: false, reason: "unknown" };
  }

  const flat3d = hit.apartment.sources.flat3d;
  if (!flat3d || baseVariant) return { ok: false, reason: "unknown" };
  const base = loadFlat3d();
  if (base.apartment.id !== flat3d) return { ok: false, reason: "unknown" };
  if (base.catalogue.currency !== hit.partner.currency) {
    throw new Error(`валюта каталога ${base.catalogue.currency} ≠ валюте застройщика ${hit.partner.currency}`);
  }
  return {
    ok: true,
    apartment: { ...base.apartment, basePrice: hit.apartment.price, developerId: hit.partner.id },
    catalogue: { ...base.catalogue, developerId: hit.partner.id },
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
  const ctx = { apartmentId: hit.apartment.id, partnerId: hit.partner.id, currency: hit.partner.currency, basePrice: hit.apartment.price };
  const built = fromDemoVariant(data, c.payload.baseVariant, ctx);
  return built ? { ok: true, ...built, hit } : { ok: false, reason: "unknown" };
}
