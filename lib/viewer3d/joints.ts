// ЗАТЕНЕНИЕ АРХИТЕКТУРНЫХ СТЫКОВ (план demo-04 п.4): пол–стена, потолок–стена, угол стена–стена.
//
// Белая коробка без теней в углах читается «недостроем» — стены сливаются в одно светлое поле. В комнате у стыков всегда
// мягкая тень от рассеянного света. Здесь — тонкие полосы у стыка с затемнением, которое спадает с расстоянием; сила и
// ширина — те же, что у серверного кадра (`services/planner-solver/planner/scene.py`: JOINT_DARK 0.16, JOINT_CM 16), чтобы
// «одна комната» и на кадре, и в 3D. Края выреза проёма стыком не считаются: полосы идут по кускам стены (`wallRects`),
// поэтому у двери полоса пола прерывается, а под окном — продолжается.

import * as THREE from "three";

const CM = 0.01;
const JOINT_DARK = 0.16;
const JOINT_CM = 16;
const STRIP_CM = 48; // ширина полосы: дальше 3σ затемнение меньше 1 %
const LIFT_CM = 0.3; // над поверхностью — иначе полоса спорит с ней за глубину

interface Rect {
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

let material: THREE.MeshBasicMaterial | null = null;

/** Чёрная полоса с прозрачностью exp(−расстояние/σ): строка 0 текстуры — у самого стыка. Канал G — для alphaMap. */
function stripMaterial(): THREE.MeshBasicMaterial {
  if (material) return material;
  const n = 64;
  const data = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) {
    const a = Math.round(255 * JOINT_DARK * Math.exp(-((i + 0.5) / n) * STRIP_CM / JOINT_CM));
    data.set([a, a, a, 255], i * 4);
  }
  const tex = new THREE.DataTexture(data, 1, n, THREE.RGBAFormat);
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  material = new THREE.MeshBasicMaterial({ color: 0x000000, alphaMap: tex, transparent: true, depthWrite: false });
  return material;
}

/** Полоса вдоль стыка в осях стены (x — вдоль, y — вверх, z — в комнату); `orient` поворачивает её край у стыка (−y). */
function strip(alongCm: number, x: number, y: number, z: number, orient: (g: THREE.PlaneGeometry) => void): THREE.Mesh {
  const g = new THREE.PlaneGeometry(alongCm * CM, STRIP_CM * CM); // v = 0 (строка 0, самая тёмная) — край −y
  orient(g);
  const m = new THREE.Mesh(g, stripMaterial());
  m.position.set(x * CM, y * CM, z * CM);
  m.renderOrder = 1;
  m.name = "joint";
  return m;
}

/**
 * Полосы стыков одной стены — группа в её осях (ставится так же, как столярка: начало стены, поворот лицом в комнату).
 * `rects` — куски стены без проёмов (`rooms.ts:wallRects`), высота комнаты — `heightCm`.
 */
export function jointStrips(lengthCm: number, heightCm: number, rects: Rect[]): THREE.Group {
  const g = new THREE.Group();
  const half = STRIP_CM / 2;
  const H = heightCm;
  for (const r of rects) {
    const len = r.u1 - r.u0;
    const mid = (r.u0 + r.u1) / 2;
    if (r.v0 <= 0) {
      g.add(strip(len, mid, half, LIFT_CM, () => undefined)); // стена у пола: тёмный край внизу
      // пол у стены: тёмный край у стены (поворот на 180° в плоскости, затем «лицом вверх»)
      g.add(strip(len, mid, LIFT_CM, half, (q) => q.rotateZ(Math.PI).rotateX(-Math.PI / 2)));
    }
    if (r.v1 >= H) {
      g.add(strip(len, mid, H - half, LIFT_CM, (q) => q.rotateZ(Math.PI))); // стена у потолка
      g.add(strip(len, mid, H - LIFT_CM, half, (q) => q.rotateX(Math.PI / 2))); // потолок у стены: «лицом вниз»
    }
  }
  // углы стена–стена: вертикальные полосы у начала и конца стены (тёмный край — к углу)
  g.add(strip(H, half, H / 2, LIFT_CM, (q) => q.rotateZ(-Math.PI / 2)));
  g.add(strip(H, lengthCm - half, H / 2, LIFT_CM, (q) => q.rotateZ(Math.PI / 2)));
  return g;
}
