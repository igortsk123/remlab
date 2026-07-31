"use client";

import { useTransition } from "react";
import type { CalcProject } from "@/contracts/calc";
import { computeRoomParts } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { clearProject } from "@/lib/calc/storage";
import { saveCalcEstimate } from "@/app/calc-actions";
import { trackGoal } from "@/lib/metrika";

// Примечание под итогом — по виду материала: «подрезка» есть не везде (у краски — расход и слои).
const RESULT_NOTE: Record<CalcProject["kind"], string> = {
  oboi: "Считаем с запасом на подрезку и подгонку рисунка. Проверьте перед покупкой.",
  plitka: "Считаем с запасом на подрезку и бой. Проверьте перед покупкой.",
  laminat: "Считаем с запасом на подрезку. Проверьте перед покупкой.",
  kraska: "Считаем по расходу и числу слоёв — фактический расход зависит от поверхности. Проверьте перед покупкой.",
};

// Итог по проекту: разбивка по комнатам, суммарная стоимость, сохранение в смету (М1).
export function ResultView({ project }: { project: CalcProject }) {
  const [pending, startTransition] = useTransition();
  const rows = project.rooms
    .flatMap((r) =>
      computeRoomParts(r, project.kind).map((p) => ({
        id: `${r.id}:${p.key}`,
        name: p.label ? `${r.name} · ${p.label.toLowerCase()}` : r.name,
        out: p.out,
      })),
    )
    // Строка нужна и когда количество ещё неизвестно (параметры материала не заданы) — площадь уже есть.
    .filter((x) => x.out.qty > 0 || x.out.areaNetM2 > 0);

  if (rows.length === 0) return null;
  const totalCost = rows.reduce((s, x) => s + (x.out.costRub ?? 0), 0);

  return (
    <div className="card stack">
      <p className="eyebrow">Итог</p>
      {rows.map((x) => (
        <div key={x.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
          <span>{x.name}</span>
          <span className="muted">
            {x.out.areaNetM2} м²
            {x.out.qtyUnknown ? ` · ? ${pluralUnit(x.out.unit, 0)}` : ` · ${x.out.qty} ${pluralUnit(x.out.unit, x.out.qty)}`}
            {x.out.costRub != null ? ` · ~${x.out.costRub.toLocaleString("ru-RU")} ₽` : ""}
          </span>
        </div>
      ))}
      {totalCost > 0 && (
        <div className="row" style={{ justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          <strong>Итого материалы</strong>
          <strong>~{totalCost.toLocaleString("ru-RU")} ₽</strong>
        </div>
      )}
      <button
        className="btn btn-block"
        disabled={pending}
        onClick={() => {
          trackGoal("estimate_saved"); // цель — в момент реального сохранения (воронка 10–13)
          startTransition(async () => {
            const res = await saveCalcEstimate(project);
            if (res.ok) {
              clearProject(project.kind); // черновик сохранён в смету — новый расчёт начнётся с «Комнаты 1»
              window.location.assign(`/e/${res.id}?saved=1`);
            }
          });
        }}
      >
        {pending ? "Сохраняем…" : "Сохранить в Мою лабораторию"}
      </button>
      <p className="note">{RESULT_NOTE[project.kind]}</p>
    </div>
  );
}
