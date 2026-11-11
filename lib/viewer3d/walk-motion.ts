// Ход камеры прогулки: шаг со скольжением вдоль стены/косяка/мебели и путь «иди сюда» в обход мебели. Чистая геометрия
// (без three.js) — гоняется тестами (`tests/unit/flat3d-walk-motion.test.ts`).
//
// ПОЧЕМУ ТАК (T-20261111-14, владелец TG 1023: «прогулка с компьютера дёргается в проходах»). Прежний шаг (`stepWithSlide`)
// при упоре пробовал ход только по X, только по Y и поворот на 30…120° в обе стороны. У косяка и у кухонного гарнитура рядом
// с дверью это давало качели: кадр — шаг вбок-вперёд, следующий — назад (замер модели квартиры /flat: 132 из 132 проходов к
// дверям с рывками, до 288 разворотов на 180° за проход). Теперь упор гасит только составляющую хода «в препятствие», а
// касательная сохраняется — камера скользит вдоль преграды и никогда не идёт назад. Обход мебели на пути к точке тапа
// делает не шаг, а путь по сетке (`planRoute`), поэтому шагу метаться незачем.

import { canStand, inRooms, type WalkArea } from "@/lib/viewer3d/walk";

export interface Pt {
  x: number;
  y: number;
}

/** Доля хода (0…1), которую можно пройти по прямой: делением пополам, точность ~1 %. */
function reach(area: WalkArea, from: Pt, dx: number, dy: number): number {
  let lo = 0;
  let hi = 1;
  for (let k = 0; k < 7; k += 1) {
    const mid = (lo + hi) / 2;
    if (canStand(area, from.x + dx * mid, from.y + dy * mid)) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Нормаль преграды в точке упора: среднее направлений к проходимым точкам кольца 8 см (стена — поперёк, угол — по биссектрисе). */
function freeNormal(area: WalkArea, x: number, y: number): Pt | null {
  let nx = 0;
  let ny = 0;
  for (let a = 0; a < 16; a += 1) {
    const ang = (a / 16) * Math.PI * 2;
    const ux = Math.cos(ang);
    const uy = Math.sin(ang);
    if (canStand(area, x + ux * 8, y + uy * 8)) {
      nx += ux;
      ny += uy;
    }
  }
  const len = Math.hypot(nx, ny);
  return len > 1e-6 ? { x: nx / len, y: ny / len } : null;
}

/**
 * Шаг прогулки: прямой ход, а при упоре — до преграды и дальше вдоль неё (касательная составляющая хода). Назад не идёт:
 * если вдоль преграды хода по желаемому направлению нет (упёрлись в лоб или в угол) — стоим у преграды.
 * Стоим вне проходимого (поставили в след предмета) — выйти можно, лишь бы не в стену.
 */
export function slideStep(area: WalkArea, from: Pt, dx: number, dy: number, memo?: SlideMemo): Pt {
  const direct = { x: from.x + dx, y: from.y + dy };
  if (canStand(area, direct.x, direct.y)) {
    // сторону забываем не сразу: у скошенного края прямой ход открывается на кадр-другой — иначе обход метался бы
    if (memo && ++memo.free >= 12) memo.side = 0;
    return direct;
  }
  if (memo) memo.free = 0;
  if (!canStand(area, from.x, from.y)) return inRooms(area, direct.x, direct.y) ? direct : { ...from };
  const slid = slideAlong(area, from, dx, dy);
  const len = Math.hypot(dx, dy);
  if (!memo || Math.hypot(slid.x - from.x, slid.y - from.y) >= 0.15 * len) return slid;
  // ПОЧТИ В ЛОБ (касательной нет): предмет у двери перегородил часть проёма (гарнитур кухни /flat). Отклоняемся на 25…45° —
  // всегда вперёд, сторона ЛИПКАЯ (`memo`), пока прямой ход снова не откроется: качелей «влево — вправо» не будет
  const sides = memo.side ? [memo.side] : [1, -1];
  for (const s of sides) {
    for (const deg of [25, 45]) {
      const r = (s * deg * Math.PI) / 180;
      const ex = dx * Math.cos(r) - dy * Math.sin(r);
      const ey = dx * Math.sin(r) + dy * Math.cos(r);
      if (canStand(area, from.x + ex, from.y + ey) && canStand(area, from.x + ex * 3, from.y + ey * 3)) {
        memo.side = s;
        return { x: from.x + ex, y: from.y + ey };
      }
    }
  }
  return slid;
}

/** Сторона обхода «почти в лоб» (+1 / −1, 0 — не выбрана): держит владелец шага (`viewer`), чтобы отклонение не металось. */
export interface SlideMemo {
  side: number;
  /** Кадров подряд со свободным прямым ходом. */
  free: number;
}

/** До преграды и дальше вдоль неё: касательная составляющая остатка хода; назад не идёт. */
function slideAlong(area: WalkArea, from: Pt, dx: number, dy: number): Pt {
  const t = reach(area, from, dx, dy);
  const contact = { x: from.x + dx * t, y: from.y + dy * t };
  const n = freeNormal(area, from.x + dx * Math.min(1, t + 0.02), from.y + dy * Math.min(1, t + 0.02));
  if (!n) return contact;
  let rx = dx * (1 - t);
  let ry = dy * (1 - t);
  const into = rx * n.x + ry * n.y;
  if (into < 0) {
    rx -= into * n.x;
    ry -= into * n.y;
  }
  if (rx * dx + ry * dy <= 1e-6) return contact;
  const t2 = reach(area, contact, rx, ry);
  return { x: contact.x + rx * t2, y: contact.y + ry * t2 };
}

/** Видно ли по прямой (шаг 5 см): по такому отрезку человек проходит без упора. */
export function clearLine(area: WalkArea, a: Pt, b: Pt): boolean {
  const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 5));
  for (let k = 1; k <= n; k += 1) {
    if (!canStand(area, a.x + ((b.x - a.x) * k) / n, a.y + ((b.y - a.y) * k) / n)) return false;
  }
  return true;
}

