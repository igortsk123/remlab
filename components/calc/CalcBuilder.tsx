"use client";

import { useState } from "react";
import { COMPANIONS, type CalcKind } from "@/lib/estimate/companions";
import { computeRoomParts } from "@/lib/calc/formulas";
import { useCalcProject } from "./useCalcProject";
import { RoomPanel } from "./RoomPanel";
import { ResultView } from "./ResultView";
import { VizCta } from "./VizCta";
import { FindCheaper } from "./FindCheaper";

const round2 = (n: number) => Math.round(n * 100) / 100;

// Билдер калькулятора v2: мультикомната (К0) + геометрия (К1) + параметры/формулы (К2) + итог/смета (К3).
export function CalcBuilder({ kind }: { kind: CalcKind }) {
  const { project, add, remove, update } = useCalcProject(kind);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [cheaperSignal, setCheaperSignal] = useState(0);

  const activeIdSafe =
    activeId && project.rooms.some((r) => r.id === activeId) ? activeId : project.rooms[0]?.id ?? null;
  const active = project.rooms.find((r) => r.id === activeIdSafe) ?? null;
  const totalNet = round2(project.rooms.flatMap((r) => computeRoomParts(r, kind)).reduce((s, p) => s + p.out.areaNetM2, 0));

  return (
    <div className="stack">
      <button
        type="button"
        className="btn btn-block"
        onClick={() => setCheaperSignal((s) => s + 1)}
      >
        Если есть ссылка на товар — найдём выгоднее
      </button>

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

      <FindCheaper kind={kind} url={project.rooms.find((r) => r.productUrl)?.productUrl} openSignal={cheaperSignal} />

      <VizCta />
    </div>
  );
}
