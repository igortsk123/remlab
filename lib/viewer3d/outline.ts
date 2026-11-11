// Рамка выделения предмета в 3D (владелец 29.09: контур по габариту вместо синего круга на полу).
//
// Габарит берём у ПОСТРОЕННОГО объекта сцены, а не у места квартиры: после замены ковра плита кладётся по размеру
// товара (`resolve.fitPlacement`), и рамка обязана совпасть с ней (T-20261019-02, приёмка: рамка 230×160 торчала за
// край новой плиты 200×140 — её не пересчитывали после пересборки). Пересчёт по пересборке — `viewer.ts:refreshSelection`.

import * as THREE from "three";

export interface OutlineFrame {
  /** Масштаб единичного куба-контура, метры сцены. */
  size: THREE.Vector3;
  centre: THREE.Vector3;
  /** Поворот рамки вокруг вертикали — как у предмета, радианы. */
  yaw: number;
}

/** Контур вокруг объекта: на 4 % больше габарита (линия не тонет в поверхности), не тоньше 5 см (у плоского ковра). */
export function outlineFrame(obj: THREE.Object3D, box = new THREE.Box3()): OutlineFrame {
  // ПО ПОВОРОТУ ПРЕДМЕТА (T-20261111-05 п.7, «Повернуть» на 45°): габарит — в осях самого предмета, рамка повёрнута вместе с ним.
  // Коробка по осям мира у повёрнутого на 45° дивана была бы вдвое шире его самого
  const yaw = obj.rotation.y;
  obj.rotation.y = 0;
  obj.updateMatrixWorld(true);
  box.setFromObject(obj);
  obj.rotation.y = yaw;
  obj.updateMatrixWorld(true);
  const s = box.getSize(new THREE.Vector3());
  const at = obj.getWorldPosition(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3()).sub(at).applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw).add(at);
  return {
    size: new THREE.Vector3(Math.max(s.x, 0.05) * 1.04, Math.max(s.y, 0.05) * 1.04, Math.max(s.z, 0.05) * 1.04),
    centre,
    yaw,
  };
}
