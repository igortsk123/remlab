// Материалы сцены: из контракта каталога → THREE.MeshStandardMaterial.
// Ключевое здесь — ФИЗИЧЕСКИЙ размер повтора (`tileCm`): без него доска пола растягивается
// на всю комнату. Повтор считаем от размера поверхности в сантиметрах, а не «на глаз».

import * as THREE from "three";

import type { Material } from "@/contracts/configurator";

export interface MaterialCtx {
  loader: THREE.TextureLoader;
  cache: Map<string, THREE.Texture>;
  materials: Map<string, THREE.MeshStandardMaterial>;
  anisotropy: number;
  useMaps: boolean;
  /** Лёгкий режим (телефон): только цветовая карта, без normal/roughness/AO. */
  extraMaps: boolean;
}

export function createMaterialCtx(anisotropy: number, useMaps: boolean, extraMaps = true): MaterialCtx {
  return {
    loader: new THREE.TextureLoader(),
    cache: new Map(),
    materials: new Map(),
    anisotropy,
    useMaps,
    extraMaps,
  };
}

function texture(ctx: MaterialCtx, url: string, srgb: boolean): THREE.Texture {
  const key = `${url}|${srgb ? "srgb" : "lin"}`;
  const hit = ctx.cache.get(key);
  if (hit) return hit;
  const t = ctx.loader.load(url);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = ctx.anisotropy;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  ctx.cache.set(key, t);
  return t;
}

/**
 * Материал по описанию. Один объект THREE на материал каталога — повтор текстуры задаётся
 * НЕ здесь, а клоном на конкретной поверхности (`tiled`), иначе пол и фартук дрались бы за
 * общий `repeat`.
 */
export function baseMaterial(ctx: MaterialCtx, m: Material): THREE.MeshStandardMaterial {
  const hit = ctx.materials.get(m.id);
  if (hit) return hit;
  const mat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(m.colorHex),
    roughness: m.roughness,
    metalness: m.metalness,
  });
  if (ctx.useMaps && m.baseColorUrl) {
    mat.map = texture(ctx, m.baseColorUrl, true);
    mat.color.set("#ffffff"); // цвет уже в текстуре, иначе двойное умножение
  }
  if (ctx.useMaps && ctx.extraMaps && m.normalUrl) {
    mat.normalMap = texture(ctx, m.normalUrl, false);
    mat.normalScale = new THREE.Vector2(0.7, 0.7);
  }
  if (ctx.useMaps && ctx.extraMaps && m.roughnessUrl) mat.roughnessMap = texture(ctx, m.roughnessUrl, false);
  if (ctx.useMaps && ctx.extraMaps && m.aoUrl) mat.aoMap = texture(ctx, m.aoUrl, false);
  ctx.materials.set(m.id, mat);
  return mat;
}

/**
 * Копия материала с повтором под размер поверхности: `wCm × hCm` — реальный размер пятна,
 * `tileCm` — сколько сантиметров в одном повторе текстуры.
 */
export function tiled(
  ctx: MaterialCtx,
  m: Material,
  wCm: number,
  hCm: number,
  rotateDeg = 0,
  offsetCm: [number, number] = [0, 0],
): THREE.MeshStandardMaterial {
  const src = baseMaterial(ctx, m);
  const mat = src.clone();
  const rx = Math.max(0.05, wCm / m.tileCm[0]);
  const ry = Math.max(0.05, hCm / m.tileCm[1]);
  for (const key of ["map", "normalMap", "roughnessMap", "aoMap"] as const) {
    const t = mat[key];
    if (!t) continue;
    const copy = t.clone();
    copy.needsUpdate = true;
    copy.wrapS = THREE.RepeatWrapping;
    copy.wrapT = THREE.RepeatWrapping;
    copy.repeat.set(rx, ry);
    // сдвиг рисунка: чтобы шов плитки шёл через простенок над дверью НЕПРЕРЫВНО,
    // каждый кусок стены смещает текстуру на своё расстояние от начала стены
    copy.offset.set(offsetCm[0] / m.tileCm[0], offsetCm[1] / m.tileCm[1]);
    if (rotateDeg) {
      copy.center.set(0.5, 0.5);
      copy.rotation = (rotateDeg * Math.PI) / 180;
    }
    mat[key] = copy;
  }
  return mat;
}

export function disposeMaterialCtx(ctx: MaterialCtx): void {
  for (const t of ctx.cache.values()) t.dispose();
  for (const m of ctx.materials.values()) m.dispose();
  ctx.cache.clear();
  ctx.materials.clear();
}
