// Формулы расчёта материалов (вход А). Чистые функции — покрыты golden-тестом (механика sub-e6).
// Возвращают количество + единицу + человекочитаемое пояснение с запасом.

export type CalcResult = { qty: number; unit: string; note: string };

const round1 = (n: number) => Math.round(n * 10) / 10;

// Обои: стандартный рулон 0.53×10.05 м. Полос из рулона с учётом подгонки рисунка (rapport),
// полос нужно по периметру, минус проёмы грубо не вычитаем (это и есть запас).
export function wallpaper(input: {
  perimeterM: number;
  heightM: number;
  rollWidthM?: number;
  rollLengthM?: number;
  rapportM?: number;
}): CalcResult {
  const rollW = input.rollWidthM ?? 0.53;
  const rollL = input.rollLengthM ?? 10.05;
  const rapport = input.rapportM ?? 0;
  const stripLen = input.heightM + rapport + 0.1; // +10 см на подрезку сверху/снизу
  const stripsPerRoll = Math.max(1, Math.floor(rollL / stripLen));
  const stripsNeeded = Math.ceil(input.perimeterM / rollW);
  const rolls = Math.ceil(stripsNeeded / stripsPerRoll);
  return {
    qty: rolls,
    unit: "рулон",
    note: `${stripsNeeded} полос по ${round1(stripLen)} м, ${stripsPerRoll} из рулона${rapport ? " (с подгонкой рисунка)" : ""}. Проёмы не вычитали — это запас.`,
  };
}

// Плитка: площадь + подрезка. reserve — доля запаса (прямая укладка 10%, диагональ 15%).
export function tile(input: { areaM2: number; reserve?: number }): CalcResult {
  const reserve = input.reserve ?? 0.1;
  const qty = round1(input.areaM2 * (1 + reserve));
  return { qty, unit: "м²", note: `${input.areaM2} м² + ${Math.round(reserve * 100)}% на подрезку и бой.` };
}

// Краска: площадь стен × слои / укрывистость (м²/л на 1 слой, дефолт 10).
export function paint(input: { areaM2: number; coats?: number; coveragePerL?: number }): CalcResult {
  const coats = input.coats ?? 2;
  const coverage = input.coveragePerL ?? 10;
  const liters = round1((input.areaM2 * coats) / coverage);
  return { qty: liters, unit: "л", note: `${input.areaM2} м² × ${coats} слоя ÷ ${coverage} м²/л.` };
}

// Ламинат: площадь пола + подрезка 5%, переводим в упаковки (дефолт 2.13 м²/упаковка).
export function laminate(input: { areaM2: number; packAreaM2?: number; reserve?: number }): CalcResult {
  const packArea = input.packAreaM2 ?? 2.13;
  const reserve = input.reserve ?? 0.05;
  const withReserve = input.areaM2 * (1 + reserve);
  const packs = Math.ceil(withReserve / packArea);
  return {
    qty: packs,
    unit: "упаковка",
    note: `${input.areaM2} м² + ${Math.round(reserve * 100)}% ÷ ${packArea} м²/упак = ${round1(withReserve)} м².`,
  };
}

// Периметр прямоугольной комнаты по двум сторонам.
export function perimeter(widthM: number, lengthM: number): number {
  return 2 * (widthM + lengthM);
}
// Площадь стен = периметр × высота (для краски/обоев).
export function wallArea(widthM: number, lengthM: number, heightM: number): number {
  return round1(perimeter(widthM, lengthM) * heightM);
}
