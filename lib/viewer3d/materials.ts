// Материалы сцены: из контракта каталога → THREE.MeshStandardMaterial.
// Ключевое здесь — ФИЗИЧЕСКИЙ размер повтора (`tileCm`): без него доска пола растягивается
// на всю комнату. Повтор считаем от размера поверхности в сантиметрах, а не «на глаз».

import * as THREE from "three";

import type { Material } from "@/contracts/configurator";

type MapSlot = "map" | "normalMap" | "roughnessMap" | "aoMap";

export interface MaterialCtx {
  loader: THREE.TextureLoader;
  cache: Map<string, THREE.Texture>;
  materials: Map<string, THREE.MeshStandardMaterial>;
  /**
   * Копии текстур, сделанные ради своего повтора (`tiled`). Держим их, чтобы РАЗДАТЬ картинку,
   * когда она догрузится: копия, снятая с ещё не загруженной текстуры, картинку уже не получит
   * и навсегда останется чёрной (дверь шкафа в прихожей — чёрная, 29.09).
   */
  copies: Map<string, THREE.Texture[]>;
  /**
   * Кто пользуется текстурой. Нужно на случай, когда картинка НЕ пришла (браузер отказал в
   * запросе — `ERR_INSUFFICIENT_RESOURCES`, сеть отвалилась): тогда карту снимаем и показываем
   * ровный цвет материала. Пустая карта рисуется ЧЁРНЫМ — это худшее, что можно показать
   * покупателю (чёрная дверь шкафа, 29.09).
   */
  uses: Map<string, { mat: THREE.MeshStandardMaterial; slot: MapSlot; hex?: string }[]>;
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
    copies: new Map(),
    uses: new Map(),
    anisotropy,
    useMaps,
    extraMaps,
  };
}

/** Картинка не пришла: снимаем карту у всех, кто её ждал, и возвращаем ровный цвет. */
function dropTexture(ctx: MaterialCtx, key: string): void {
  for (const use of ctx.uses.get(key) ?? []) {
    use.mat[use.slot] = null;
    if (use.slot === "map" && use.hex) use.mat.color.set(use.hex);
    use.mat.needsUpdate = true;
  }
  ctx.uses.delete(key);
  ctx.copies.delete(key);
}

function texture(ctx: MaterialCtx, url: string, srgb: boolean): THREE.Texture {
  const key = `${url}|${srgb ? "srgb" : "lin"}`;
  const hit = ctx.cache.get(key);
  if (hit) return hit;
  // Когда картинка приедет, раздаём её копиям: они снимались с ещё пустой текстуры и сами
  // обновиться не могут (three не связывает клон с оригиналом).
  const t = ctx.loader.load(
    url,
    (loaded) => {
      for (const copy of ctx.copies.get(key) ?? []) {
        copy.image = loaded.image;
        copy.needsUpdate = true;
      }
      ctx.copies.delete(key);
      ctx.uses.delete(key);
    },
    undefined,
    () => {
      // Одна попытка повтора, но С ПАУЗОЙ: браузер отказывает в запросах, когда их разом
      // слишком много (`ERR_INSUFFICIENT_RESOURCES`), и немедленный повтор только добавляет
      // давления. Через секунду очередь обычно уже разгребли.
      setTimeout(() => ctx.loader.load(
        url,
        (loaded) => {
          t.image = loaded.image;
          t.needsUpdate = true;
          for (const copy of ctx.copies.get(key) ?? []) {
            copy.image = loaded.image;
            copy.needsUpdate = true;
          }
          ctx.copies.delete(key);
          ctx.uses.delete(key);
        },
        undefined,
        () => dropTexture(ctx, key),
      ), 1200);
    },
  );
  t.userData.texKey = key;
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = ctx.anisotropy;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  ctx.cache.set(key, t);
  return t;
}

/** Текстура + запись «кто её ждёт»: при отказе загрузки материал вернётся к ровному цвету. */
function attachTexture(
  ctx: MaterialCtx,
  mat: THREE.MeshStandardMaterial,
  slot: MapSlot,
  url: string,
  srgb: boolean,
  hex?: string,
): THREE.Texture {
  const t = texture(ctx, url, srgb);
  const key = t.userData.texKey as string;
  const list = ctx.uses.get(key);
  if (list) list.push({ mat, slot, hex });
  else ctx.uses.set(key, [{ mat, slot, hex }]);
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
    mat.map = attachTexture(ctx, mat, "map", m.baseColorUrl, true, m.colorHex);
    mat.color.set("#ffffff"); // цвет уже в текстуре, иначе двойное умножение
  }
  if (ctx.useMaps && ctx.extraMaps && m.normalUrl) {
    mat.normalMap = attachTexture(ctx, mat, "normalMap", m.normalUrl, false);
    mat.normalScale = new THREE.Vector2(0.7, 0.7);
  }
  if (ctx.useMaps && ctx.extraMaps && m.roughnessUrl) {
    mat.roughnessMap = attachTexture(ctx, mat, "roughnessMap", m.roughnessUrl, false);
  }
  if (ctx.useMaps && ctx.extraMaps && m.aoUrl) mat.aoMap = attachTexture(ctx, mat, "aoMap", m.aoUrl, false);
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
    // копия снята с ещё не загруженной текстуры → запоминаем её, чтобы отдать картинку потом
    // (и чтобы снять карту, если картинка так и не приедет)
    const texKey = t.userData.texKey as string | undefined;
    if (texKey && !t.image) {
      const list = ctx.copies.get(texKey);
      if (list) list.push(copy);
      else ctx.copies.set(texKey, [copy]);
      const uses = ctx.uses.get(texKey);
      const use = { mat, slot: key, hex: key === "map" ? m.colorHex : undefined };
      if (uses) uses.push(use);
      else ctx.uses.set(texKey, [use]);
    }
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
  for (const list of ctx.copies.values()) for (const t of list) t.dispose();
  ctx.copies.clear();
  ctx.uses.clear();
  for (const t of ctx.cache.values()) t.dispose();
  for (const m of ctx.materials.values()) m.dispose();
  ctx.cache.clear();
  ctx.materials.clear();
}
