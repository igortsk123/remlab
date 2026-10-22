"use client";

import { useEffect, useRef, useState } from "react";

// ТОЧКИ НА ЗАМЕНЯЕМЫХ ПРЕДМЕТАХ (план flat3d-sims-ux D6, референс A101): человек сразу видит, ЧТО в комнате можно
// заменить; ближе ~2,5 м точка раскрывается в плашку с названием. Позиции — проекция центра предмета
// (`viewer.projectSlot`) раз в два кадра; предмет вне кадра — точки нет. Нажатие = выбор предмета, как клик по нему.
// ЗОНЫ КАДРА (flat3d-375-overlaps, 21–22.10): сверху — строка кнопок «Вся квартира / ? / i», снизу по центру — прямоугольник
// стрелок ходьбы; в них точек и подписей нет, иначе на телефоне подпись ложилась на стрелки. Подпись — внутри кадра: справа
// от точки, у правого края — слева от неё; у точки сбоку от стрелок — над стрелками с линией к точке (`labelBox`); ширина —
// сколько осталось до края. Магазина в подписи нет — он в строке товара панели выбора (`lib/configurator/label.ts`).
export type Spot = { slotId: string; label: string };
type Pos = { x: number; y: number; visible: boolean; distM: number } | null;
/** Полосы кадра, занятые управлением (px от верхнего и нижнего края), и прямоугольник стрелок по центру у нижнего края. */
export type Zones = { top: number; bottom: number; pad?: { w: number; h: number } };

const NEAR_M = 2.5;
const DOT_GAP = 14; // от центра точки до подписи
const EDGE = 8; // поле у края кадра
const LABEL_MAX = 220;
const LABEL_MIN = 72; // уже — подпись не показываем: в неё не влезет и слово
const TAP_HALF = 22;
const LABEL_HALF = 14; // половина высоты подписи
const LEADER_GAP = 6; // от верхнего края стрелок до низа поднятой подписи
const DOT_R = 10; // кружок 14 px с обводкой 3 px

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
  const pad = zones.pad ? { l: (w - zones.pad.w) / 2, r: (w + zones.pad.w) / 2, t: h - zones.pad.h } : null;
  const onPad = (x: number, y: number, half: number) => !!pad && y + half > pad.t && x + TAP_HALF > pad.l && x - TAP_HALF < pad.r;
  const inFrame = (p: Pos): p is NonNullable<Pos> => !!p && p.visible && (!h || (p.y - TAP_HALF > zones.top && p.y + TAP_HALF < h - zones.bottom
    && p.x - TAP_HALF > 0 && p.x + TAP_HALF < w && !onPad(p.x, p.y, TAP_HALF)));
  const shown = spots.filter((s) => inFrame(pos[s.slotId] ?? null));
  const labelled = new Set(shown.filter((s) => pos[s.slotId]!.distM < NEAR_M)
    .sort((a, b) => pos[a.slotId]!.distM - pos[b.slotId]!.distM).slice(0, maxLabels).map((s) => s.slotId));
  return (
    <div ref={boxRef} data-flat3d="hotspots" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 3 }}>
      {shown.map((s) => {
        const p = pos[s.slotId]!;
        const box = w && labelled.has(s.slotId) ? labelBox(p, w, pad) : null;
        const label = !!box && box.room >= LABEL_MIN;
        return (
          <span key={s.slotId}>
            <button type="button" onClick={() => onPick(s.slotId)} aria-label={s.label}
              className="min-h-11 min-w-11 rounded-full"
              style={{ position: "absolute", left: p.x, top: p.y, transform: "translate(-50%, -50%)", pointerEvents: "auto",
                display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span aria-hidden style={{ width: 14, height: 14, borderRadius: 7, background: "var(--color-bg-brand-solid)",
                boxShadow: "0 0 0 3px var(--color-bg-primary)" }} />
            </button>
            {label && box.leader ? (
              <span aria-hidden style={{ position: "absolute", left: p.x - 1, top: box.leader.top, height: box.leader.height, width: 2,
                background: "var(--color-bg-primary)", boxShadow: "0 0 2px rgba(0,0,0,0.25)" }} />
            ) : null}
            {label ? (
              <button type="button" tabIndex={-1} onClick={() => onPick(s.slotId)} data-flat3d="spot-label" data-place={box.place}
                className="rounded-md bg-primary px-2 py-1 text-xs text-primary shadow-md"
                style={{ position: "absolute", pointerEvents: "auto", maxWidth: box.room,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", ...box.style }}>
                {s.label}
              </button>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}

type Box = { room: number; style: React.CSSProperties; leader?: { top: number; height: number }; place: "side" | "pad-left" | "pad-right" };

/**
 * Где стоит подпись точки `p` в кадре шириной `w`. Обычно — сбоку от точки, в сторону, где шире.
 * Точка на высоте стрелок (сбоку от них): до края там ~75 px на 375 — подпись не влезает, поэтому она встаёт НАД стрелками,
 * от столбца точки к середине кадра, а к точке ведёт тонкая линия (снимки 22.10).
 */
function labelBox(p: { x: number; y: number }, w: number, pad: { l: number; r: number; t: number } | null): Box {
  if (pad && p.y + LABEL_HALF > pad.t) {
    const toLeft = p.x >= pad.r; // точка правее стрелок — подпись тянется влево
    const anchor = toLeft ? Math.min(w - EDGE, p.x + DOT_GAP) : Math.max(EDGE, p.x - DOT_GAP);
    const top = pad.t - LEADER_GAP;
    return {
      room: Math.min(LABEL_MAX, toLeft ? anchor - EDGE : w - EDGE - anchor),
      style: { top, transform: "translateY(-100%)", ...(toLeft ? { right: w - anchor } : { left: anchor }) },
      leader: { top, height: Math.max(0, p.y - DOT_R - top) },
      place: toLeft ? "pad-right" : "pad-left",
    };
  }
  const right = p.x <= w / 2;
  return {
    room: Math.min(LABEL_MAX, (right ? w - p.x : p.x) - DOT_GAP - EDGE),
    style: { top: p.y, transform: "translateY(-50%)", ...(right ? { left: p.x + DOT_GAP } : { right: w - p.x + DOT_GAP }) },
    place: "side",
  };
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
