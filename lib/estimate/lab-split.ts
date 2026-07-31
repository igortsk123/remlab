// Раскладка смет по вкладкам лаборатории: «Ремонт» = source "remont", остальное — «Материалы»
// (calc и manual — это расчёты материалов и ручные списки покупок).

import type { Estimate } from "@/contracts/estimate";

export function splitEstimatesBySource(estimates: Estimate[]): { materials: Estimate[]; remont: Estimate[] } {
  const materials: Estimate[] = [];
  const remont: Estimate[] = [];
  for (const e of estimates) (e.source === "remont" ? remont : materials).push(e);
  return { materials, remont };
}
