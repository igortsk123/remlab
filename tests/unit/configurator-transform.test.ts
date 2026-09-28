import { describe, expect, it } from "vitest";

import type * as ThreeNs from "three";

import { frontDirection, worldVertices, type Vec3 } from "@/lib/viewer3d/transform";
import golden from "@/tests/fixtures/transform-golden.json";

// Сверка с ЭТАЛОНОМ из конвейера фото (`tools/scout/scene_mesh.py`). Если этот тест упал —
// 3D-сцена и кадр разъехались, и покупатель увидит на фото не то, что собрал в 3D.
// Эталон пересобирается: ~/venvs/scout/bin/python tools/assets/transform_golden.py

const cube: Vec3[] = (golden.cube as number[][]).map(([x, y, z]) => ({ x: x!, y: y!, z: z! }));

describe("трансформ предмета: 3D совпадает с конвейером фото", () => {
  for (const c of golden.cases) {
    it(`${c.name}: 8 вершин совпадают с эталоном (допуск 0,01 см)`, () => {
      const got = worldVertices(cube, {
        xCm: c.x,
        yCm: c.y,
        rotDeg: c.rot,
        wCm: c.w,
        dCm: c.d,
        hCm: c.h,
        elevCm: c.elev,
        yawDeg: c.yaw,
      });
      const want = c.vertices as number[][];
      expect(got.length).toBe(want.length);
      got.forEach((v, i) => {
        const w = want[i]!;
        expect(Math.abs(v.x - w[0]!), `вершина ${i} x`).toBeLessThan(0.01);
        expect(Math.abs(v.y - w[1]!), `вершина ${i} y`).toBeLessThan(0.01);
        expect(Math.abs(v.z - w[2]!), `вершина ${i} z`).toBeLessThan(0.01);
      });
    });
  }

  it("габарит после посадки равен паспортному (масштаб по трём осям, не «по большей стороне»)", () => {
    const got = worldVertices(cube, { xCm: 0, yCm: 0, rotDeg: 0, wCm: 210, dCm: 95, hCm: 85, yawDeg: 0 });
    const xs = got.map((v) => v.x);
    const ys = got.map((v) => v.y);
    const zs = got.map((v) => v.z);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(210, 3);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(85, 3);
    expect(Math.max(...zs) - Math.min(...zs)).toBeCloseTo(95, 3);
    expect(Math.min(...ys), "низ предмета стоит на полу").toBeCloseTo(0, 3);
  });

  it("направление лица: 0 → север (+y), 90 → восток (+x), 270 → запад (−x)", () => {
    expect(frontDirection(0).y).toBeCloseTo(1, 6);
    expect(frontDirection(90).x).toBeCloseTo(1, 6);
    expect(frontDirection(180).y).toBeCloseTo(-1, 6);
    expect(frontDirection(270).x).toBeCloseTo(-1, 6);
  });
});

// Отдельно: РАНТАЙМ (three.js) обязан давать то же, что чистая математика выше. Иначе тест
// эталона зелёный, а сцена всё равно ставит мебель не туда — проверяем сам `placeMesh`.
describe("рантайм three.js совпадает с чистой математикой", () => {
  it("placeMesh ставит куб в те же мировые координаты (допуск 0,5 см)", async () => {
    const THREE = await import("three");
    const { placeMesh } = await import("@/lib/viewer3d/meshes");

    const positions = new Float32Array(cube.flatMap((v) => [v.x, v.y, v.z]));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const source = new THREE.Mesh(geo, new THREE.MeshBasicMaterial());

    const p = { xCm: 400, yCm: 300, rotDeg: 90, wCm: 140, dCm: 80, hCm: 75, elevCm: 0, yawDeg: 45 };
    const group = placeMesh(source, p);
    group.updateMatrixWorld(true);

    const want = worldVertices(cube, p);
    const attr = (group.children[0] as ThreeNs.Mesh).geometry.getAttribute("position");
    const v = new THREE.Vector3();
    for (let i = 0; i < attr.count; i += 1) {
      v.fromBufferAttribute(attr, i).applyMatrix4((group.children[0] as ThreeNs.Mesh).matrixWorld);
      const w = want[i]!;
      expect(Math.abs(v.x * 100 - w.x), `вершина ${i} x`).toBeLessThan(0.5);
      expect(Math.abs(v.y * 100 - w.y), `вершина ${i} y`).toBeLessThan(0.5);
      expect(Math.abs(v.z * 100 - w.z), `вершина ${i} z`).toBeLessThan(0.5);
    }
  });
});
