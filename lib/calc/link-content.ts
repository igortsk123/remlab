// Очистка HTML карточки товара для LLM (link-fetch-max): из мегабайтной страницы собираем
// компактный вход — JSON-LD Product (структурированные данные магазина, вырезались бы вместе со
// <script>) + заголовок + окно текста вокруг «Характеристики» + начало страницы.

import { htmlToText } from "@/lib/calc/link-parse";

const LD_BLOCK_CAP = 6000; // один JSON-LD блок в LLM-входе
const HEAD_CAP = 4000; // начало страницы: заголовок/цена почти всегда тут
const SPECS_WINDOW = 9000; // окно вокруг «Характеристики»
export const LLM_INPUT_CAP = 16_000;

// <script type="application/ld+json"> с товарными данными (Product/offers). До 3 блоков.
export function extractJsonLd(html: string): string[] {
  const out: string[] = [];
  const re = /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const m of html.matchAll(re)) {
    const body = (m[1] ?? "").trim();
    if (!/["']@type["']\s*:\s*["'][^"']*Product|["']offers["']/i.test(body)) continue;
    out.push(body.length > LD_BLOCK_CAP ? body.slice(0, LD_BLOCK_CAP) : body);
    if (out.length >= 3) break;
  }
  return out;
}

// Детерминированные title/цена из JSON-LD Product (надёжнее OG-меты: это машинные данные).
export function jsonLdProduct(blocks: string[]): { title?: string; priceRub?: number } {
  for (const block of blocks) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(block);
    } catch {
      continue; // обрезанный/битый блок — не страшно, он всё равно уйдёт в LLM текстом
    }
    const nodes: unknown[] = Array.isArray(parsed) ? parsed : [parsed];
    for (const node of nodes) {
      if (!node || typeof node !== "object") continue;
      const obj = node as Record<string, unknown>;
      const type = String(obj["@type"] ?? "");
      if (!/product/i.test(type)) continue;
      const title = typeof obj.name === "string" && obj.name.trim() ? obj.name.trim() : undefined;
      const offers = obj.offers;
      const offer = (Array.isArray(offers) ? offers[0] : offers) as Record<string, unknown> | undefined;
      const raw = offer?.price ?? offer?.lowPrice;
      const price = typeof raw === "number" ? raw : typeof raw === "string" ? parseFloat(raw.replace(",", ".")) : NaN;
      const priceRub = Number.isFinite(price) && price > 0 && price <= 10_000_000 ? price : undefined;
      if (title || priceRub) return { title, priceRub };
    }
  }
  return {};
}

// Релевантный текст: начало страницы + окно вокруг первого «Характеристик…» (там таблица
// параметров). На коротких страницах — просто начало. Итог ≤ maxLen.
export function relevantText(html: string, maxLen = LLM_INPUT_CAP): string {
  const text = htmlToText(html).trim();
  if (text.length <= maxLen) return text;
  const idx = text.search(/характеристик/i);
  if (idx < 0 || idx < HEAD_CAP) return text.slice(0, maxLen);
  const head = text.slice(0, HEAD_CAP);
  const window = text.slice(Math.max(0, idx - 500), idx + SPECS_WINDOW);
  return `${head}\n…\n${window}`.slice(0, maxLen);
}

// Единый вход LLM: структурированные данные вперёд, затем релевантный текст.
export function buildLlmInput(html: string): string {
  const ld = extractJsonLd(html);
  const ldPart = ld.length ? `Структурированные данные (JSON-LD):\n${ld.join("\n")}\n\n` : "";
  const budget = Math.max(4000, LLM_INPUT_CAP - ldPart.length);
  return `${ldPart}Текст страницы:\n${relevantText(html, budget)}`;
}
