// НАСТЕННАЯ ПЛОСКОСТЬ — зеркало или картина (T-20261106-73, план hall-demo-01 этап 2). Стратегия ассета роли —
// `procedural_plane` (`tools/scout/rules/asset-strategies.json`): модели нет и не будет, предмет собирается кодом по габаритам
// товара. Рама — коробка Ш×В×Г у стены, полотно — плоскость на лицевой стороне (+Z). Зеркало — светлый гладкий металл: в сцене
// есть карта окружения (`viewer.ts`, RoomEnvironment), и оно даёт слабый отблеск; настоящих отражений нет (скоуп плана).
// Высоту подвеса задаёт место (`placement.elevCm` → `placeGroup`), а не набор.

import * as THREE from "three";

import type { Placement } from "@/contracts/apartment";
import { CM, boxOn, mat, type KitCtx } from "@/lib/viewer3d/kits/common";

export interface WallPlaneSpec {
  widthCm: number;
  heightCm: number;
  depthCm: number;
  mirror: boolean;
  /** Материал рамы (зеркало) или полотна с фото товара (картина). */
  materialId?: string;
}

/** Ширина рамы: 6 % меньшей стороны, 1,5…4 см — у маленького зеркала рама не съедает полотно. */
export function frameCm(widthCm: number, heightCm: number): number {
  return Math.min(4, Math.max(1.5, Math.min(widthCm, heightCm) * 0.06));
}

/** Полотно в локальных осях набора: прямоугольник внутри рамы, на лицевой стороне (z = глубина/2 + зазор от мерцания). */
export function canvasRect(spec: Pick<WallPlaneSpec, "widthCm" | "heightCm" | "depthCm">): { w: number; h: number; y: number; z: number } {
  const f = frameCm(spec.widthCm, spec.heightCm);
  return { w: Math.max(1, spec.widthCm - 2 * f), h: Math.max(1, spec.heightCm - 2 * f), y: spec.heightCm / 2, z: spec.depthCm / 2 + 0.2 };
}

/**
 * Лицевая сторона в координатах квартиры (см): четыре угла полотна (низ-лево, низ-право, верх-право, верх-лево — если смотреть
 * на зеркало) и нормаль. Та же конвенция, что `placeGroup` (`viewer.ts`): центр следа (x, y), поворот по часовой, rot 0 — лицом
 * на +y; высота — от пола. Нужна для проверок «на какой стене, куда смотрит, на какой высоте».
 */
export function wallPlaneFace(p: Placement): { corners: [number, number, number][]; normal: [number, number] } {
  const r = canvasRect({ widthCm: p.wCm, heightCm: p.hCm, depthCm: p.dCm });
  const a = (p.rot * Math.PI) / 180;
  const [nx, ny] = [Math.sin(a), Math.cos(a)];          // локальная +Z
  const [ux, uy] = [Math.cos(a), -Math.sin(a)];         // локальная +X
  const cx = p.x + nx * r.z, cy = p.y + ny * r.z;
  const z0 = (p.elevCm ?? 0) + r.y - r.h / 2, z1 = z0 + r.h;
  const at = (s: number, z: number): [number, number, number] => [round(cx + ux * s), round(cy + uy * s), round(z)];
  return { corners: [at(-r.w / 2, z0), at(r.w / 2, z0), at(r.w / 2, z1), at(-r.w / 2, z1)], normal: [round(nx), round(ny)] };
}

const round = (v: number): number => Math.round(v * 100) / 100 || 0;

/**
 * Полотно зеркала: светлое, холодноватое, гладкое — с небольшой долей металла для блика от карты окружения. Полный металл
 * (metalness 1) отражал только тёмную процедурную комнату окружения и читался выключенным экраном (снимки стенда 06.11).
 */
const MIRROR = { color: 0xdfe7eb, metalness: 0.3, roughness: 0.12, envMapIntensity: 1 };

export function buildWallPlane(ctx: KitCtx, spec: WallPlaneSpec): THREE.Group {
  const g = new THREE.Group();
  const frame = mat(ctx, spec.materialId);
  const r = canvasRect(spec);
  if (spec.mirror) {
    g.add(boxOn(spec.widthCm, spec.heightCm, spec.depthCm, 0, 0, 0, frame));
    g.add(sheet(r.w, r.h, r.y, r.z, new THREE.MeshStandardMaterial(MIRROR)));
  } else {
    // картина: тонкий подрамник и фото товара на всё полотно
    g.add(boxOn(spec.widthCm, spec.heightCm, spec.depthCm, 0, 0, 0, new THREE.MeshStandardMaterial({ color: 0x8c857b, roughness: 0.8 })));
    g.add(sheet(spec.widthCm, spec.heightCm, spec.heightCm / 2, r.z, frame));
  }
  return g;
}

/** Плоскость Ш×В (см) лицом в +Z, центр на высоте y и глубине z. */
function sheet(w: number, h: number, y: number, z: number, material: THREE.Material): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w * CM, h * CM), material);
  m.position.set(0, y * CM, z * CM);
  return m;
}
