"use client";

import { useTransition } from "react";
import type { CalcProject } from "@/contracts/calc";
import { computeRoomParts } from "@/lib/calc/formulas";
import { pluralUnit } from "@/lib/format/plural";
import { saveCalcEstimate } from "@/app/calc-actions";

// Итог по проекту: разбивка по комнатам, суммарная стоимость, сохранение в смету (М1).
export function ResultView({ project }: { project: CalcProject }) {
  const [pending, startTransition] = useTransition();
  const rows = project.rooms
    .flatMap((r) =>
      computeRoomParts(r, project.kind).map((p) => ({
        id: `${r.id}:${p.key}`,
        name: p.label ? `${r.name} — ${p.label.toLowerCase()}` : r.name,
        out: p.out,
      })),
    )
    .filter((x) => x.out.qty > 0);

  if (rows.length === 0) return null;
  const totalCost = rows.reduce((s, x) => s + (x.out.costRub ?? 0), 0);

  return (
    <div className="card stack">
      <p className="eyebrow">Итог</p>
      {rows.map((x) => (
        <div key={x.id} className="row" style={{ justifyContent: "space-between", gap: 8 }}>
          <span>{x.name}</span>
          <span className="muted">
            {x.out.qty} {pluralUnit(x.out.unit, x.out.qty)}
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
        onClick={() => startTransition(() => { void saveCalcEstimate(project); })}
      >
        {pending ? "Сохраняем…" : "Сохранить смету"}
      </button>
      <p className="note">Считаем с запасом на подрезку. Проверьте перед покупкой.</p>
    </div>
  );
}
