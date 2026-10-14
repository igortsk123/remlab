// Окна и двери: рама, стекло, подоконник, откосы, дверное полотно с наличником.
//
// ЗАЧЕМ ОТДЕЛЬНО: до этого проём был просто дыркой в стене — окно читалось как синий
// прямоугольник, дверь как пустой вырез (владелец 29.09: «вставь вид из окон и окна нормально
// чтоб было; двери и окна визуально должны выглядеть стандартно но хорошо»).
//
// СИСТЕМА КООРДИНАТ: всё строится в ЛОКАЛЬНЫХ осях стены — группа ставится в начало стены и
// поворачивается так, что локальный X идёт вдоль стены (как отступ `offsetCm`), Y — вверх,
// Z — ВНУТРЬ комнаты. Поэтому здесь нет ни одной тригонометрии: размеры пишутся как на чертеже.

import * as THREE from "three";

import type { Opening } from "@/contracts/apartment";
import { openingIR, type OpeningIR, type OpeningMaterial } from "@/lib/viewer3d/opening-ir";

const CM = 0.01;

const WHITE_FRAME = new THREE.MeshStandardMaterial({ color: 0xf4f3f0, roughness: 0.55 });
const REVEAL = new THREE.MeshStandardMaterial({ color: 0xeceae5, roughness: 0.9 });
// Стекло: почти прозрачное. При opacity 0.22 окно читалось белой панелью и закрывало вид
// (кадр 29.09) — стекло должно показывать улицу, а не заменять её.
const GLASS = new THREE.MeshPhysicalMaterial({
  color: 0xeaf2f6,
  roughness: 0.04,
  metalness: 0,
  transparent: true,
  opacity: 0.07,
  depthWrite: false,
  side: THREE.DoubleSide,
});
const DOOR_LEAF = new THREE.MeshStandardMaterial({ color: 0xf2f0ec, roughness: 0.6 });
const DOOR_PANEL = new THREE.MeshStandardMaterial({ color: 0xe8e5e0, roughness: 0.65 });
const HANDLE = new THREE.MeshStandardMaterial({ color: 0xb9bdc2, roughness: 0.25, metalness: 0.85 });

function box(
  w: number,
  h: number,
  d: number,
  x: number,
  y: number,
  z: number,
  material: THREE.Material,
): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w * CM, h * CM, d * CM), material);
  m.position.set(x * CM, y * CM, z * CM);
  m.castShadow = false;
  m.receiveShadow = true;
  return m;
}

const MATERIAL: Record<OpeningMaterial, THREE.Material> = {
  frame: WHITE_FRAME,
  reveal: REVEAL,
  glass: GLASS,
  leaf: DOOR_LEAF,
  panel: DOOR_PANEL,
  handle: HANDLE,
};

/** Меши проёма из его описания (`opening-ir.ts`) — те же коробки, что получает серверный кадр. */
export function meshesFromIR(ir: OpeningIR): THREE.Group {
  const g = new THREE.Group();
  const groups = new Map<string, THREE.Group>();
  for (const [name, gr] of Object.entries(ir.groups)) {
    const sub = new THREE.Group();
    sub.position.set(gr.x * CM, gr.y * CM, gr.z * CM);
    sub.rotation.y = (gr.rotYDeg * Math.PI) / 180;
    groups.set(name, sub);
    g.add(sub);
  }
  ir.boxes.forEach((x, i) => {
    const m = box(x.w, x.h, x.d, x.x, x.y, x.z, MATERIAL[x.material]);
    m.userData.part = x.role;
    m.userData.irIndex = i; // номер коробки в описании — по нему тест сверяет деталь с серверным кадром
    (x.group ? groups.get(x.group) ?? g : g).add(m);
  });
  return g;
}

export interface OpeningVisualOpts {
  /** Входная дверь квартиры: полотно закрыто. */
  entranceWall?: string;
  /** Все полотна закрыты (квартира из одной комнаты — двери ведут в несуществующее). */
  doorsClosed?: boolean;
  heightCm: number;
}

/** Все проёмы одной стены. `openings` уже в координатах «вдоль стены от её начала». */
export function buildOpenings(openings: Opening[], side: string, opts: OpeningVisualOpts): THREE.Group {
  const g = new THREE.Group();
  for (const o of openings) g.add(meshesFromIR(openingIR(o, { wallHeightCm: opts.heightCm, entrance: !!opts.doorsClosed || opts.entranceWall === side })));
  return g;
}