/** Мин-куча по цене для A*: [цена, клетка]. */
function heapPush(h: [number, number][], v: [number, number]): void {
  h.push(v);
  let i = h.length - 1;
  while (i > 0) {
    const p = (i - 1) >> 1;
    if (h[p]![0] <= h[i]![0]) break;
    [h[p], h[i]] = [h[i]!, h[p]!];
    i = p;
  }
}

function heapPop(h: [number, number][]): [number, number] | undefined {
  const top = h[0];
  const last = h.pop();
  if (h.length && last) {
    h[0] = last;
    let i = 0;
    for (;;) {
      const l = 2 * i + 1;
      const r = l + 1;
      let m = i;
      if (l < h.length && h[l]![0] < h[m]![0]) m = l;
      if (r < h.length && h[r]![0] < h[m]![0]) m = r;
      if (m === i) break;
      [h[m], h[i]] = [h[i]!, h[m]!];
      i = m;
    }
  }
  return top;
}

/**
 * Путь «иди сюда» (тап по полу): A* по сетке проходимого с шагом `cellCm`, без срезания углов, затем «натянутая нить» —
 * из каждой точки к самой дальней видимой. Ответ — точки поворота до `to` (без `from`); пути нет — null (идём по прямой).
 */
export function planRoute(area: WalkArea, from: Pt, to: Pt, cellCm = 10): Pt[] | null {
  if (clearLine(area, from, to)) return [{ ...to }];
  const xs = area.rooms.flatMap((r) => [r.x, r.x + r.w]);
  const ys = area.rooms.flatMap((r) => [r.y, r.y + r.d]);
  const x0 = Math.min(...xs);
  const y0 = Math.min(...ys);
  const nx = Math.ceil((Math.max(...xs) - x0) / cellCm) + 1;
  const ny = Math.ceil((Math.max(...ys) - y0) / cellCm) + 1;
  if (nx * ny > 60_000) return null;
  const cx = (i: number): number => x0 + (i % nx) * cellCm;
  const cy = (i: number): number => y0 + Math.floor(i / nx) * cellCm;
  const free = new Int8Array(nx * ny).fill(-1); // -1 не проверено, 0 нельзя, 1 можно
  const ok = (i: number): boolean => {
    if (free[i] === -1) free[i] = canStand(area, cx(i), cy(i)) ? 1 : 0;
    return free[i] === 1;
  };
  const cellOf = (p: Pt): number =>
    Math.min(ny - 1, Math.max(0, Math.round((p.y - y0) / cellCm))) * nx + Math.min(nx - 1, Math.max(0, Math.round((p.x - x0) / cellCm)));
  // старт и цель — ближайшие проходимые клетки, с которыми точка связана прямой
  const near = (p: Pt): number => {
    const c = cellOf(p);
    let best = -1;
    let bd = Infinity;
    for (let dy = -2; dy <= 2; dy += 1) {
      for (let dx = -2; dx <= 2; dx += 1) {
        const ix = (c % nx) + dx;
        const iy = Math.floor(c / nx) + dy;
        if (ix < 0 || iy < 0 || ix >= nx || iy >= ny) continue;
        const i = iy * nx + ix;
        const d = Math.hypot(cx(i) - p.x, cy(i) - p.y);
        if (d < bd && ok(i) && clearLine(area, p, { x: cx(i), y: cy(i) })) {
          bd = d;
          best = i;
        }
      }
    }
    return best;
  };
  const s = near(from);
  const g = near(to);
  if (s < 0) return null;
  const cost = new Float32Array(nx * ny).fill(Infinity);
  const prev = new Int32Array(nx * ny).fill(-1);
  const heap: [number, number][] = [];
  const hz = (i: number): number => Math.hypot(cx(i) - to.x, cy(i) - to.y);
  cost[s] = 0;
  heapPush(heap, [hz(s), s]);
  // цель за мебелью, куда не пройти (тап по полу за диваном у стены): идём к ближайшей к ней достижимой точке и встаём,
  // а не упираемся в спинку — прежде тут шаг качался «вперёд — назад» (тур «Этажи», гостиная: 199,214 ↔ 186,215)
  let closest = s;
  const STEPS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]] as const;
  for (let top = heapPop(heap); top; top = heapPop(heap)) {
    const i = top[1];
    if (i === g) break;
    if (top[0] > cost[i]! + hz(i) + 1e-3) continue;
    if (hz(i) < hz(closest)) closest = i;
    const ix = i % nx;
    const iy = Math.floor(i / nx);
    for (const [dx, dy] of STEPS) {
      const jx = ix + dx;
      const jy = iy + dy;
      if (jx < 0 || jy < 0 || jx >= nx || jy >= ny) continue;
      const j = jy * nx + jx;
      if (!ok(j)) continue;
      if (dx && dy && (!ok(iy * nx + jx) || !ok(jy * nx + ix))) continue; // угол не срезаем
      const c = cost[i]! + (dx && dy ? Math.SQRT2 : 1) * cellCm;
      if (c < cost[j]!) {
        cost[j] = c;
        prev[j] = i;
        heapPush(heap, [c + hz(j), j]);
      }
    }
  }
  const reached = g >= 0 && (g === s || prev[g] !== -1);
  const end = reached ? g : closest;
  const cells: Pt[] = [];
  for (let i = end; i !== -1; i = prev[i]!) cells.push({ x: cx(i), y: cy(i) });
  cells.reverse();
  if (reached) cells.push({ ...to });
  // натянутая нить: из текущей точки — к самой дальней точке пути, видимой по прямой
  const out: Pt[] = [];
  let cur: Pt = from;
  let k = 0;
  while (k < cells.length) {
    let far = k;
    for (let j = cells.length - 1; j > k; j -= 1) {
      if (clearLine(area, cur, cells[j]!)) {
        far = j;
        break;
      }
    }
    out.push(cells[far]!);
    cur = cells[far]!;
    k = far + 1;
  }
  return out;
}

