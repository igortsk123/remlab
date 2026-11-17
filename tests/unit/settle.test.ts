// Посадка мягких вещей на меш опоры (T-20261117-10): подушка стоит на верхе сиденья по мешу, а не на отметке решателя; наклон к спинке — по
// углу спинки; опора дальше `maxSnapCm` или её нет — вещь не трогается; повторный вызов не накапливает сдвиг. Без сети и моделей: диван — коробки.
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { isSettled, SETTLE_RULES, settleOnSupport, type SettleRules } from "@/lib/viewer3d/settle";

const CM = 0.01;
const box = (w: number, h: number, d: number, x: number, y: number, z: number): THREE.Mesh => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w * CM, h * CM, d * CM), new THREE.MeshBasicMaterial());
  m.position.set(x * CM, (y + h / 2) * CM, z * CM);
  return m;
};
/** Диван в начале координат лицом в +Z: сиденье 90×seat×80 (глубина −40…+40), спинка сзади на всю ширину, наклон назад на `tiltDeg`. */
function sofa(seatCm: number, tiltDeg = 0): THREE.Group {
  const g = new THREE.Group();
  g.add(box(90, seatCm, 80, 0, 0, 0));
  const back = box(90, 40, 12, 0, seatCm, -40 + 6);       // нижний край спинки на сиденье, у задней кромки
  back.geometry.translate(0, 20 * CM, 0);                  // ось поворота — по низу спинки
  back.position.y = seatCm * CM;
  back.rotation.x = (-tiltDeg * Math.PI) / 180;            // верх — назад (−Z)
  g.add(back);
  g.updateMatrixWorld(true);
  return g;
}
/** Подушка 45×45×12 стоя: низ группы в нуле, центр следа в начале, лицо в +Z. */
function pillow(): THREE.Group {
  const g = new THREE.Group();
  const m = box(45, 45, 12, 0, 0, 0);
  g.add(m);
  return g;
}
const place = (g: THREE.Group, x: number, y: number, z: number): void => { g.position.set(x * CM, y * CM, z * CM); g.updateMatrixWorld(true); };
const bottomCm = (g: THREE.Group): number => new THREE.Box3().setFromObject(g).min.y / CM;

describe("посадка мягких вещей на меш опоры", () => {
  it("подушка с отметкой решателя 45 садится на сиденье 41 см с осадкой — не парит", () => {
    const s = sofa(41);
    const p = pillow();
    place(p, 0, 45, -30);                                  // как решатель: низ 45, у спинки
    const r = settleOnSupport(p, 0.45, [s]);
    expect(r.why).toBe("settled");
    expect(r.supportCm).toBeCloseTo(41, 1);
    expect(bottomCm(p)).toBeCloseTo(41 - SETTLE_RULES.sinkCm, 1);
    expect(r.deltaCm).toBeCloseTo(-5, 1);
  });

  it("сиденье выше отметки (47 см) — подушка поднимается; повторный вызов ничего не накапливает", () => {
    const s = sofa(47);
    const p = pillow();
    place(p, 0, 45, -30);
    const a = settleOnSupport(p, 0.45, [s]);
    const y1 = p.position.y;
    const b = settleOnSupport(p, 0.45, [s]);
    expect(a.why).toBe("settled");
    expect(p.position.y).toBeCloseTo(y1, 9);
    expect(b.deltaCm).toBeCloseTo(a.deltaCm, 1);
    expect(bottomCm(p)).toBeCloseTo(47 - SETTLE_RULES.sinkCm, 1);
  });

  it("наклон к спинке равен наклону самой спинки, не выше предела; прямая спинка — без наклона", () => {
    const tilted = sofa(41, 12);
    const p = pillow();
    place(p, 0, 45, -20);
    const r = settleOnSupport(p, 0.45, [tilted]);
    expect(r.leanDeg).toBeGreaterThan(8);
    expect(r.leanDeg).toBeLessThanOrEqual(SETTLE_RULES.lean.maxDeg);
    expect(p.rotation.x).toBeLessThan(0);                  // верх — назад
    expect(bottomCm(p)).toBeGreaterThan(41 - SETTLE_RULES.sinkCm - 0.6);   // задний нижний край на сиденье, наклон не проваливает вещь
    const straight = sofa(41, 0);
    const q = pillow();
    place(q, 0, 45, -20);
    expect(settleOnSupport(q, 0.45, [straight]).leanDeg).toBeLessThan(1);
    const steep = sofa(41, 35);
    const z = pillow();
    place(z, 0, 45, -20);
    expect(settleOnSupport(z, 0.45, [steep]).leanDeg).toBe(SETTLE_RULES.lean.maxDeg);
  });

  it("верх опоры дальше maxSnapCm от отметки — вещь не трогается (луч попал не в сиденье); опоры нет — тоже", () => {
    const low = sofa(30);
    const p = pillow();
    place(p, 0, 45, -30);
    const r = settleOnSupport(p, 0.45, [low]);
    expect(r.why).toBe("too-far");
    expect(p.position.y).toBeCloseTo(0.45, 9);
    const q = pillow();
    place(q, 300, 45, 300);
    expect(settleOnSupport(q, 0.45, [sofa(41)]).why).toBe("no-support");
    expect(q.position.y).toBeCloseTo(0.45, 9);
  });

  it("правило — по данным: роли и формы из settle.json, других вещей не касается", () => {
    expect(isSettled("mesh", "подушка")).toBe(true);
    expect(isSettled("mesh", "подушка 2")).toBe(true);
    expect(isSettled("textile", "pillow")).toBe(true);
    expect(isSettled("textile", "curtain")).toBe(false);
    expect(isSettled("mesh", "лампа")).toBe(false);
    const own: SettleRules = { ...SETTLE_RULES, roles: ["плед"] };
    expect(isSettled("mesh", "плед", own)).toBe(true);
    expect(isSettled("mesh", "подушка", own)).toBe(false);
  });
});
