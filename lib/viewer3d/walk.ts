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
  /** Высота, см (demo-15): низкое — столик, пуф — взгляду не мешает; высокое (шкаф, стеллаж) — закрывает предмет за ним. */
  h?: number;
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

/**
 * Запас от края мебели — 30 см (прогон d8 15.10, приёмка п.5 метрикой «≥ 25 см до ближайшего следа»): при 20 см камера на
 * высоте глаз упиралась взглядом в тумбу и стену за ней — экран целиком серый, не понять, где стоишь. Узкие щели
 * (диван — столик 40 см) от этого не проходятся, как и в жизни с камерой в руках.
 */
export const BODY_CM = 30;

export function walkArea(a: Apartment, marginCm = 28, obstacles: Obstacle[] = [], bodyCm = BODY_CM): WalkArea {
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

/** Расстояние от точки до следа предмета, см (0 — внутри). Тем же поворотом, что `insideObstacle`. */
export function obstacleDistanceCm(o: Obstacle, x: number, y: number): number {
  const r = (o.rot * Math.PI) / 180;
  const dx = x - o.x;
  const dy = y - o.y;
  const u = Math.abs(dx * Math.cos(r) - dy * Math.sin(r)) - o.w / 2;
  const v = Math.abs(dx * Math.sin(r) + dy * Math.cos(r)) - o.d / 2;
  return Math.hypot(Math.max(u, 0), Math.max(v, 0));
}

/** Внутри комнаты или проёма — без учёта мебели. */
export function inRooms(area: WalkArea, x: number, y: number): boolean {
  for (const r of area.rooms) if (insideRoom(r, x, y, area.marginCm)) return true;
  for (const p of area.passages) if (x >= p.x0 && x <= p.x1 && y >= p.y0 && y <= p.y1) return true;
  return false;
}

export function canStand(area: WalkArea, x: number, y: number): boolean {
  if (area.obstacles?.some((o) => insideObstacle(o, x, y, area.bodyCm ?? BODY_CM))) return false;
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
  const pad = area.bodyCm ?? BODY_CM;
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

/** Наведение на предмет (demo-15): не ближе 1 м к его следу, кольцо поиска точки 1–1.8 м, «высокое» закрывает взгляд от 110 см. */
export const FRAME_MIN_CM = 100;
const FRAME_RING_CM = [100, 140, 180], FRAME_TALL_CM = 110;

/**
 * ОТКУДА СМОТРЕТЬ НА ПРЕДМЕТ (demo-15, критика Codex п.5): `turn` — текущая точка годится (до следа ≥ 1 м, взгляд не закрыт
 * высоким), только поворот; `move` — ближайшая к текущей точка кольца 1–1.8 м вокруг следа, где можно стоять, предмет виден и
 * прямой путь проходим; `none` — такой нет, только поворот. `rot` — взгляд позы на предмет: (sin rot, −cos rot).
 */
export function frameSpot(area: WalkArea, cur: { x: number; y: number }, at: { x: number; y: number }): { x: number; y: number; rot: number; kind: "turn" | "move" | "none" } {
  const obs = area.obstacles ?? [];
  // след предмета — тот же, что у прогулки (её поворот и размеры), иначе «вокруг» считалось бы не от того контура
  let it: Obstacle = { x: at.x, y: at.y, w: 1, d: 1, rot: 0 }, bd = 15;
  for (const o of obs) { const d = Math.hypot(o.x - at.x, o.y - at.y); if (d < bd) { bd = d; it = o; } }
  const aim = (px: number, py: number) => (Math.atan2(it.x - px, -(it.y - py)) * 180) / Math.PI;
  const seen = (ax: number, ay: number) => {
    const n = Math.max(4, Math.ceil(Math.hypot(it.x - ax, it.y - ay) / 10));
    for (let k = 1; k < n; k++) {
      const px = ax + ((it.x - ax) * k) / n, py = ay + ((it.y - ay) * k) / n;
      if (obstacleDistanceCm(it, px, py) <= 0) return true;                 // дошли до самого предмета
      if (obs.some((o) => o !== it && (o.h ?? 0) >= FRAME_TALL_CM && obstacleDistanceCm(o, px, py) <= 0)) return false;
    }
    return true;
  };
  const path = (bx: number, by: number) => {     // у стены сама точка съёмки может не проходить — первые 40 см пути не проверяем
    const len = Math.hypot(bx - cur.x, by - cur.y), n = Math.max(2, Math.ceil(len / 10));
    for (let k = 1; k <= n; k++) {
      const px = cur.x + ((bx - cur.x) * k) / n, py = cur.y + ((by - cur.y) * k) / n;
      if (Math.hypot(px - cur.x, py - cur.y) >= 40 && !canStand(area, px, py)) return false;
    }
    return true;
  };
  if (obstacleDistanceCm(it, cur.x, cur.y) >= FRAME_MIN_CM && seen(cur.x, cur.y)) return { x: cur.x, y: cur.y, rot: aim(cur.x, cur.y), kind: "turn" };
  let best: { x: number; y: number; cost: number } | null = null;
  for (let a = 0; a < 360; a += 15) {
    const dx = Math.sin((a * Math.PI) / 180), dy = -Math.cos((a * Math.PI) / 180);
    for (const want of FRAME_RING_CM) {
      let r = 5;
      while (r < 700 && obstacleDistanceCm(it, it.x + dx * r, it.y + dy * r) < want) r += 5;
      const px = it.x + dx * r, py = it.y + dy * r;
      if (!canStand(area, px, py) || !seen(px, py) || !path(px, py)) continue;
      const cost = Math.hypot(px - cur.x, py - cur.y);
      if (!best || cost < best.cost) best = { x: px, y: py, cost };
    }
  }
  if (best) return { x: best.x, y: best.y, rot: aim(best.x, best.y), kind: "move" };
  return { x: cur.x, y: cur.y, rot: aim(cur.x, cur.y), kind: "none" };
}

