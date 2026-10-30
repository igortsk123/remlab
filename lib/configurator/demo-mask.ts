// БРИТАНСКАЯ МАСКА АНГЛИЙСКОГО ДЕМО В /flat (demo-31, владелец 30.10): пока нет британских фидов, товары российской витрины
// на квартире-двойнике показываются по-английски (`name_en` сборки, `tools/scout/flat215_demo.py`), без магазина, цена × наценку.
// Те же правила, что у страницы демо (`tools/scout/flat215-demo/index.html`, блок DEMOMASK). Чистые функции.

import type { DemoMask } from "@/contracts/partner";

/** Роли витрины по-английски — словарь слоя перевода страницы (`index.html` → `ROLE`). */
export const ROLE_EN: Record<string, string> = {
  "диван": "sofa", "кресло": "armchair", "столик": "coffee table", "тв-тумба": "TV unit", "ковёр": "rug", "торшер": "floor lamp",
  "стеллаж": "shelving", "комод": "chest of drawers", "пуф": "pouf", "кашпо": "planter", "ваза": "vase", "стул": "chair", "стол": "table",
  "стол обеденный": "dining table", "банкетка": "bench", "витрина": "display cabinet", "камин": "fireplace", "стенка": "wall unit",
  "люстра": "chandelier", "лампа": "lamp", "подушка": "cushion", "шторы": "curtains", "плед": "throw", "покрывало": "bedspread",
  "полка": "shelf", "приставной": "side table", "декор": "decor",
};
/** Стили витрины по-английски (`index.html` → `STYLE`). */
export const STYLE_EN: Record<string, string> = {
  "сканди": "Scandi", "современный": "Modern", "минимализм": "Minimalist", "лофт": "Loft", "неоклассика": "Neoclassic", "джапанди": "Japandi",
};

const CYR = /[А-Яа-яЁё]/;
const cap = (t: string): string => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

/** «стул 2» → «chair»; неизвестная роль — «item» (кириллицы в английском показе нет). */
export function roleEn(role: string | undefined): string {
  const k = String(role ?? "").toLowerCase().replace(/\s+\d+$/, "").trim();
  return ROLE_EN[k] ?? (k && !CYR.test(k) ? k : "item");
}

/** «сканди» → «Scandi»; неизвестный стиль — пусто. */
export function styleEn(style: string | undefined): string {
  const k = String(style ?? "").toLowerCase().trim();
  return STYLE_EN[k] ?? (k && !CYR.test(k) ? cap(k) : "");
}

/** Название товара при маске: английское из сборки; нет или с кириллицей — нейтральное по роли («Sofa»). */
export function maskedName(sku: { name_en?: string } | undefined, role: string | undefined): string {
  const n = String(sku?.name_en ?? "").trim();
  return n && !CYR.test(n) ? n : cap(roleEn(role));
}

/** Курс показа с наценкой маски: множитель только у маски, без неё — курс как есть. */
export function maskedRate(rate: number, mask: Pick<DemoMask, "priceMarkup"> | null | undefined): number {
  return rate * (mask?.priceMarkup ?? 1);
}
