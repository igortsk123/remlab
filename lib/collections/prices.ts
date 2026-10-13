// Товары витрины для коллекций (план b2b-05, ADR-0264): явный индекс sid → карточка из последнего
// опубликованного demo-data.json квартиры. Им сервер (1) проверяет товары при сохранении и подставляет
// название/ссылку/магазин/цену САМ — клиенту не верим (разбор Codex 13.10: иначе подмена ссылки магазина);
// (2) отдаёт ТЕКУЩИЕ цены при открытии. Витрина не загрузилась — «временно недоступно», а не «снято».

import type { CurrentPrice } from "@/contracts/collection";

export type ShowcaseSku = { sid: string; msid?: string; name: string; url?: string; shop?: string; price: number; priceAt: string | null; pack?: number };

/** sid → карточка по всем местам витрины (варианты, ленты замен, комплекты). Первая запись побеждает. */
export function priceIndex(raw: unknown): Map<string, ShowcaseSku> {
  const out = new Map<string, ShowcaseSku>();
  const walk = (x: unknown): void => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (!x || typeof x !== "object") return;
    const o = x as Record<string, unknown>;
    if (typeof o.sid === "string" && typeof o.price === "number" && o.price > 0 && typeof o.name === "string" && !out.has(o.sid)) {
      out.set(o.sid, {
        sid: o.sid, name: o.name, price: o.price,
        priceAt: typeof o.price_at === "string" ? o.price_at : null,
        ...(typeof o.msid === "string" ? { msid: o.msid } : {}),
        ...(typeof o.url === "string" && /^https?:\/\//.test(o.url) ? { url: o.url } : {}),
        ...(typeof o.shop === "string" ? { shop: o.shop } : {}),
        ...(typeof o.pack === "number" && o.pack > 0 ? { pack: Math.round(o.pack) } : {}),
      });
    }
    Object.values(o).forEach(walk);
  };
  walk(raw);
  return out;
}

export function currentPrices(sids: string[], idx: Map<string, ShowcaseSku> | null): Record<string, CurrentPrice> {
  const out: Record<string, CurrentPrice> = {};
  for (const sid of sids) {
    const e = idx?.get(sid);
    out[sid] = !idx ? { price: null, priceAt: null, unavailable: false, temporarilyUnavailable: true }
      : e ? { price: e.price, priceAt: e.priceAt, unavailable: false, name: e.name, url: e.url ?? null, shop: e.shop ?? null }
      : { price: null, priceAt: null, unavailable: true };
  }
  return out;
}
