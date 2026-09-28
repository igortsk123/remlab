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

/**
 * Отпечаток данных: по нему через месяц видно, из какой версии квартиры и каталога собран
 * подбор. Считаем по СОДЕРЖИМОМУ (id + цена + ассет), а не по количеству записей: иначе смена
 * цены или материала при том же числе опций не меняла бы «ревизию» (находка verify 28.09).
 */
function fingerprint(parts: string[]): string {
  let h = 0x811c9dc5;
  for (const part of parts) {
    for (let i = 0; i < part.length; i += 1) {
      h ^= part.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
  }
  return h.toString(36);
}

export function revisions(a: Apartment, c: Catalogue): { apartmentRevision: string; catalogueRevision: string } {
  const apartmentParts = a.rooms
    .map((r) => `${r.id}:${r.x},${r.y},${r.w},${r.d}`)
    .concat(a.slots.map((s) => `${s.id}:${s.defaultOptionId}:${s.optionIds.join("|")}`));
  const catalogueParts = c.options
    .map((o) => `${o.id}:${o.tier}:${o.priceGbp}:${JSON.stringify(o.asset)}`)
    .concat(c.materials.map((m) => `${m.id}:${m.colorHex}:${m.tileCm.join("x")}`));
  return {
    apartmentRevision: `${a.id}:${a.rooms.length}r:${a.slots.length}s:${fingerprint(apartmentParts)}`,
    catalogueRevision: `${c.developerId}:${c.options.length}o:${c.materials.length}m:${fingerprint(catalogueParts)}`,
  };
}
