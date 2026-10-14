"use client";

import { useEffect, useState } from "react";

// ТОЧКИ НА ЗАМЕНЯЕМЫХ ПРЕДМЕТАХ (план flat3d-sims-ux D6, референс A101): человек сразу видит, ЧТО в комнате можно
// заменить; ближе ~2,5 м точка раскрывается в плашку «магазин · название». Позиции — проекция центра предмета
// (`viewer.projectSlot`) раз в два кадра; предмет вне кадра — точки нет. Нажатие = выбор предмета, как клик по нему.
export type Spot = { slotId: string; label: string };
type Pos = { x: number; y: number; visible: boolean; distM: number } | null;

const NEAR_M = 2.5;

export function Hotspots({ spots, project, onPick, hidden }: {
  spots: Spot[];
  project: (slotId: string) => Pos;
  onPick: (slotId: string) => void;
  /** Пока предмет выбран или «взят», точки прячем — они мешали бы кнопкам у предмета. */
  hidden: boolean;
}) {
  const [pos, setPos] = useState<Record<string, Pos>>({});
  useEffect(() => {
    if (hidden || !spots.length) return;
    let raf = 0;
    let frame = 0;
    const tick = () => {
      if (frame++ % 2 === 0) {
        const next: Record<string, Pos> = {};
        for (const s of spots) next[s.slotId] = project(s.slotId);
        setPos((old) => (same(old, next) ? old : next));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [spots, project, hidden]);
  if (hidden) return null;
  return (
    <div data-flat3d="hotspots" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 3 }}>
      {spots.map((s) => {
        const p = pos[s.slotId];
        if (!p || !p.visible) return null;
        const near = p.distM < NEAR_M;
        return (
          <button key={s.slotId} type="button" onClick={() => onPick(s.slotId)} aria-label={s.label}
            className="min-h-11 min-w-11 rounded-full"
            style={{ position: "absolute", left: p.x, top: p.y, transform: "translate(-50%, -50%)", pointerEvents: "auto",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6, padding: near ? "0 10px" : 0 }}>
            <span aria-hidden style={{ width: 14, height: 14, borderRadius: 7, background: "var(--color-bg-brand-solid)",
              boxShadow: "0 0 0 3px var(--color-bg-primary)" }} />
            {near ? <span className="rounded-md bg-primary px-2 py-1 text-xs text-primary shadow-md" style={{ whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>{s.label}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

function same(a: Record<string, Pos>, b: Record<string, Pos>): boolean {
  for (const k of Object.keys(b)) {
    const x = a[k];
    const y = b[k];
    if (!x || !y) { if (x !== y) return false; continue; }
    if (Math.abs(x.x - y.x) > 1 || Math.abs(x.y - y.y) > 1 || x.visible !== y.visible || (x.distM < NEAR_M) !== (y.distM < NEAR_M)) return false;
  }
  return Object.keys(a).length === Object.keys(b).length;
}
