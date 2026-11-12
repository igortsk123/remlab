"use client";

// Увеличение на весь экран (T-20261112-118): компьютер — фото и модель рядом, телефон — одно из двух, переключатель и смахивание
// вбок; щипок — родное увеличение браузера, колесо — своё (1–4×). Снимок модели 1024 px; где партия моделей залита — «покрутить 3D»
// (тот же model-viewer, что на /lab/mesh-audit). Esc — закрыть, ← → — соседняя карточка. Кнопки «ок»/«брак» — те же, что в карточке.

import { useEffect, useRef, useState } from "react";
import type { AuditItemView } from "@/lib/mesh-audit/types";
import type { ZoomWhich } from "./MeshCheckCard";
import { MeshCheckPresses } from "./MeshCheckPresses";
import { useReviewer } from "./MeshCheckReviewer";
import { useMeshPress } from "./useMeshPress";

interface Props {
  item: AuditItemView;
  which: ZoomWhich;
  modelUrl: string | null;
  onWhich: (w: ZoomWhich) => void;
  onClose: () => void;
  onNav: (step: -1 | 1) => void;
  onChange: (it: AuditItemView) => void;
}

function Wheel({ src, alt }: { src: string | null; alt: string }) {
  const [z, setZ] = useState({ s: 1, x: 50, y: 50 });
  useEffect(() => setZ({ s: 1, x: 50, y: 50 }), [src]);
  if (!src) return <span className="flex h-full items-center justify-center text-sm text-tertiary">снимка ещё нет</span>;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      className="h-full w-full object-contain transition-transform duration-100"
      style={{ transform: `scale(${z.s})`, transformOrigin: `${z.x}% ${z.y}%` }}
      onWheel={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const s = Math.min(4, Math.max(1, z.s * (e.deltaY < 0 ? 1.25 : 0.8)));
        setZ({ s, x: ((e.clientX - r.left) / r.width) * 100, y: ((e.clientY - r.top) / r.height) * 100 });
      }}
      onDoubleClick={() => setZ({ s: 1, x: 50, y: 50 })}
    />
  );
}

export function MeshCheckZoom({ item, which, modelUrl, onWhich, onClose, onNav, onChange }: Props) {
  const reviewer = useReviewer();
  const { busy, error, press } = useMeshPress(item, reviewer, onChange);
  const [show3d, setShow3d] = useState(false);
  const touch = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => setShow3d(false), [item.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onNav(-1);
      else if (e.key === "ArrowRight") onNav(1);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose, onNav]);

  const fig = (w: ZoomWhich) =>
    `relative min-h-0 overflow-hidden rounded-xl ${w === which ? "block" : "hidden"} lg:block ${w === "photo" ? "bg-primary" : "bg-secondary"}`;
  const tag = "absolute top-2 left-2 z-10 rounded-md bg-primary px-2 py-0.5 text-xs font-semibold text-secondary";

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-primary-solid"
      role="dialog"
      aria-modal="true"
      aria-label={item.name ?? item.sku}
      onTouchStart={(e) => (touch.current = e.touches.length === 1 ? { x: e.touches[0]!.clientX, y: e.touches[0]!.clientY } : null)}
      onTouchEnd={(e) => {
        const t = touch.current;
        touch.current = null;
        const dx = t ? e.changedTouches[0]!.clientX - t.x : 0;
        const dy = t ? e.changedTouches[0]!.clientY - t.y : 0;
        if ((window.visualViewport?.scale ?? 1) > 1.05 || Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        onWhich(which === "photo" ? "model" : "photo"); // смахнули вбок — другая картинка той же карточки
      }}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <span className="truncate text-sm text-white">{item.name ?? item.sku}</span>
        <button type="button" onClick={onClose} aria-label="Закрыть" className="min-h-11 min-w-11 rounded-lg bg-primary/10 text-xl text-white">
          ×
        </button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 px-2 lg:grid-cols-2">
        <figure className={fig("photo")}>
          <figcaption className={tag}>фото</figcaption>
          <Wheel src={item.imageUrl} alt="фото товара" />
        </figure>
        <figure className={fig("model")}>
          <figcaption className={tag}>модель</figcaption>
          {show3d && modelUrl ? (
            <model-viewer src={modelUrl} alt="3D-модель" camera-controls="" auto-rotate="" style={{ width: "100%", height: "100%" }} />
          ) : (
            <Wheel src={item.posterHdUrl ?? item.posterUrl} alt="снимок модели" />
          )}
          {modelUrl && !show3d && (
            <button type="button" onClick={() => setShow3d(true)} className="absolute right-2 bottom-2 min-h-11 rounded-lg bg-primary px-3 text-sm font-semibold text-secondary shadow-xs ring-1 ring-secondary">
              ▶ покрутить 3D
            </button>
          )}
        </figure>
      </div>
      <div className="mx-auto flex w-full max-w-lg flex-col gap-2 px-3 pt-2 pb-3">
        <div className="mx-auto flex overflow-hidden rounded-lg ring-1 ring-secondary_alt lg:hidden" role="group" aria-label="Что показать">
          {(["photo", "model"] as const).map((w) => (
            <button key={w} type="button" aria-pressed={w === which} onClick={() => onWhich(w)} className={`min-h-11 px-5 text-sm ${w === which ? "bg-primary font-semibold text-primary" : "text-white"}`}>
              {w === "photo" ? "фото" : "модель"}
            </button>
          ))}
        </div>
        <MeshCheckPresses mark={item.mark} busy={busy} onPress={press} dark />
        {error && <p className="text-center text-xs text-error-primary">{error}</p>}
        <p className="text-center text-xs text-quaternary lg:hidden">щипком увеличить · смахнуть вбок: фото / модель</p>
        <p className="hidden text-center text-xs text-quaternary lg:block">колёсиком увеличить · Esc закрыть · ← → соседняя карточка</p>
      </div>
    </div>
  );
}
