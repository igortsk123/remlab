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
  /** Свободная глубина комнаты перед линией, см. Остров ставится только если он влезает. */
  roomDepthCm?: number;
  /**
   * С какого конца линии ставить колонны до потолка. Их место — ДАЛЬШЕ ОТ ДВЕРИ: у входа
   * они перекрывают вид на всю кухню (кадр 29.09) и мешают пройти.
   */
  columnsAt?: "start" | "end";
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

  // СОСТАВ ПО УРОВНЮ: с ценой должна расти ФУНКЦИЯ, а не только цвет фасадов
  // (владелец 29.09: «кухня когда меняешь на премиум лучше побогаче… по функциональнее»).
  // Base — короткая линия и открытая полка; Practical — линия почти во всю стену и верхние
  // шкафы; Comfort — полная линия + колонна до потолка; Premium — две колонны, верх до потолка,
  // остров с барной стойкой, открытые полки и подсветка рабочей зоны.
  const LEVEL = {
    base: { run: 0.62, uppers: 0, columns: 0, island: false, shelves: false, lighting: false },
    practical: { run: 0.84, uppers: 0.62, columns: 0, island: false, shelves: false, lighting: false },
    comfort: { run: 1.0, uppers: 1.0, columns: 1, island: false, shelves: true, lighting: true },
    premium: { run: 1.0, uppers: 1.0, columns: 2, island: true, shelves: true, lighting: true },
  }[spec.level];

  const columns = has("tall-unit") ? Math.max(1, LEVEL.columns) : LEVEL.columns;
  const tall = columns > 0;
  const tallW = columns * 60;
  const atEnd = (spec.columnsAt ?? "start") === "end";
  const runW = Math.max(120, (W - tallW) * LEVEL.run);
  const runX0 = atEnd ? -W / 2 : -W / 2 + tallW; // ряд слева или справа от колонн
  const colX0 = atEnd ? -W / 2 + runW : -W / 2;  // начало блока колонн

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
  // В столешнице ПРОРЕЗАЕМ отверстие под мойку: цельная плита накрывала чашу сверху, и мойки
  // не было видно вовсе (владелец 30.09: «раковина не пашет»). Вырезать нечем — CSG нет,
  // поэтому кладём четыре куска вокруг отверстия.
  const sinkSlot = slots[sinkIdx];
  const SINK_W = sinkSlot ? Math.min(sinkSlot.w - 14, 52) : 0;
  const SINK_D = 40;
  const SINK_Z = 2;
  const LIP = 3;
  const topW = runW + (tall ? tallW : 0);
  const topX0 = -W / 2;
  const topX1 = topX0 + topW;
  const topZ0 = 1 - (D + 2) / 2;
  const topZ1 = 1 + (D + 2) / 2;
  const slab = (x0: number, x1: number, z0: number, z1: number): void => {
    if (x1 - x0 < 0.4 || z1 - z0 < 0.4) return;
    g.add(boxOn(x1 - x0, WORKTOP_H, z1 - z0, (x0 + x1) / 2, BASE_TOP, (z0 + z1) / 2, topMat));
  };
  if (sinkSlot && SINK_W > 10) {
    const hx0 = sinkSlot.x - SINK_W / 2 - LIP;
    const hx1 = sinkSlot.x + SINK_W / 2 + LIP;
    const hz0 = SINK_Z - SINK_D / 2 - LIP;
    const hz1 = SINK_Z + SINK_D / 2 + LIP;
    slab(topX0, hx0, topZ0, topZ1);
    slab(hx1, topX1, topZ0, topZ1);
    slab(hx0, hx1, topZ0, hz0);
    slab(hx0, hx1, hz1, topZ1);
  } else {
    slab(topX0, topX1, topZ0, topZ1);
  }
  g.add(boxOn(W, SPLASH_TOP - (BASE_TOP + WORKTOP_H), 1.5, 0, BASE_TOP + WORKTOP_H, back + 0.5, splashMat));

  // МОЙКА: настоящая чаша, а не пластина. Плоская накладка сливалась со столешницей —
  // владелец 30.09: «раковину практически не видно». Чашу собираем из стенок и дна:
  // вырезать отверстие в столешнице нечем (CSG нет), но тёмное углубление читается сразу.
  const sink = sinkSlot;
  if (sink) {
    const top = BASE_TOP + WORKTOP_H;      // уровень столешницы
    const sw = SINK_W;                      // ширина чаши — та же, что у отверстия
    const sd = SINK_D;                      // глубина чаши по горизонтали
    const deep = 16;                        // насколько чаша утоплена
    const wall = 1.2;
    const bowl = new THREE.MeshStandardMaterial({ color: 0xb9bec3, roughness: 0.3, metalness: 0.85 });
    const rim = new THREE.MeshStandardMaterial({ color: 0xd2d6da, roughness: 0.2, metalness: 0.9 });
    // дно и четыре стенки
    g.add(boxOn(sw, wall, sd, sink.x, top - deep, SINK_Z, bowl));
    g.add(boxOn(wall, deep, sd, sink.x - sw / 2, top - deep, SINK_Z, bowl));
    g.add(boxOn(wall, deep, sd, sink.x + sw / 2, top - deep, SINK_Z, bowl));
    g.add(boxOn(sw, deep, wall, sink.x, top - deep, SINK_Z - sd / 2, bowl));
    g.add(boxOn(sw, deep, wall, sink.x, top - deep, SINK_Z + sd / 2, bowl));
    // бортик по периметру — он и даёт «блик», по которому мойку видно издалека
    const lip = LIP;
    g.add(boxOn(sw + lip * 2, 1.4, lip, sink.x, top - 1.4, SINK_Z - sd / 2 - lip / 2, rim));
    g.add(boxOn(sw + lip * 2, 1.4, lip, sink.x, top - 1.4, SINK_Z + sd / 2 + lip / 2, rim));
    g.add(boxOn(lip, 1.4, sd, sink.x - sw / 2 - lip / 2, top - 1.4, SINK_Z, rim));
    g.add(boxOn(lip, 1.4, sd, sink.x + sw / 2 + lip / 2, top - 1.4, SINK_Z, rim));
    // слив
    g.add(cylinder(4, 4, 0.8, sink.x, top - deep + wall, SINK_Z, rim, 14));
    // смеситель: стойка выше, излив длиннее — иначе теряется на фоне фартука
    g.add(cylinder(1.8, 2.2, 30, sink.x, top, back + 7, rim, 12));
    g.add(cylinder(1.4, 1.4, 18, sink.x, top + 29, back + 7, rim, 12).rotateX(Math.PI / 2));
  }

  // ВАРОЧНАЯ ПАНЕЛЬ: стекло плюс четыре конфорки — иначе это просто тёмный прямоугольник
  const hob = slots[hobIdx];
  if (hob && has("hob")) {
    const top = BASE_TOP + WORKTOP_H;
    const hw = Math.min(hob.w - 8, 58);
    g.add(boxOn(hw, 1.4, 50, hob.x, top - 0.6, 1, DARK_GLASS));
    const ring = new THREE.MeshStandardMaterial({ color: 0x4a4f55, roughness: 0.4, metalness: 0.2 });
    for (const dx of [-hw / 4, hw / 4]) {
      for (const dz of [-11, 11]) {
        g.add(cylinder(8, 8, 0.3, hob.x + dx, top + 0.8, 1 + dz, ring, 20));
      }
    }
  }

  // ── верхние шкафы ───────────────────────────────────────────────────────
  if (LEVEL.uppers > 0 || has("uppers")) {
    const upperD = 35;
    const hoodX = hob ? hob.x : 0;
    const upperW = runW * Math.max(LEVEL.uppers, has("uppers") ? 0.62 : 0);
    for (const s of splitUnitsWithX(runX0, upperW)) {
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
  for (let c = 0; c < columns; c += 1) {
    const cw = 60;
    const cx = colX0 + cw / 2 + c * cw;
    g.add(boxOn(cw, TALL_TOP, D, cx, 0, 0, bodyMat));
    // первая колонна — холодильник/кладовая, вторая (Premium) — духовка, СВЧ и винный шкаф
    if (c === 0) {
      if (has("fridge")) {
        frontPanel(g, doorMat, cx, 0, 122, cw, front);
        frontPanel(g, doorMat, cx, 124, 90, cw, front);
      } else {
        frontPanel(g, doorMat, cx, 0, 104, cw, front);
        frontPanel(g, doorMat, cx, 106, 108, cw, front);
      }
      continue;
    }
    let y = 0;
    frontPanel(g, doorMat, cx, y, 60, cw, front);
    y += 62;
    if (has("oven")) {
      g.add(boxOn(cw - 2, 58, 2, cx, y, front, DARK_GLASS));
      g.add(handle(cw * 0.7, cx, y + 56, front + 1.8, METAL));
      y += 60;
    }
    if (has("microwave")) {
      g.add(boxOn(cw - 2, 38, 2, cx, y, front, DARK_GLASS));
      y += 40;
    }
    if (has("wine-cooler") && y + 44 < TALL_TOP) {
      g.add(boxOn(cw - 2, 42, 2, cx, y, front, DARK_GLASS));
      y += 44;
    }
    if (y < TALL_TOP) frontPanel(g, doorMat, cx, y, TALL_TOP - y, cw, front);
  }

  // ── остров (Premium) ────────────────────────────────────────────────────
  // ОСТРОВ ТОЛЬКО ЕСЛИ ВЛЕЗАЕТ. В кухне глубиной 1,8 м он упирался в противоположную стену
  // (кадр 29.09): между линией и островом нужен проход 100 см плюс сам остров 90 см.
  const roomDepth = spec.roomDepthCm ?? spec.depthCm * 3;
  const islandFits = roomDepth >= spec.depthCm + 100 + 90 + 80;
  if ((LEVEL.island || has("island")) && islandFits) {
    const iw = Math.min(180, W * 0.6);
    const iz = front + 110;
    g.add(boxOn(iw, KICK_H, 84, 0, 0, iz, kickMat));
    g.add(boxOn(iw, BASE_TOP - KICK_H, 90, 0, KICK_H, iz, bodyMat));
    for (const s of splitUnitsWithX(-iw / 2, iw)) {
      frontPanel(g, doorMat, s.x, KICK_H, BASE_TOP - KICK_H, s.w, iz - 45);
    }
    // барная стойка: столешница со свесом и два табурета — это «функция», а не декор
    g.add(boxOn(iw + 6, WORKTOP_H, 128, 0, BASE_TOP, iz + 16, mat(ctx, spec.worktopMaterialId, [iw, 128])));
    for (const sx of [-iw / 4, iw / 4]) {
      g.add(cylinder(16, 18, 66, sx, 0, iz + 88, METAL, 12));
      g.add(boxOn(36, 5, 34, sx, 66, iz + 88, doorMat));
    }
    g.add(boxOn(iw, 0.6, 3, 0, UPPER_BOTTOM - 20, iz, LIGHT_STRIP));
  }

  // стеклянная перегородка фартука у премиума — тонкий блик
  if (spec.level === "premium") {
    g.add(boxOn(W, 1, 0.6, 0, SPLASH_TOP - 1, back + 1.6, GLASS));
  }
  if ((LEVEL.island || has("island")) && !islandFits) {
    // барная стойка вместо острова: столешница со свесом на торце линии и табурет
    const bx = runX0 + runW - 20;
    g.add(boxOn(70, WORKTOP_H, D + 34, bx, BASE_TOP, 17, mat(ctx, spec.worktopMaterialId, [70, D + 34])));
    g.add(cylinder(16, 18, 66, bx, 0, front + 34, METAL, 12));
    g.add(boxOn(34, 5, 32, bx, 66, front + 34, doorMat));
  }
  if (spec.level === "base") {
    // база: открытая полка вместо верхних шкафов
    g.add(boxOn(runW * 0.5, 4, 24, runX0 + runW * 0.5, UPPER_BOTTOM, back + 12, WHITE_GLOSS));
  }
  if (LEVEL.shelves) {
    // открытые полки в свободном конце линии
    const sx = runX0 + runW - 45;
    for (const y of [152, 186]) g.add(boxOn(86, 3.5, 26, sx, y, back + 13, WHITE_GLOSS));
  }
  if (LEVEL.lighting) {
    // подсветка рабочей зоны под верхними шкафами
    g.add(boxOn(runW * Math.max(LEVEL.uppers, 0.5) - 6, 1.2, 3, runX0 + runW * 0.5, UPPER_BOTTOM - 2, back + 30, LIGHT_STRIP));
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