/** Ход по пути «иди сюда» на один кадр. */
export interface RouteState {
  pts: Pt[];
  /** Лучший остаток до цели и сколько кадров подряд без продвижения — стоп, если упёрлись. */
  best: number;
  idle: number;
}

export function newRoute(pts: Pt[]): RouteState {
  return { pts, best: Infinity, idle: 0 };
}

function routeLeft(pos: Pt, pts: Pt[]): number {
  let d = 0;
  let cur = pos;
  for (const p of pts) {
    d += Math.hypot(p.x - cur.x, p.y - cur.y);
    cur = p;
  }
  return d;
}

/**
 * Один кадр по пути: `stepCm` вдоль ломаной (остаток шага переходит на следующий отрезок — на повороте скорость не
 * проседает), каждый кусок — через `slideStep`. `aim` — точка в ~`lookCm` впереди по пути: туда плавно поворачивается взгляд,
 * поэтому на изломе пути камера не дёргается курсом. `done` — дошли или 9 кадров без продвижения.
 */
export function followRoute(area: WalkArea, pos: Pt, route: RouteState, stepCm: number, lookCm = 60): { pos: Pt; done: boolean; aim: Pt | null } {
  let p = { ...pos };
  let left = stepCm;
  while (left > 1e-3 && route.pts.length) {
    const w = route.pts[0]!;
    const d = Math.hypot(w.x - p.x, w.y - p.y);
    if (d <= left) {
      const n = slideStep(area, p, w.x - p.x, w.y - p.y);
      left -= Math.hypot(n.x - p.x, n.y - p.y);
      p = n;
      if (Math.hypot(w.x - p.x, w.y - p.y) > 1) break; // не дошли до точки поворота — упор
      route.pts.shift();
    } else {
      p = slideStep(area, p, ((w.x - p.x) / d) * left, ((w.y - p.y) / d) * left);
      left = 0;
    }
  }
  const rest = routeLeft(p, route.pts);
  if (rest <= route.best - stepCm / 4) {
    route.best = rest;
    route.idle = 0;
  } else route.idle += 1;
  const done = route.pts.length === 0 || rest < 3 || route.idle >= 9;
  // точка взгляда — на lookCm вперёд по пути
  let aim: Pt | null = null;
  let need = lookCm;
  let cur = p;
  for (const w of route.pts) {
    const d = Math.hypot(w.x - cur.x, w.y - cur.y);
    if (d >= need) {
      aim = { x: cur.x + ((w.x - cur.x) / d) * need, y: cur.y + ((w.y - cur.y) / d) * need };
      break;
    }
    need -= d;
    cur = w;
    aim = w;
  }
  return { pos: p, done, aim };
}
