// Ширины нижних модулей кухни (план onb-09, T-20261105-18): ряд магазина 40/45/60/80 см вместо равных долей. Равные доли
// (~56 см у 2,8-метровой) не давали поставить мойку и варочную так, чтобы прошёл рабочий треугольник; модули разной ширины
// сдвигают их центры. ПОДБОР: все упорядоченные наборы из ряда с наибольшей достижимой суммой ≤ длины ряда (остаток < 40 —
// добор), для каждого — лучшая пара мойка/варочная (`scoreWorkPoints`); при равенстве — больше модулей по 60 (их больше всего
// в линейках) и ближе к 60, без варочной — то же без её правил. Кухни застройщика (demo-uk-1) этим не пользуются — у них `modulesCm` нет, ряд прежний.

import { scoreWorkPoints } from "@/lib/viewer3d/kits/kitchen-checks";
import { kitchenLayout, type KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";

export const MODULE_SERIES_CM = [40, 45, 60, 80] as const;
/** Предел перебора на ряд: у 2,8 м наборов ~1,5 тыс., дальше — первые по порядку (длинные ряды не наш случай). */
const MAX_ROWS = 4000;

/** Все упорядоченные наборы модулей из ряда с наибольшей суммой ≤ `len`; остаток ≥ 40 не допускаем (пусто). */
export function moduleRows(len: number): number[][] {
  const L = Math.floor(len + 1e-6);
  const reach: boolean[] = [true];
  for (let s = 1; s <= L; s += 1) reach[s] = MODULE_SERIES_CM.some((w) => s >= w && reach[s - w] === true);
  let target = L;
  while (target > 0 && !reach[target]) target -= 1;
  if (target === 0 || len - target >= 40) return [];
  const out: number[][] = [];
  const walk = (left: number, acc: number[]): void => {
    if (out.length >= MAX_ROWS) return;
    if (left === 0) {
      out.push(acc);
      return;
    }
    for (const w of MODULE_SERIES_CM) if (w <= left && reach[left - w]) walk(left - w, [...acc, w]);
  };
  walk(target, []);
  return out;
}

/**
 * Штраф «непривычности» набора: модуль не по 60 — 1, отход от 60 — 0,01/см. Меньше штрафов треугольника (10/см) и мест
 * мойки/варочной (200–500), поэтому решает только между наборами, равными по ним.
 */
const oddness = (row: number[]): number => row.reduce((a, w) => a + (w === 60 ? 0 : 1) + Math.abs(w - 60) * 0.01, 0);

export interface ModulePick {
  modulesCm: number[];
  legModulesCm?: number[];
  sinkAtCm: number;
  hobAtCm: number;
  score: number;
}

/**
 * Ширины модулей и точки мойки/варочной под треугольник. `fixed` — ширины из паспорта: берём их, подбираем только точки.
 * Нет подходящих наборов (ряд короче 40) — null, набор останется с равными долями.
 */
export function pickModules(spec: KitchenSpec, fixed?: { modulesCm?: number[]; legModulesCm?: number[] }): ModulePick | null {
  const lay = kitchenLayout(spec);
  const mainW = lay.corner ? lay.runW - lay.D : lay.runW;
  const mains = fixed?.modulesCm ? [fixed.modulesCm] : moduleRows(mainW);
  const legs: (number[] | undefined)[] = !lay.leg ? [undefined] : fixed?.legModulesCm ? [fixed.legModulesCm] : moduleRows(lay.leg.runCm);
  if (!mains.length) return null;
  let best: ModulePick | null = null;
  for (const modulesCm of mains) {
    for (const legModulesCm of legs.length ? legs : [undefined]) {
      const trial: KitchenSpec = { ...spec, modulesCm, ...(legModulesCm ? { legModulesCm } : {}) };
      const work = scoreWorkPoints(trial);
      if (!work) continue;
      const score = work.score + oddness(modulesCm) + (legModulesCm ? oddness(legModulesCm) : 0);
      if (!best || score < best.score - 1e-9) {
        best = { modulesCm, ...(legModulesCm ? { legModulesCm } : {}), sinkAtCm: work.sinkAtCm, hobAtCm: work.hobAtCm, score };
      }
    }
  }
  return best;
}
