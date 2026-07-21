"use client";

import type { CalcKind, Opening, Surface } from "@/contracts/calc";
import { surfaceNet } from "@/lib/calc/geometry";
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

// Редактор стен/поверхностей. Обои: проёмы не вводятся (формула по периметру), вместо них — подсказка.
// Плитка/краска: проёмы по галочке «Учесть окна и двери» (Ширина×Высота, без типа) и вычитаются из площади.
export function SurfaceEditor({
  surfaces,
  onChange,
  kind,
  countOpenings,
  onCountOpenings,
}: {
  surfaces: Surface[];
  onChange: (surfaces: Surface[]) => void;
  kind: CalcKind;
  countOpenings?: boolean;
  onCountOpenings?: (v: boolean) => void;
}) {
  const isOboi = kind === "oboi";
  const showOpenings = !isOboi && !!countOpenings;
  const patch = (id: string, p: Partial<Surface>) =>
    onChange(surfaces.map((s) => (s.id === id ? { ...s, ...p } : s)));
  const patchOpenings = (sid: string, fn: (o: Opening[]) => Opening[]) =>
    onChange(surfaces.map((s) => (s.id === sid ? { ...s, openings: fn(s.openings) } : s)));
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
      {!isOboi && (
        <div className="openings-group">
          <label className="row" style={{ gap: 8, alignItems: "center", margin: 0 }}>
            <input type="checkbox" checked={!!countOpenings} onChange={(e) => onCountOpenings?.(e.target.checked)} />
            <span>Учесть окна и двери</span>
          </label>
          {showOpenings && (
            <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>
              Проёмы задаёте у каждой стены ниже — кнопкой «+ добавить проём».
            </p>
          )}
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

          {showOpenings && s.openings.map((o) => (
            <div key={o.id} className="stack" style={{ gap: 8, borderLeft: "2px solid var(--accent)", paddingLeft: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: 14 }}>Проём</strong>
                <button type="button" className="quiz-link" style={{ fontSize: 12 }} onClick={() => patchOpenings(s.id, (os) => os.filter((x) => x.id !== o.id))}>удалить</button>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
                  <span className="eyebrow">Ширина, м</span>
                  <NumInput style={inp} value={o.widthM} onChange={(n) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, widthM: n ?? 0 } : x)))} />
                </label>
                <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
                  <span className="eyebrow">Высота, м</span>
                  <NumInput style={inp} value={o.heightM} onChange={(n) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, heightM: n ?? 0 } : x)))} />
                </label>
              </div>
            </div>
          ))}

          {showOpenings && (
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <button type="button" className="chip" onClick={() => patchOpenings(s.id, (os) => [...os, { id: uid(), kind: "window", widthM: 0, heightM: 0, count: 1 }])}>+ добавить проём</button>
              <span className="muted" style={{ fontSize: 13 }}>чистая площадь: {surfaceNet(s)} м²</span>
            </div>
          )}
        </div>
      ))}
      <button type="button" className="chip" style={{ background: "var(--accent)", color: "var(--surface)", borderColor: "var(--accent)" }} onClick={addWall}>+ добавить размеры стены</button>
    </div>
  );
}
