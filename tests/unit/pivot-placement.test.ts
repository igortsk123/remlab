import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { placeMesh } from "@/lib/viewer3d/meshes";

// ПЕРЕМЕЩЕНИЕ БЕЗ ПЕРЕСОЗДАНИЯ (план demo-01 п.4): движок держит предмет как внешнюю опору (место и поворот) с моделью,
// посаженной в начале координат. Это обязано давать ТЕ ЖЕ мировые вершины, что прежняя посадка `placeMesh` сразу в
// точку и с поворотом (её сверяет с конвейером фото `configurator-transform.test.ts`) — иначе 3D разъедется с фото.

const CM = 0.01;
function source(): THREE.Object3D {
  const g = new THREE.BoxGeometry(2, 1.2, 1.6);
  g.translate(0.3, -0.2, 0.15);
  return new THREE.Mesh(g, new THREE.MeshBasicMaterial());
}
function worldVerts(o: THREE.Object3D): THREE.Vector3[] {
  o.updateMatrixWorld(true);
  const out: THREE.Vector3[] = [];
  o.traverse((n) => {
    const m = n as THREE.Mesh;
    if (!m.isMesh) return;
    const pos = m.geometry.getAttribute("position");
    for (let i = 0; i < pos.count; i++) out.push(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld));
  });
  return out;
}

const CASES = [
  { x: 200, y: 52, rot: 0, w: 210, d: 95, h: 85, yaw: 0, elev: 0 },
  { x: 400, y: 300, rot: 90, w: 140, d: 80, h: 75, yaw: 0, elev: 0 },
  { x: 120, y: 640, rot: 180, w: 140, d: 40, h: 45, yaw: 90, elev: 0 },
  { x: 500, y: 400, rot: 37, w: 100, d: 60, h: 42, yaw: 45, elev: 0 },
  { x: 700, y: 250, rot: 0, w: 60, d: 35, h: 70, yaw: 0, elev: 148 },
];

describe("опора + модель в центре = прежняя посадка в точку", () => {
  for (const c of CASES) {
    it(`x${c.x} y${c.y} rot${c.rot} yaw${c.yaw}`, () => {
      const direct = placeMesh(source(), { xCm: c.x, yCm: c.y, rotDeg: c.rot, wCm: c.w, dCm: c.d, hCm: c.h, elevCm: c.elev, yawDeg: c.yaw });
      const outer = new THREE.Group();
      outer.add(placeMesh(source(), { xCm: 0, yCm: 0, rotDeg: 0, wCm: c.w, dCm: c.d, hCm: c.h, elevCm: 0, yawDeg: c.yaw }));
      outer.position.set(c.x * CM, c.elev * CM, c.y * CM);
      outer.rotation.y = (c.rot * Math.PI) / 180;
      const a = worldVerts(direct);
      const b = worldVerts(outer);
      expect(b.length).toBe(a.length);
      a.forEach((v, i) => expect(v.distanceTo(b[i]!)).toBeLessThan(1e-5));
    });
  }
});
