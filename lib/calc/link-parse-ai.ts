// ИИ-фолбэк извлечения характеристик товара (OpenAI ChatGPT). Зовём ТОЛЬКО когда детерминированный
// парсер (link-parse.ts) не нашёл ключевые поля. Правило: только реально найденное, без выдумывания/округления.

import type { CalcKind, MaterialSpec } from "@/contracts/calc";

type Field = { key: keyof MaterialSpec; desc: string };

// Поля по виду (в тех же единицах, что MaterialSpec) + человекочитаемое описание для промпта.
const FIELDS: Record<CalcKind, Field[]> = {
  oboi: [
    { key: "rollWidthM", desc: "ширина рулона в метрах (напр. 1.06 или 0.53)" },
    { key: "rollLengthM", desc: "длина рулона в метрах (напр. 10.05)" },
    { key: "rapportM", desc: "раппорт / повтор / смещение рисунка в метрах (64 см = 0.64)" },
    { key: "pricePerRollRub", desc: "цена за рулон в рублях" },
  ],
  plitka: [
    { key: "tileLengthMm", desc: "длина плитки в мм (20 см = 200)" },
    { key: "tileWidthMm", desc: "ширина плитки в мм" },
    { key: "tilesPerPack", desc: "штук в упаковке" },
    { key: "pricePerPackRub", desc: "цена за упаковку в рублях" },
  ],
  kraska: [
    { key: "packVolumeL", desc: "объём упаковки в литрах" },
    { key: "consumptionM2PerL", desc: "расход, м² на литр" },
    { key: "pricePerPackRub", desc: "цена за упаковку в рублях" },
  ],
  laminat: [
    { key: "panelLengthMm", desc: "длина панели в мм" },
    { key: "panelWidthMm", desc: "ширина панели в мм" },
    { key: "panelsPerPack", desc: "штук в упаковке" },
    { key: "pricePerPackRub", desc: "цена за упаковку в рублях" },
  ],
};

const OPENAI_URL = "https://api.openai.com/v1/chat/completions";

// Достаём из ответа ИИ только нужные ключи как положительные числа (валидация границы доверия).
function pick(parsed: unknown, fields: Field[]): Partial<MaterialSpec> {
  const out: Partial<MaterialSpec> = {};
  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    for (const f of fields) {
      const v = obj[f.key as string];
      if (typeof v === "number" && Number.isFinite(v) && v > 0) {
        (out as Record<string, number>)[f.key as string] = v;
      }
    }
  }
  return out;
}

// Возвращает только НЕДОСТАЮЩИЕ поля, найденные ИИ. Нет ключа/ошибка/таймаут → {} (тихо).
export async function aiExtractSpec(pageText: string, kind: CalcKind, needed: (keyof MaterialSpec)[]): Promise<Partial<MaterialSpec>> {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey || needed.length === 0) return {};
  const fields = FIELDS[kind].filter((f) => needed.includes(f.key));
  if (fields.length === 0) return {};

  const model = process.env.OPENAI_EXTRACT_MODEL || "gpt-4o-mini";
  const text = pageText.slice(0, 12000);
  const fieldList = fields.map((f) => `- ${String(f.key)}: ${f.desc}`).join("\n");
  const prompt =
    "Ты извлекаешь характеристики товара со страницы интернет-магазина. Верни СТРОГО JSON-объект с " +
    "перечисленными ключами. Значение бери ТОЛЬКО если оно ЯВНО указано на странице; если нет — null. " +
    "Ничего НЕ выдумывай и НЕ округляй. Числа — без единиц измерения, ровно в указанных единицах.\n\n" +
    `Ключи:\n${fieldList}\n\nТекст страницы:\n"""${text}"""`;

  try {
    const res = await fetch(OPENAI_URL, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model,
        temperature: 0,
        response_format: { type: "json_object" },
        messages: [{ role: "user", content: prompt }],
      }),
      signal: AbortSignal.timeout(12000),
    });
    if (!res.ok) return {};
    const data = await res.json();
    const raw = data?.choices?.[0]?.message?.content;
    if (typeof raw !== "string") return {};
    return pick(JSON.parse(raw), fields);
  } catch {
    return {};
  }
}

// Ключевые поля вида: если они пусты после детерминированного парса — есть смысл звать ИИ.
export const KEY_FIELDS: Record<CalcKind, (keyof MaterialSpec)[]> = {
  oboi: ["rollWidthM", "rollLengthM", "pricePerRollRub"],
  plitka: ["tileLengthMm", "tileWidthMm", "pricePerPackRub"],
  kraska: ["packVolumeL", "pricePerPackRub"],
  laminat: ["panelLengthMm", "panelWidthMm", "pricePerPackRub"],
};
