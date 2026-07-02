// Оценка стоимости шага (ориентир, НЕ биллинг). Цены — из access-and-integrations (2026).
// Обновлять при смене моделей/тарифов вместе с реестром пайплайна.

const IMAGE_USD: Record<string, number> = {
  "gemini-3.1-flash-image": 0.067, // ~1K px
};

// $/Mtok (вход/выход), очень грубо; flash-модели дёшевы — не лимитирующий фактор.
const TEXT_USD: Record<string, { in: number; out: number }> = {
  "gemini-flash-latest": { in: 0.1, out: 0.4 },
};

export function estimateImageCost(model: string): number {
  return IMAGE_USD[model] ?? 0.06;
}

export function estimateTextCost(model: string, inputChars: number, outputChars: number): number {
  const price = TEXT_USD[model] ?? { in: 0.1, out: 0.4 };
  const inTok = inputChars / 4; // ~4 символа на токен
  const outTok = outputChars / 4;
  return (inTok / 1e6) * price.in + (outTok / 1e6) * price.out;
}
