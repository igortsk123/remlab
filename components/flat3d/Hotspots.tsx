"use client";

import { useEffect, useRef, useState } from "react";

// ТОЧКИ НА ЗАМЕНЯЕМЫХ ПРЕДМЕТАХ (план flat3d-sims-ux D6, референс A101): человек сразу видит, ЧТО в комнате можно
// заменить; ближе ~2,5 м точка раскрывается в плашку с названием. Позиции — проекция центра предмета
// (`viewer.projectSlot`) раз в два кадра; предмет вне кадра — точки нет. Нажатие = выбор предмета, как клик по нему.
// ЗОНЫ КАДРА (flat3d-375-overlaps, 21.10): сверху — строка кнопок «Вся квартира / ? / i», снизу — стрелки ходьбы; в этих
// полосах точек и подписей нет, иначе на телефоне подпись ложилась на стрелки. Подпись — внутри кадра: справа от точки,
// у правого края — слева от неё, ширина — сколько осталось до края. Магазин в подписи не пишем — он в карточке товара.
export type Spot = { slotId: string; label: string };
type Pos = { x: number; y: number; visible: boolean; distM: number } | null;
/** Полосы кадра, занятые управлением, px от верхнего и нижнего края. */
export type Zones = { top: number; bottom: number };

const NEAR_M = 2.5;
const DOT_GAP = 14; // от центра точки до подписи
const EDGE = 8; // поле у края кадра
const LABEL_MAX = 220;
const LABEL_MIN = 72; // уже — подпись не показываем: в неё не влезет и слово
const TAP_HALF = 22;

export function Hotspots({ spots, project, onPick, hidden, zones, maxLabels }: {
  spots: Spot[];
  project: (slotId: string) => Pos;
  onPick: (slotId: string) => void;
  /** Пока предмет выбран или «взят», точки прячем — они мешали бы кнопкам у предмета. */
  hidden: boolean;
  zones: Zones;
  /** Сколько подписей раскрывать одновременно (ближайшие): на телефоне одна, иначе стулья у стола слипаются. */
  maxLabels: number;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
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
  const w = boxRef.current?.clientWidth ?? 0;
  const h = boxRef.current?.clientHeight ?? 0;
  // точка — кнопка 44 px: ни в зону управления, ни за боковой край кадра не должна заходить и её половина
  const inFrame = (p: Pos): p is NonNullable<Pos> => !!p && p.visible && (!h || (p.y - TAP_HALF > zones.top && p.y + TAP_HALF < h - zones.bottom
    && p.x - TAP_HALF > 0 && p.x + TAP_HALF < w));
  const shown = spots.filter((s) => inFrame(pos[s.slotId] ?? null));
  const labelled = new Set(shown.filter((s) => pos[s.slotId]!.distM < NEAR_M)
    .sort((a, b) => pos[a.slotId]!.distM - pos[b.slotId]!.distM).slice(0, maxLabels).map((s) => s.slotId));
  return (
    <div ref={boxRef} data-flat3d="hotspots" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 3 }}>
      {shown.map((s) => {
        const p = pos[s.slotId]!;
        const right = p.x <= w / 2;
        const room = Math.min(LABEL_MAX, (right ? w - p.x : p.x) - DOT_GAP - EDGE);
        const label = w && labelled.has(s.slotId) && room >= LABEL_MIN;
        return (
          <span key={s.slotId}>
            <button type="button" onClick={() => onPick(s.slotId)} aria-label={s.label}
              className="min-h-11 min-w-11 rounded-full"
              style={{ position: "absolute", left: p.x, top: p.y, transform: "translate(-50%, -50%)", pointerEvents: "auto",
                display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span aria-hidden style={{ width: 14, height: 14, borderRadius: 7, background: "var(--color-bg-brand-solid)",
                boxShadow: "0 0 0 3px var(--color-bg-primary)" }} />
            </button>
            {label ? (
              <button type="button" tabIndex={-1} onClick={() => onPick(s.slotId)} data-flat3d="spot-label"
                className="rounded-md bg-primary px-2 py-1 text-xs text-primary shadow-md"
                style={{ position: "absolute", top: p.y, transform: "translateY(-50%)", pointerEvents: "auto", maxWidth: room,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  ...(right ? { left: p.x + DOT_GAP } : { right: w - p.x + DOT_GAP }) }}>
                {s.label}
              </button>
            ) : null}
          </span>
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
