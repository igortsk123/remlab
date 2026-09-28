// Снимок цены подбора. Считаем ТОЛЬКО на сервере из разрешённой сцены: цена, пришедшая
// с клиента, ничего не значит (её можно поправить в браузере), а менеджеру нужна честная.

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue, Configuration } from "@/contracts/configurator";
import { resolveScene } from "@/lib/configurator/resolve";
import type { Quote, QuoteLine } from "@/lib/configurator/repo";

export function buildQuote(a: Apartment, c: Catalogue, config: Configuration): Quote {
  const scene = resolveScene(a, c, config);
  const lines: QuoteLine[] = [];
  const all = [
    ...scene.items.map((i) => ({ slotId: i.slotId, optionId: i.optionId, titleRu: i.titleRu, roomId: i.roomId, priceGbp: i.priceGbp })),
    ...scene.surfaces.map((s) => ({ slotId: s.slotId, optionId: s.optionId, titleRu: s.titleRu, roomId: s.roomId, priceGbp: s.priceGbp })),
  ];
  for (const l of all) if (l.priceGbp > 0) lines.push(l);
  lines.sort((x, y) => y.priceGbp - x.priceGbp);
  return {
    basePriceGbp: scene.totals.basePriceGbp,
    upgradesGbp: scene.totals.upgradesGbp,
    totalGbp: scene.totals.totalGbp,
    currency: "GBP",
    lines,
    computedAt: new Date().toISOString(),
  };
}

/** Отпечаток данных: по нему видно, из какой версии квартиры и каталога собран подбор. */
export function revisions(a: Apartment, c: Catalogue): { apartmentRevision: string; catalogueRevision: string } {
  return {
    apartmentRevision: `${a.id}:${a.rooms.length}r:${a.slots.length}s`,
    catalogueRevision: `${c.developerId}:${c.options.length}o:${c.materials.length}m`,
  };
}
