// Телевизор над ТВ-тумбой — собирается кодом, как на серверном кадре (`draft_render._tv_parts`, план demo-05 п.9).
// Готовая модель не годится (владелец 02.09, «стоит задом наперёд»): экран у неё утоплен в корпус, стойка вынесена вперёд.
// Здесь лицо задано построением: экран — самая передняя поверхность (+Z, как у всех комплектов), подставка — сзади.

import * as THREE from "three";

import { box, type KitCtx } from "@/lib/viewer3d/kits/common";

export interface TvSpec {
  widthCm: number;
  heightCm: number;
  depthCm: number;
  /** На стене — без подставки, панель всей высотой. */
  hung: boolean;
}

const SCREEN = new THREE.MeshStandardMaterial({ color: 0x181a1c, roughness: 0.18, metalness: 0.2 }); // выключенный экран
const CASE = new THREE.MeshStandardMaterial({ color: 0x2e3135, roughness: 0.45, metalness: 0.3 });
const STAND = new THREE.MeshStandardMaterial({ color: 0x26292d, roughness: 0.4, metalness: 0.4 });

export function buildTv(_ctx: KitCtx, spec: TvSpec): THREE.Group {
  const g = new THREE.Group();
  const { widthCm: w, heightCm: h, depthCm: d, hung } = spec;
  const panelD = Math.min(6, d * 0.45);
  const bez = Math.min(2.2, w * 0.03);
  // низ телевизора: на тумбе его приподнимает подставка, на стене он висит всей высотой
  const foot = hung ? 0 : Math.min(9, h * 0.14);
  const ph = h - foot;
  const cy = h / 2 + foot / 2; // центр панели от низа предмета
  const zf = d / 2 - panelD / 2; // панель прижата к переднему краю
  g.add(box(w, ph, panelD, 0, cy, zf, CASE));
  g.add(box(w - 2 * bez, ph - 2 * bez, 0.7, 0, cy, zf + panelD / 2 - 0.35, SCREEN));
  if (!hung) {
    g.add(box(7, foot, d * 0.5, 0, foot / 2 + 1, zf - panelD, STAND)); // шея
    g.add(box(w * 0.34, 2, d * 0.9, 0, 1, 0, STAND)); // опора
  }
  return g;
}
