"use client";

import type { Floor } from "@/contracts/calc";
import { floorNet } from "@/lib/calc/geometry";
import { numToStr, strToNum } from "@/lib/calc/num";

const uid = () => Math.random().toString(36).slice(2, 10);

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

type ZoneKey = "extraZones" | "excludedZones";

// Редактор пола (ламинат): длина×ширина + дополнительные и исключаемые зоны (длина×ширина).
export function FloorEditor({ floor, onChange }: { floor: Floor; onChange: (f: Floor) => void }) {
  const patch = (p: Partial<Floor>) => onChange({ ...floor, ...p });

  const zones = (key: ZoneKey) => (
    <div className="stack" style={{ gap: 6 }}>
      {floor[key].map((z) => (
        <div key={z.id} className="row" style={{ gap: 6, alignItems: "center" }}>
          <input style={inp} inputMode="decimal" placeholder="Длина, м" value={numToStr(z.lengthM)} onChange={(e) => patch({ [key]: floor[key].map((x) => (x.id === z.id ? { ...x, lengthM: strToNum(e.target.value) } : x)) } as Partial<Floor>)} />
          <input style={inp} inputMode="decimal" placeholder="Ширина, м" value={numToStr(z.widthM)} onChange={(e) => patch({ [key]: floor[key].map((x) => (x.id === z.id ? { ...x, widthM: strToNum(e.target.value) } : x)) } as Partial<Floor>)} />
          <button type="button" className="quiz-link" onClick={() => patch({ [key]: floor[key].filter((x) => x.id !== z.id) } as Partial<Floor>)}>×</button>
        </div>
      ))}
      <button type="button" className="chip" onClick={() => patch({ [key]: [...floor[key], { id: uid(), label: "", lengthM: 0, widthM: 0 }] } as Partial<Floor>)}>+ зона</button>
    </div>
  );

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8 }}>
        <label className="stack" style={{ flex: 1, minWidth: 110, gap: 4 }}>
          <span className="eyebrow">Длина пола, м</span>
          <input style={inp} inputMode="decimal" value={numToStr(floor.lengthM)} onChange={(e) => patch({ lengthM: strToNum(e.target.value) })} />
        </label>
        <label className="stack" style={{ flex: 1, minWidth: 110, gap: 4 }}>
          <span className="eyebrow">Ширина пола, м</span>
          <input style={inp} inputMode="decimal" value={numToStr(floor.widthM)} onChange={(e) => patch({ widthM: strToNum(e.target.value) })} />
        </label>
      </div>
      <div className="stack" style={{ gap: 4 }}>
        <span className="eyebrow">Дополнительные зоны</span>
        {zones("extraZones")}
      </div>
      <div className="stack" style={{ gap: 4 }}>
        <span className="eyebrow">Исключить зоны</span>
        {zones("excludedZones")}
      </div>
      <span className="muted" style={{ fontSize: 13 }}>чистая площадь пола: {floorNet(floor)} м²</span>
    </div>
  );
}
