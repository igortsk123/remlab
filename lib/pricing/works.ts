// Нормативы стоимости работ (вход Б). Медианы масс-рынка Москвы (₽/ед.) + региональные
// коэффициенты. Источники (веб-ресёрч 2026-07-11): profi.ru (медианы частных мастеров),
// titanremont/letoremont (прайсы под ключ), banki.ru/cian (обзоры), realty.yandex (журнал).
// Региональный коэф. 0.6–0.8 к Москве (регионы дешевле в РАБОТАХ на 20–30%; материалы
// федеральные, к ним k не применяется). Полный провенанс — domain/pricing-works-ru.md.

export type Depth = "refresh" | "update" | "capital";
export type Region = "msk" | "spb" | "million" | "mid" | "small" | "far";

// Медианы работ Москвы, ₽ за единицу (масс-рынок; наш юзер — эконом/DIY, не премиум-компании).
const WORK_RATES_MSK = {
  gruntovka: { unit: "м²", rub: 100 },
  shpaklevka: { unit: "м²", rub: 550 },
  pokraska: { unit: "м²", rub: 300 },
  oboi_rabota: { unit: "м²", rub: 400 },
  plitka_rabota: { unit: "м²", rub: 1200 },
  styazhka: { unit: "м²", rub: 850 },
  laminat_rabota: { unit: "м²", rub: 450 },
  demontazh: { unit: "м²", rub: 300 },
} as const;

// Материалы, ₽ за м² (федеральные — маркетплейсы ~едины, k не применяется).
const MATERIAL_RATES = {
  gruntovka: { rub: 40 },
  shpaklevka: { rub: 130 },
  kraska: { rub: 180 },
  oboi: { rub: 350 },
  laminat: { rub: 800 },
} as const;

// Коэффициент к Москве по группе региона (к работам). Юзер уточняет регион на входе Б.
export const REGION_K: Record<Region, number> = {
  msk: 1.0,       // Москва
  spb: 0.88,      // Санкт-Петербург
  million: 0.70,  // город-миллионник (Екб, Новосиб, Казань, Краснодар…)
  mid: 0.62,      // средний город (100–500 тыс.)
  small: 0.55,    // малый город
  far: 0.95,      // Дальний Восток / Крайний Север (дорогая логистика)
};

export const REGION_LABEL: Record<Region, string> = {
  msk: "Москва",
  spb: "Санкт-Петербург",
  million: "Город-миллионник",
  mid: "Средний город",
  small: "Малый город / посёлок",
  far: "Дальний Восток / Север",
};

export type BudgetLine = { title: string; kind: "work" | "material"; rub: number };
export type BudgetVariant = { key: "eco" | "mid" | "high"; label: string; worksRub: number; materialsRub: number; totalRub: number; lines: BudgetLine[] };

const round = (n: number) => Math.round(n / 100) * 100;

export function estimateRemont(areaM2: number, depth: Depth, region: Region = "msk"): { eco: BudgetVariant; mid: BudgetVariant; high: BudgetVariant } {
  const k = REGION_K[region];
  const wallArea = areaM2 * 2.7; // грубо: площадь стен ≈ пол × 2.7
  const floor = areaM2;

  function variant(key: BudgetVariant["key"], label: string, opts: { qualityMul: number; worksMul: number }): BudgetVariant {
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
    w("Покраска / поклейка обоев", WORK_RATES_MSK.pokraska, wallArea);
    m("Отделка стен (материал)", MATERIAL_RATES.kraska, wallArea);
    if (depth === "capital") {
      w("Пол: стяжка и укладка", WORK_RATES_MSK.laminat_rabota, floor);
      m("Напольное покрытие", MATERIAL_RATES.laminat, floor);
    }

    const worksRub = lines.filter((l) => l.kind === "work").reduce((s, l) => s + l.rub, 0);
    const materialsRub = lines.filter((l) => l.kind === "material").reduce((s, l) => s + l.rub, 0);
    return { key, label, worksRub, materialsRub, totalRub: worksRub + materialsRub, lines };
  }

  return {
    eco: variant("eco", "Эконом", { qualityMul: 0.7, worksMul: 0.85 }),
    mid: variant("mid", "Средний", { qualityMul: 1.0, worksMul: 1.0 }),
    high: variant("high", "Получше", { qualityMul: 1.6, worksMul: 1.25 }),
  };
}

// Ставка работы для региона (для будущих детальных смет; используется входом Б через estimateRemont).
export function rateFor(work: keyof typeof WORK_RATES_MSK, region: Region = "msk"): number {
  return Math.round(WORK_RATES_MSK[work].rub * REGION_K[region]);
}

export const DEPTH_LABEL: Record<Depth, string> = {
  refresh: "Освежить (косметика, стены)",
  update: "Обновить (стены + грунт)",
  capital: "Капитально (стены + пол + подготовка)",
};
