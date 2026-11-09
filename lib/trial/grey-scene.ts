// Серый 3D-тур пробы (план agent-trial-01, T-C): порт `tools/floorplan/render/scene.js:build` на TS. Вход — один лист
// `contracts/trial.ts:floorplanResult` (см, x вправо, y вниз по листу); сцена — метры, X = x, Z = y, Y вверх (как
// `lib/viewer3d/rooms.ts`). Стены — полосы по высоте (подоконник/проём/перемычка) выдавливанием, пол — `contour` комнаты.
// Без WebGL: сцену можно собрать и проверить в node (тест `tests/unit/trial-grey-scene.test.ts`).

import * as THREE from "three";
import type { FloorplanResult } from "@/contracts/trial";
import { labelPoint } from "@/lib/trial/plan-geom";

export type TrialPanel = FloorplanResult["panels"][number];
export type TrialRoom = TrialPanel["rooms"][number];
type Pt = readonly [number, number];

const M = 0.01; // см → м сцены
export const CUT_H = 0.3; // высота срезанных стен, м
export const GREY = { bg: 0xffffff, wall: 0x9a9a9a, edge: 0x57534e, floor: 0xd6d3d1, selected: 0xe8c8b7 } as const;

export type SceneRoom = {
  id: string; name: string; kind: TrialRoom["kind"]; areaM2: number; flagged: boolean;
  /** Точка подписи внутри многоугольника (на полу), центр и размер рамки — в метрах сцены. */
  label: THREE.Vector3; center: THREE.Vector3; size: THREE.Vector3;
};
export type GreyScene = {
  scene: THREE.Scene; center: THREE.Vector3; size: THREE.Vector3; bounds: THREE.Box3; rooms: SceneRoom[];
  /** Углы стен (низ и верх полос) и полов — по ним камера вписывает модель плотнее, чем по рамке. */
  points: THREE.Vector3[];
  floors: Map<string, THREE.Mesh>; walls: THREE.Mesh[];
  /** Подсветить пол комнаты (null — снять). */
  highlight(id: string | null): void;
  /** «Срез» для вида к комнате: стены ближе середины комнаты к камере (`toward` — горизонталь к камере, по умолчанию +Z)
   *  — ниже `CUT_H`; null — стены целиком. Нужен `renderer.localClippingEnabled = true`. */
  cutaway(room: SceneRoom | null, toward?: THREE.Vector3): void;
  dispose(): void;
};

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
  // DoubleSide: у срезанной стены видна внутренность, а не дыра
  const wallMat = new THREE.MeshStandardMaterial({ color: col.wall, roughness: 0.9, side: THREE.DoubleSide, clipIntersection: true });
  const edgeMat = new THREE.LineBasicMaterial({ color: col.edge, clipIntersection: true });
  const floorMat = new THREE.MeshStandardMaterial({ color: col.floor, roughness: 1, side: THREE.DoubleSide });
  const flagMat = new THREE.MeshStandardMaterial({ color: col.floor, roughness: 1, side: THREE.DoubleSide, map: opts.hatch ?? null });
  const selMat = new THREE.MeshStandardMaterial({ color: col.selected, roughness: 1, side: THREE.DoubleSide });
  const box = new THREE.Box3();
  const walls: THREE.Mesh[] = [];
  const points: THREE.Vector3[] = [];
  for (const band of panel.walls) {
    for (const p of band.polys) {
      for (const [x, y] of p.outer) points.push(new THREE.Vector3(x * M, band.z0 * M, y * M), new THREE.Vector3(x * M, band.z1 * M, y * M));
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
    for (const [x, y] of r.contour) points.push(new THREE.Vector3(x * M, 0, y * M));
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
  if (!points.length) points.push(box.min.clone(), box.max.clone());
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  sun.position.set(center.x - size.x * 0.4, 12, center.z + size.z * 0.9);
  sun.target.position.copy(center);
  scene.add(sun.target);
  return {
    scene, center, size, bounds: box, points, rooms, floors, walls,
    highlight(id) {
      for (const [rid, m] of floors) m.material = rid === id ? selMat : m.userData.flagged ? flagMat : floorMat;
    },
    cutaway(room, toward = new THREE.Vector3(0, 0, 1)) {
      // отсекается пересечение «выше CUT_H» и «ближе середины комнаты к камере» (clipIntersection)
      const h = toward.clone().setY(0).normalize();
      const planes = room ? [new THREE.Plane(new THREE.Vector3(0, -1, 0), CUT_H), new THREE.Plane(h.clone().negate(), h.dot(room.center))] : [];
      for (const m of [wallMat, edgeMat]) { m.clippingPlanes = planes; m.needsUpdate = true; }
    },
    dispose() {
      scene.traverse((o) => { if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) o.geometry.dispose(); });
      for (const m of [wallMat, edgeMat, floorMat, flagMat, selMat]) m.dispose();
    },
  };
}
