// Нормативы стоимости работ (вход Б). ⚠️ ПЛЕЙСХОЛДЕР — точные медианы Москвы и региональные
// коэффициенты придут из плана `pricing-db-ru` (веб-ресёрч). Интерфейс стабилен, наполнение — позже.
// source: placeholder — числа грубые, только чтобы вилка была правдоподобной.

export type Depth = "refresh" | "update" | "capital";
export type RegionK = number; // множитель к Москве (Москва = 1.0)

// Грубые медианы Москвы, ₽ за единицу (плейсхолдер).
const WORK_RATES_MSK = {
  demontazh: { unit: "м²", rub: 250 },
  gruntovka: { unit: "м²", rub: 90 },
  shpaklevka: { unit: "м²", rub: 450 },
  pokraska: { unit: "м²", rub: 350 },
  oboi_rabota: { unit: "м²", rub: 400 },
  plitka_rabota: { unit: "м²", rub: 1300 },
  styazhka: { unit: "м²", rub: 700 },
  laminat_rabota: { unit: "м²", rub: 500 },
  potolok: { unit: "м²", rub: 600 },
} as const;

// Материалы, ₽ за единицу (плейсхолдер; федеральные — маркетплейсы ~едины).
const MATERIAL_RATES = {
  gruntovka: { unit: "м²", rub: 40 },
  shpaklevka: { unit: "м²", rub: 120 },
  kraska: { unit: "м²", rub: 150 },
  oboi: { unit: "м²", rub: 300 },
  plitka: { unit: "м²", rub: 900 },
  laminat: { unit: "м²", rub: 800 },
} as const;

export type BudgetLine = { title: string; kind: "work" | "material"; rub: number };
export type BudgetVariant = { key: "eco" | "mid" | "high"; label: string; worksRub: number; materialsRub: number; totalRub: number; lines: BudgetLine[] };

// Состав по глубине ремонта: доля площади стен/пола, участвующей в работах.
const round = (n: number) => Math.round(n / 100) * 100;

export function estimateRemont(areaM2: number, depth: Depth, k: RegionK = 1): { eco: BudgetVariant; mid: BudgetVariant; high: BudgetVariant } {
  const wallArea = areaM2 * 2.7; // грубо: стены ≈ пол × 2.7
  const floor = areaM2;

  function variant(key: BudgetVariant["key"], label: string, opts: { qualityMul: number; withPlitka?: boolean; worksMul: number }): BudgetVariant {
    const lines: BudgetLine[] = [];
    const w = (title: string, rate: { rub: number }, qty: number) =>
      lines.push({ title, kind: "work", rub: round(rate.rub * qty * k * opts.worksMul) });
    const m = (title: string, rate: { rub: number }, qty: number) =>
      lines.push({ title, kind: "material", rub: round(rate.rub * qty * opts.qualityMul) });

    if (depth !== "refresh") {
      w("Грунтовка стен", WORK_RATES_MSK.gruntovka, wallArea);
      m("Грунтовка (материал)", MATERIAL_RATES.gruntovka, wallArea);
    }
    if (depth === "capital") {
      w("Шпаклёвка стен", WORK_RATES_MSK.shpaklevka, wallArea);
      m("Шпаклёвка (материал)", MATERIAL_RATES.shpaklevka, wallArea);
    }
    w("Покраска/обои стен", WORK_RATES_MSK.pokraska, wallArea);
    m("Отделка стен (материал)", MATERIAL_RATES.kraska, wallArea);
    if (depth === "capital") {
      w("Пол (стяжка/ламинат)", WORK_RATES_MSK.laminat_rabota, floor);
      m("Напольное покрытие", MATERIAL_RATES.laminat, floor);
    }

    const worksRub = lines.filter((l) => l.kind === "work").reduce((s, l) => s + l.rub, 0);
    const materialsRub = lines.filter((l) => l.kind === "material").reduce((s, l) => s + l.rub, 0);
    return { key, label, worksRub, materialsRub, totalRub: worksRub + materialsRub, lines };
  }

  return {
    eco: variant("eco", "Эконом", { qualityMul: 0.7, worksMul: 0.85 }),
    mid: variant("mid", "Средний", { qualityMul: 1.0, worksMul: 1.0 }),
    high: variant("high", "Получше", { qualityMul: 1.6, worksMul: 1.2 }),
  };
}

export const DEPTH_LABEL: Record<Depth, string> = {
  refresh: "Освежить (косметика, стены)",
  update: "Обновить (стены + грунт)",
  capital: "Капитально (стены + пол + подготовка)",
};
