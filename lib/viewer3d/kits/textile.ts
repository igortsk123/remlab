// УСЛОВНАЯ ТКАНЬ — ШТОРА И ПЛЕД ЦВЕТОМ ТОВАРА (T-20261112-74, владелец TG 953): из фото магазина ткань чисто не вырезать (разбор
// T-73), меш строит чужую мебель — поэтому простая форма своим цветом, в карточке «вид условный». Штора — полотна той же формы, что
// декоративные шторы сцены (`window-light.ts:curtainPanels`); плед — сложенный брусок с мягкими краями на подлокотнике и свисающий
// край спереди. Материал — цвет товара; тюль и вуаль — полупрозрачные (окно и свет видны).
//
// Локальные оси пледа — как у прочих наборов (`kits/common.ts`): центр следа, X — ширина (поперёк подлокотника), Z — глубина
// (вдоль глубины дивана), лицо в +Z (туда, куда смотрит диван); низ — на высоте места (`placement.elevCm` → `placeGroup`).

import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

import type { Room } from "@/contracts/apartment";
import { CM, mat, type KitCtx } from "@/lib/viewer3d/kits/common";
import { curtainPanels } from "@/lib/viewer3d/window-light";

/** Прозрачность тюля: окно видно, полотно читается. */
export const SHEER_OPACITY = 0.45;
/** Свисающий край пледа спереди подлокотника, см. */
export const THROW_DROP_CM = 22;

/** Материал ткани товара: шероховатый, двусторонний (полотно видно и из-за окна); тюль — полупрозрачный, без записи глубины. */
export function clothMaterial(ctx: KitCtx, materialId: string | undefined, sheer: boolean): THREE.MeshStandardMaterial {
  const m = mat(ctx, materialId).clone();
  m.side = THREE.DoubleSide;
  m.roughness = 0.95;
  if (sheer) {
    m.transparent = true;
    m.opacity = SHEER_OPACITY;
    m.depthWrite = false;
  }
  return m;
}

/**
 * Штора-товар у окна `opening` комнаты: полотна в координатах сцены переводятся в оси группы (группу ставит `placeGroup` по месту
 * слота), поэтому рамка выбора и ценник — по самим полотнам. Окна нет — пустая группа.
 */
export function buildProductCurtain(ctx: KitCtx, room: Room, opening: number, materialId: string | undefined, sheer: boolean,
  frame: THREE.Object3D): THREE.Group {
  const g = new THREE.Group();
  const material = clothMaterial(ctx, materialId, sheer);
  frame.updateMatrixWorld(true);
  const inv = frame.matrixWorld.clone().invert();
  for (const m of curtainPanels(room, opening, material, { sheer })) {
    m.updateMatrix();
    m.applyMatrix4(inv);
    m.castShadow = !sheer;
    m.receiveShadow = true;
    // тюль закрывает стекло: тап сквозь него — «подойти к окну», не выбор шторы (`viewer.walkAim`; выбор — ценником и краем у стены)
    if (sheer) m.userData.seeThrough = true;
    g.add(m);
  }
  return g;
}

/** Сложенный плед: брусок со скруглёнными краями на подлокотнике и свисающий край спереди (тоньше, чуть отстоит от подлокотника). */
export function buildThrow(ctx: KitCtx, spec: { widthCm: number; depthCm: number; heightCm: number; materialId?: string }): THREE.Group {
  const g = new THREE.Group();
  const material = clothMaterial(ctx, spec.materialId, false);
  const { widthCm: w, depthCm: d, heightCm: h } = spec;
  const top = new THREE.Mesh(new RoundedBoxGeometry(w * CM, h * CM, d * CM, 3, Math.min(h / 2, 2) * CM), material);
  top.position.set(0, (h / 2) * CM, 0);
  const t = Math.max(1.5, h / 2);
  const flap = new THREE.Mesh(new RoundedBoxGeometry(w * 0.96 * CM, THROW_DROP_CM * CM, t * CM, 3, (t / 2) * CM), material);
  flap.position.set(0, (h - THROW_DROP_CM / 2) * CM, (d / 2 + t / 2 - 0.5) * CM);
  for (const m of [top, flap]) {
    m.castShadow = true;
    m.receiveShadow = true;
    g.add(m);
  }
  return g;
}
