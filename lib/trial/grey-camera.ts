// Камеры серого тура пробы (план agent-trial-01, T-C/2): рамку (Box3, м) вписываем в кадр по её проекции — все 8 углов
// внутри холста с отступами (доли холста: сверху — ещё и панель кнопок «3D / From above»). Подбор численный:
// расстояние — делением пополам (углы монотонно сходятся к центру), цель — сдвигом, пока рамка не встанет по центру
// допустимой области. Проверяет `tests/unit/trial-grey-scene.test.ts`.

import * as THREE from "three";

export type View = { position: THREE.Vector3; target: THREE.Vector3 };
export type Insets = { top: number; right: number; bottom: number; left: number };
export const FOV = 35;
export const MARGIN = 0.08;
export const DEFAULT_INSETS: Insets = { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN };

/** «3D» — наискосок с нижнего края листа (как `scene.js` «oblique»); «top» — сверху, север вверх; «room» — к комнате
 *  спереди и круче, без бокового наклона: ближние стены срезает `GreyScene.cutaway`, боковые комнату не заслоняют. */
export const DIRS = {
  oblique: new THREE.Vector3(-0.25, 0.75, 0.62).normalize(),
  top: new THREE.Vector3(0, 1, 0.0001).normalize(),
  room: new THREE.Vector3(0, 0.82, 0.57).normalize(),
} as const;

/** Четверть оборота вокруг вертикали: 0 — с нижнего края листа, 1 / -1 — с правого / левого. */
export type Turn = -1 | 0 | 1;
const turn = (v: THREE.Vector3, k: Turn) => (k === 0 ? v.clone() : new THREE.Vector3(k * v.z, v.y, -k * v.x));
/** Направления камеры при повороте `k`; `toward` — горизонталь к камере (по ней `cutaway` срезает ближние стены).
 *  «Сверху» всегда как на исходном плане (север вверх) — чтобы сверять с загруженной картинкой. */
export function dirsFor(k: Turn) {
  return { oblique: turn(DIRS.oblique, k), top: DIRS.top.clone(), room: turn(DIRS.room, k), toward: turn(new THREE.Vector3(0, 0, 1), k) };
}

function corners(b: THREE.Box3 | THREE.Vector3[]): THREE.Vector3[] {
  if (Array.isArray(b)) return b;
  const out: THREE.Vector3[] = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}

/** Камера (как у three `lookAt` с up = Y): экранные координаты угла рамки при цели `t` и расстоянии `d`. */
function project(ps: THREE.Vector3[], t: THREE.Vector3, dir: THREE.Vector3, d: number, tanV: number, tanH: number) {
  const r = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), dir).normalize();
  const u = new THREE.Vector3().crossVectors(dir, r);
  return ps.map((p) => {
    const q = p.clone().sub(t), depth = d - q.dot(dir);
    return { x: q.dot(r) / (depth * tanH), y: q.dot(u) / (depth * tanV), depth, r, u };
  });
}

export function frameView(box: THREE.Box3 | THREE.Vector3[], dir: THREE.Vector3, aspect: number, insets: Insets = DEFAULT_INSETS, fovDeg = FOV): View {
  const tanV = Math.tan((fovDeg * Math.PI) / 360), tanH = tanV * Math.max(aspect, 0.1);
  const lo = { x: -1 + 2 * insets.left, y: -1 + 2 * insets.bottom }, hi = { x: 1 - 2 * insets.right, y: 1 - 2 * insets.top };
  const mid = { x: (lo.x + hi.x) / 2, y: (lo.y + hi.y) / 2 }, half = { x: (hi.x - lo.x) / 2, y: (hi.y - lo.y) / 2 };
  const ps = corners(box);
  const bb = Array.isArray(box) ? new THREE.Box3().setFromPoints(box) : box;
  const target = bb.getCenter(new THREE.Vector3());
  const radius = Math.max(bb.getSize(new THREE.Vector3()).length() / 2, 0.5);
  let d = radius * 3;
  for (let pass = 0; pass < 5; pass++) {
    // наименьшее расстояние, при котором рамка влезает в «половину» допустимой области вокруг её середины
    let a = radius + 0.2, b = radius * 60 + 50;
    const fits = (dd: number) => {
      const pr = project(ps, target, dir, dd, tanV, tanH);
      const xs = pr.map((p) => p.x), ys = pr.map((p) => p.y);
      return pr.every((p) => p.depth > 0.1) && Math.max(...xs) - Math.min(...xs) <= 2 * half.x && Math.max(...ys) - Math.min(...ys) <= 2 * half.y;
    };
    for (let i = 0; i < 40; i++) { const m = (a + b) / 2; if (fits(m)) b = m; else a = m; }
    d = b;
    // сдвиг цели: середина проекции рамки → середина допустимой области
    const pr = project(ps, target, dir, d, tanV, tanH);
    const xs = pr.map((p) => p.x), ys = pr.map((p) => p.y);
    const dx = (Math.max(...xs) + Math.min(...xs)) / 2 - mid.x, dy = (Math.max(...ys) + Math.min(...ys)) / 2 - mid.y;
    const depth = pr.reduce((s, p) => s + p.depth, 0) / pr.length;
    target.addScaledVector(pr[0]!.r, dx * depth * tanH).addScaledVector(pr[0]!.u, dy * depth * tanV);
  }
  return { position: target.clone().addScaledVector(dir, d), target };
}

/** Поворот общего вида «3D», при котором модель крупнее в кадре (длинная сторона плана — вдоль длинной стороны холста).
 *  С нижнего края — по умолчанию; боковой — только если ближе на 15 %+. */
export function pickTurn(points: THREE.Vector3[], aspect: number, insets: Insets = DEFAULT_INSETS): Turn {
  const dist = (k: Turn) => { const v = frameView(points, dirsFor(k).oblique, aspect, insets); return v.position.distanceTo(v.target); };
  const d0 = dist(0), [k, d] = ([1, -1] as const).map((x) => [x, dist(x)] as const).sort((p, q) => p[1] - q[1])[0]!;
  return d < d0 * 0.85 ? k : 0;
}

/** Рамка комнаты для вида «к комнате»: пол с запасом на стены, по высоте — до среза. */
export function roomBox(center: THREE.Vector3, size: THREE.Vector3, height: number): THREE.Box3 {
  const pad = 0.3;
  return new THREE.Box3(
    new THREE.Vector3(center.x - size.x / 2 - pad, 0, center.z - size.z / 2 - pad),
    new THREE.Vector3(center.x + size.x / 2 + pad, height, center.z + size.z / 2 + pad),
  );
}
