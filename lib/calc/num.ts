// Парсинг числовых полей форм калькулятора: строка → неотрицательное число; 0 показываем пустым.

export const strToNum = (s: string): number => {
  const v = parseFloat(s.replace(",", "."));
  return Number.isFinite(v) && v >= 0 ? v : 0;
};

export const numToStr = (n: number): string => (n === 0 ? "" : String(n));
