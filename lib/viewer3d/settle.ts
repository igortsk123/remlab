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
/** Грань смотрит вверх (нормаль в мире, y > 0,3): низ и бока опоры сиденьем не считаются. */
const faceUp = (h: THREE.Intersection): boolean =>
  !h.face || h.face.normal.clone().transformDirection(h.object.matrixWorld).y > 0.3;
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
  const band = rules.maxSnapCm * CM;
  for (const dx of [0, -rules.probeFrac * width, rules.probeFrac * width]) {
    // луч — сверху вниз с запасом выше подлокотника и спинки; сиденье — обращённая вверх грань в полосе вокруг отметки решателя: верх
    // подлокотника или спинки (выше полосы) луч пропускает, подпушка под подлокотником не цепляет
    const from = group.localToWorld(new THREE.Vector3(cx + dx, lb.min.y, cz));
    from.y = bottom + rules.rayUpCm * CM;
    ray.set(from, down);
    const hits = ray.intersectObjects(supports, true).filter((h) => (h.object as THREE.Mesh).isMesh && h.object.visible && faceUp(h));
    if (hits.length) anyHit = true;
    // в полосе берём САМУЮ НИЗКУЮ грань: выше сиденья в полосе бывают валик спинки и край подлокотника, подушка лежит на сиденье под ними
    const inBand = hits.filter((h) => Math.abs(h.point.y - bottom) <= band);
    if (inBand.length) tops.push(Math.min(...inBand.map((h) => h.point.y)));
  }
  if (!tops.length) return result(anyHit ? "too-far" : "no-support", null, 0, 0);
  tops.sort((a, b) => a - b);
  const top = tops[Math.floor((tops.length - 1) / 2)]!;                 // середина по трём лучам: один неудачный (шов, пуговица) не двигает вещь
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
  // доводка по самой низкой точке пробовалась (T-20261117-10) и отвергнута: на мягком диване низшая вершина попадает в шов между подушками и
  // утапливает всю подушку на 2–3 см глубже (замер after5) — три луча по ширине и их середина (выше) ложатся точнее
  return result("settled", top / CM, (group.position.y - plannedY) / CM, lean);
}

/** Самая низкая точка видимых мешей группы в мире, м (вершины); пусто — null. Для доводки посадки и для замера зазора (`FlatViewer.supportGaps`). */
export function lowestPoint(group: THREE.Object3D): THREE.Vector3 | null {
  group.updateWorldMatrix(true, true);
  const low = new THREE.Vector3(0, Infinity, 0);
  const v = new THREE.Vector3();
  group.traverse((o) => {
    const m = o as THREE.Mesh;
    const pos = m.isMesh && m.visible ? m.geometry?.getAttribute("position") : undefined;
    if (!pos) return;
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos as THREE.BufferAttribute, i).applyMatrix4(m.matrixWorld);
      if (v.y < low.y) low.copy(v);
    }
  });
  return Number.isFinite(low.y) ? low : null;
}
