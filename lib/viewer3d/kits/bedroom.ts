// Кровать и шкаф. Оба — параметрические: уровень и материал приходят из выбранной опции.

import * as THREE from "three";

import {
  GLASS,
  LIGHT_STRIP,
  METAL,
  boxOn,
  handle,
  mat,
  splitUnits,
  type KitCtx,
} from "@/lib/viewer3d/kits/common";
import { tiled } from "@/lib/viewer3d/materials";

export interface BedSpec {
  level: "base" | "practical" | "comfort" | "premium";
  features: string[];
  bodyMaterialId?: string;
  widthCm: number;
  depthCm: number;
}

export function buildBed(ctx: KitCtx, spec: BedSpec): THREE.Group {
  const g = new THREE.Group();
  const W = Math.min(spec.widthCm, 200);
  const D = spec.depthCm;
  const has = (f: string): boolean => spec.features.includes(f);
  const body = mat(ctx, spec.bodyMaterialId, [W, 60]);
  const linen = new THREE.MeshStandardMaterial({ color: 0xf1ede6, roughness: 0.95 });
  const pillow = new THREE.MeshStandardMaterial({ color: 0xfbf8f3, roughness: 0.95 });

  // изголовье у «головы» кровати — это сторона −Z (лицо кровати смотрит в +Z)
  const headH = has("tall-headboard") ? 118 : 88;
  g.add(boxOn(W + 8, headH, 8, 0, 0, -D / 2 + 4, body));

  const baseH = has("storage") ? 32 : 26;
  g.add(boxOn(W, baseH, D - 10, 0, 0, 2, body));
  if (has("storage")) {
    g.add(handle(W * 0.35, 0, baseH / 2, D / 2 - 4, METAL));
  }
  // матрас и одеяло
  g.add(boxOn(W - 6, 22, D - 18, 0, baseH, 3, linen));
  g.add(boxOn(W - 4, 8, D * 0.62, 0, baseH + 20, D * 0.16, linen));
  // подушки
  const px = W / 4 - 4;
  g.add(boxOn(W / 2 - 10, 14, 34, -px, baseH + 20, -D / 2 + 30, pillow));
  g.add(boxOn(W / 2 - 10, 14, 34, px, baseH + 20, -D / 2 + 30, pillow));

  if (spec.level === "premium" || spec.level === "comfort") {
    // прикроватные тумбы — их не выбирают отдельно, они часть комплекта
    const nightstand = mat(ctx, spec.bodyMaterialId, [40, 40]);
    for (const sx of [-(W / 2 + 26), W / 2 + 26]) {
      g.add(boxOn(42, 44, 38, sx, 0, -D / 2 + 24, nightstand));
      g.add(handle(18, sx, 30, -D / 2 + 43, METAL));
    }
  }
  return g;
}

export interface WardrobeSpec {
  level: "base" | "practical" | "comfort" | "premium";
  features: string[];
  doorMaterialId?: string;
  widthCm: number;
  depthCm: number;
  heightCm: number;
}

export function buildWardrobe(ctx: KitCtx, spec: WardrobeSpec): THREE.Group {
  const g = new THREE.Group();
  const { widthCm: W, depthCm: D, heightCm: H } = spec;
  const has = (f: string): boolean => spec.features.includes(f);
  const body = new THREE.MeshStandardMaterial({ color: 0xe7e4de, roughness: 0.85 });
  const doorMat = mat(ctx, spec.doorMaterialId, [60, H]);

  g.add(boxOn(W, H, D, 0, 0, 0, body));

  const widths = splitUnits(W, has("sliding") ? 90 : 55);
  let cursor = -W / 2;
  widths.forEach((w, i) => {
    const x = cursor + w / 2;
    cursor += w;
    const z = D / 2 + (has("sliding") && i % 2 === 1 ? 2.5 : 0.6);
    g.add(boxOn(w - 0.8, H - 4, 2, x, 2, z, doorMat));
    if (has("sliding")) {
      g.add(handle(2, x + w / 2 - 3, H / 2, z + 1.4, METAL));
    } else {
      g.add(handle(3, x + w / 2 - 6, H / 2, z + 1.4, METAL));
    }
  });
  if (has("lighting")) g.add(boxOn(W - 6, 1.2, 2, 0, H - 3, D / 2 + 1, LIGHT_STRIP));
  if (has("internals")) g.add(boxOn(W - 10, 2, D - 8, 0, H * 0.55, -1, GLASS));
  return g;
}

export interface RugSpec {
  materialId?: string;
  widthCm: number;
  depthCm: number;
  pile: "flat" | "soft";
}

/**
 * Ковёр — намеренно ПРОСТАЯ геометрия плюс текстура (требование ТЗ для почти плоских вещей):
 * полноценный меш ворса не нужен, а плита 1,5–3 см с честным размером повтора читается верно
 * и весит ноль. Кайма чуть темнее — без неё ковёр сливается с полом.
 */
export function buildRug(ctx: KitCtx, spec: RugSpec): THREE.Group {
  const g = new THREE.Group();
  const h = spec.pile === "soft" ? 3 : 1.5;
  const { widthCm: W, depthCm: D } = spec;
  // КАЙМА — ТОЛЬКО РАМКОЙ. Первая версия клала поверх ковра сплошную плиту и полностью
  // закрывала рисунок: в кадре 29.09 ковёр читался серым прямоугольником.
  // РАМКА ВОКРУГ ПОЛОТНА, НЕ ПОВЕРХ (T-20261112-33, владелец 12.11 «когда двигаю — полоска белая мерцает под ковром»). Прежде
  // плита с фото шла во весь ковёр, а рамка лежала на её верхней половине: верх рамки и верх плиты — одна плоскость (y = h),
  // наружные бока рамки — в плоскостях боков плиты. Глубина у них равная, и при движении камеры пиксель достаётся то рамке, то
  // плите — по краю «рвётся» полоса, а бок плиты (сжатое в 1,5 см фото, на свету почти белое) ещё и виден ниже рамки. Теперь
  // полотно — внутри рамки, рамка — во всю высоту ковра: общих плоскостей у коробок нет, бока ковра — серая рамка.
  const t = Math.min(4, W / 4, D / 4);
  const iw = W - 2 * t, id = D - 2 * t;
  // фото — как прежде во весь ковёр: полотну достаётся его середина, край шириной в рамку остаётся под ней (повтор и сдвиг)
  const body = tiled(ctx.materials, (spec.materialId ? ctx.byId(spec.materialId) : undefined) ?? ctx.fallback, iw, id, 0, [t, t]);
  g.add(boxOn(iw, h, id, 0, 0, 0, body));
  const trim = new THREE.MeshStandardMaterial({ color: 0x9a958c, roughness: 1 });
  g.add(boxOn(W, h, t, 0, 0, D / 2 - t / 2, trim));
  g.add(boxOn(W, h, t, 0, 0, -D / 2 + t / 2, trim));
  g.add(boxOn(t, h, id, -W / 2 + t / 2, 0, 0, trim));
  g.add(boxOn(t, h, id, W / 2 - t / 2, 0, 0, trim));
  return g;
}
