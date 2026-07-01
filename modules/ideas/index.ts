// Идеи изменений (LLM) + превью товаров и материалов (seed-каталог) + грубый диапазон бюджета.
// Каталог здесь — заглушка (реальные источники/цены — отдельный план, решение владельца).

import { getVisionProvider } from "@/lib/providers";
import { z } from "zod";
import type { Analysis, Brief, Idea, CatalogItem, BudgetRange } from "@/contracts/project";

const ideasSchema = z.object({ ideas: z.array(z.object({ title: z.string(), detail: z.string() })).max(6) });

const FALLBACK_IDEAS: Idea[] = [
  { title: "Тёплый текстиль", detail: "Ковёр, плотные шторы и пара подушек в природной палитре." },
  { title: "Сценарный свет", detail: "Торшер и настольная лампа тёплого спектра вместо верхнего света." },
  { title: "Зелень и декор", detail: "1–2 крупных растения и минималистичный декор на открытых полках." },
  { title: "Акцентная зона", detail: "Постер или панно над диваном, чтобы задать характер." },
];

export async function generateIdeas(analysis: Analysis, brief: Partial<Brief>): Promise<Idea[]> {
  const prompt = [
    "Дай 4–5 конкретных идей, как обновить комнату, недорого и с максимальным визуальным эффектом.",
    `Комната: ${brief.roomType ?? "жилая"}. Что заметил ИИ: ${analysis.summary}`,
    'Верни СТРОГО JSON: {"ideas":[{"title":"...","detail":"одно предложение"}]}',
  ].join("\n");
  const r = await getVisionProvider().generateText(prompt);
  if (!r.ok) return FALLBACK_IDEAS;
  const start = r.value.indexOf("{");
  const end = r.value.lastIndexOf("}");
  if (start < 0 || end < 0) return FALLBACK_IDEAS;
  try {
    const parsed = ideasSchema.parse(JSON.parse(r.value.slice(start, end + 1)));
    return parsed.ideas.length ? parsed.ideas : FALLBACK_IDEAS;
  } catch {
    return FALLBACK_IDEAS;
  }
}

// Seed-витрина: товары (мебель/декор/свет/текстиль) И материалы (краска/обои/покрытие).
// Первые FREE_VISIBLE видны бесплатно, остальные заблокированы до оплаты.
const FREE_VISIBLE = 3;

const SEED: Omit<CatalogItem, "locked">[] = [
  { kind: "product", category: "Свет", title: "Торшер с тёплым светом", priceRub: 6900 },
  { kind: "product", category: "Текстиль", title: "Ковёр 160×230, шерсть", priceRub: 12500 },
  { kind: "material", category: "Краска", title: "Матовая краска, greige, 2.5 л", priceRub: 3200 },
  { kind: "product", category: "Декор", title: "Постер в раме A2", priceRub: 2400 },
  { kind: "material", category: "Обои", title: "Флизелиновые, акцентная стена", priceRub: 4100 },
  { kind: "product", category: "Растения", title: "Фикус лировидный в кашпо", priceRub: 5400 },
  { kind: "product", category: "Хранение", title: "Открытый стеллаж, дуб", priceRub: 14900 },
  { kind: "material", category: "Пол", title: "Ламинат, светлый дуб, м²", priceRub: 1350 },
];

export function buildCatalog(): CatalogItem[] {
  return SEED.map((it, i) => ({ ...it, locked: i >= FREE_VISIBLE }));
}

const BAND_RANGE: Record<string, [number, number]> = {
  u30: [12000, 30000], "30_70": [30000, 70000], "70_150": [70000, 150000],
  "150_300": [150000, 300000], "300p": [300000, 500000], unknown: [30000, 120000],
};

export function estimateBudget(brief: Partial<Brief>): BudgetRange {
  const [min, max] = BAND_RANGE[brief.budgetBand ?? "unknown"] ?? BAND_RANGE.unknown!;
  const confidence = brief.budgetBand && brief.budgetBand !== "unknown" ? "medium" : "low";
  return { minRub: min, maxRub: max, confidence };
}
