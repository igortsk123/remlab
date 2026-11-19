"use client";

// Окно увеличения: картинка на весь экран, на том же фоне (шахматка / тёмный / белый). Закрытие — крестик, тап по фону или Esc.

import { useEffect } from "react";
import type { Bg, ZoomTarget } from "./CutoutCheckCard";

const BG: Record<Bg, string> = {
  photo: "bg-white",
  checker: "[background:repeating-conic-gradient(#d4d4d8_0%_25%,#f4f4f5_0%_50%)_50%/24px_24px]",
  dark: "bg-[#1b1b1f]",
};

export function CutoutCheckZoom({ target, onClose }: { target: ZoomTarget; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  return (
    <div role="dialog" aria-modal="true" aria-label={`${target.label.ru} / ${target.label.en}`} className="fixed inset-0 z-50 flex flex-col bg-black/80 p-2 sm:p-6" onClick={onClose}>
      <div className="flex items-center justify-between pb-2 text-sm font-semibold text-white">
        <span>
          {target.label.ru} · {target.label.en}
        </span>
        <button type="button" onClick={onClose} aria-label="Закрыть / Close" className="grid min-h-11 min-w-11 place-items-center rounded-lg text-xl text-white ring-1 ring-white/40">
          ✕
        </button>
      </div>
      <div className={`min-h-0 flex-1 overflow-hidden rounded-lg ${BG[target.bg]}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={target.src} alt="" className="h-full w-full object-contain" />
      </div>
    </div>
  );
}
