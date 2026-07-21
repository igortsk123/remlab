// Русские склонения по числу (славянское правило 1 / 2–4 / 5–20). Единый источник для UI.
// Тест — tests/unit/plural.test.ts.

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// Единицы калькулятора материалов: счётные склоняем, инвариантные (м²/л) отдаём как есть.
const UNIT_FORMS: Record<string, [string, string, string]> = {
  рулон: ["рулон", "рулона", "рулонов"],
  упаковка: ["упаковка", "упаковки", "упаковок"],
  шт: ["шт", "шт", "шт"],
};

export function pluralUnit(unit: string, n: number): string {
  const forms = UNIT_FORMS[unit];
  return forms ? plural(n, forms[0], forms[1], forms[2]) : unit;
}
