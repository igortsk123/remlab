import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { boxPoints, livePitchDeg, LIVE_EYE_CM, LIVE_PITCH_DEFAULT, LIVE_TOP_CAP_CM, type LiveBand } from "@/lib/viewer3d/live-eye";
import { verticalFov } from "@/lib/viewer3d/viewer";

// «3D» ГЛАЗАМИ СТОЯЩЕГО (demo-27): наклон из `livePitchDeg` ставится настоящей камерой three.js так, как это делает движок (глаз
// 152 см, цель на уровне глаза + tan(наклон)·400), и все точки мебели в поле зрения обязаны лечь в видимую полосу холста.

const CM = 0.01;
const pose = { x: 0, y: 0, rot: 180, fov: 72 };   // взгляд в +y плана: (sin 180°, −cos 180°) = (0, 1)

function screenY(pitchDeg: number, aspect: number, p: { x: number; y: number; h: number }): number {
  const cam = new THREE.PerspectiveCamera(verticalFov(pose.fov, aspect), aspect, 0.05, 100);
  cam.position.set(pose.x * CM, LIVE_EYE_CM * CM, pose.y * CM);
  const a = (pose.rot * Math.PI) / 180;
  cam.lookAt((pose.x + 400 * Math.sin(a)) * CM, (LIVE_EYE_CM + Math.tan((pitchDeg * Math.PI) / 180) * 400) * CM, (pose.y - 400 * Math.cos(a)) * CM);
  cam.updateMatrixWorld();
  const v = new THREE.Vector3(p.x * CM, p.h * CM, p.y * CM).project(cam);
  return (1 - v.y) / 2;   // доля высоты холста, 0 — верх
}

// гостиная: диван у дальней стены, столик перед ним, тумба сбоку — точки углов коробок
const room = [
  ...boxPoints({ x: -100, y: 330, h: 0 }, { x: 100, y: 420, h: 85 }),
  ...boxPoints({ x: -45, y: 230, h: 0 }, { x: 45, y: 290, h: 45 }),
  ...boxPoints({ x: 90, y: 150, h: 0 }, { x: 140, y: 290, h: 60 }),
];

describe("наклон «3D» глазами стоящего", () => {
  for (const [name, aspect, band] of [
    ["телефон 375×464 над переключателем", 375 / 464, { top: 0.1, bottom: 0.78 }],
    ["компьютер 1265×1100", 1265 / 1100, { top: 0.06, bottom: 0.9 }],
  ] as [string, number, LiveBand][]) {
    it(`${name}: вся мебель — в видимой полосе, взгляд вниз`, () => {
      const pitch = livePitchDeg(pose, room, aspect, band);
      expect(pitch).toBeLessThan(0);
      for (const p of room) {
        const y = screenY(pitch, aspect, { ...p, h: Math.min(p.h, LIVE_TOP_CAP_CM) });
        expect(y).toBeGreaterThanOrEqual(band.top - 1e-6);
        expect(y).toBeLessThanOrEqual(band.bottom + 1e-6);
      }
    });
  }

  it("за спиной, у самых ног и вне кадра по ширине — не учитываются; мебели нет — наклон по умолчанию", () => {
    const behind = [{ x: 0, y: -300, h: 0 }, { x: 0, y: 30, h: 0 }, { x: 800, y: 200, h: 0 }];
    expect(livePitchDeg(pose, behind, 1, { top: 0, bottom: 1 })).toBe(LIVE_PITCH_DEFAULT);
  });

  it("не влезает — перелёт делится поровну сверху и снизу", () => {
    const aspect = 1, band = { top: 0.35, bottom: 0.65 };   // полоса ~24.6°, мебель 2 м впереди от пола до 110 см — ~25.3°
    const tall = [{ x: 0, y: 200, h: 0 }, { x: 0, y: 200, h: 110 }];
    const pitch = livePitchDeg(pose, tall, aspect, band);
    const top = screenY(pitch, aspect, tall[1]!), bottom = screenY(pitch, aspect, tall[0]!);
    expect(top).toBeLessThan(band.top);
    expect(bottom).toBeGreaterThan(band.bottom);
    const over = (a: number) => Math.atan(Math.tan((verticalFov(72, aspect) * Math.PI) / 360) * (1 - 2 * a));
    // перелёт поровну — в углах: верхняя точка выше полосы на столько же градусов, на сколько нижняя ниже
    expect(Math.abs((over(top) - over(band.top)) - (over(band.bottom) - over(bottom)))).toBeLessThan(1e-6);
  });

  it("висящее выше 120 см (люстра) — не точки мебели", () => {
    expect(boxPoints({ x: 0, y: 0, h: 200 }, { x: 10, y: 10, h: 230 })).toEqual([]);
    expect(boxPoints({ x: 0, y: 0, h: 0 }, { x: 10, y: 10, h: 230 })).toHaveLength(8);
  });
});
