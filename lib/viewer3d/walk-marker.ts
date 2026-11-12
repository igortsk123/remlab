// КОЛЬЦО «СЮДА МОЖНО ПРОЙТИ» (T-20261112-36, владелец TG 1737, 1791): тонкое кольцо на полу с лёгким пульсом — под мышью на
// компьютере и в точке, куда идём после касания на телефоне. Терракота бренда, как рамка выбранного предмета (`viewer.ts:showOutline`).
//
// Видно только там, где пол виден: `depthTest` включён (кольцо не рисуется сквозь стену и мебель, в отличие от рамки выбора),
// `depthWrite` выключен и `polygonOffset` — не мерцает с полом. Поднято на 4 см — над ворсом ковра (до 3 см), иначе ковёр его прячет.

import * as THREE from "three";

export const WALK_MARKER_COLOR = 0xc8805c;
/** Радиусы кольца, м: снаружи ~ шаг человека, читается и с телефона, но не закрывает пол. */
export const WALK_MARKER_R = [0.19, 0.255] as const;
export const WALK_MARKER_LIFT_M = 0.04;
/** Пульс: период, мс, и размах масштаба. */
const PULSE_MS = 1200;
const PULSE_SCALE = 0.08;

export type WalkMarker = THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;

export function createWalkMarker(): WalkMarker {
  const m: WalkMarker = new THREE.Mesh(
    new THREE.RingGeometry(WALK_MARKER_R[0], WALK_MARKER_R[1], 40),
    new THREE.MeshBasicMaterial({
      color: WALK_MARKER_COLOR, transparent: true, opacity: 0.75, depthTest: true, depthWrite: false, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, toneMapped: false,
    }),
  );
  m.rotation.x = -Math.PI / 2;
  m.name = "walk-marker";
  m.visible = false;
  m.renderOrder = 2;
  return m;
}

/** Поставить кольцо в точку плана (см). */
export function placeWalkMarker(m: WalkMarker, xCm: number, yCm: number): void {
  m.position.set(xCm / 100, WALK_MARKER_LIFT_M, yCm / 100);
  m.visible = true;
}

/** Пульс на кадр: масштаб 1 ± 8 % и прозрачность в такт. */
export function pulseWalkMarker(m: WalkMarker, nowMs: number): void {
  const s = Math.sin(((nowMs % PULSE_MS) / PULSE_MS) * Math.PI * 2);
  m.scale.setScalar(1 + PULSE_SCALE * s);
  m.material.opacity = 0.68 + 0.17 * s;
}
