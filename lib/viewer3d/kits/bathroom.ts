// Санузел: ванна/душ, унитаз, раковина или тумба, шторка, зеркало.
// Комплект занимает всю комнату, поэтому его локальные оси = оси комнаты (центр в центре).

import * as THREE from "three";

import {
  DARK_GLASS,
  GLASS,
  LIGHT_STRIP,
  METAL,
  WHITE_GLOSS,
  boxOn,
  cylinder,
  handle,
  mat,
  type KitCtx,
} from "@/lib/viewer3d/kits/common";

export interface BathroomSpec {
  level: "base" | "practical" | "comfort" | "premium";
  features: string[];
  widthCm: number;
  depthCm: number;
  vanityMaterialId?: string;
}

export function buildBathroom(ctx: KitCtx, spec: BathroomSpec): THREE.Group {
  const g = new THREE.Group();
  const W = spec.widthCm;
  const D = spec.depthCm;
  const has = (f: string): boolean => spec.features.includes(f);
  const ceramic = WHITE_GLOSS;
  const cabinet = mat(ctx, spec.vanityMaterialId, [60, 60]);

  // ── ванна или душевая зона (задняя стена) ───────────────────────────────
  if (has("bath") || has("bath-free")) {
    const bl = Math.min(175, W - 60);
    const bx = -W / 2 + bl / 2 + (has("bath-free") ? 18 : 0);
    const bz = -D / 2 + (has("bath-free") ? 55 : 38);
    g.add(boxOn(bl, 52, 72, bx, 0, bz, ceramic));
    // внутренняя чаша: тёмная вставка сверху читается как углубление
    g.add(boxOn(bl - 14, 2, 58, bx, 50, bz, new THREE.MeshStandardMaterial({ color: 0xe6ebee, roughness: 0.1 })));
    g.add(cylinder(1.4, 1.4, 22, bx + bl / 2 - 14, 52, bz - 26, METAL, 10));
    if (has("screen")) g.add(boxOn(1.2, 145, 72, bx - bl / 2 + 2, 52, bz, GLASS));
  }
  if (has("shower")) {
    const sw = 92;
    const sx = W / 2 - sw / 2 - 6;
    const sz = -D / 2 + sw / 2 + 6;
    g.add(boxOn(sw, 5, sw, sx, 0, sz, ceramic));
    g.add(boxOn(1.2, 200, sw, sx - sw / 2, 5, sz, GLASS));
    g.add(boxOn(sw, 200, 1.2, sx, 5, sz + sw / 2, GLASS));
    g.add(cylinder(1.2, 1.2, 40, sx, 165, sz - sw / 2 + 8, METAL, 10));
    g.add(cylinder(11, 11, 2, sx, 203, sz - sw / 2 + 22, METAL, 16));
  }

  // ── унитаз ──────────────────────────────────────────────────────────────
  const wcX = has("shower") && !has("bath") ? -W / 2 + 34 : W / 2 - 34;
  const wcZ = -D / 2 + 34;
  if (has("wc-wall")) {
    g.add(boxOn(38, 22, 56, wcX, 38, wcZ + 6, ceramic));
    g.add(boxOn(44, 100, 18, wcX, 0, wcZ - 18, WHITE_GLOSS));
    g.add(boxOn(20, 1.4, 12, wcX, 100, wcZ - 12, METAL));
  } else {
    g.add(boxOn(36, 40, 58, wcX, 0, wcZ + 6, ceramic));
    g.add(boxOn(38, 32, 18, wcX, 40, wcZ - 16, ceramic));
    g.add(boxOn(40, 4, 52, wcX, 40, wcZ + 8, WHITE_GLOSS));
  }

  // ── раковина / тумба ────────────────────────────────────────────────────
  const double = has("vanity-double");
  const vw = double ? Math.min(140, W - 80) : 70;
  const vx = W / 2 - vw / 2 - 8;
  const vz = D / 2 - 34;
  if (has("vanity") || double) {
    g.add(boxOn(vw, 62, 48, vx, 18, vz, cabinet));
    g.add(boxOn(vw + 4, 4, 52, vx, 80, vz, mat(ctx, "quartz-white", [vw, 52])));
    const basins = double ? [vx - vw / 4, vx + vw / 4] : [vx];
    for (const bx of basins) {
      g.add(boxOn(44, 12, 34, bx, 84, vz, ceramic));
      g.add(cylinder(1.4, 1.4, 20, bx, 84, vz - 18, METAL, 10));
      g.add(handle(vw / (double ? 3 : 1.6), bx, 44, vz + 25, METAL));
    }
  } else {
    g.add(cylinder(9, 14, 62, vx, 0, vz, ceramic, 14));
    g.add(boxOn(52, 16, 40, vx, 62, vz, ceramic));
    g.add(cylinder(1.4, 1.4, 20, vx, 78, vz - 14, METAL, 10));
  }

  if (has("mirror")) {
    g.add(boxOn(vw, 90, 1.2, vx, 110, D / 2 - 3, new THREE.MeshStandardMaterial({ color: 0xd8e2e6, roughness: 0.08, metalness: 0.45 })));
    g.add(boxOn(vw - 8, 1.2, 1.6, vx, 202, D / 2 - 4, LIGHT_STRIP));
  } else {
    g.add(boxOn(48, 62, 1.2, vx, 112, D / 2 - 3, new THREE.MeshStandardMaterial({ color: 0xd8e2e6, roughness: 0.08, metalness: 0.45 })));
  }

  // полотенцесушитель — мелочь, которая делает кадр «жилым»
  g.add(boxOn(4, 70, 4, -W / 2 + 12, 90, D / 2 - 22, METAL));
  if (spec.level === "premium") g.add(boxOn(30, 2, 20, -W / 2 + 26, 150, D / 2 - 22, DARK_GLASS));

  return g;
}
