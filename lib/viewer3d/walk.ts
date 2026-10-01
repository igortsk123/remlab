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

/**
 * Прямоугольники дверных проёмов (и открытых порталов) в координатах квартиры, см.
 *
 * ТОЛЩИНА ОБЯЗАНА ПЕРЕКРЫВАТЬ ОТСТУП ОТ СТЕН. Иначе между «внутри комнаты с отступом 28 см» и
 * «в проёме ±20 см» остаётся мёртвая полоса 8 см: шаг туда не попадает, и человек упирается в
 * дверь — из гостиной нельзя было выйти в коридор (жалоба владельца 30.09). Берём 90 см: полоса
 * ±45 см с запасом перекрывает отступ 28 см, но не выходит за ширину самого проёма.
 */
export function passages(a: Apartment, thicknessCm = 90): Passage[] {
  const out: Passage[] = [];
  // Комната с той стороны проёма должна БЫТЬ. Иначе через входную дверь человек выходит на
  // улицу и гуляет по газону (замер 30.09: ушёл на 40 см за стену дома).
  const roomBeyond = (x: number, y: number): boolean =>
    a.rooms.some((r) => x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.d);
  for (const r of a.rooms) {
    for (const o of r.openings) {
      if (o.kind === "window") continue;
      const t = thicknessCm / 2;
      if (o.wall === "south" || o.wall === "north") {
        const x0 = r.x + o.offsetCm;
        const mid = x0 + o.widthCm / 2;
        const y = o.wall === "south" ? r.y : r.y + r.d;
        const outside = o.wall === "south" ? y - 20 : y + 20;
        if (!roomBeyond(mid, outside)) continue;
        out.push({ x0, x1: x0 + o.widthCm, y0: y - t, y1: y + t });
      } else {
        const y0 = r.y + o.offsetCm;
        const mid = y0 + o.widthCm / 2;
        const x = o.wall === "west" ? r.x : r.x + r.w;
        const outside = o.wall === "west" ? x - 20 : x + 20;
        if (!roomBeyond(outside, mid)) continue;
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
