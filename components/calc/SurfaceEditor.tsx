"use client";

import type { CalcKind, Opening, Surface } from "@/contracts/calc";
import { surfaceNet } from "@/lib/calc/geometry";
import { numToStr, strToNum } from "@/lib/calc/num";

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

  return (
    <div className="stack" style={{ gap: 12 }}>
      {isOboi && (
        <div className="row" style={{ justifyContent: "flex-end", margin: 0 }}>
          <DoorHint />
        </div>
      )}
      {!isOboi && (
        <label className="row" style={{ gap: 8, alignItems: "center", margin: 0 }}>
          <input type="checkbox" checked={!!countOpenings} onChange={(e) => onCountOpenings?.(e.target.checked)} />
          <span>Учесть окна и двери</span>
        </label>
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
              <input style={inp} inputMode="decimal" value={numToStr(s.lengthM)} onChange={(e) => patch(s.id, { lengthM: strToNum(e.target.value) })} />
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 100, gap: 4 }}>
              <span className="eyebrow">Высота, м</span>
              <input style={inp} inputMode="decimal" value={numToStr(s.heightM)} onChange={(e) => patch(s.id, { heightM: strToNum(e.target.value) })} />
            </label>
          </div>

          {showOpenings && s.openings.map((o) => (
            <div key={o.id} className="row" style={{ gap: 6, alignItems: "center" }}>
              <label className="stack" style={{ flex: 1, minWidth: 90, gap: 4 }}>
                <span className="eyebrow">Ширина, м</span>
                <input style={inp} inputMode="decimal" value={numToStr(o.widthM)} onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, widthM: strToNum(e.target.value) } : x)))} />
              </label>
              <label className="stack" style={{ flex: 1, minWidth: 90, gap: 4 }}>
                <span className="eyebrow">Высота, м</span>
                <input style={inp} inputMode="decimal" value={numToStr(o.heightM)} onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, heightM: strToNum(e.target.value) } : x)))} />
              </label>
              <button type="button" className="quiz-link" style={{ alignSelf: "flex-end", padding: "8px 0" }} onClick={() => patchOpenings(s.id, (os) => os.filter((x) => x.id !== o.id))}>×</button>
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
      <button type="button" className="chip" onClick={() => onChange([...surfaces, { id: uid(), label: `Стена ${surfaces.length + 1}`, lengthM: 0, heightM: 0, openings: [] }])}>+ добавить размеры стены</button>
    </div>
  );
}
