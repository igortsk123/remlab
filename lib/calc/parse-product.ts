// Полный парс карточки товара (link-fetch-max): детерминированный слой (regex + OG + JSON-LD) →
// ИИ-дочитка ВСЕХ оставшихся пустых полей вида одним вызовом (аккуратный JSON-экстракт).
// Вызывается из роута parse-link после серверной добычи HTML (fetch-page).

import type { CalcKind, MaterialSpec } from "@/contracts/calc";
import { deriveLaminateM2Price, parseProductHtml, type ParsedProduct } from "@/lib/calc/link-parse";
import { buildLlmInput, extractJsonLd, jsonLdProduct } from "@/lib/calc/link-content";
import { AI_FIELD_KEYS, aiExtractSpec } from "@/lib/calc/link-parse-ai";

// Ценовые поля одного вида — взаимозаменяемые единицы: нашлась цена в одной → остальные не спрашиваем.
const PRICE_GROUPS: Record<CalcKind, (keyof MaterialSpec)[]> = {
  oboi: ["pricePerRollRub"],
  plitka: ["pricePerM2Rub", "pricePerPieceRub", "pricePerPackRub"],
  kraska: ["pricePerPackRub"],
  laminat: ["pricePerM2Rub", "pricePerPackRub"],
};

// Цена из JSON-LD — за товарную единицу (рулон/упаковка), единица не указана → как meta-фолбэк
// в extractPrice: обоям — за рулон, остальным — за упаковку. Только если цены ещё нет.
function applyJsonLdPrice(spec: Partial<MaterialSpec>, kind: CalcKind, priceRub: number): void {
  if (PRICE_GROUPS[kind].some((k) => spec[k] != null)) return;
  if (kind === "oboi") spec.pricePerRollRub = priceRub;
  else spec.pricePerPackRub = priceRub;
}

export function missingAiFields(spec: Partial<MaterialSpec>, kind: CalcKind): (keyof MaterialSpec)[] {
  const priceFound = PRICE_GROUPS[kind].some((k) => spec[k] != null);
  return AI_FIELD_KEYS[kind].filter((k) => spec[k] == null && !(priceFound && PRICE_GROUPS[kind].includes(k)));
}

export async function parseProductFull(html: string, kind: CalcKind): Promise<ParsedProduct> {
  const result = parseProductHtml(html, kind);

  const ld = jsonLdProduct(extractJsonLd(html));
  if (ld.title && !result.title) result.title = ld.title;
  if (ld.priceRub != null) {
    applyJsonLdPrice(result.spec, kind, ld.priceRub);
    if (result.priceRub == null) result.priceRub = ld.priceRub;
  }

  const missing = missingAiFields(result.spec, kind);
  if (missing.length > 0 && !process.env.OPENAI_API_KEY) {
    console.error("[parse-product] OPENAI_API_KEY не задан — ИИ-дочитка пропущена, поля:", missing.join(","));
  }
  if (missing.length > 0 && process.env.OPENAI_API_KEY) {
    const aiSpec = await aiExtractSpec(buildLlmInput(html), kind, missing);
    const target = result.spec as Record<string, number>;
    for (const [k, v] of Object.entries(aiSpec)) {
      if (result.spec[k as keyof MaterialSpec] == null && typeof v === "number") target[k] = v;
    }
  }
  // Размеры/шт-упак или цена упаковки могли дочитаться → вывести цену за м², если её всё ещё нет.
  if (kind === "laminat") deriveLaminateM2Price(result.spec);
  return result;
}
