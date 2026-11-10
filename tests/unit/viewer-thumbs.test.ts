import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { THUMB_FOV, thumbView } from "@/lib/viewer3d/thumbs";

// МИНИАТЮРА ПРЕДМЕТА В ТУРЕ (T-20261109-35/2): своя камера на предмет — весь предмет в квадратном кадре, смотрим на лицо (+z группы)
// чуть сбоку и сверху. Без WebGL проверяем только геометрию кадра: углы коробки внутри кадра и с полем.

const project = (box: THREE.Box3) => {
  const v = thumbView(box);
  const cam = new THREE.PerspectiveCamera(THUMB_FOV, 1, v.near, v.far);
  cam.position.copy(v.eye);
  cam.lookAt(v.target);
  cam.updateMatrixWorld(true);
  cam.updateProjectionMatrix();
  const pts: THREE.Vector3[] = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    pts.push(new THREE.Vector3(x, y, z).project(cam));
  }
  return { v, pts };
};

describe("thumbView — кадр миниатюры предмета", () => {
  it.each([
    ["диван 214×90×98", new THREE.Box3(new THREE.Vector3(-1.07, 0, -0.49), new THREE.Vector3(1.07, 0.9, 0.49))],
    ["торшер 40×160×40", new THREE.Box3(new THREE.Vector3(-0.2, 0, -0.2), new THREE.Vector3(0.2, 1.6, 0.2))],
    ["ковёр 300×1×200", new THREE.Box3(new THREE.Vector3(-1.5, 0, -1), new THREE.Vector3(1.5, 0.01, 1))],
  ])("%s целиком в кадре, с полем, между ближней и дальней плоскостью", (_n, box) => {
    const { pts } = project(box);
    for (const p of pts) {
      expect(Math.abs(p.x)).toBeLessThan(0.97);
      expect(Math.abs(p.y)).toBeLessThan(0.97);
      expect(p.z).toBeGreaterThan(-1);
      expect(p.z).toBeLessThan(1);
    }
  });

  it("смотрим на лицо предмета (+z), справа и сверху", () => {
    const box = new THREE.Box3(new THREE.Vector3(-1, 0, -0.5), new THREE.Vector3(1, 0.9, 0.5));
    const { v } = project(box);
    const d = v.eye.clone().sub(v.target);
    expect(d.z).toBeGreaterThan(0);
    expect(d.x).toBeGreaterThan(0);
    expect(d.y).toBeGreaterThan(0);
    expect(d.z).toBeGreaterThan(d.x);   // три четверти, а не сбоку
  });

  it("предмет крупно: коробка занимает больше половины кадра по большей стороне", () => {
    const box = new THREE.Box3(new THREE.Vector3(-0.25, 0, -0.25), new THREE.Vector3(0.25, 0.45, 0.25));   // пуф
    const { pts } = project(box);
    const span = Math.max(Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x)),
      Math.max(...pts.map((p) => p.y)) - Math.min(...pts.map((p) => p.y)));
    expect(span).toBeGreaterThan(1);   // из 2 (NDC −1…1)
  });
});
