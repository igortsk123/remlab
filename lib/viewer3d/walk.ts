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

/** След предмета на полу (см, координаты квартиры): центр, размеры, поворот как у `placeGroup` (ось ширины (cos, −sin)). */
export interface Obstacle {
  x: number;
  y: number;
  w: number;
  d: number;
  rot: number;
}

export interface WalkArea {
  rooms: Room[];
  passages: Passage[];
  marginCm: number;
  /** Мебель: сквозь неё не ходят (demo-05 п.5 — камера оказывалась внутри абажура торшера). */
  obstacles: Obstacle[];
  /** Полуширина человека: столько держим от края предмета. */
  bodyCm: number;
}

export function walkArea(a: Apartment, marginCm = 28, obstacles: Obstacle[] = [], bodyCm = 20): WalkArea {
  return { rooms: a.rooms, passages: passages(a), marginCm, obstacles, bodyCm };
}

function insideObstacle(o: Obstacle, x: number, y: number, pad: number): boolean {
  const r = (o.rot * Math.PI) / 180;
  const dx = x - o.x;
  const dy = y - o.y;
  const u = dx * Math.cos(r) - dy * Math.sin(r); // вдоль ширины
  const v = dx * Math.sin(r) + dy * Math.cos(r); // вдоль глубины
  return Math.abs(u) <= o.w / 2 + pad && Math.abs(v) <= o.d / 2 + pad;
}

/** Внутри комнаты или проёма — без учёта мебели. */
function inRooms(area: WalkArea, x: number, y: number): boolean {
  for (const r of area.rooms) if (insideRoom(r, x, y, area.marginCm)) return true;
  for (const p of area.passages) if (x >= p.x0 && x <= p.x1 && y >= p.y0 && y <= p.y1) return true;
  return false;
}

export function canStand(area: WalkArea, x: number, y: number): boolean {
  if (area.obstacles?.some((o) => insideObstacle(o, x, y, area.bodyCm ?? 20))) return false;
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
  // уже стоим в следе предмета (поставили туда, предмет передвинули рядом) — выйти можно, лишь бы не в стену
  if (!canStand(area, from.x, from.y) && inRooms(area, direct.x, direct.y)) return direct;
  const pad = area.bodyCm ?? 20;
  const block = area.obstacles?.find((o) => insideObstacle(o, direct.x, direct.y, pad));
  const slide = (): { x: number; y: number } | null => {
    // шаг вдоль оси с ничтожной длиной (sin π ≈ 1e-16) — это «стоять на месте», а не скольжение: пропускаем,
    // иначе человек замирал перед препятствием, идя строго по оси
    const alongX = { x: from.x + dx, y: from.y };
    if (Math.abs(dx) > 1e-3 && canStand(area, alongX.x, alongX.y)) return alongX;
    const alongY = { x: from.x, y: from.y + dy };
    if (Math.abs(dy) > 1e-3 && canStand(area, alongY.x, alongY.y)) return alongY;
    return null;
  };
  // ОБХОД МЕБЕЛИ (demo-05 п.5): путь перегородил ПРЕДМЕТ — отклоняемся на 30…120° сначала в ту сторону, куда человек
  // уже смещён от центра предмета (иначе шаг метался бы «вбок — снова прямо»); скольжение вдоль осей — для стен, у
  // предмета оно тянуло обратно к его середине
  const detour = (): { x: number; y: number } | null => {
    const side = block ? Math.sign(dx * (from.y - block.y) - dy * (from.x - block.x)) || 1 : 1;
    for (const deg of [30, 60, 90, 120].map((d) => side * d).concat([30, 60, 90, 120].map((d) => -side * d))) {
      const r = (deg * Math.PI) / 180;
      const p = { x: from.x + dx * Math.cos(r) - dy * Math.sin(r), y: from.y + dx * Math.sin(r) + dy * Math.cos(r) };
      if (canStand(area, p.x, p.y)) return p;
    }
    return null;
  };
  return (block ? detour() ?? slide() : slide() ?? detour()) ?? from;
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
