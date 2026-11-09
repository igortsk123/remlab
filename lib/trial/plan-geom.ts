// Геометрия контура комнаты для серого тура пробы (план agent-trial-01, T-C): площадь, точка внутри, место подписи.
// Координаты — как в `contracts/trial.ts:floorplanResult` (см листа). Проверяет `tests/unit/trial-grey-scene.test.ts`.

type Pt = readonly [number, number];

export function polyArea(pts: readonly Pt[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i]!, [x2, y2] = pts[(i + 1) % pts.length]!;
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a / 2);
}

export function inside(pts: readonly Pt[], x: number, y: number): boolean {
  let r = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]!, [xj, yj] = pts[j]!;
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) r = !r;
  }
  return r;
}

/** Точка подписи: центр масс, а у Г-образных (центр снаружи) — середина самого широкого отрезка на его высоте. */
export function labelPoint(pts: readonly Pt[]): [number, number] {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i]!, [x2, y2] = pts[(i + 1) % pts.length]!;
    const k = x1 * y2 - x2 * y1;
    a += k; cx += (x1 + x2) * k; cy += (y1 + y2) * k;
  }
  if (Math.abs(a) < 1e-9) return [pts[0]![0], pts[0]![1]];
  const c: [number, number] = [cx / (3 * a), cy / (3 * a)];
  if (inside(pts, c[0], c[1])) return c;
  const ys = pts.map((p) => p[1]);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  let best: [number, number] = [pts[0]![0], pts[0]![1]], bw = -1;
  for (let s = 1; s < 10; s++) {
    const y = y0 + ((y1 - y0) * s) / 10;
    const xs: number[] = [];
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i]!, [xj, yj] = pts[j]!;
      if ((yi > y) !== (yj > y)) xs.push(((xj - xi) * (y - yi)) / (yj - yi) + xi);
    }
    xs.sort((p, q) => p - q);
    for (let k = 0; k + 1 < xs.length; k += 2) {
      if (xs[k + 1]! - xs[k]! > bw) { bw = xs[k + 1]! - xs[k]!; best = [(xs[k]! + xs[k + 1]!) / 2, y]; }
    }
  }
  return best;
}
