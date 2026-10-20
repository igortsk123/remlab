// Коллекция наружу (план b2b-05; пачкой — demo-19 А1): снимок без хеша секрета + ТЕКУЩИЕ цены из витрины её квартиры.
// Один сборщик для `GET /api/collections/[id]` и пачки `GET /api/collections?ids=…` — ответы одинаковые.

import type { CollectionOut } from "@/contracts/collection";
import { currentPrices, priceIndex, type ShowcaseSku } from "@/lib/collections/prices";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { findApartment } from "@/lib/partners/registry";
import type { StoredCollection } from "@/modules/collections/repository";

type Idx = Map<string, ShowcaseSku> | null;
export type IndexOf = (apartmentId: string) => Promise<Idx>;

/** Индексы витрин на один запрос: пачка коллекций одной квартиры читает её витрину один раз. */
export function showcaseIndexes(): IndexOf {
  const memo = new Map<string, Promise<Idx>>();
  return (apartmentId) => {
    let p = memo.get(apartmentId);
    if (!p) {
      const src = findApartment(apartmentId)?.apartment.sources.demoData;
      p = src ? loadDemoRaw(src).then(priceIndex) : Promise.resolve(null);
      memo.set(apartmentId, p);
    }
    return p;
  };
}

export async function collectionOut(row: StoredCollection, indexOf: IndexOf): Promise<CollectionOut> {
  const idx = await indexOf(row.payload.apartmentId);
  const sids = [...row.payload.items, ...row.payload.decor].map((i) => i.sku?.sid).filter((x): x is string => !!x);
  const { editHash: _secret, ...pub } = row.payload;      // хеш секрета редактирования наружу не уходит
  return { ...pub, id: row.id, partnerId: row.partnerId, createdAt: row.createdAt.toISOString(),
    expiresAt: new Date(row.createdAt.getTime() + 365 * 86_400_000).toISOString(),
    current: currentPrices([...new Set(sids)], idx && idx.size ? idx : null) };
}
