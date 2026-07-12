"use client";

import type { Opening, Surface } from "@/contracts/calc";
import { surfaceNet } from "@/lib/calc/geometry";
import { numToStr, strToNum } from "@/lib/calc/num";

const uid = () => Math.random().toString(36).slice(2, 10);

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Редактор стен/поверхностей (обои/плитка/краска): длина, высота + проёмы (окна/двери/прочее).
export function SurfaceEditor({
  surfaces,
  onChange,
}: {
  surfaces: Surface[];
  onChange: (surfaces: Surface[]) => void;
}) {
  const patch = (id: string, p: Partial<Surface>) =>
    onChange(surfaces.map((s) => (s.id === id ? { ...s, ...p } : s)));
  const patchOpenings = (sid: string, fn: (o: Opening[]) => Opening[]) =>
    onChange(surfaces.map((s) => (s.id === sid ? { ...s, openings: fn(s.openings) } : s)));

  return (
    <div className="stack" style={{ gap: 12 }}>
      {surfaces.map((s) => (
        <div key={s.id} className="stack" style={{ gap: 8, borderLeft: "2px solid var(--border)", paddingLeft: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ fontSize: 15 }}>{s.label || "Стена"}</strong>
            <button type="button" className="quiz-link" onClick={() => onChange(surfaces.filter((x) => x.id !== s.id))}>убрать</button>
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

          {s.openings.map((o) => (
            <div key={o.id} className="row" style={{ gap: 6, alignItems: "center" }}>
              <select
                style={{ ...inp, width: "auto" }}
                value={o.kind}
                onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, kind: e.target.value as Opening["kind"] } : x)))}
              >
                <option value="window">Окно</option>
                <option value="door">Дверь</option>
                <option value="other">Проём</option>
              </select>
              <input style={inp} inputMode="decimal" placeholder="Ш, м" value={numToStr(o.widthM)} onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, widthM: strToNum(e.target.value) } : x)))} />
              <input style={inp} inputMode="decimal" placeholder="В, м" value={numToStr(o.heightM)} onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, heightM: strToNum(e.target.value) } : x)))} />
              <input style={{ ...inp, width: 56 }} inputMode="numeric" value={String(o.count)} onChange={(e) => patchOpenings(s.id, (os) => os.map((x) => (x.id === o.id ? { ...x, count: Math.max(1, Math.round(strToNum(e.target.value))) } : x)))} />
              <button type="button" className="quiz-link" onClick={() => patchOpenings(s.id, (os) => os.filter((x) => x.id !== o.id))}>×</button>
            </div>
          ))}

          <div className="row" style={{ gap: 8, alignItems: "center" }}>
            <button type="button" className="chip" onClick={() => patchOpenings(s.id, (os) => [...os, { id: uid(), kind: "window", widthM: 0, heightM: 0, count: 1 }])}>+ проём</button>
            <span className="muted" style={{ fontSize: 13 }}>чистая площадь: {surfaceNet(s)} м²</span>
          </div>
        </div>
      ))}
      <button type="button" className="chip" onClick={() => onChange([...surfaces, { id: uid(), label: `Стена ${surfaces.length + 1}`, lengthM: 0, heightM: 0, openings: [] }])}>+ стена</button>
    </div>
  );
}
