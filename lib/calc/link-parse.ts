// Извлечение характеристик товара из HTML страницы (К4). Чистая функция (тест на фикстурах).
// OG-мета + эвристики размеров/цены по виду. Ненадёжно для маркетплейсов с анти-ботом → деградация к ручному.

import type { CalcKind, MaterialSpec } from "@/contracts/calc";

export type PriceUnit = "m2" | "piece" | "pack";
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

// Размеры «AxB» → мм. Единица: явная «см/мм» или подсказка «(см)» из метки; без единицы —
// эвристика: оба ≥100 → уже мм (напр. «300x300»), иначе см (напр. «60x120» = 600×1200 мм,
// «7,4*15» = 74×150 мм). Разделитель x|×|х|*, десятичная , или . . Guard 10..3000 мм.
function dimsToMm(aStr: string | undefined, bStr: string | undefined, unit: string): { a: number; b: number } | undefined {
  const a0 = toNum(aStr);
  const b0 = toNum(bStr);
  if (a0 == null || b0 == null) return undefined;
  const mul = /^(см|cm)$/i.test(unit) ? 10 : /^(мм|mm)$/i.test(unit) ? 1 : a0 >= 100 && b0 >= 100 ? 1 : 10;
  const a = Math.round(a0 * mul);
  const b = Math.round(b0 * mul);
  if (a < 10 || b < 10 || a > 3000 || b > 3000) return undefined;
  return { a, b };
}

const NUM = "([0-9][0-9.,]*[0-9]|[0-9])";
const SEP = "[x×х*]";

// Размер: сначала по метке «Размер [(см)]: A×B [ед.]» из тела (надёжно для плиточных магазинов РФ),
// иначе первый «A×B [ед.]» из заголовка/описания. Пропускаем фильтр-СПИСКИ («Размер 10х10 10х20 …» —
// за размером сразу идёт ещё размер) и предпочитаем матч с явной единицей/пометкой «(см)».
function extractSize(text: string, bodyText: string): { a: number; b: number } | undefined {
  const labeledRe = new RegExp(`Размер[а-я]{0,2}\\s*(\\(\\s*см\\s*\\))?\\s*[:\\-]?\\s*${NUM}\\s*${SEP}\\s*${NUM}\\s*(см|cm|мм|mm)?`, "gi");
  const isListRe = new RegExp(`^\\s*${NUM}\\s*${SEP}\\s*${NUM}`);
  const hinted: { a: number; b: number }[] = [];
  const plain: { a: number; b: number }[] = [];
  for (const m of bodyText.matchAll(labeledRe)) {
    const after = bodyText.slice((m.index ?? 0) + m[0].length, (m.index ?? 0) + m[0].length + 14);
    if (isListRe.test(after)) continue; // за размером сразу другой размер → это список фильтра
    const hasUnit = !!(m[1] || m[4]);
    const r = dimsToMm(m[2], m[3], m[1] ? "см" : m[4] ?? "");
    if (r) (hasUnit ? hinted : plain).push(r);
  }
  if (hinted[0]) return hinted[0];
  if (plain[0]) return plain[0];
  const generic = new RegExp(`${NUM}\\s*${SEP}\\s*${NUM}\\s*(см|cm|мм|mm)?`, "i").exec(text);
  if (generic) {
    const r = dimsToMm(generic[1], generic[2], generic[3] ?? "");
    if (r) return r;
  }
  return undefined;
}

// Цена + единица. Ищем «<число> ₽|руб [/|за] <ед.>»; предпочитаем за м² (заголовочная цена плитки),
// затем за упаковку, затем за штуку. Фолбэк — цена из OG/itemprop-меты без единицы (считаем за упак.).
function extractPrice(text: string, html: string): { rub: number; unit: PriceUnit } | undefined {
  const re = /(\d[\d\s.,]*\d|\d)\s*(?:₽|руб)\.?\s*(?:\/|за\s*)?\s*(кв\.?\s*м|м²|м2|шт|упак\w*)?/gi;
  const hits: { rub: number; unit: PriceUnit; ranked: boolean }[] = [];
  for (const m of text.matchAll(re)) {
    const rub = toNum(m[1]);
    if (rub == null || rub <= 0) continue;
    const u = (m[2] ?? "").toLowerCase();
    const unit: PriceUnit = /кв|м²|м2/.test(u) ? "m2" : /шт/.test(u) ? "piece" : "pack";
    hits.push({ rub, unit, ranked: !!m[2] });
  }
  const byM2 = hits.find((h) => h.unit === "m2");
  const byPack = hits.find((h) => h.unit === "pack" && h.ranked);
  const byPiece = hits.find((h) => h.unit === "piece");
  const chosen = byM2 ?? byPack ?? byPiece ?? hits[0];
  if (chosen) return { rub: chosen.rub, unit: chosen.unit };

  const meta =
    toNum(ogContent(html, "product:price:amount")) ??
    toNum(ogContent(html, "og:price:amount")) ??
    toNum(/itemprop=["']price["'][^>]*content=["']([\d.,\s]+)["']/i.exec(html)?.[1]);
  return meta != null ? { rub: meta, unit: "pack" } : undefined;
}

export function parseProductHtml(html: string, kind: CalcKind): ParsedProduct {
  const title = ogContent(html, "og:title") ?? titleTag(html);
  const text = `${title ?? ""} ${ogContent(html, "og:description") ?? ""}`;
  // Текст со снятыми тегами — характеристики часто в таблице (значение в соседнем <td>).
  const bodyText = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  const spec: Partial<MaterialSpec> = {};

  if (kind === "plitka" || kind === "laminat") {
    const size = extractSize(text, bodyText);
    if (size) {
      if (kind === "plitka") { spec.tileLengthMm = size.a; spec.tileWidthMm = size.b; }
      else { spec.panelLengthMm = size.a; spec.panelWidthMm = size.b; }
    }
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

  const price = extractPrice(`${text} ${bodyText}`, html);
  if (price != null) {
    if (kind === "oboi") spec.pricePerRollRub = price.rub;
    else if (kind === "plitka") {
      if (price.unit === "m2") spec.pricePerM2Rub = price.rub;
      else if (price.unit === "piece") spec.pricePerPieceRub = price.rub;
      else spec.pricePerPackRub = price.rub;
    } else spec.pricePerPackRub = price.rub;
  }
  return { title, priceRub: price?.rub, spec };
}
