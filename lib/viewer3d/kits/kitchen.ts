// Кухня: нижний ряд, столешница, фартук, верхние шкафы, колонна, остров и встроенная техника.
// Уровень (`level`) даёт состав корпусов, `features` — технику. Материалы фасада/столешницы/
// фартука приходят из СВОИХ слотов, поэтому «кухня Comfort + мрамор» собирается как у застройщика.

import * as THREE from "three";

import {
  CM,
  DARK_GLASS,
  GLASS,
  LIGHT_STRIP,
  METAL,
  WHITE_GLOSS,
  boxOn,
  cylinder,
  handle,
  mat,
  splitUnits,
  type KitCtx,
} from "@/lib/viewer3d/kits/common";

export interface KitchenSpec {
  level: "base" | "practical" | "comfort" | "premium";
  features: string[];
  doorMaterialId?: string;
  worktopMaterialId?: string;
  splashbackMaterialId?: string;
  widthCm: number;
  depthCm: number;
}

const KICK_H = 10;
const BASE_TOP = 86;
const WORKTOP_H = 4;
const SPLASH_TOP = 148;
const UPPER_BOTTOM = 148;
const UPPER_TOP = 215;
const TALL_TOP = 215;

/** Фасад с ручкой: единый кирпичик всей кухни. */
function frontPanel(
  g: THREE.Group,
  doorMat: THREE.Material,
  x: number,
  y0: number,
  h: number,
  w: number,
  z: number,
  withHandle = true,
): void {
  g.add(boxOn(w - 0.6, h - 0.6, 2, x, y0, z, doorMat));
  if (withHandle) g.add(handle(Math.min(w * 0.5, 30), x, y0 + h - 4, z + 1.6, METAL));
}

