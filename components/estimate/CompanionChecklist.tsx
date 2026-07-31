"use client";

import { useEffect, useState } from "react";
import { COMPANIONS, type CalcKind } from "@/lib/estimate/companions";

// Сопутствующие материалы галочками (ADR-0040): подсказка «не забудьте», НЕ позиции расчёта.
// Отметки живут только в браузере (localStorage по id расчёта), на сервер не пишутся.
export function CompanionChecklist({ estimateId, kind }: { estimateId: string; kind: CalcKind }) {
  const storageKey = `remlab-companions-${estimateId}`;
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) setChecked(JSON.parse(raw) as Record<string, boolean>);
    } catch {
      // повреждённое значение — начинаем с пустых галочек
    }
  }, [storageKey]);

  function toggle(name: string) {
    const next = { ...checked, [name]: !checked[name] };
    setChecked(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // приватный режим — галочки не переживут перезагрузку, но работают в сессии
    }
  }

  return (
    <div className="card stack" style={{ marginTop: 16, gap: 10 }}>
      <p className="eyebrow" style={{ margin: 0 }}>Не забудьте — понадобится для работы</p>
      {COMPANIONS[kind].map((name) => (
        <label key={name} className="row" style={{ alignItems: "center", gap: 10, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={!!checked[name]}
            onChange={() => toggle(name)}
            style={{ width: 18, height: 18, accentColor: "var(--accent)" }}
          />
          <span style={checked[name] ? { textDecoration: "line-through", color: "var(--muted)" } : undefined}>
            {name}
          </span>
        </label>
      ))}
    </div>
  );
}
