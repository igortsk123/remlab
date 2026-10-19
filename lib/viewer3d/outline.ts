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
}

/** Контур вокруг объекта: на 4 % больше габарита (линия не тонет в поверхности), не тоньше 5 см (у плоского ковра). */
export function outlineFrame(obj: THREE.Object3D, box = new THREE.Box3()): OutlineFrame {
  box.setFromObject(obj);
  const s = box.getSize(new THREE.Vector3());
  return {
    size: new THREE.Vector3(Math.max(s.x, 0.05) * 1.04, Math.max(s.y, 0.05) * 1.04, Math.max(s.z, 0.05) * 1.04),
    centre: box.getCenter(new THREE.Vector3()),
  };
}
