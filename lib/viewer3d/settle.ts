// ПОСАДКА МЯГКИХ ВЕЩЕЙ НА МЕШ ОПОРЫ (T-20261117-10, владелец TG 1379 «подушки висят в воздухе»). Решатель паспорта ставит подушку на
// ОТМЕТКУ сиденья по норме (45 см), а верх сиденья настоящего дивана — 40–43 см: вещь парила на 2–5 см. Здесь, уже в сцене, отметка
// заменяется поверхностью меша опоры: луч вниз от центра и от краёв вещи → верх опоры, низ вещи = верх − осадка; наклон к спинке — по двум
// горизонтальным лучам назад (угол самой спинки). Без чтения названий и номеров товаров: только геометрия и правила `data/flat3d/settle.json`.
// Локальные оси вещи — как у прочих наборов (`kits/common.ts`): центр следа, X — ширина, +Z — туда, куда смотрит опора; низ группы — на её месте.

import * as THREE from "three";

import settleJson from "@/data/flat3d/settle.json";

export type SettleRules = {
  roles: string[];
  shapes: string[];
  sinkCm: number;
  maxSnapCm: number;
  rayUpCm: number;
  probeFrac: number;
  lean: { maxDeg: number; lowCm: number; highCm: number; reachCm: number };
};
export const SETTLE_RULES: SettleRules = settleJson.soft;

const CM = 0.01;

/** Подходит ли вещь под посадку: роль меша («подушка», «подушка 2») или форма условной ткани. */
export function isSettled(kind: string, roleOrShape: string | null | undefined, rules: SettleRules = SETTLE_RULES): boolean {
  const base = String(roleOrShape ?? "").replace(/\s+\d+$/, "").trim().toLowerCase();
  if (!base) return false;
  return kind === "textile" ? rules.shapes.includes(base) : kind === "mesh" ? rules.roles.includes(base) : false;
}

export interface SettleResult {
  /** `settled` — посажена; `no-support` — под вещью ничего нет; `too-far` — верх опоры дальше `maxSnapCm` от отметки решателя (не сиденье). */
  why: "settled" | "no-support" | "too-far";
  /** Отметка низа от решателя и верх опоры под вещью, см (опоры нет — null). */
  plannedCm: number;
  supportCm: number | null;
  /** На сколько сдвинуто по вертикали, см, и угол наклона к спинке, градусы. */
  deltaCm: number;
  leanDeg: number;
}

/** Границы группы в её СОБСТВЕННЫХ осях (поворот места не растягивает ящик, как у мирового `Box3`). */
function localBox(group: THREE.Object3D): THREE.Box3 {
  group.updateWorldMatrix(true, true);
  const inv = new THREE.Matrix4().copy(group.matrixWorld).invert();
  const out = new THREE.Box3();
  const m = new THREE.Matrix4();
  group.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.visible || !mesh.geometry) return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const b = mesh.geometry.boundingBox!.clone();
    m.multiplyMatrices(inv, mesh.matrixWorld);
    out.union(b.applyMatrix4(m));
  });
  return out;
}

const ray = new THREE.Raycaster();
const solid = (supports: THREE.Object3D[], from: THREE.Vector3, dir: THREE.Vector3): THREE.Intersection | undefined => {
  ray.set(from, dir);
  return ray.intersectObjects(supports, true).find((h) => (h.object as THREE.Mesh).isMesh && h.object.visible);
};

/**
 * Посадить вещь `group` на `supports` (остальные предметы сцены без мягких вещей и растений). `plannedY` — отметка низа от решателя, м
 * (от неё считается каждый раз заново: повторный вызов не накапливает сдвиг). Вещь двигается только по высоте и наклону.
 */
export function settleOnSupport(group: THREE.Object3D, plannedY: number, supports: THREE.Object3D[], rules: SettleRules = SETTLE_RULES): SettleResult {
  group.rotation.order = "YXZ";
  group.rotation.x = 0;
  group.position.y = plannedY;
  const lb = localBox(group);
  const result = (why: SettleResult["why"], supportCm: number | null, deltaCm: number, leanDeg: number): SettleResult =>
    ({ why, plannedCm: +(plannedY / CM).toFixed(1), supportCm: supportCm === null ? null : +supportCm.toFixed(1), deltaCm: +deltaCm.toFixed(1), leanDeg: +leanDeg.toFixed(1) });
  if (lb.isEmpty()) return result("no-support", null, 0, 0);

  const bottom = plannedY + lb.min.y;                                   // низ вещи в мире, м
  const cx = (lb.min.x + lb.max.x) / 2, cz = (lb.min.z + lb.max.z) / 2, width = lb.max.x - lb.min.x;
  const down = new THREE.Vector3(0, -1, 0);
  const tops: number[] = [];
  let anyHit = false;
  for (const dx of [0, -rules.probeFrac * width, rules.probeFrac * width]) {
    const from = group.localToWorld(new THREE.Vector3(cx + dx, lb.min.y, cz));
    from.y = bottom + rules.rayUpCm * CM;
    const hit = solid(supports, from, down);
    if (!hit) continue;
    anyHit = true;
    if (Math.abs(hit.point.y - bottom) <= rules.maxSnapCm * CM) tops.push(hit.point.y);
  }
  if (!tops.length) return result(anyHit ? "too-far" : "no-support", null, 0, 0);
  const top = Math.max(...tops);
  const want = top - rules.sinkCm * CM;                                 // низ вещи в мире, м
  group.position.y += want - bottom;

  // наклон к спинке: два луча назад (−Z вещи) на двух высотах над сиденьем, угол — по росту расстояния до спинки с высотой
  group.updateWorldMatrix(true, true);
  const back = new THREE.Vector3(0, 0, -1).transformDirection(group.matrixWorld);
  const lo = rules.lean.lowCm * CM, hi = rules.lean.highCm * CM;
  const probe = (h: number): number | null => {
    const from = group.localToWorld(new THREE.Vector3(cx, lb.min.y, lb.max.z + rules.lean.reachCm * CM));
    from.y = top + h;
    return solid(supports, from, back)?.distance ?? null;
  };
  const t1 = probe(lo), t2 = probe(hi);
  let lean = 0;
  if (t1 !== null && t2 !== null && t2 >= t1) lean = Math.min(rules.lean.maxDeg, (Math.atan((t2 - t1) / (hi - lo)) * 180) / Math.PI);
  if (lean > 0) {
    group.rotation.x = (-lean * Math.PI) / 180;                         // верх — к спинке; ось через начало группы (низ, центр следа)
    group.updateWorldMatrix(true, true);
    // заваливаясь назад, подушка опирается на задний нижний край (передний чуть приподнимается — мягкая, не проваливается)
    const rear = group.localToWorld(new THREE.Vector3(cx, lb.min.y, lb.min.z));
    group.position.y += want - rear.y;
  }
  return result("settled", top / CM, (group.position.y - plannedY) / CM, lean);
}
