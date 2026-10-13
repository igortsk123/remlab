// Реестр застройщиков и квартир (план b2b-06, ADR-0258): JSON-файлы `data/partners/*.json`,
// проверка Zod при первом обращении — битые данные падают в тесте, а не у покупателя.
// Сертификат и подписи считаются ТОЛЬКО здесь: витрина, 3D и отчёт читают готовую карточку.

import { partner as partnerSchema, type ApartmentCard, type ApartmentRef, type Complex, type Lang, type Partner } from "@/contracts/partner";
import demoJson from "@/data/partners/demo.json";
import demoUkJson from "@/data/partners/demo-uk.json";

const RAW: unknown[] = [demoJson, demoUkJson];

let cached: Partner[] | null = null;

/** Все партнёры; повтор id квартиры между партнёрами — ошибка данных. */
export function partners(raw: unknown[] = RAW): Partner[] {
  if (cached && raw === RAW) return cached;
  const list = raw.map((p) => partnerSchema.parse(p));
  const seen = new Set<string>();
  for (const p of list) {
    for (const a of p.apartments) {
      if (seen.has(a.id)) throw new Error(`квартира ${a.id} описана дважды`);
      if (!p.complexes.some((c) => c.id === a.complexId)) throw new Error(`у квартиры ${a.id} нет ЖК ${a.complexId}`);
      seen.add(a.id);
    }
  }
  if (raw === RAW) cached = list;
  return list;
}

export type ApartmentHit = { partner: Partner; complex: Complex; apartment: ApartmentRef };

export function findApartment(id: string, list: Partner[] = partners()): ApartmentHit | null {
  for (const p of list) {
    const a = p.apartments.find((x) => x.id === id);
    if (a) return { partner: p, complex: p.complexes.find((c) => c.id === a.complexId)!, apartment: a };
  }
  return null;
}

export function findPartner(id: string, list: Partner[] = partners()): Partner | null {
  return list.find((p) => p.id === id) ?? null;
}

/** Предельная сумма сертификата: доля цены, округлённая ВНИЗ (₽ — до 10 000, £ — до 100): не обещаем больше доли. */
export function certificateAmount(p: Partner, a: ApartmentRef): number {
  const step = p.currency === "RUB" ? 10_000 : 100;
  return Math.floor((a.price * p.certificateShare) / step) * step;
}

export function money(n: number, currency: Partner["currency"], lang: Lang): string {
  const s = Math.round(n).toLocaleString(lang === "en" ? "en-GB" : "ru-RU").replace(/ /g, " ");
  return currency === "GBP" ? `£${s}` : `${s} ₽`;
}

export function handoverText(c: Complex, lang: Lang): string {
  const h = c.handover;
  if (h.status === "delivered") return lang === "en" ? "completed" : "дом сдан";
  if (!h.quarter) return lang === "en" ? "under construction" : "строится";
  const [y, q] = h.quarter.split("-Q");
  return lang === "en" ? `completion Q${q} ${y}` : `сдача ${q} кв. ${y}`;
}

export function apartmentCard(hit: ApartmentHit, lang: Lang = hit.partner.defaultLang): ApartmentCard {
  const { partner: p, complex: c, apartment: a } = hit;
  const en = lang === "en";
  const floor = a.floor && a.floorsTotal ? (en ? `floor ${a.floor} of ${a.floorsTotal}` : `эт. ${a.floor} из ${a.floorsTotal}`) : null;
  const bld = a.building ? (en ? `building ${a.building}` : `корп. ${a.building}`) : null;
  const complexName = en ? c.nameEn : c.nameRu;
  const amount = certificateAmount(p, a);
  return {
    id: a.id, partnerId: p.id, complexId: c.id, market: p.market, lang, currency: p.currency,
    kind: `${en ? a.kindEn : a.kindRu} ${String(a.areaM2).replace(".", en ? "." : ",")} ${en ? "m²" : "м²"}`,
    number: a.number ?? null,
    areaM2: a.areaM2,
    complex: complexName,
    handover: handoverText(c, lang),
    meta: [complexName, handoverText(c, lang), floor, bld].filter(Boolean).join(" · "),
    price: a.price,
    demoPrice: a.demoPrice,
    priceAsOf: a.priceAsOf ?? null,
    certificate: amount > 0
      ? {
          amount,
          title: en ? `Furniture and fit-out allowance up to ${money(amount, p.currency, lang)}` : `Сертификат на мебель и встраиваемое — до ${money(amount, p.currency, lang)}`,
          text: (en ? p.certificateTextEn : p.certificateTextRu) ?? (en
            ? "Choose any furniture and fit-out from the developer's partners for your new home."
            : "Выбирайте любую мебель и встраиваемое из набора партнёров застройщика для своей новой квартиры."),
        }
      : null,
    sources: a.sources,
  };
}
