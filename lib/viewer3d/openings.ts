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

/** Окно: коробка рамы, две створки со средником, стекло, подоконник и откосы. */
function window3d(u0: number, u1: number, sill: number, top: number): THREE.Group {
  const g = new THREE.Group();
  const w = u1 - u0;
  const h = top - sill;
  const cx = (u0 + u1) / 2;
  const cy = (sill + top) / 2;
  const P = 6; // профиль рамы
  const DEPTH = 12; // толщина оконного блока

  // откосы: без них проём выглядит бумажным
  g.add(box(w + 2, 4, DEPTH, cx, top + 2, 0, REVEAL));
  g.add(box(w + 2, 4, DEPTH, cx, sill - 2, 0, REVEAL));
  g.add(box(4, h + 8, DEPTH, u0 - 2, cy, 0, REVEAL));
  g.add(box(4, h + 8, DEPTH, u1 + 2, cy, 0, REVEAL));

  // коробка рамы
  g.add(box(w, P, DEPTH, cx, top - P / 2, 0, WHITE_FRAME));
  g.add(box(w, P, DEPTH, cx, sill + P / 2, 0, WHITE_FRAME));
  g.add(box(P, h, DEPTH, u0 + P / 2, cy, 0, WHITE_FRAME));
  g.add(box(P, h, DEPTH, u1 - P / 2, cy, 0, WHITE_FRAME));

  // средник: стандартное окно в две створки
  g.add(box(P * 0.8, h - P * 2, DEPTH * 0.9, cx, cy, 0, WHITE_FRAME));

  // стекло — чуть наружу от плоскости стены
  g.add(box(w - P * 2, h - P * 2, 1.2, cx, cy, -3, GLASS));

  // подоконник внутрь комнаты
  g.add(box(w + 10, 3.5, 20, cx, sill - 1, 9, WHITE_FRAME));
  return g;
}

/**
 * Дверь: наличник + полотно. Межкомнатное полотно показываем ОТКРЫТЫМ к стене — так проём
 * остаётся проходимым (по нему ходит человек) и при этом видно, что дверь есть.
 * Входная дверь — закрытая, с ручкой: это «лицо» квартиры.
 */
function door3d(u0: number, u1: number, top: number, entrance: boolean): THREE.Group {
  const g = new THREE.Group();
  const w = u1 - u0;
  const cx = (u0 + u1) / 2;
  const P = 5;
  const DEPTH = 12;

  g.add(box(4, top + 6, DEPTH, u0 - 2, (top + 6) / 2, 0, REVEAL));
  g.add(box(4, top + 6, DEPTH, u1 + 2, (top + 6) / 2, 0, REVEAL));
  g.add(box(w + 8, 4, DEPTH, cx, top + 2, 0, REVEAL));

  g.add(box(P, top, DEPTH, u0 + P / 2, top / 2, 0, WHITE_FRAME));
  g.add(box(P, top, DEPTH, u1 - P / 2, top / 2, 0, WHITE_FRAME));
  g.add(box(w, P, DEPTH, cx, top - P / 2, 0, WHITE_FRAME));

  const leafW = w - P * 2 - 1;
  const leafH = top - P - 1;
  const leaf = new THREE.Group();
  leaf.add(box(leafW, leafH, 4, leafW / 2, leafH / 2, 0, DOOR_LEAF));
  // две филёнки — «стандартная, но хорошая» межкомнатная дверь
  leaf.add(box(leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.28, 2.2, DOOR_PANEL));
  leaf.add(box(leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.68, 2.2, DOOR_PANEL));
  const handleY = 105;
  leaf.add(box(12, 2.2, 2.2, leafW - 8, handleY, 3.2, HANDLE));
  leaf.add(box(2.4, 2.4, 4, leafW - 4, handleY, 2.6, HANDLE));

  if (entrance) {
    leaf.position.set(u0 + P / 2, 0, 0);
  } else {
    // распахнута к стене на ~100°: полотно уходит внутрь комнаты вдоль стены
    leaf.position.set(u0 + P / 2, 0, 2);
    leaf.rotation.y = -Math.PI * 0.55;
  }
  g.add(leaf);
  return g;
}

/** Открытый портал (кухня-гостиная): только наличник, полотна нет. */
function portal3d(u0: number, u1: number, top: number): THREE.Group {
  const g = new THREE.Group();
  const w = u1 - u0;
  const cx = (u0 + u1) / 2;
  g.add(box(5, top, 14, u0 + 2.5, top / 2, 0, WHITE_FRAME));
  g.add(box(5, top, 14, u1 - 2.5, top / 2, 0, WHITE_FRAME));
  g.add(box(w, 5, 14, cx, top - 2.5, 0, WHITE_FRAME));
  return g;
}

export interface OpeningVisualOpts {
  /** Входная дверь квартиры: полотно закрыто. */
  entranceWall?: string;
  heightCm: number;
}

/** Все проёмы одной стены. `openings` уже в координатах «вдоль стены от её начала». */
export function buildOpenings(openings: Opening[], side: string, opts: OpeningVisualOpts): THREE.Group {
  const g = new THREE.Group();
  for (const o of openings) {
    const u0 = o.offsetCm;
    const u1 = o.offsetCm + o.widthCm;
    if (o.kind === "window") {
      const sill = o.sillCm ?? 90;
      const top = Math.min(opts.heightCm, sill + (o.heightCm ?? 140));
      g.add(window3d(u0, u1, sill, top));
      continue;
    }
    const top = Math.min(opts.heightCm - 5, o.heightCm ?? 205);
    if (o.kind === "opening") {
      g.add(portal3d(u0, u1, top));
      continue;
    }
    g.add(door3d(u0, u1, top, opts.entranceWall === side));
  }
  return g;
}
