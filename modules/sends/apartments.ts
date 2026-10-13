// Какие квартиры может отправить менеджер партнёра (план b2b-02) — из реестра застройщиков
// (`lib/partners/registry.ts`, план b2b-06). Неизвестная квартира — отказ, не умолчание.

import { apartmentCard, findApartment as findHit, findPartner } from "@/lib/partners/registry";

export type ApartmentRef = { id: string; title: string; lang: "ru" | "en"; market: "ru" | "uk" };

export function apartmentsOf(partnerId: string): ApartmentRef[] {
  const p = findPartner(partnerId);
  return p ? p.apartments.map((a) => findApartmentRef(a.id)!).filter(Boolean) : [];
}

export function findApartment(partnerId: string, id: string): ApartmentRef | null {
  const ref = findApartmentRef(id);
  return ref && findHit(id)?.partner.id === partnerId ? ref : null;
}

function findApartmentRef(id: string): ApartmentRef | null {
  const hit = findHit(id);
  if (!hit) return null;
  const card = apartmentCard(hit);
  return { id, title: card.kind, lang: hit.partner.defaultLang, market: hit.partner.market };
}

/** Ссылка покупателю. Демо-страница читает `?s=` и подставляет карточку менеджера. */
export function sendUrl(sendId: string, base = process.env.APP_URL || "https://remont-lab.online"): string {
  return `${base.replace(/\/$/, "")}/demo/?s=${sendId}`;
}
