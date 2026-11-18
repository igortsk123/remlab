// Подушка и замена товара не зависят от часов (T-20261118-10/2): новая модель при замене «подрастает» 0.94 → 1 за 250 мс (`swap-ghost`), а выгрузка сцены для
// рендера шла сразу после загрузки — подушка попадала в файл то в 0.94, то в 1 (размер −6 %, узел сдвинут на 1,4 см). Теперь выгрузка доводит анимации до конца
// (`settleSwaps`), а посадка на опору считается по ПОЛНОМУ размеру (`atFullSize`) — результат не зависит от стадии роста.
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { settleOnSupport } from "@/lib/viewer3d/settle";
import { appearScale, SwapGhosts } from "@/lib/viewer3d/swap-ghost";
import { FlatViewer } from "@/lib/viewer3d/viewer";

const CM = 0.01;
/** Сиденье: плита 90×41×80 см, верх на 41 см, в начале координат. */
const seat = (): THREE.Group => {
  const g = new THREE.Group();
  const m = new THREE.Mesh(new THREE.BoxGeometry(90 * CM, 41 * CM, 80 * CM), new THREE.MeshBasicMaterial());
  m.position.y = 20.5 * CM;
  g.add(m);
  g.updateMatrixWorld(true);
  return g;
};
/** Подушка, у которой начало группы — в ЦЕНТРЕ модели (низ ящика ниже нуля на 20 см), как у мешей из сканов. */
const pillow = (): THREE.Group => {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.BoxGeometry(45 * CM, 40 * CM, 12 * CM), new THREE.MeshBasicMaterial()));
  g.position.set(0, 0.65, -30 * CM);
  g.updateMatrixWorld(true);
  return g;
};
const worldBottomCm = (g: THREE.Object3D): number => new THREE.Box3().setFromObject(g).min.y / CM;
/** Подушка в сцене как после замены товара: прежняя была, новая пришла — подрастает (масштаб 0.94 на момент `release`). */
function growing(): { gh: SwapGhosts<{ group: THREE.Object3D }>; fresh: THREE.Group } {
  const scene = new THREE.Scene();
  const gh = new SwapGhosts<{ group: THREE.Object3D }>(scene);
  const old = pillow();
  scene.add(old);
  gh.hold("подушка#0", { group: old }, true, 0);
  const fresh = pillow();
  scene.add(fresh);
  gh.release("подушка#0", fresh, 10);
  return { gh, fresh };
}

describe("посадка подушки не зависит от стадии роста новой модели", () => {
  it("с atFullSize посадка подрастающей модели = посадке по полному размеру, масштаб роста возвращается; после settle — тот же итог", () => {
    const supports = [seat()];
    const ref = pillow();
    settleOnSupport(ref, 0.65, supports);
    const fixed = growing();
    const r = fixed.gh.atFullSize(fixed.fresh, () => settleOnSupport(fixed.fresh, 0.65, supports));
    expect(r.why).toBe("settled");
    expect(fixed.fresh.position.y).toBeCloseTo(ref.position.y, 9);
    expect(fixed.fresh.rotation.x).toBeCloseTo(ref.rotation.x, 9);
    expect(fixed.fresh.scale.x).toBeCloseTo(appearScale(0));          // анимация роста продолжается, посадку не трогает
    fixed.gh.settle();
    expect(fixed.fresh.scale.x).toBe(1);
    fixed.fresh.updateMatrixWorld(true);
    expect(worldBottomCm(fixed.fresh)).toBeCloseTo(worldBottomCm(ref), 6);
  });

  it("при любой стадии роста результат посадки один и тот же", () => {
    const supports = [seat()];
    const ys: number[] = [];
    for (const k of [0.94, 0.96, 0.985, 1]) {
      const { gh, fresh } = growing();
      fresh.scale.setScalar(k);
      fresh.updateMatrixWorld(true);
      gh.atFullSize(fresh, () => settleOnSupport(fresh, 0.65, supports));
      ys.push(fresh.position.y);
    }
    for (const y of ys) expect(y).toBeCloseTo(ys[0]!, 9);
  });

  it("FlatViewer.settleSwaps: подрастающие модели — в полный размер, матрицы обновлены; повтор ничего не меняет", () => {
    const scene = new THREE.Scene();
    const v = Object.create(FlatViewer.prototype) as FlatViewer;
    const gh = new SwapGhosts<{ group: THREE.Object3D }>(scene);
    Object.assign(v, { scene, ghosts: gh });
    const old = pillow();
    scene.add(old);
    gh.hold("a", { group: old }, true, 0);
    const fresh = pillow();
    scene.add(fresh);
    gh.release("a", fresh, 10);
    expect(fresh.scale.x).toBeCloseTo(0.94);
    v.settleSwaps();
    expect(fresh.scale.x).toBe(1);
    expect(worldBottomCm(fresh)).toBeCloseTo(0.65 / CM - 20, 6);       // ящик по высоте 40 см, начало в центре: низ на 45 см
    expect(scene.children).not.toContain(old);                         // силуэт прежней — убран
    v.settleSwaps();
    expect(fresh.scale.x).toBe(1);
  });
});
