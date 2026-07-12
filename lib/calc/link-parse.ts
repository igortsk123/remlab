// Извлечение характеристик товара из HTML страницы (К4). Чистая функция (тест на фикстурах).
// OG-мета + эвристики размеров по виду. Ненадёжно для маркетплейсов с анти-ботом → деградация к ручному.

import type { CalcKind, MaterialSpec } from "@/contracts/calc";

export type ParsedProduct = { title?: string; priceRub?: number; spec: Partial<MaterialSpec> };

function toNum(s: string | undefined): number | undefined {
  if (!s) return undefined;
  const v = parseFloat(s.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(v) ? v : undefined;
}

function ogContent(html: string, prop: string): string | undefined {
  const a = new RegExp(`<meta[^>]+(?:property|name)=["']${prop}["'][^>]+content=["']([^"']*)["']`, "i").exec(html);
  if (a?.[1]) return a[1];
  const b = new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]+(?:property|name)=["']${prop}["']`, "i").exec(html);
  return b?.[1];
}

function titleTag(html: string): string | undefined {
  return /<title[^>]*>([^<]*)<\/title>/i.exec(html)?.[1]?.trim();
}

function priceFrom(html: string): number | undefined {
  return (
    toNum(ogContent(html, "product:price:amount")) ??
    toNum(ogContent(html, "og:price:amount")) ??
    toNum(/itemprop=["']price["'][^>]*content=["']([\d.,]+)["']/i.exec(html)?.[1]) ??
    toNum(/(\d[\d\s]{1,})\s*(?:₽|руб)/i.exec(html)?.[1])
  );
}

export function parseProductHtml(html: string, kind: CalcKind): ParsedProduct {
  const title = ogContent(html, "og:title") ?? titleTag(html);
  const priceRub = priceFrom(html);
  const text = `${title ?? ""} ${ogContent(html, "og:description") ?? ""}`;
  const spec: Partial<MaterialSpec> = {};

  const dim = /(\d{2,4})\s*[x×х]\s*(\d{2,4})/i.exec(text);
  if (dim) {
    const a = toNum(dim[1]);
    const b = toNum(dim[2]);
    if (kind === "plitka") { if (a) spec.tileLengthMm = a; if (b) spec.tileWidthMm = b; }
    if (kind === "laminat") { if (a) spec.panelLengthMm = a; if (b) spec.panelWidthMm = b; }
  }
  if (kind === "oboi") {
    const w = toNum(/ширин[аы][^0-9]{0,12}(\d[.,]?\d*)\s*(?:м|m)\b/i.exec(text)?.[1]);
    if (w && w < 2) spec.rollWidthM = w;
    const l = toNum(/длин[аы][^0-9]{0,12}(\d{1,2}[.,]?\d*)\s*(?:м|m)\b/i.exec(text)?.[1]);
    if (l && l > 3) spec.rollLengthM = l;
  }
  if (priceRub != null) {
    if (kind === "oboi") spec.pricePerRollRub = priceRub;
    else spec.pricePerPackRub = priceRub;
  }
  return { title, priceRub, spec };
}
