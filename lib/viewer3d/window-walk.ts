/**
 * ПОДОЙТИ К ОКНУ (T-20261112-30, владелец TG 1731: «при клике на окно к нему надо подходить, чтоб посмотреть вид из окна»). Тап или
 * клик по стеклу, раме или подоконнику в «3D» тура и /demo: человек идёт к окну тем же путём в обход мебели, что и по тапу в пол
 * (`viewer.ts:goTo` — `planRoute`), и встаёт напротив середины окна взглядом наружу по нормали — так далеко, чтобы окно по ширине
 * вошло в кадр целиком с полосой стены (`windowGap`, T-30/2), но не ближе `WINDOW_GAP_CM` и не дальше середины комнаты.
 * Мебель на этой точке — ищем свободную ближе к окну, потом дальше в комнату вдоль нормали (не сквозь мебель и не вбок за неё).
 * Попадание считаем по точке, куда луч упёрся в оболочку комнаты (`viewer.ts:windowAt`): она лежит в вырезе окна — значит, окно.
 */
import type { Room } from "@/contracts/apartment";
import { canStand, type WalkArea } from "@/lib/viewer3d/walk";

/** Ближе этого к плоскости окна не подходим, см. */
export const WINDOW_GAP_CM = 70;
/** Сколько стены с каждой стороны окна должно войти в кадр по ширине (рама, откос, штора), см (ведущий, T-30/2). */
export const WINDOW_WALL_CM = 25;
/** Дальше этого от окна не отходим: дальше — уже не «подошёл к окну», остаёмся на месте. */
const WINDOW_FAR_CM = 260;
/** Шаг поиска свободной точки вдоль нормали и вбок (вбок — не дальше половины ширины окна), см. */
const STEP_CM = 10;
/** Допуск попадания вокруг выреза: наружу — вид за окном и откосы, внутрь — подоконник и рама, см. */
const OUT_CM = 80, IN_CM = 30, EDGE_CM = 6, FLOOR_CM = 8;

export interface WindowHit {
  roomId: string;
  /** Середина окна на плоскости стены (план, см), нормаль внутрь комнаты, касательная вдоль стены. */
  cx: number;
  cy: number;
  nx: number;
  ny: number;
  widthCm: number;
  /** Размер комнаты по нормали к окну, см: дальше его половины от окна не встаём (если там свободно). */
  depthCm: number;
  /** Низ и верх выреза над полом, см. */
  sill: number;
  top: number;
}

/** Окно (или остеклённая балконная дверь), в вырез которого попала точка оболочки `x, y` (план) на высоте `h`. */
export function windowAtPoint(rooms: Room[], x: number, y: number, h: number): WindowHit | null {
  for (const r of rooms) {
    for (const o of r.openings) {
      if (o.kind !== "window" && o.kind !== "balcony") continue;
      const sill = o.kind === "balcony" ? 0 : o.sillCm ?? 90;
      const top = Math.min(r.heightCm, o.kind === "balcony" ? o.heightCm ?? 220 : sill + (o.heightCm ?? 140));
      const u = o.offsetCm + o.widthCm / 2;
      // плоскость стены, нормаль внутрь; `offsetCm` — запад→восток / юг→север, как в данных
      const [px, py, nx, ny] = o.wall === "south" ? [r.x + u, r.y, 0, 1] : o.wall === "north" ? [r.x + u, r.y + r.d, 0, -1]
        : o.wall === "west" ? [r.x, r.y + u, 1, 0] : [r.x + r.w, r.y + u, -1, 0];
      const depth = (x - px) * nx + (y - py) * ny, along = Math.abs((x - px) * ny - (y - py) * nx);
      // у балконной двери вырез до пола — пол у порога остаётся полом (шаг туда, как раньше), не «окно»
      if (depth < -OUT_CM || depth > IN_CM || along > o.widthCm / 2 + EDGE_CM || h < Math.max(sill - EDGE_CM, FLOOR_CM) || h > top + EDGE_CM) continue;
      return { roomId: r.id, cx: px, cy: py, nx, ny, widthCm: o.widthCm, depthCm: nx ? r.w : r.d, sill, top };
    }
  }
  return null;
}

