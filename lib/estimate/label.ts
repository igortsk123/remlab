// Единая подпись сохранённого расчёта: одно имя на кнопке сохранения, в списке /lab и в
// заголовке /e/[id]. По виду материала из meta.kind («Расчёт обоев»), фолбэк — title сметы
// (стоимость ремонта и ручные списки приходят со своим title).

import type { Estimate } from "@/contracts/estimate";
import { CALC_META, type CalcKind } from "@/lib/estimate/companions";

export function estimateKind(e: Estimate): CalcKind | undefined {
  const kind = (e.meta as { kind?: string } | undefined)?.kind as CalcKind | undefined;
  return kind && CALC_META[kind] ? kind : undefined;
}

export function estimateLabel(e: Estimate): string {
  const kind = estimateKind(e);
  return kind ? `Расчёт ${CALC_META[kind].titleGen}` : e.title;
}
