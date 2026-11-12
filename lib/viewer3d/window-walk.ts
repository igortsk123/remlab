/**
 * ПОДОЙТИ К ОКНУ (T-20261112-30, владелец TG 1731: «при клике на окно к нему надо подходить, чтоб посмотреть вид из окна»). Тап или
 * клик по стеклу, раме или подоконнику в «3D» тура и /demo: человек идёт к окну тем же путём в обход мебели, что и по тапу в пол
 * (`viewer.ts:goTo` — `planRoute`), и встаёт в `WINDOW_GAP_CM` от плоскости окна напротив его середины, взглядом наружу по нормали.
 * Мебель у окна (диван, стол) — точка отходит в комнату вдоль нормали до первой свободной (не сквозь мебель и не вбок за неё).
 * Попадание считаем по точке, куда луч упёрся в оболочку комнаты (`viewer.ts:windowAt`): она лежит в вырезе окна — значит, окно.
 */
import type { Room } from "@/contracts/apartment";
import { canStand, type WalkArea } from "@/lib/viewer3d/walk";

/** От плоскости окна до глаза, см (просьба ведущего: 60–80 см — видно и раму, и вид за окном). */
export const WINDOW_GAP_CM = 70;
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
      return { roomId: r.id, cx: px, cy: py, nx, ny, widthCm: o.widthCm, sill, top };
    }
  }
  return null;
}

/** Где встать у окна: в `WINDOW_GAP_CM` от него по нормали; занято — дальше в комнату, затем чуть вбок; нет — `null`. */
export function windowSpot(area: WalkArea, w: WindowHit): { x: number; y: number; heading: number; gapCm: number } | null {
  const tx = -w.ny, ty = w.nx, side = Math.max(0, Math.floor(w.widthCm / 2 / STEP_CM)) * STEP_CM;
  // взгляд наружу: heading прогулки — 0 вдоль +y, направление (sin, cos)
  const heading = ((Math.atan2(-w.nx, -w.ny) * 180) / Math.PI + 360) % 360;
  for (let d = WINDOW_GAP_CM; d <= WINDOW_FAR_CM; d += STEP_CM) {
    for (let s = 0; s <= side; s += STEP_CM) {
      for (const sg of s ? [1, -1] : [0]) {
        const x = w.cx + w.nx * d + tx * s * sg, y = w.cy + w.ny * d + ty * s * sg;
        if (canStand(area, x, y)) return { x, y, heading, gapCm: d };
      }
    }
  }
  return null;
}
