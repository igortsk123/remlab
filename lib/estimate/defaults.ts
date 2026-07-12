// Умные дефолты и таблицы для калькулятора v2 (К2). Используются формулами и формой параметров.

export const SURFACE_TYPES = ["Штукатурка", "Шпаклёвка", "Дерево", "Металл", "Другое"] as const;

// Расход краски, м²/л на 1 слой (типовой ориентир; редактируется).
export const PAINT_CONSUMPTION: Record<string, number> = {
  Водоэмульсионная: 10,
  Акриловая: 11,
  Латексная: 12,
  Алкидная: 13,
  Масляная: 14,
};
export const PAINT_TYPES = Object.keys(PAINT_CONSUMPTION);

export const ROW_OFFSET_LABEL: Record<"random" | "half" | "third", string> = {
  random: "Произвольно",
  half: "1/2",
  third: "1/3",
};

export const DIRECTION_LABEL: Record<"length" | "width" | "diag45" | "diag135", string> = {
  length: "По длине",
  width: "По ширине",
  diag45: "Диагональ 45°",
  diag135: "Диагональ 135°",
};

// Дефолты, подставляемые при пустых полях.
export const DEF = {
  rollWidthM: 0.53,
  rollLengthM: 10.05,
  seamMm: 3,
  paintConsumption: 10,
  coats: 2,
  wallGapMm: 10,
  tileCutReserve: 0.1, // прямая укладка
  laminateReserve: 0.05,
  laminateDiagExtra: 0.1, // диагональ +10%
  packAreaLaminate: 2.13,
} as const;
