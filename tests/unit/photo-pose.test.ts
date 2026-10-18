import { readFileSync } from "node:fs";
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { applyPhotoShift, photoRay, photoShift, verticalFov } from "@/lib/viewer3d/viewer";

// ФОТО-ПОЗА БРАУЗЕРА = КАМЕРА СЕРВЕРНОГО КАДРА (план demo-01 п.3, урок 414). Эталон — `tools/assets/camera_golden.py`
// (`draft_render.cams_from_request` + `scene_mesh.project_pts`): пиксели углов комнаты и точек внутри на кадре 1344×896.
// Здесь та же поза ставится камерой three.js так, как это делает движок (`photoRay`, `verticalFov`), и точки обязаны
// попасть в те же пиксели. Зеркальный кадр или чужая конвенция угла дают ошибку в сотни пикселей, а не в доли.

type Pose = { name: string; x: number; y: number; rot: number; fov: number; pose?: number; shift_y?: number; eye: number[]; target: number[];
  width: number; height: number;
  points: { p: [number, number, number]; px: [number, number] | null }[] };
const golden = JSON.parse(readFileSync("tests/fixtures/camera-golden.json", "utf8")) as { poses: Pose[] };

describe("фото-поза движка совпадает с серверной камерой", () => {
  for (const pose of golden.poses) {
    it(pose.name, () => {
      const { eye, target } = photoRay(pose);
      expect(eye).toEqual(pose.eye.map(Number));
      expect(target.map((v) => Math.round(v * 1000) / 1000)).toEqual(pose.target.map((v) => Math.round(Number(v) * 1000) / 1000));
      const cam = new THREE.PerspectiveCamera(verticalFov(pose.fov, pose.width / pose.height), pose.width / pose.height, 1, 10_000);
      cam.position.set(eye[0], eye[1], eye[2]);
      cam.lookAt(target[0], target[1], target[2]);
      expect(photoShift(pose)).toBeCloseTo(pose.shift_y ?? 0, 6);
      applyPhotoShift(cam, photoShift(pose));     // сдвиг объектива — так же, как движок (`viewer.ts` фото-ветка)
      cam.updateMatrixWorld(true);
      let checked = 0;
      for (const { p, px } of pose.points) {
        if (!px) continue;                                   // за спиной у серверной камеры — не сравниваем
        const v = new THREE.Vector3(p[0], p[1], p[2]).project(cam);
        const sx = ((v.x + 1) / 2) * pose.width;
        const sy = ((1 - v.y) / 2) * pose.height;
        expect(Math.hypot(sx - px[0], sy - px[1]), `${pose.name}: точка ${p.join(",")}`).toBeLessThan(1.5);
        checked++;
      }
      expect(checked).toBeGreaterThanOrEqual(4);
    });
  }
});

// КАДР КОМПЬЮТЕРА ВО ВСЮ ОБЛАСТЬ (demo-15): область между квадратом и 3:2 — верхний край как у кадра 3:2, добавка — вниз, в пол
describe("кадр во всю область компьютера", () => {
  const pose = { x: 200, y: 300, rot: 0, fov: 72, pose: 2 };
  const edge = (aspect: number, sy: number) => {        // направление луча через центр края кадра (sy: 1 — верх, −1 — низ)
    const cam = new THREE.PerspectiveCamera(verticalFov(pose.fov, aspect), aspect, 1, 10_000);
    const { eye, target } = photoRay(pose);
    cam.position.set(eye[0], eye[1], eye[2]); cam.lookAt(target[0], target[1], target[2]);
    applyPhotoShift(cam, photoShift(pose, aspect)); cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
    const v = new THREE.Vector3(0, sy, 0.5).unproject(cam).sub(cam.position).normalize();
    return Math.asin(v.y) * 180 / Math.PI;                 // угол к горизонту, градусы
  };
  it("3:2 — прежний сдвиг", () => expect(photoShift(pose, 1.5)).toBeCloseTo(-0.1, 9));
  for (const a of [1, 1.15, 1.3]) {
    it(`${a}: потолка не больше, чем в 3:2, пола больше`, () => {
      expect(edge(a, 1)).toBeCloseTo(edge(1.5, 1), 6);
      expect(edge(a, -1)).toBeLessThan(edge(1.5, -1) - 3);
    });
  }
  it("вертикальный кадр телефона с подобранным сдвигом не затронут", () => expect(photoShift({ ...pose, pshift: -0.05 }, 0.5)).toBe(-0.05));
});
