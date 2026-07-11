import { describe, it, expect } from "vitest";
import { wallpaper, tile, paint, laminate, perimeter, wallArea } from "@/lib/estimate/calc";

// Golden-набор формул смет (механика sub-e6): эталонные комнаты → правильные количества.
// Меняешь формулу — этот тест ловит регрессию расчётов.
describe("estimate calc (golden)", () => {
  it("периметр и площадь стен", () => {
    expect(perimeter(3, 4)).toBe(14);
    expect(wallArea(3, 4, 2.7)).toBeCloseTo(37.8, 1);
  });

  it("обои: комната 3.5×4, высота 2.7 → рулоны с запасом", () => {
    const r = wallpaper({ perimeterM: perimeter(3.5, 4), heightM: 2.7 });
    // периметр 15 м / 0.53 = 29 полос; рулон 10.05/(2.7+0.1)=3 полосы; 29/3 = 10 рулонов
    expect(r.unit).toBe("рулон");
    expect(r.qty).toBe(10);
  });

  it("плитка: 12 м² + 10% подрезка", () => {
    const r = tile({ areaM2: 12 });
    expect(r.qty).toBeCloseTo(13.2, 1);
    expect(r.unit).toBe("м²");
  });

  it("плитка: диагональная укладка — запас 15%", () => {
    expect(tile({ areaM2: 10, reserve: 0.15 }).qty).toBeCloseTo(11.5, 1);
  });

  it("краска: 40 м² стен, 2 слоя, укрывистость 10 → 8 л", () => {
    expect(paint({ areaM2: 40 }).qty).toBe(8);
  });

  it("ламинат: 20 м² + 5% ÷ 2.13 → 10 упаковок", () => {
    const r = laminate({ areaM2: 20 });
    expect(r.unit).toBe("упаковка");
    expect(r.qty).toBe(10); // 21 м² / 2.13 = 9.86 → 10
  });

  it("нулевые размеры не роняют расчёт", () => {
    expect(wallpaper({ perimeterM: 0, heightM: 2.7 }).qty).toBe(0);
    expect(tile({ areaM2: 0 }).qty).toBe(0);
  });
});

// Нормативы работ + региональный коэффициент (pricing-db-ru).
import { estimateRemont, rateFor, REGION_K } from "@/lib/pricing/works";

describe("pricing works (регионы)", () => {
  it("регион дешевле Москвы (коэф 0.6–0.95)", () => {
    for (const k of Object.values(REGION_K)) {
      expect(k).toBeGreaterThanOrEqual(0.5);
      expect(k).toBeLessThanOrEqual(1.0);
    }
    expect(REGION_K.msk).toBe(1.0);
    expect(REGION_K.million).toBeLessThan(REGION_K.msk);
  });

  it("работы масштабируются коэффициентом, материалы — нет", () => {
    const msk = estimateRemont(20, "capital", "msk");
    const mil = estimateRemont(20, "capital", "million");
    // работы в миллионнике дешевле, материалы те же (федеральные)
    expect(mil.mid.worksRub).toBeLessThan(msk.mid.worksRub);
    expect(mil.mid.materialsRub).toBe(msk.mid.materialsRub);
  });

  it("вилка растёт eco < mid < high", () => {
    const v = estimateRemont(18, "capital", "msk");
    expect(v.eco.totalRub).toBeLessThan(v.mid.totalRub);
    expect(v.mid.totalRub).toBeLessThan(v.high.totalRub);
  });

  it("rateFor применяет региональный коэффициент к ставке Москвы", () => {
    expect(rateFor("plitka_rabota", "msk")).toBe(1200);
    expect(rateFor("plitka_rabota", "million")).toBe(840); // 1200 × 0.70
  });
});
