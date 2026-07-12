"use client";

import { useState } from "react";
import { COMPANIONS, type CalcKind } from "@/lib/estimate/companions";
import { useCalcProject } from "./useCalcProject";

const nameInputStyle = {
  font: "inherit", fontWeight: 600, fontSize: 16,
  border: "1px solid var(--base)", borderRadius: 8,
  background: "var(--surface)", color: "var(--text)", padding: "6px 10px", maxWidth: 240,
} as const;

// Каркас билдера калькулятора v2 (К0): мультикомната. Геометрия/параметры/результат — К1–К3.
export function CalcBuilder({ kind }: { kind: CalcKind }) {
  const { project, add, remove, rename } = useCalcProject(kind);
  const [activeId, setActiveId] = useState<string | null>(null);

  if (!project) return <p className="muted">Загрузка…</p>;

  const activeIdSafe =
    activeId && project.rooms.some((r) => r.id === activeId) ? activeId : project.rooms[0]?.id ?? null;
  const active = project.rooms.find((r) => r.id === activeIdSafe) ?? null;

  return (
    <div className="stack">
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
        <div className="card stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <input
              value={active.name}
              onChange={(e) => rename(active.id, e.target.value)}
              aria-label="Название комнаты"
              style={nameInputStyle}
            />
            {project.rooms.length > 1 && (
              <button
                type="button"
                className="quiz-link"
                onClick={() => {
                  remove(active.id);
                  setActiveId(null);
                }}
              >
                Удалить
              </button>
            )}
          </div>
          <p className="note">
            Размеры и параметры материала появятся здесь на следующих шагах. Сейчас можно завести
            комнаты — данные сохраняются локально в этом браузере.
          </p>
        </div>
      )}

      <div className="card stack">
        <p className="eyebrow">Заодно не забудьте</p>
        <div className="row">
          {COMPANIONS[kind].map((c) => (
            <span key={c} className="chip" data-selected="false">{c}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
