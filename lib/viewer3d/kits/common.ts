// Общее для параметрических комплектов (кухня, санузел, кровать, шкаф) — ADR-0213.
//
// ПОЧЕМУ КОДОМ, А НЕ МЕШЕМ: мешей кухонь и сантехники у нас нет, а варианты застройщика —
// это по сути материалы и набор техники. Кодом это весит ноль байт, переключается мгновенно
// и остаётся честным по размерам. Тот же код потом станет основой Sims-редактора.
//
// ЛОКАЛЬНЫЕ ОСИ комплекта (как у мешей): начало — центр footprint на полу, X — ширина,
// Y — вверх, Z — глубина, лицо смотрит в +Z. Поворот и место задаёт вызывающий.

import * as THREE from "three";

import type { Material } from "@/contracts/configurator";
import { type MaterialCtx, baseMaterial, tiled } from "@/lib/viewer3d/materials";

export const CM = 0.01;

export interface KitCtx {
  materials: MaterialCtx;
  byId: (id: string) => Material | undefined;
  fallback: Material;
}

export function mat(ctx: KitCtx, id: string | undefined, sizeCm?: [number, number]): THREE.MeshStandardMaterial {
  const m = (id ? ctx.byId(id) : undefined) ?? ctx.fallback;
  return sizeCm ? tiled(ctx.materials, m, sizeCm[0], sizeCm[1]) : baseMaterial(ctx.materials, m);
}

/** Коробка в сантиметрах с центром в (x, y, z) — y отсчитывается от пола до ЦЕНТРА. */
export function box(
  w: number,
  h: number,
  d: number,
  x: number,
  y: number,
  z: number,
  material: THREE.Material,
): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w * CM, h * CM, d * CM), material);
  mesh.position.set(x * CM, y * CM, z * CM);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

/** Коробка, стоящая НА полу: y0 — низ. Так удобнее описывать мебель. */
export function boxOn(
  w: number,
  h: number,
  d: number,
  x: number,
  y0: number,
  z: number,
  material: THREE.Material,
): THREE.Mesh {
  return box(w, h, d, x, y0 + h / 2, z, material);
}

export function cylinder(
  rTop: number,
  rBottom: number,
  h: number,
  x: number,
  y0: number,
  z: number,
  material: THREE.Material,
  segments = 16,
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(rTop * CM, rBottom * CM, h * CM, segments),
    material,
  );
  mesh.position.set(x * CM, (y0 + h / 2) * CM, z * CM);
  mesh.castShadow = true;
  return mesh;
}

/** Ручка-рейлинг: тонкая планка вдоль X. */
export function handle(lenCm: number, x: number, y: number, z: number, material: THREE.Material): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(lenCm * CM, 0.015, 0.02), material);
  m.position.set(x * CM, y * CM, z * CM);
  return m;
}

export const METAL = new THREE.MeshStandardMaterial({ color: 0xc8ccd0, roughness: 0.25, metalness: 0.9 });
export const DARK_GLASS = new THREE.MeshStandardMaterial({ color: 0x24262a, roughness: 0.15, metalness: 0.3 });
export const WHITE_GLOSS = new THREE.MeshStandardMaterial({ color: 0xf7f6f3, roughness: 0.12, metalness: 0 });
export const GLASS = new THREE.MeshPhysicalMaterial({
  color: 0xdfe8ea,
  roughness: 0.05,
  metalness: 0,
  transparent: true,
  opacity: 0.35,
});
export const LIGHT_STRIP = new THREE.MeshStandardMaterial({
  color: 0xfff4d8,
  emissive: 0xffe9b0,
  emissiveIntensity: 0.8,
  roughness: 0.6,
});

/** Разбиение длины на створки примерно равной ширины (не уже 30 см). */
export function splitUnits(lengthCm: number, targetCm = 60): number[] {
  const n = Math.max(1, Math.round(lengthCm / targetCm));
  const w = lengthCm / n;
  return Array.from({ length: n }, () => w);
}
