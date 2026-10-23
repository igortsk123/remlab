/**
 * «3D» ГЛАЗАМИ СТОЯЩЕГО ЧЕЛОВЕКА (demo-27, владелец 23.10: «человек смотрит сверху вниз… глаза где-то 150–155 см — так и камеру
 * располагать, тогда и мебель вся будет видна сразу»). Камера живой сцены в точке ракурса стоит на высоте глаза `LIVE_EYE_CM` и
 * наклонена вниз так, чтобы мебель комнаты легла в ВИДИМУЮ полосу холста — над переключателем ракурсов и шторкой (на телефоне
 * они закрывают низ). Камеры фото и кадры нейросети этим не меняются (`photoRay`/`capturePhoto` — своя высота и сдвиг объектива).
 *
 * Расчёт точный для камеры-обскуры: у точки на расстоянии `f` вперёд по взгляду и высоте `h` экранная высота зависит только от
 * угла места `α = atan2(h − глаз, f)` и наклона камеры `θ` — `y = tan(α − θ) / tan(vfov/2)`; боковое смещение на неё не влияет.
 * Видимая полоса [top, bottom] (доли высоты холста, 0 — верх) — это углы `θ + At … θ + Ab`; все точки мебели внутри полосы ⇔
 * `θ ∈ [max α − At, min α − Ab]`. Влезает — середина интервала; не влезает — середина «перелёта» (обрезается поровну сверху и снизу).
 */

export const LIVE_EYE_CM = 152;
/** Верх мебели считаем не выше этого: тело дивана, стола, тумбы — в кадре; верх стеллажа или торшера может уйти за край. */
export const LIVE_TOP_CAP_CM = 120;
/** Ближе этого по взгляду точки не учитываем: край предмета у самых ног тянул бы взгляд в пол. */
export const LIVE_NEAR_CM = 60;
/** Наклон, когда мебели в поле зрения нет, и пределы наклона, градусы (вниз — минус; вверх не смотрим). */
export const LIVE_PITCH_DEFAULT = -12;
export const LIVE_PITCH_MIN = -40;

/**
 * Глаз «3D» — не ближе этого к стенам комнаты (и к проёмам в них), см (demo-27 Г). Точки ракурсов кадра стоят в 3 см от стены:
 * для фото это верно (камера в углу), а в «3D» при повороте стена ближе ближней плоскости камеры (5 см) срезается — сквозь неё
 * видна панорама вокруг дома, а окно в упор — край картинки вида за ним. Камеры фото этим не меняются.
 */
export const LIVE_WALL_CM = 50;

/** Точка глаза «3D»: внутри комнаты точки (нет такой — ближайшей), не ближе `LIVE_WALL_CM` к стенам; узкая — посередине. */
export function liveSpot(
  p: { x: number; y: number },
  rooms: { x: number; y: number; w: number; d: number }[],
  wallCm = LIVE_WALL_CM,
): { x: number; y: number } {
  const gap = (r: (typeof rooms)[number]): number =>
    Math.hypot(Math.max(r.x - p.x, 0, p.x - r.x - r.w), Math.max(r.y - p.y, 0, p.y - r.y - r.d));
  let room: (typeof rooms)[number] | undefined;
  for (const r of rooms) if (!room || gap(r) < gap(room)) room = r;
  if (!room) return { x: p.x, y: p.y };
  const fit = (v: number, a: number, len: number): number => {
    const m = Math.min(wallCm, len / 2);
    return Math.min(Math.max(v, a + m), a + len - m);
  };
  return { x: fit(p.x, room.x, room.w), y: fit(p.y, room.y, room.d) };
}

export interface LiveBand {
  /** Доли высоты холста: верх и низ видимой полосы (0 — верх холста, 1 — низ). */
  top: number;
  bottom: number;
}

export interface LivePoint {
  /** План квартиры, см. */
  x: number;
  y: number;
  /** Высота над полом, см. */
  h: number;
}

/** Наклон камеры (градусы, вниз — минус), при котором точки мебели `pts` лежат в полосе `band` кадра из позы `pose`. */
export function livePitchDeg(
  pose: { x: number; y: number; rot: number; fov?: number },
  pts: LivePoint[],
  aspect: number,
  band: LiveBand,
  eyeCm = LIVE_EYE_CM,
): number {
  const a = (pose.rot * Math.PI) / 180;
  const fx = Math.sin(a), fy = -Math.cos(a);                   // взгляд позы на плане — как `photoRay`
  const tanH = Math.tan(((pose.fov ?? 72) * Math.PI) / 360);
  const tanV = tanH / Math.max(aspect, 1e-3);
  let hi = -Infinity, lo = Infinity;
  for (const p of pts) {
    const dx = p.x - pose.x, dy = p.y - pose.y;
    const f = dx * fx + dy * fy;
    if (f < LIVE_NEAR_CM || Math.abs(dx * fy - dy * fx) > f * tanH) continue;   // за спиной, у ног или вне кадра по ширине
    const el = Math.atan2(Math.min(p.h, LIVE_TOP_CAP_CM) - eyeCm, f);
    hi = Math.max(hi, el);
    lo = Math.min(lo, el);
  }
  if (!Number.isFinite(hi)) return LIVE_PITCH_DEFAULT;
  const top = Math.min(Math.max(band.top, 0), 1), bottom = Math.min(Math.max(band.bottom, top + 0.05), 1);
  const at = Math.atan(tanV * (1 - 2 * top)), ab = Math.atan(tanV * (1 - 2 * bottom));
  const theta = ((hi - at) + (lo - ab)) / 2;
  return Math.max(LIVE_PITCH_MIN, Math.min(0, (theta * 180) / Math.PI));
}

/** Точки предмета для `livePitchDeg` из его габаритной коробки (см): 8 углов; висящее выше `LIVE_TOP_CAP_CM` (люстра, полка) — нет. */
export function boxPoints(min: { x: number; y: number; h: number }, max: { x: number; y: number; h: number }): LivePoint[] {
  if (min.h > LIVE_TOP_CAP_CM) return [];
  const out: LivePoint[] = [];
  for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const h of [min.h, max.h]) out.push({ x, y, h });
  return out;
}