export function buildKitchen(ctx: KitCtx, spec: KitchenSpec): THREE.Group {
  const g = new THREE.Group();
  const W = spec.widthCm;
  const D = spec.depthCm;
  const front = D / 2;
  const back = -D / 2;
  const has = (f: string): boolean => spec.features.includes(f);

  const doorMat = mat(ctx, spec.doorMaterialId, [60, 76]);
  const bodyMat = new THREE.MeshStandardMaterial({ color: 0xdedbd5, roughness: 0.8 });
  const kickMat = new THREE.MeshStandardMaterial({ color: 0x4a4d52, roughness: 0.8 });
  const topMat = mat(ctx, spec.worktopMaterialId, [W, D]);
  const splashMat = mat(ctx, spec.splashbackMaterialId, [W, SPLASH_TOP - (BASE_TOP + WORKTOP_H)]);

  // колонна (шкаф до потолка) занимает край ряда
  const tall = spec.level === "comfort" || spec.level === "premium" || has("tall-unit");
  const tallW = tall ? 60 : 0;
  const runW = W - tallW;
  const runX0 = -W / 2 + tallW; // ряд правее колонны

  // ── нижний ряд ───────────────────────────────────────────────────────────
  g.add(boxOn(runW, KICK_H, D - 6, runX0 + runW / 2, 0, -3, kickMat));
  g.add(boxOn(runW, BASE_TOP - KICK_H, D - 2, runX0 + runW / 2, KICK_H, 0, bodyMat));

  const widths = splitUnits(runW, 60);
  let cursor = runX0;
  const slots: { x: number; w: number }[] = [];
  for (const w of widths) {
    slots.push({ x: cursor + w / 2, w });
    cursor += w;
  }

  // распределение техники по ряду: мойка ближе к центру, варочная рядом
  const sinkIdx = Math.min(slots.length - 1, Math.max(0, Math.floor(slots.length / 2)));
  const hobIdx = Math.max(0, sinkIdx - 2 >= 0 ? sinkIdx - 2 : sinkIdx + 2);
  const dishIdx = has("dishwasher") ? Math.min(slots.length - 1, sinkIdx + 1) : -1;
  const ovenIdx = has("oven") && !tall ? Math.max(0, hobIdx) : -1;
  const wineIdx = has("wine-cooler") ? Math.max(0, sinkIdx - 1) : -1;

  slots.forEach((s, i) => {
    if (i === dishIdx) {
      frontPanel(g, doorMat, s.x, KICK_H, BASE_TOP - KICK_H, s.w, front, false);
      g.add(handle(Math.min(s.w * 0.6, 40), s.x, BASE_TOP - 6, front + 1.6, METAL));
      return;
    }
    if (i === wineIdx) {
      g.add(boxOn(s.w - 0.6, BASE_TOP - KICK_H - 0.6, 2, s.x, KICK_H, front, DARK_GLASS));
      return;
    }
    if (i === ovenIdx) {
      g.add(boxOn(s.w - 0.6, 58, 2, s.x, KICK_H + 2, front, DARK_GLASS));
      g.add(handle(s.w * 0.7, s.x, KICK_H + 56, front + 1.8, METAL));
      frontPanel(g, doorMat, s.x, KICK_H + 62, BASE_TOP - KICK_H - 62, s.w, front);
      return;
    }
    // обычный корпус: два ящика или дверца
    if (i % 2 === 0) {
      frontPanel(g, doorMat, s.x, KICK_H, (BASE_TOP - KICK_H) * 0.42, s.w, front);
      frontPanel(g, doorMat, s.x, KICK_H + (BASE_TOP - KICK_H) * 0.44, (BASE_TOP - KICK_H) * 0.56, s.w, front);
    } else {
      frontPanel(g, doorMat, s.x, KICK_H, BASE_TOP - KICK_H, s.w, front);
    }
  });

  // ── столешница и фартук ─────────────────────────────────────────────────
  g.add(boxOn(runW + (tall ? tallW : 0), WORKTOP_H, D + 2, -W / 2 + (runW + (tall ? tallW : 0)) / 2, BASE_TOP, 1, topMat));
  g.add(boxOn(W, SPLASH_TOP - (BASE_TOP + WORKTOP_H), 1.5, 0, BASE_TOP + WORKTOP_H, back + 0.5, splashMat));

  // мойка со смесителем
  const sink = slots[sinkIdx];
  if (sink) {
    g.add(boxOn(Math.min(sink.w - 14, 52), 1.2, 40, sink.x, BASE_TOP + WORKTOP_H - 1.2, 2, METAL));
    g.add(cylinder(1.6, 1.6, 26, sink.x, BASE_TOP + WORKTOP_H, back + 8, METAL, 10));
    const spout = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.03, 0.18), METAL);
    spout.position.set(sink.x * CM, (BASE_TOP + WORKTOP_H + 25) * CM, (back + 17) * CM);
    g.add(spout);
  }

  // варочная панель
  const hob = slots[hobIdx];
  if (hob && has("hob")) {
    g.add(boxOn(Math.min(hob.w - 8, 58), 1.4, 50, hob.x, BASE_TOP + WORKTOP_H - 0.6, 1, DARK_GLASS));
  }

  // ── верхние шкафы ───────────────────────────────────────────────────────
  if (has("uppers") || spec.level !== "base") {
    const upperD = 35;
    const hoodX = hob ? hob.x : 0;
    for (const s of splitUnitsWithX(runX0, runW)) {
      if (has("hood") && Math.abs(s.x - hoodX) < 30) continue; // место под вытяжку
      g.add(boxOn(s.w, UPPER_TOP - UPPER_BOTTOM, upperD, s.x, UPPER_BOTTOM, back + upperD / 2, bodyMat));
      frontPanel(g, doorMat, s.x, UPPER_BOTTOM, UPPER_TOP - UPPER_BOTTOM, s.w, back + upperD + 0.5, true);
    }
    if (has("hood")) {
      g.add(boxOn(60, 14, 48, hoodX, UPPER_BOTTOM + 4, back + 24, METAL));
      g.add(boxOn(26, UPPER_TOP - UPPER_BOTTOM - 18, 26, hoodX, UPPER_BOTTOM + 18, back + 14, METAL));
    }
  }

  // ── колонна: духовой шкаф / холодильник / микроволновка ─────────────────
  if (tall) {
    const cx = -W / 2 + tallW / 2;
    g.add(boxOn(tallW, TALL_TOP, D, cx, 0, 0, bodyMat));
    if (has("fridge")) {
      frontPanel(g, doorMat, cx, 0, 122, tallW, front);
      frontPanel(g, doorMat, cx, 124, 58, tallW, front);
    } else {
      frontPanel(g, doorMat, cx, 0, 80, tallW, front);
    }
    let y = has("fridge") ? 184 : 82;
    if (has("oven")) {
      g.add(boxOn(tallW - 2, 58, 2, cx, y, front, DARK_GLASS));
      g.add(handle(tallW * 0.7, cx, y + 56, front + 1.8, METAL));
      y += 60;
    }
    if (has("microwave") && y + 40 < TALL_TOP) {
      g.add(boxOn(tallW - 2, 38, 2, cx, y, front, DARK_GLASS));
      y += 40;
    }
    if (y < TALL_TOP) frontPanel(g, doorMat, cx, y, TALL_TOP - y, tallW, front);
  }

  // ── остров (Premium) ────────────────────────────────────────────────────
  if (has("island")) {
    const iw = Math.min(180, W * 0.6);
    const iz = front + 110;
    g.add(boxOn(iw, KICK_H, 84, 0, 0, iz, kickMat));
    g.add(boxOn(iw, BASE_TOP - KICK_H, 90, 0, KICK_H, iz, bodyMat));
    for (const s of splitUnitsWithX(-iw / 2, iw)) {
      frontPanel(g, doorMat, s.x, KICK_H, BASE_TOP - KICK_H, s.w, iz - 45);
    }
    g.add(boxOn(iw + 6, WORKTOP_H, 96, 0, BASE_TOP, iz, mat(ctx, spec.worktopMaterialId, [iw, 96])));
    g.add(boxOn(iw, 0.6, 3, 0, UPPER_BOTTOM - 20, iz, LIGHT_STRIP));
  }

  // стеклянная перегородка фартука у премиума — тонкий блик
  if (spec.level === "premium") {
    g.add(boxOn(W, 1, 0.6, 0, SPLASH_TOP - 1, back + 1.6, GLASS));
  }
  if (spec.level === "base") {
    // база: открытая полка вместо верхних шкафов
    g.add(boxOn(runW * 0.5, 4, 24, runX0 + runW * 0.5, UPPER_BOTTOM, back + 12, WHITE_GLOSS));
  }

  return g;
}

function splitUnitsWithX(x0: number, length: number, target = 60): { x: number; w: number }[] {
  const widths = splitUnits(length, target);
  const out: { x: number; w: number }[] = [];
  let cursor = x0;
  for (const w of widths) {
    out.push({ x: cursor + w / 2, w });
    cursor += w;
  }
  return out;
}
