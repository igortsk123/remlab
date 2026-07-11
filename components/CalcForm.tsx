"use client";

import { trackGoal } from "@/lib/metrika";
import type { CalcKind } from "@/lib/estimate/companions";

const inputStyle = {
  padding: "12px 14px", borderRadius: 10, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 16, fontFamily: "inherit", width: "100%",
} as const;

// Поля зависят от вида: обои/краска считаем по периметру и высоте; плитка/ламинат — по площади.
const NEEDS_HEIGHT: Record<CalcKind, boolean> = { oboi: true, kraska: true, plitka: false, laminat: false };
const AREA_LABEL: Record<CalcKind, string> = {
  oboi: "Стены оклеиваем по периметру комнаты",
  kraska: "Красим стены по периметру комнаты",
  plitka: "Площадь укладки (пол или стены)",
  laminat: "Площадь пола",
};

export function CalcForm({ kind, action }: { kind: CalcKind; action: (fd: FormData) => void | Promise<void> }) {
  const byArea = kind === "plitka" || kind === "laminat";
  return (
    <form action={action} className="stack" onSubmit={() => trackGoal("calc_started")}>
      <p className="muted" style={{ fontSize: 14 }}>{AREA_LABEL[kind]}</p>

      {byArea ? (
        <div className="stack">
          <label className="eyebrow">Площадь, м² (или введите стороны ниже)</label>
          <input name="area" type="number" step="0.1" min="0" placeholder="напр. 12" style={inputStyle} inputMode="decimal" />
        </div>
      ) : null}

      <div className="row" style={{ gap: 12 }}>
        <div className="stack" style={{ flex: 1, minWidth: 120 }}>
          <label className="eyebrow">Ширина, м</label>
          <input name="width" type="number" step="0.1" min="0" placeholder="напр. 3.5" style={inputStyle} inputMode="decimal" />
        </div>
        <div className="stack" style={{ flex: 1, minWidth: 120 }}>
          <label className="eyebrow">Длина, м</label>
          <input name="length" type="number" step="0.1" min="0" placeholder="напр. 4" style={inputStyle} inputMode="decimal" />
        </div>
        {NEEDS_HEIGHT[kind] ? (
          <div className="stack" style={{ flex: 1, minWidth: 120 }}>
            <label className="eyebrow">Высота, м</label>
            <input name="height" type="number" step="0.1" min="0" placeholder="2.7" style={inputStyle} inputMode="decimal" />
          </div>
        ) : null}
      </div>

      <button className="btn btn-block" type="submit">Посчитать и собрать смету</button>
      <p className="note">Считаем с запасом на подрезку. Точность — как у обычного калькулятора; проверьте перед покупкой.</p>
    </form>
  );
}
