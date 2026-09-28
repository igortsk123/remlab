// Где человек может стоять. Чистая геометрия (без three.js) — гоняется тестами.
//
// Правило простое: внутри комнаты с отступом от стен ИЛИ в дверном проёме между комнатами.
// Без второго условия пройти из комнаты в комнату нельзя — отступ от стены закрывает дверь.

import type { Apartment, Room } from "@/contracts/apartment";

export interface Passage {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** Прямоугольники дверных проёмов (и открытых порталов) в координатах квартиры, см. */
export function passages(a: Apartment, thicknessCm = 40): Passage[] {
  const out: Passage[] = [];
  for (const r of a.rooms) {
    for (const o of r.openings) {
      if (o.kind === "window") continue;
      const t = thicknessCm / 2;
      if (o.wall === "south" || o.wall === "north") {
        const x0 = r.x + o.offsetCm;
        const y = o.wall === "south" ? r.y : r.y + r.d;
        out.push({ x0, x1: x0 + o.widthCm, y0: y - t, y1: y + t });
      } else {
        const y0 = r.y + o.offsetCm;
        const x = o.wall === "west" ? r.x : r.x + r.w;
        out.push({ x0: x - t, x1: x + t, y0, y1: y0 + o.widthCm });
      }
    }
  }
  return out;
}

function insideRoom(r: Room, x: number, y: number, marginCm: number): boolean {
  return (
    x >= r.x + marginCm && x <= r.x + r.w - marginCm && y >= r.y + marginCm && y <= r.y + r.d - marginCm
  );
}

export interface WalkArea {
  rooms: Room[];
  passages: Passage[];
  marginCm: number;
}

export function walkArea(a: Apartment, marginCm = 28): WalkArea {
  return { rooms: a.rooms, passages: passages(a), marginCm };
}

export function canStand(area: WalkArea, x: number, y: number): boolean {
  for (const r of area.rooms) if (insideRoom(r, x, y, area.marginCm)) return true;
  for (const p of area.passages) if (x >= p.x0 && x <= p.x1 && y >= p.y0 && y <= p.y1) return true;
  return false;
}

/**
 * Шаг с «скольжением вдоль стены»: если прямой ход упёрся, пробуем идти только по X или
 * только по Y. Так человек не залипает в углу — приём взят из перетаскивания мебели в демо.
 */
export function stepWithSlide(
  area: WalkArea,
  from: { x: number; y: number },
  dx: number,
  dy: number,
): { x: number; y: number } {
  const direct = { x: from.x + dx, y: from.y + dy };
  if (canStand(area, direct.x, direct.y)) return direct;
  const alongX = { x: from.x + dx, y: from.y };
  if (dx !== 0 && canStand(area, alongX.x, alongX.y)) return alongX;
  const alongY = { x: from.x, y: from.y + dy };
  if (dy !== 0 && canStand(area, alongY.x, alongY.y)) return alongY;
  return from;
}

/** Ближайшая точка, где можно стоять — для телепорта в комнату и для тапа мимо пола. */
export function nearestStandable(
  area: WalkArea,
  x: number,
  y: number,
  stepCm = 10,
  maxRings = 12,
): { x: number; y: number } | null {
  if (canStand(area, x, y)) return { x, y };
  for (let ring = 1; ring <= maxRings; ring += 1) {
    const r = ring * stepCm;
    for (let a = 0; a < 16; a += 1) {
      const ang = (a / 16) * Math.PI * 2;
      const px = x + Math.cos(ang) * r;
      const py = y + Math.sin(ang) * r;
      if (canStand(area, px, py)) return { x: px, y: py };
    }
  }
  return null;
}