/**
 * На каком расстоянии от окна оно целиком входит в кадр по ширине вместе с `WINDOW_WALL_CM` стены с каждой стороны: на телефоне
 * (узкий кадр) в 70 см было одно небо без рамы и стен (ведущий, T-30/2). `hfovDeg` — угол обзора камеры по горизонтали.
 * Не ближе `WINDOW_GAP_CM` и не дальше середины комнаты (`depthCm / 2`, но не ближе 70).
 */
export function windowGap(w: Pick<WindowHit, "widthCm" | "depthCm">, hfovDeg: number): number {
  const need = (w.widthCm / 2 + WINDOW_WALL_CM) / Math.tan((Math.max(10, Math.min(170, hfovDeg)) * Math.PI) / 360);
  const far = Math.max(WINDOW_GAP_CM, w.depthCm / 2);
  return Math.round(Math.max(WINDOW_GAP_CM, Math.min(far, need)) / STEP_CM) * STEP_CM;
}

/** Насколько дальше края окна можно отойти вбок, если напротив окна всё занято (кровать, стол), см — смотрим на окно наискось. */
const SIDE_EXTRA_CM = 60;

/** Штраф выбора точки: за каждый см вбок от оси окна и за каждый см от нужного расстояния (доля «окна в кадре»). */
const SIDE_PENALTY = 0.002, DEPTH_PENALTY = 0.001;

/**
 * Где встать у окна. Кандидаты — от `gapCm` (`windowGap`) до `WINDOW_GAP_CM` ближе к окну, вбок до `SIDE_EXTRA_CM` за край окна
 * (окно наискось). Выбор — по доле окна с полосой стены, что входит в кадр шириной `hfovDeg` (взгляд — на середину окна), минус
 * штраф за уход вбок и от нужного расстояния: T-30/2 — в спальне перед окном кровать, ближайшая свободная точка напротив была в
 * 80 см, и в кадре было одно небо; сбоку на нужном расстоянии окно видно целиком. Без `hfovDeg` — ближе к оси и к `gapCm`.
 * Перед окном всё занято — дальше в комнату (до `WINDOW_FAR_CM`) в пределах ширины окна. Негде — `null`.
 */
export function windowSpot(area: WalkArea, w: WindowHit, gapCm = WINDOW_GAP_CM, hfovDeg?: number): { x: number; y: number; heading: number; gapCm: number } | null {
  const tx = -w.ny, ty = w.nx, snap = (v: number) => Math.max(0, Math.floor(v / STEP_CM)) * STEP_CM;
  const narrow = snap(w.widthCm / 2), wide = snap(w.widthCm / 2 + SIDE_EXTRA_CM), half = w.widthCm / 2 + WINDOW_WALL_CM;
  const want = Math.max(WINDOW_GAP_CM, Math.min(WINDOW_FAR_CM, gapCm)), closer: number[] = [], farther: number[] = [];
  for (let d = want; d >= WINDOW_GAP_CM; d -= STEP_CM) closer.push(d);
  for (let d = want + STEP_CM; d <= WINDOW_FAR_CM; d += STEP_CM) farther.push(d);
  // доля окна с полосой стены в кадре: половина угла обзора / наибольший угол от середины окна до его края (вдоль стены)
  const fit = (d: number, s: number): number => {
    if (!hfovDeg) return 1;
    const c = Math.atan2(-s, d), need = Math.max(Math.abs(Math.atan2(half - s, d) - c), Math.abs(Math.atan2(-half - s, d) - c));
    return Math.min(1, (hfovDeg * Math.PI) / 360 / Math.max(need, 1e-6));
  };
  for (const [depths, side] of [[closer, wide], [farther, narrow]] as const) {
    let best: { x: number; y: number; d: number; score: number } | null = null;
    for (const d of depths) {
      for (let s = 0; s <= side; s += STEP_CM) {
        for (const sg of s ? [1, -1] : [0]) {
          const x = w.cx + w.nx * d + tx * s * sg, y = w.cy + w.ny * d + ty * s * sg;
          const score = fit(d, s) - SIDE_PENALTY * s - DEPTH_PENALTY * Math.abs(d - want);
          if ((!best || score > best.score + 1e-9) && canStand(area, x, y)) best = { x, y, d, score };
        }
      }
    }
    // взгляд на середину окна: heading прогулки — 0 вдоль +y, направление (sin, cos); напротив середины — по нормали наружу
    if (best) return { x: best.x, y: best.y, heading: ((Math.atan2(w.cx - best.x, w.cy - best.y) * 180) / Math.PI + 360) % 360, gapCm: best.d };
  }
  return null;
}
