"use client";

import { useState } from "react";
import { COMPANIONS, type CalcKind } from "@/lib/estimate/companions";
import { computeRoomParts } from "@/lib/calc/formulas";
import { useCalcProject } from "./useCalcProject";
import { RoomPanel } from "./RoomPanel";
import { ResultView } from "./ResultView";
import { VizCta } from "./VizCta";

const round2 = (n: number) => Math.round(n * 100) / 100;

// Билдер калькулятора v2: мультикомната (К0) + геометрия (К1) + параметры/формулы (К2) + итог/смета (К3).
export function CalcBuilder({ kind }: { kind: CalcKind }) {
  const { project, add, remove, update } = useCalcProject(kind);
  const [activeId, setActiveId] = useState<string | null>(null);

  const activeIdSafe =
    activeId && project.rooms.some((r) => r.id === activeId) ? activeId : project.rooms[0]?.id ?? null;
  const active = project.rooms.find((r) => r.id === activeIdSafe) ?? null;
  const allParts = project.rooms.flatMap((r) => computeRoomParts(r, kind));
  const totalNet = round2(allParts.reduce((s, p) => s + p.out.areaNetM2, 0));
  const totalCost = allParts.reduce((s, p) => s + (p.out.costRub ?? 0), 0);

  return (
    <div className="stack">
      <div className="calc-sticky">
        <span className="eyebrow" style={{ margin: 0 }}>Итог</span>
        <span>Площадь: <strong>{totalNet} м²</strong></span>
        {totalCost > 0 && <span>≈ <strong>{totalCost.toLocaleString("ru-RU")} ₽</strong></span>}
      </div>

      <div className="row" style={{ gap: 8 }}>
        {project.rooms.map((r) => (
          <button
            key={r.id}
            type="button"
            className="chip"
            data-selected={r.id === activeIdSafe}
            onClick={() => setActiveId(r.id)}
          >
            {r.name}
          </button>
        ))}
        <button type="button" className="chip" onClick={add}>+ Комната</button>
      </div>

      {active && (
        <RoomPanel
          key={active.id}
          room={active}
          kind={kind}
          canDelete={project.rooms.length > 1}
          onUpdate={(fn) => update(active.id, fn)}
          onDelete={() => {
            remove(active.id);
            setActiveId(null);
          }}
        />
      )}

      {project.rooms.length > 1 && (
        <p className="muted" style={{ fontSize: 14 }}>
          Итого по {project.rooms.length} комнатам: {totalNet} м²
        </p>
      )}

      <ResultView project={project} />

      <div className="card stack">
        <p className="eyebrow">Также не забудьте</p>
        <ul className="checklist">
          {COMPANIONS[kind].map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>

      <VizCta />
    </div>
  );
}
