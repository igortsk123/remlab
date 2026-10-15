// ОБЖИТАЯ КОРОБКА: ПЛИНТУС, КАРНИЗ, ПОТОЛОЧНЫЙ СВЕТИЛЬНИК (план demo-04 п.6) — одно описание для 3D и серверного кадра.
//
// Белая коробка без плинтуса, карниза и света читается недостроем. Здесь — чистая функция без three.js: коробки в
// сантиметрах, как у проёмов (`opening-ir.ts`). Плинтус и карниз — в осях стены (x вдоль, y вверх, z в комнату), идут по
// кускам стены (`rooms.ts:wallRects`) и вырезу окна; светильник — в осях комнаты (x, высота, y плана). Браузер строит меши
// (`rooms.ts`), сервер получает то же самое (`room.fixtures_ir`, `tools/scout/opening_ir.py`). Цвета — без фантазий:
// плинтус в тон стены, карниз графитовый, светильник белый матовый.

import type { IrBox } from "@/lib/viewer3d/opening-ir";

export const SKIRTING_H = 7;
export const SKIRTING_D = 1.6;

interface Rect {
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

/** Плинтус по низу кусков стены (у двери прерывается) и карниз над каждым окном/балконом стены. */
export function wallFixturesIR(rects: Rect[], windows: { u0: number; u1: number; top: number }[], wallHeightCm: number): IrBox[] {
  const out: IrBox[] = [];
  for (const r of rects) {
    if (r.v0 > 0 || r.u1 - r.u0 < 2) continue;
    out.push({ role: "skirting", material: "skirting", w: r.u1 - r.u0, h: SKIRTING_H, d: SKIRTING_D,
      x: (r.u0 + r.u1) / 2, y: SKIRTING_H / 2, z: SKIRTING_D / 2 });
  }
  for (const w of windows) {
    // карниз: штанга шире проёма на 15 см с каждой стороны, на 12 см над ним (не выше потолка), в 10 см от стены
    const y = Math.min(w.top + 12, wallHeightCm - 6);
    const len = w.u1 - w.u0 + 30;
    const cx = (w.u0 + w.u1) / 2;
    out.push({ role: "cornice", material: "cornice", w: len, h: 2.2, d: 2.2, x: cx, y, z: 10 });
    for (const sx of [-1, 1]) {
      out.push({ role: "cornice", material: "cornice", w: 2, h: 2, d: 10, x: cx + sx * (len / 2 - 6), y, z: 5 });
    }
  }
  return out;
}

/** Потолочный светильник — плоский круглый плафон по центру комнаты (коробка 42×3×42 см, у потолка). */
export function ceilingLampIR(wCm: number, dCm: number, heightCm: number): IrBox[] {
  return [
    { role: "lamp", material: "lamp", w: 42, h: 3, d: 42, x: wCm / 2, y: heightCm - 2.5, z: dCm / 2 },
    { role: "lamp", material: "cornice", w: 10, h: 1, d: 10, x: wCm / 2, y: heightCm - 0.5, z: dCm / 2 },
  ];
}
