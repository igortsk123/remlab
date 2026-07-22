"use client";

import type { CalcKind, Surface } from "@/contracts/calc";
import { NumInput } from "./NumInput";

const uid = () => Math.random().toString(36).slice(2, 10);

const OPENINGS_NOTE =
  "Окна и двери не вычитаются из расчёта, т.к. обои клеятся целыми полосами, поэтому кусок, " +
  "оставшийся из-за проёма, обычно нельзя использовать в другом месте. За счёт этого получается " +
  "небольшой запас: на подгонку рисунка, обрезки и непредвиденные ошибки.";

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Иконка-«дверь» (прямоугольник + точка-ручка) — приглушённый подсказчик, почему проёмы не вводим (обои).
function DoorHint() {
  return (
    <span className="help" tabIndex={0} role="note" aria-label={OPENINGS_NOTE} data-tip={OPENINGS_NOTE}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <rect x="6" y="3" width="12" height="18" rx="1" />
        <circle cx="14.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
      </svg>
    </span>
  );
}

// Редактор стен/поверхностей. Проёмы не вводятся ни для одного вида: обои клеятся полосами,
// у плитки/краски окна и двери идут в запас на подрезку — вычет только запутывал бы.
export function SurfaceEditor({
  surfaces,
  onChange,
  kind,
}: {
  surfaces: Surface[];
  onChange: (surfaces: Surface[]) => void;
  kind: CalcKind;
}) {
  const isOboi = kind === "oboi";
  const patch = (id: string, p: Partial<Surface>) =>
    onChange(surfaces.map((s) => (s.id === id ? { ...s, ...p } : s)));
  // Высота первой стены подставляется остальным стенам, где высота ещё пустая (0). Каждую можно менять.
  const setHeight = (id: string, h: number) => {
    const isFirst = surfaces[0]?.id === id;
    onChange(surfaces.map((s) => {
      if (s.id === id) return { ...s, heightM: h };
      if (isFirst && s.heightM === 0) return { ...s, heightM: h };
      return s;
    }));
  };
  const addWall = () =>
    onChange([...surfaces, { id: uid(), label: `Стена ${surfaces.length + 1}`, lengthM: 0, heightM: surfaces[0]?.heightM ?? 0, openings: [] }]);

  return (
    <div className="stack" style={{ gap: 12 }}>
      {isOboi && (
        <div className="row" style={{ justifyContent: "flex-end", margin: 0 }}>
          <DoorHint />
        </div>
      )}

      {surfaces.map((s) => (
        <div key={s.id} className="stack" style={{ gap: 8, borderLeft: "2px solid var(--border)", paddingLeft: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ fontSize: 15 }}>{s.label || "Стена"}</strong>
            <button type="button" className="quiz-link" style={{ fontSize: 12 }} onClick={() => onChange(surfaces.filter((x) => x.id !== s.id))}>удалить</button>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
              <span className="eyebrow">Длина, м</span>
              <NumInput style={inp} value={s.lengthM} onChange={(n) => patch(s.id, { lengthM: n ?? 0 })} />
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
              <span className="eyebrow">Высота, м</span>
              <NumInput style={inp} value={s.heightM} onChange={(n) => setHeight(s.id, n ?? 0)} />
            </label>
          </div>
        </div>
      ))}
      <button type="button" className="chip" style={{ background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" }} onClick={addWall}>+ добавить размеры стены</button>
    </div>
  );
}
