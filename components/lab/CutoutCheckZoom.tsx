"use client";

// Окно увеличения: картинка на весь экран на том же фоне (шахматка / тёмный / белый), чтобы кромку смотреть при 200–400 %.
// Колёсико и щипок двумя пальцами — масштаб ×1…×8 к точке под курсором/пальцами; тащить — двигать; двойной тап — ×3 / обратно.
// Закрытие — крестик, Esc или кнопка «закрыть» внизу (тап по картинке не закрывает: тапы нужны для сдвига).

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Bg, ZoomTarget } from "./CutoutCheckCard";

const BG: Record<Bg, string> = {
  photo: "bg-white",
  checker: "[background:repeating-conic-gradient(#d4d4d8_0%_25%,#f4f4f5_0%_50%)_50%/24px_24px]",
  dark: "bg-[#1b1b1f]",
};
const MAX = 8;

interface View {
  s: number;
  x: number;
  y: number;
}

/** Новый вид при масштабе к точке (px,py) внутри рамки: точка под пальцем остаётся на месте. Размеры рамки — w×h, картинка по центру. */
export function zoomAt(v: View, factor: number, px: number, py: number, w: number, h: number): View {
  const s = Math.min(MAX, Math.max(1, v.s * factor));
  if (s === 1) return { s: 1, x: 0, y: 0 };
  const k = s / v.s;
  const cx = px - w / 2;
  const cy = py - h / 2;
  const x = cx - (cx - v.x) * k;
  const y = cy - (cy - v.y) * k;
  const mx = (w * (s - 1)) / 2;
  const my = (h * (s - 1)) / 2;
  return { s, x: Math.max(-mx, Math.min(mx, x)), y: Math.max(-my, Math.min(my, y)) };
}

export function CutoutCheckZoom({ target, onClose }: { target: ZoomTarget; onClose: () => void }) {
  const frame = useRef<HTMLDivElement | null>(null);
  const [v, setV] = useState<View>({ s: 1, x: 0, y: 0 });
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const last = useRef<{ d: number; mx: number; my: number; tap: number } | null>(null);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const rect = () => frame.current?.getBoundingClientRect();
  const at = useCallback((f: number, cx: number, cy: number) => {
    const r = frame.current?.getBoundingClientRect();
    if (r) setV((o) => zoomAt(o, f, cx - r.left, cy - r.top, r.width, r.height));
  }, []);

  // колёсико: нативным слушателем без passive, иначе страница под окном прокручивается
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const w = (e: WheelEvent) => {
      e.preventDefault();
      at(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
    };
    el.addEventListener("wheel", w, { passive: false });
    return () => el.removeEventListener("wheel", w);
  }, [at]);

  const centre = () => {
    const p = [...pts.current.values()];
    return { mx: p.reduce((a, b) => a + b.x, 0) / p.length, my: p.reduce((a, b) => a + b.y, 0) / p.length, d: p.length > 1 ? Math.hypot(p[0]!.x - p[1]!.x, p[0]!.y - p[1]!.y) : 0 };
  };
  const down = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const c = centre();
    const prev = last.current;
    const now = Date.now();
    if (pts.current.size === 1 && prev && now - prev.tap < 300) {
      at(v.s > 1 ? 1 / v.s : 3, e.clientX, e.clientY); // двойной тап
      last.current = { ...c, tap: 0 };
      return;
    }
    last.current = { ...c, tap: pts.current.size === 1 ? now : 0 };
  };
  const move = (e: React.PointerEvent) => {
    if (!pts.current.has(e.pointerId)) return;
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const c = centre();
    const l = last.current;
    const r = rect();
    if (!l || !r) return;
    if (pts.current.size > 1 && l.d > 0 && c.d > 0) {
      at(c.d / l.d, c.mx, c.my); // щипок
    }
    const dx = c.mx - l.mx;
    const dy = c.my - l.my;
    if (Math.abs(dx) + Math.abs(dy) > 0) {
      setV((o) => {
        const mx = (r.width * (o.s - 1)) / 2;
        const my = (r.height * (o.s - 1)) / 2;
        return o.s === 1 ? o : { s: o.s, x: Math.max(-mx, Math.min(mx, o.x + dx)), y: Math.max(-my, Math.min(my, o.y + dy)) };
      });
    }
    last.current = { ...c, tap: Math.abs(dx) + Math.abs(dy) > 3 ? 0 : l.tap };
  };
  const up = (e: React.PointerEvent) => {
    pts.current.delete(e.pointerId);
    if (pts.current.size > 0) last.current = { ...centre(), tap: 0 };
  };

  if (typeof document === "undefined") return null;
  // в body и поверх всего: липкие разделы страницы не должны просвечивать сквозь окно
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`${target.label.ru} / ${target.label.en}`} style={{ zIndex: 1000, background: "rgba(10,10,12,0.92)" }} className="fixed inset-0 flex flex-col p-2 sm:p-6">
      <div className="flex items-center justify-between gap-2 pb-2 text-sm font-semibold text-white">
        <span className="flex flex-col leading-tight">
          <span>{target.label.ru}</span>
          <span className="text-xs font-normal opacity-80">
            {target.label.en} · ×{v.s.toFixed(1)}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <button type="button" onClick={() => setV({ s: 1, x: 0, y: 0 })} className="min-h-11 rounded-lg px-3 text-xs text-white ring-1 ring-white/40">
            ×1
          </button>
          <button type="button" onClick={onClose} aria-label="Закрыть / Close" className="grid min-h-11 min-w-11 place-items-center rounded-lg text-xl text-white ring-1 ring-white/40">
            ✕
          </button>
        </span>
      </div>
      <div
        ref={frame}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        className={`min-h-0 flex-1 touch-none overflow-hidden rounded-lg select-none ${BG[target.bg]} ${v.s > 1 ? "cursor-grab" : "cursor-zoom-in"}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={target.src} alt="" draggable={false} style={{ transform: `translate(${v.x}px, ${v.y}px) scale(${v.s})` }} className="h-full w-full object-contain" />
      </div>
      <p className="pt-2 text-center text-xs text-white/70">
        колёсико / щипок — увеличить, тащить — двигать, двойной тап — ×3 · wheel / pinch to zoom, drag to pan, double-tap ×3
      </p>
    </div>,
    document.body,
  );
}
