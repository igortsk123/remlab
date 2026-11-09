// Серый 3D-тур пробы (план agent-trial-01, T-C): порт `tools/floorplan/render/scene.js:build` на TS. Вход — один лист
// `contracts/trial.ts:floorplanResult` (см, x вправо, y вниз по листу); сцена — метры, X = x, Z = y, Y вверх (как
// `lib/viewer3d/rooms.ts`). Стены — полосы по высоте (подоконник/проём/перемычка) выдавливанием, пол — `contour` комнаты.
// Без WebGL: сцену можно собрать и проверить в node (тест `tests/unit/trial-grey-scene.test.ts`).

import * as THREE from "three";
import type { FloorplanResult } from "@/contracts/trial";

export type TrialPanel = FloorplanResult["panels"][number];
export type TrialRoom = TrialPanel["rooms"][number];
type Pt = readonly [number, number];

const M = 0.01; // см → м сцены
export const GREY = { bg: 0xffffff, wall: 0x9a9a9a, edge: 0x57534e, floor: 0xd6d3d1, selected: 0xe8c8b7 } as const;

export type SceneRoom = {
  id: string; name: string; kind: TrialRoom["kind"]; areaM2: number; flagged: boolean;
  /** Точка подписи внутри многоугольника (на полу), центр и размер рамки — в метрах сцены. */
  label: THREE.Vector3; center: THREE.Vector3; size: THREE.Vector3;
};
export type GreyScene = {
  scene: THREE.Scene; center: THREE.Vector3; size: THREE.Vector3; rooms: SceneRoom[];
  floors: Map<string, THREE.Mesh>; walls: THREE.Mesh[];
  /** Подсветить пол комнаты (null — снять). */
  highlight(id: string | null): void;
  dispose(): void;
};

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

function shapeOf(outer: readonly Pt[], holes: readonly (readonly Pt[])[] = []): THREE.Shape {
  const s = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x * M, -y * M)));
  for (const h of holes) s.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x * M, -y * M))));
  return s;
}

/** Сцена листа. `hatch` — текстура штриховки комнат с флагами (в браузере — холст; в тесте — пустая). */
export function buildGreyScene(
  panel: TrialPanel, opts: { hatch?: THREE.Texture | null; transparent?: boolean; colors?: Partial<typeof GREY> } = {},
): GreyScene {
  const col = { ...GREY, ...opts.colors };
  const scene = new THREE.Scene();
  scene.background = opts.transparent ? null : new THREE.Color(col.bg); // прозрачный — фон даёт страница (токен)
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a8a, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  scene.add(sun);
  const wallMat = new THREE.MeshStandardMaterial({ color: col.wall, roughness: 0.9 });
  const edgeMat = new THREE.LineBasicMaterial({ color: col.edge });
  const floorMat = new THREE.MeshStandardMaterial({ color: col.floor, roughness: 1, side: THREE.DoubleSide });
  const flagMat = new THREE.MeshStandardMaterial({ color: col.floor, roughness: 1, side: THREE.DoubleSide, map: opts.hatch ?? null });
  const selMat = new THREE.MeshStandardMaterial({ color: col.selected, roughness: 1, side: THREE.DoubleSide });
  const box = new THREE.Box3();
  const walls: THREE.Mesh[] = [];
  for (const band of panel.walls) {
    for (const p of band.polys) {
      const g = new THREE.ExtrudeGeometry(shapeOf(p.outer, p.holes), { depth: (band.z1 - band.z0) * M, bevelEnabled: false });
      g.rotateX(-Math.PI / 2);
      g.translate(0, band.z0 * M, 0);
      const m = new THREE.Mesh(g, wallMat);
      walls.push(m);
      scene.add(m, new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), edgeMat));
      g.computeBoundingBox();
      box.union(g.boundingBox!);
    }
  }
  const floors = new Map<string, THREE.Mesh>();
  const rooms: SceneRoom[] = [];
  for (const r of panel.rooms) {
    const flagged = r.flags.length > 0;
    const g = new THREE.ShapeGeometry(shapeOf(r.contour));
    g.rotateX(-Math.PI / 2);
    g.translate(0, 0.005, 0);
    const m = new THREE.Mesh(g, flagged ? flagMat : floorMat);
    m.userData = { roomId: r.id, flagged };
    floors.set(r.id, m);
    scene.add(m);
    g.computeBoundingBox();
    box.union(g.boundingBox!);
    const [lx, ly] = labelPoint(r.contour);
    rooms.push({
      id: r.id, name: r.name, kind: r.kind, areaM2: r.areaM2, flagged, label: new THREE.Vector3(lx * M, 0.02, ly * M),
      center: new THREE.Vector3((r.bbox.x + r.bbox.w / 2) * M, 0, (r.bbox.y + r.bbox.d / 2) * M),
      size: new THREE.Vector3(r.bbox.w * M, 0, r.bbox.d * M),
    });
  }
  if (box.isEmpty()) box.set(new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 0, 1));
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  sun.position.set(center.x - size.x * 0.4, 12, center.z + size.z * 0.9);
  sun.target.position.copy(center);
  scene.add(sun.target);
  return {
    scene, center, size, rooms, floors, walls,
    highlight(id) {
      for (const [rid, m] of floors) m.material = rid === id ? selMat : m.userData.flagged ? flagMat : floorMat;
    },
    dispose() {
      scene.traverse((o) => { if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) o.geometry.dispose(); });
      for (const m of [wallMat, edgeMat, floorMat, flagMat, selMat]) m.dispose();
    },
  };
}

export type View = { position: THREE.Vector3; target: THREE.Vector3 };
const OBLIQUE = new THREE.Vector3(-0.25, 0.75, 0.62).normalize(); // как `scene.js` «oblique»: с нижнего края листа

/** Камера, в которую рамка (ширина × глубина, м) влезает целиком: «3D» — наискосок, «top» — сверху (север вверх). */
export function fitView(center: THREE.Vector3, w: number, d: number, aspect: number, mode: "oblique" | "top", fovDeg = 35): View {
  const half = Math.tan((fovDeg * Math.PI) / 360);
  // сверху стены ближе к камере и в перспективе шире плана — запас больше
  const need = Math.max(w / Math.max(aspect, 0.1), d) * (mode === "top" ? 1.45 : 1.4);
  const dist = Math.max(need / 2 / half, 2);
  // сверху холста — кнопки «3D / From above»: модель чуть ниже середины кадра (верх экрана ≈ −Z сцены в обоих видах)
  const target = new THREE.Vector3(center.x, 0, center.z - need * (mode === "top" ? 0.06 : 0.05));
  const dir = mode === "top" ? new THREE.Vector3(0, 1, 0.0001).normalize() : OBLIQUE;
  return { position: target.clone().addScaledVector(dir, dist), target };
}

/** Камера к комнате: наискосок, с запасом, чтобы были видны соседние стены. */
export const roomView = (r: SceneRoom, aspect: number): View =>
  fitView(r.center, Math.max(r.size.x, 2.5) * 1.5, Math.max(r.size.z, 2.5) * 1.5, aspect, "oblique");
