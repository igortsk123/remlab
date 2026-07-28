"use client";

// «Масштаб экрана» для слабовидящих: ступени 100/110/120/130% через data-font-scale на <html>
// (CSS zoom — globals.css), persist в localStorage; анти-FOUC — inline-скрипт в app/layout.tsx.
// Механика перенесена из sup2 (components/shared/zoom-control.tsx), UI — на классах remlab.

import { useEffect, useState } from "react";

type FontScale = "M" | "L" | "XL" | "XXL";

const STORAGE_KEY = "remlab-font-scale";
const ORDER: FontScale[] = ["M", "L", "XL", "XXL"];
const PERCENT: Record<FontScale, number> = { M: 100, L: 110, XL: 120, XXL: 130 };

function applyScale(scale: FontScale) {
  if (typeof document === "undefined") return;
  if (scale === "M") document.documentElement.removeAttribute("data-font-scale");
  else document.documentElement.setAttribute("data-font-scale", scale);
}

export function ZoomControl() {
  const [scale, setScale] = useState<FontScale>("M");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as FontScale | null;
      if (stored === "L" || stored === "XL" || stored === "XXL") {
        setScale(stored);
        applyScale(stored);
      }
    } catch { /* private mode — ок */ }
    setHydrated(true);
  }, []);

  function set(next: FontScale) {
    setScale(next);
    applyScale(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  }

  const idx = ORDER.indexOf(scale);
  const canMinus = idx > 0;
  const canPlus = idx < ORDER.length - 1;

  return (
    <span className="zoom-control" role="group" aria-label="Масштаб экрана" title="Масштаб экрана">
      <button type="button" aria-label="Уменьшить масштаб" disabled={!canMinus} onClick={() => canMinus && set(ORDER[idx - 1]!)}>−</button>
      <span aria-live="polite" className="zoom-control-value">{hydrated ? PERCENT[scale] : 100}%</span>
      <button type="button" aria-label="Увеличить масштаб" disabled={!canPlus} onClick={() => canPlus && set(ORDER[idx + 1]!)}>+</button>
    </span>
  );
}
