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
  // Текст со снятыми тегами — характеристики часто в таблице (значение в соседнем <td>).
  const bodyText = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  const spec: Partial<MaterialSpec> = {};

  const dim = /(\d{2,4})\s*[x×х]\s*(\d{2,4})/i.exec(text);
  if (dim) {
    const a = toNum(dim[1]);
    const b = toNum(dim[2]);
    if (kind === "plitka") { if (a) spec.tileLengthMm = a; if (b) spec.tileWidthMm = b; }
    if (kind === "laminat") { if (a) spec.panelLengthMm = a; if (b) spec.panelWidthMm = b; }
  }
  if (kind === "oboi") {
    // Размеры рулона в формате «ширина × длина м»: «1,06*10м», «0,53х10,05 м», «1.06 x 10 м».
    // Разделитель *|x|х|×, десятичная , или . , единица «м» после длины. Guard: ширина<2.5, длина 3..50.
    const roll = /(\d[.,]?\d*)\s*[*xх×]\s*(\d{1,2}[.,]?\d*)\s*м/i.exec(text);
    if (roll) {
      const w = toNum(roll[1]);
      const l = toNum(roll[2]);
      if (w != null && w > 0 && w < 2.5) spec.rollWidthM = w;
      if (l != null && l >= 3 && l <= 50) spec.rollLengthM = l;
    }
    // Фолбэк по словам, если формат «W×L» не сработал. (?![а-яёa-z]) вместо \b — \b не срабатывает
    // после кириллической «м» (кириллица не входит в \w в JS-regex).
    if (spec.rollWidthM == null) {
      const w = toNum(/ширин[аы][^0-9]{0,12}(\d[.,]?\d*)\s*(?:м|m)(?![а-яёa-z])/i.exec(text)?.[1]);
      if (w != null && w > 0 && w < 2.5) spec.rollWidthM = w;
    }
    if (spec.rollLengthM == null) {
      const l = toNum(/длин[аы][^0-9]{0,12}(\d{1,2}[.,]?\d*)\s*(?:м|m)(?![а-яёa-z])/i.exec(text)?.[1]);
      if (l != null && l >= 3 && l <= 50) spec.rollLengthM = l;
    }
    // Раппорт: «рапорт/раппорт … N см|мм|м» (напр. «Рапорт смещения рисунка: 64 см»). Ищем в body
    // со снятыми тегами; требуем ЧИСЛО (пустой лейбл «раппорт (см)» не матчим); в метры, guard 0<r<2.
    const rap = /рап+орт[^0-9]{0,40}(\d{1,3}(?:[.,]\d+)?)\s*(мм|см|м)(?![а-яёa-z])/i.exec(bodyText);
    const rapNum = toNum(rap?.[1]);
    const rapUnit = rap?.[2]?.toLowerCase();
    if (rapNum != null && rapUnit) {
      const m = rapUnit === "мм" ? rapNum / 1000 : rapUnit === "см" ? rapNum / 100 : rapNum;
      if (m > 0 && m < 2) spec.rapportM = m;
    }
  }
  if (priceRub != null) {
    if (kind === "oboi") spec.pricePerRollRub = priceRub;
    else spec.pricePerPackRub = priceRub;
  }
  return { title, priceRub, spec };
}
