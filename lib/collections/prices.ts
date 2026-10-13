// Текущие цены товаров коллекции — из живой витрины (план b2b-05, ADR-0254 п.6). Каталога на проде нет
// (он на DEV), витрина — то, что сейчас видит покупатель. Товара нет в витрине — `unavailable`.

import type { CurrentPrice } from "@/contracts/collection";

type Entry = { price: number; priceAt: string | null };

/** sid → цена/дата по всему demo-data.json (варианты, ленты замен, комплекты). */
export function priceIndex(raw: unknown): Map<string, Entry> {
  const out = new Map<string, Entry>();
  const walk = (x: unknown): void => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (!x || typeof x !== "object") return;
    const o = x as Record<string, unknown>;
    if (typeof o.sid === "string" && typeof o.price === "number" && o.price > 0 && !out.has(o.sid)) {
      out.set(o.sid, { price: o.price, priceAt: typeof o.price_at === "string" ? o.price_at : null });
    }
    Object.values(o).forEach(walk);
  };
  walk(raw);
  return out;
}

export function currentPrices(sids: string[], idx: Map<string, Entry> | null): Record<string, CurrentPrice> {
  const out: Record<string, CurrentPrice> = {};
  for (const sid of sids) {
    const e = idx?.get(sid);
    out[sid] = e ? { price: e.price, priceAt: e.priceAt, unavailable: false } : { price: null, priceAt: null, unavailable: !!idx };
  }
  return out;
}
