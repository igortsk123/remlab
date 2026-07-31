// Материализация проекта калькулятора v2 → позиции сметы (M1). Чистая функция (тестируется).
// По комнате — расчётная позиция; плюс сопутствующие по виду. Внешние ссылки уйдут через /go/.

import type { CalcProject } from "@/contracts/calc";
import type { EstimateItem } from "@/contracts/estimate";
import { computeRoomParts } from "./formulas";
import { CALC_META, COMPANIONS } from "@/lib/estimate/companions";
import { domainFromUrl } from "@/lib/estimate/links";

export function calcToItems(project: CalcProject, mkId: () => string): EstimateItem[] {
  const items: EstimateItem[] = [];
  for (const room of project.rooms) {
    for (const part of computeRoomParts(room, project.kind)) {
      const out = part.out;
      // Параметры материала не заданы → количество неизвестно: в смету пишем площадь, а не число,
      // полученное из молчаливых дефолтов (ADR-0034).
      const qty = out.qtyUnknown ? out.areaNetM2 : out.qty;
      const unit = out.qtyUnknown ? "м²" : out.unit;
      if (qty <= 0) continue;
      const domain = part.productUrl ? domainFromUrl(part.productUrl) ?? undefined : undefined;
      const url = domain ? part.productUrl : undefined; // валидный url только если распарсился домен
      const title = part.label
        ? `${CALC_META[project.kind].title} — ${room.name} — ${part.label.toLowerCase()}`
        : `${CALC_META[project.kind].title} — ${room.name}`;
      items.push({
        id: mkId(),
        title,
        qty,
        unit,
        unitPriceRub: out.costRub != null && qty > 0 ? Math.round(out.costRub / qty) : undefined,
        url,
        domain,
        source: "calc",
        note: out.note,
      });
    }
  }
  for (const c of COMPANIONS[project.kind]) {
    items.push({ id: mkId(), title: c, qty: 1, unit: "шт", source: "our_pick", note: "сопутствующее — не забудьте" });
  }
  return items;
}
