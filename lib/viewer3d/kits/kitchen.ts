// Кухня: нижний ряд, столешница, фартук, верхние шкафы, колонна, остров и встроенная техника.
// Уровень (`level`) даёт состав корпусов, `features` — технику. Материалы фасада/столешницы/
// фартука приходят из СВОИХ слотов, поэтому «кухня Comfort + мрамор» собирается как у застройщика.
// ГДЕ ЧТО СТОИТ — `kits/kitchen-layout.ts` (чистая раскладка, её же меряют нормы `kits/kitchen-checks.ts`);
// здесь только рисование. Г-форма — второе плечо вдоль боковой стены, остров — только признаком `island` (onb-09).

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
import { UPPER_D, kitchenLayout, type KitchenLayout, type KitchenSlot, type KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";
import { kitchenMaterial } from "@/lib/viewer3d/kits/kitchen-materials";

export type { KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";

const KICK_H = 10;
const BASE_TOP = 86;
const WORKTOP_H = 4;
const SPLASH_TOP = 148;
const UPPER_BOTTOM = 148;
const UPPER_TOP = 215;
const TALL_TOP = 215;
const SINK_D = 40;
const SINK_Z = 2;
const LIP = 3;
/** Свес столешницы полуострова за спину, см — под колени сидящего (у стойки — 25–30). */
const PENINSULA_OVERHANG = 28;

interface Mats {
  door: THREE.Material;
  doorUpper: THREE.Material;
  body: THREE.Material;
  kick: THREE.Material;
}

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

/** Корпуса нижнего ряда (цоколь и короб) от x0 длиной len — в кадре ряда (лицо в +Z). */
function baseBody(g: THREE.Group, m: Mats, x0: number, len: number, D: number): void {
  g.add(boxOn(len, KICK_H, D - 6, x0 + len / 2, 0, -3, m.kick));
  g.add(boxOn(len, BASE_TOP - KICK_H, D - 2, x0 + len / 2, KICK_H, 0, m.body));
}

/** Фасад модуля по его роли: посудомойка, винный шкаф, духовка или обычный корпус. */
function baseFront(g: THREE.Group, m: Mats, s: { x: number; w: number }, i: number, role: "dish" | "wine" | "oven" | "plain", front: number): void {
  if (role === "dish") {
    frontPanel(g, m.door, s.x, KICK_H, BASE_TOP - KICK_H, s.w, front, false);
    g.add(handle(Math.min(s.w * 0.6, 40), s.x, BASE_TOP - 6, front + 1.6, METAL));
    return;
  }
  if (role === "wine") {
    g.add(boxOn(s.w - 0.6, BASE_TOP - KICK_H - 0.6, 2, s.x, KICK_H, front, DARK_GLASS));
    return;
  }
  if (role === "oven") {
    g.add(boxOn(s.w - 0.6, 58, 2, s.x, KICK_H + 2, front, DARK_GLASS));
    g.add(handle(s.w * 0.7, s.x, KICK_H + 56, front + 1.8, METAL));
    frontPanel(g, m.door, s.x, KICK_H + 62, BASE_TOP - KICK_H - 62, s.w, front);
    return;
  }
  // обычный корпус: два ящика или дверца
  if (i % 2 === 0) {
    frontPanel(g, m.door, s.x, KICK_H, (BASE_TOP - KICK_H) * 0.42, s.w, front);
    frontPanel(g, m.door, s.x, KICK_H + (BASE_TOP - KICK_H) * 0.44, (BASE_TOP - KICK_H) * 0.56, s.w, front);
  } else {
    frontPanel(g, m.door, s.x, KICK_H, BASE_TOP - KICK_H, s.w, front);
  }
}

/**
 * Столешница от x0 до x1 и мойка в модуле `sink` (кадр ряда). В столешнице ПРОРЕЗАЕМ отверстие под мойку: цельная плита
 * накрывала чашу сверху, и мойки не было видно вовсе (владелец 30.09: «раковина не пашет»). Вырезать нечем — CSG нет,
 * поэтому кладём четыре куска вокруг отверстия.
 */
function worktopWithSink(g: THREE.Group, topMat: THREE.Material, x0: number, x1: number, D: number, sink: { x: number; w: number } | undefined): void {
  const z0 = 1 - (D + 2) / 2;
  const z1 = 1 + (D + 2) / 2;
  const slab = (a: number, b: number, c: number, d: number): void => {
    if (b - a < 0.4 || d - c < 0.4) return;
    g.add(boxOn(b - a, WORKTOP_H, d - c, (a + b) / 2, BASE_TOP, (c + d) / 2, topMat));
  };
  const sw = sink ? Math.min(sink.w - 14, 52) : 0;
  if (!sink || sw <= 10) {
    slab(x0, x1, z0, z1);
    return;
  }
  const hx0 = sink.x - sw / 2 - LIP;
  const hx1 = sink.x + sw / 2 + LIP;
  const hz0 = SINK_Z - SINK_D / 2 - LIP;
  const hz1 = SINK_Z + SINK_D / 2 + LIP;
  slab(x0, hx0, z0, z1);
  slab(hx1, x1, z0, z1);
  slab(hx0, hx1, z0, hz0);
  slab(hx0, hx1, hz1, z1);

  // МОЙКА: настоящая чаша, а не пластина. Плоская накладка сливалась со столешницей —
  // владелец 30.09: «раковину практически не видно». Чашу собираем из стенок и дна.
  const top = BASE_TOP + WORKTOP_H;
  const sd = SINK_D;
  const deep = 16;
  const wall = 1.2;
  const bowl = new THREE.MeshStandardMaterial({ color: 0xb9bec3, roughness: 0.3, metalness: 0.85 });
  const rim = new THREE.MeshStandardMaterial({ color: 0xd2d6da, roughness: 0.2, metalness: 0.9 });
  g.add(boxOn(sw, wall, sd, sink.x, top - deep, SINK_Z, bowl));
  g.add(boxOn(wall, deep, sd, sink.x - sw / 2, top - deep, SINK_Z, bowl));
  g.add(boxOn(wall, deep, sd, sink.x + sw / 2, top - deep, SINK_Z, bowl));
  g.add(boxOn(sw, deep, wall, sink.x, top - deep, SINK_Z - sd / 2, bowl));
  g.add(boxOn(sw, deep, wall, sink.x, top - deep, SINK_Z + sd / 2, bowl));
  // бортик по периметру — он и даёт «блик», по которому мойку видно издалека
  g.add(boxOn(sw + LIP * 2, 1.4, LIP, sink.x, top - 1.4, SINK_Z - sd / 2 - LIP / 2, rim));
  g.add(boxOn(sw + LIP * 2, 1.4, LIP, sink.x, top - 1.4, SINK_Z + sd / 2 + LIP / 2, rim));
  g.add(boxOn(LIP, 1.4, sd, sink.x - sw / 2 - LIP / 2, top - 1.4, SINK_Z, rim));
  g.add(boxOn(LIP, 1.4, sd, sink.x + sw / 2 + LIP / 2, top - 1.4, SINK_Z, rim));
  g.add(cylinder(4, 4, 0.8, sink.x, top - deep + wall, SINK_Z, rim, 14));
  // смеситель: стойка выше, излив длиннее — иначе теряется на фоне фартука
  const back = -D / 2;
  g.add(cylinder(1.8, 2.2, 30, sink.x, top, back + 7, rim, 12));
  g.add(cylinder(1.4, 1.4, 18, sink.x, top + 29, back + 7, rim, 12).rotateX(Math.PI / 2));
}

/** Верхние шкафы по готовым местам (центр и ширина) у стены (кадр ряда). */
function upperBoxes(g: THREE.Group, m: Mats, slots: { x: number; w: number }[], back: number): void {
  for (const s of slots) {
    g.add(boxOn(s.w, UPPER_TOP - UPPER_BOTTOM, UPPER_D, s.x, UPPER_BOTTOM, back + UPPER_D / 2, m.body));
    frontPanel(g, m.doorUpper, s.x, UPPER_BOTTOM, UPPER_TOP - UPPER_BOTTOM, s.w, back + UPPER_D + 0.5, true);
  }
}

/** Верхние шкафы поровну от x0 длиной len (кадр ряда); `skipAt` — место под вытяжку. */
function uppers(g: THREE.Group, m: Mats, x0: number, len: number, back: number, skipAt: number | null): void {
  upperBoxes(g, m, splitUnitsWithX(x0, len).filter((s) => skipAt === null || Math.abs(s.x - skipAt) >= 30), back);
}

/** Доборы ряда (`lay.fillers`): узкая панель в цвет фасада без ручки — закрывает остаток, куда модуль из ряда не встал. */
function fillerFronts(g: THREE.Group, m: Mats, lay: KitchenLayout, leg: boolean): void {
  for (const f of lay.fillers) {
    if (f.leg === leg) frontPanel(g, m.door, f.along, KICK_H, BASE_TOP - KICK_H, f.w, lay.front, false);
  }
}

function roleOf(lay: KitchenLayout, i: number): "dish" | "wine" | "oven" | "plain" {
  if (i === lay.dish) return "dish";
  if (i === lay.wine) return "wine";
  if (i === lay.oven) return "oven";
  return "plain";
}

/** Второе плечо Г: свой кадр (лицо в комнату), корпуса, столешница, фартук и верх вдоль боковой стены. */
function buildLeg(
  ctx: KitCtx,
  spec: KitchenSpec,
  lay: KitchenLayout,
  m: Mats,
  splashMat: (len: number) => THREE.Material,
): THREE.Group {
  const leg = lay.leg as NonNullable<KitchenLayout["leg"]>;
  const lg = new THREE.Group();
  lg.position.set(leg.origin.x * CM, 0, leg.origin.z * CM);
  lg.rotation.y = leg.yaw;
  const D = lay.D;
  const len = leg.x1 - leg.x0;
  baseBody(lg, m, leg.x0, len, D);
  // торец плеча смотрит в комнату — закрываем его панелью в цвет фасада, а не серым коробом
  const tipX = leg.at === "end" ? leg.x1 + 0.9 : leg.x0 - 0.9;
  lg.add(boxOn(1.8, BASE_TOP, D, tipX, 0, 0, m.door));
  lay.slots.forEach((s, i) => {
    if (s.leg) baseFront(lg, m, { x: s.along, w: s.w }, i, roleOf(lay, i), lay.front);
  });
  const sink = lay.slots[lay.sink];
  const legSink = sink?.leg ? { x: sink.along, w: sink.w } : undefined;
  worktopWithSink(lg, mat(ctx, spec.worktopMaterialId, [len, D]), leg.x0, leg.x1, D, legSink);
  fillerFronts(lg, m, lay, true);
  if (spec.peninsula) {
    // ПОЛУОСТРОВ: стены за плечом нет — спина в комнату закрыта панелью в цвет фасада, столешница свисает за спину
    // (там садятся), верха и фартука нет (как у Wickes на фото)
    lg.add(boxOn(len, BASE_TOP, 1.8, (leg.x0 + leg.x1) / 2, 0, lay.back - 0.9, m.door));
    lg.add(boxOn(len + 1.8, WORKTOP_H, PENINSULA_OVERHANG, (leg.x0 + leg.x1) / 2 + (leg.at === "end" ? 0.9 : -0.9), BASE_TOP, lay.back - PENINSULA_OVERHANG / 2, mat(ctx, spec.worktopMaterialId, [len, PENINSULA_OVERHANG])));
    return lg;
  }
  // фартук и верх — по всей боковой стене, от задней стены линии; верх — за глубиной верхних шкафов линии
  const wallX0 = leg.at === "end" ? -D : leg.x0;
  const wallX1 = leg.at === "end" ? leg.x1 : D;
  lg.add(boxOn(wallX1 - wallX0, SPLASH_TOP - (BASE_TOP + WORKTOP_H), 1.5, (wallX0 + wallX1) / 2, BASE_TOP + WORKTOP_H, lay.back + 0.5, splashMat(wallX1 - wallX0)));
  if (lay.uppersW > 0) {
    const ux0 = leg.at === "end" ? -D + UPPER_D : leg.x0;
    const ux1 = leg.at === "end" ? leg.x1 : D - UPPER_D;
    uppers(lg, m, ux0, ux1 - ux0, lay.back, null);
  }
  return lg;
}

export function buildKitchen(ctx: KitCtx, spec: KitchenSpec): THREE.Group {
  // свои цвета набора (примеры из магазина) — только если каталог сцены такого id не знает
  const kctx: KitCtx = { ...ctx, byId: (id) => ctx.byId(id) ?? kitchenMaterial(id) };
  const lay = kitchenLayout(spec);
  const out = new THREE.Group();
  const { W, D, front, back, runX0, runW } = lay;
  const has = (f: string): boolean => spec.features.includes(f);

  const door = mat(kctx, spec.doorMaterialId, [60, 76]);
  const m: Mats = {
    door,
    doorUpper: spec.doorUpperMaterialId ? mat(kctx, spec.doorUpperMaterialId, [60, 76]) : door,
    body: new THREE.MeshStandardMaterial({ color: 0xdedbd5, roughness: 0.8 }),
    kick: new THREE.MeshStandardMaterial({ color: 0x4a4d52, roughness: 0.8 }),
  };
  const splashH = SPLASH_TOP - (BASE_TOP + WORKTOP_H);
  const splashMat = (len: number): THREE.Material => mat(kctx, spec.splashbackMaterialId, [len, splashH]);

  // ── нижний ряд основной линии ───────────────────────────────────────────
  baseBody(out, m, runX0, runW, D);
  lay.slots.forEach((s, i) => {
    if (!s.leg) baseFront(out, m, { x: s.along, w: s.w }, i, roleOf(lay, i), front);
  });

  // ── столешница (с мойкой, если она на линии) и фартук ───────────────────
  const sinkSlot: KitchenSlot | undefined = lay.slots[lay.sink];
  const mainSink = sinkSlot && !sinkSlot.leg ? { x: sinkSlot.along, w: sinkSlot.w } : undefined;
  fillerFronts(out, m, lay, false);
  // столешница — только над нижним рядом: сквозь колонну она торчала из её фасада светлой полосой на высоте 86–90 см
  // (кадр Wickes 05.11, T-20261105-18; так было и у Comfort/Premium застройщика)
  worktopWithSink(out, mat(kctx, spec.worktopMaterialId, [W, D]), runX0, runX0 + runW, D, mainSink);
  out.add(boxOn(W, splashH, 1.5, 0, BASE_TOP + WORKTOP_H, back + 0.5, splashMat(W)));

  // ВАРОЧНАЯ ПАНЕЛЬ: стекло плюс четыре конфорки — иначе это просто тёмный прямоугольник
  const hob = lay.slots[lay.hob];
  if (hob && has("hob")) {
    const top = BASE_TOP + WORKTOP_H;
    const hw = Math.min(hob.w - 8, 58);
    out.add(boxOn(hw, 1.4, 50, hob.along, top - 0.6, 1, DARK_GLASS));
    const ring = new THREE.MeshStandardMaterial({ color: 0x4a4f55, roughness: 0.4, metalness: 0.2 });
    for (const dx of [-hw / 4, hw / 4]) {
      for (const dz of [-11, 11]) {
        out.add(cylinder(8, 8, 0.3, hob.along + dx, top + 0.8, 1 + dz, ring, 20));
      }
    }
  }

  // ── верхние шкафы и вытяжка ─────────────────────────────────────────────
  if (lay.uppersW > 0) {
    const hoodX = hob ? hob.along : 0;
    // ширины из паспорта, если сошлись (вытяжка точно над варочной); иначе поровну, как у вариантов застройщика
    if (lay.upperSlots) upperBoxes(out, m, lay.upperSlots, back);
    else uppers(out, m, runX0, lay.uppersW, back, has("hood") ? hoodX : null);
    if (has("hood")) {
      out.add(boxOn(60, 14, 48, hoodX, UPPER_BOTTOM + 4, back + 24, METAL));
      out.add(boxOn(26, UPPER_TOP - UPPER_BOTTOM - 18, 26, hoodX, UPPER_BOTTOM + 18, back + 14, METAL));
    }
  }

  // ── колонна: холодильник/кладовая; вторая (Premium) — духовка, СВЧ и винный шкаф ─
  lay.columns.forEach((col, c) => {
    const cw = 60;
    const cx = col.x;
    out.add(boxOn(cw, TALL_TOP, D, cx, 0, 0, m.body));
    if (c === 0) {
      if (has("fridge")) {
        frontPanel(out, m.door, cx, 0, 122, cw, front);
        frontPanel(out, m.door, cx, 124, 90, cw, front);
      } else {
        frontPanel(out, m.door, cx, 0, 104, cw, front);
        frontPanel(out, m.door, cx, 106, 108, cw, front);
      }
      return;
    }
    let y = 0;
    frontPanel(out, m.door, cx, y, 60, cw, front);
    y += 62;
    if (lay.ovenInColumn) {
      out.add(boxOn(cw - 2, 58, 2, cx, y, front, DARK_GLASS));
      out.add(handle(cw * 0.7, cx, y + 56, front + 1.8, METAL));
      y += 60;
    }
    if (has("microwave")) {
      out.add(boxOn(cw - 2, 38, 2, cx, y, front, DARK_GLASS));
      y += 40;
    }
    if (has("wine-cooler") && y + 44 < TALL_TOP) {
      out.add(boxOn(cw - 2, 42, 2, cx, y, front, DARK_GLASS));
      y += 44;
    }
    if (y < TALL_TOP) frontPanel(out, m.door, cx, y, TALL_TOP - y, cw, front);
  });

  // ── второе плечо Г ──────────────────────────────────────────────────────
  if (lay.leg) out.add(buildLeg(kctx, spec, lay, m, splashMat));

  // ── остров: только признаком и только если влезает (раскладка держит проходы) ─
  if (lay.island) {
    const { w: iw, z: iz, d: id } = lay.island;
    out.add(boxOn(iw, KICK_H, id - 6, 0, 0, iz, m.kick));
    out.add(boxOn(iw, BASE_TOP - KICK_H, id, 0, KICK_H, iz, m.body));
    for (const s of splitUnitsWithX(-iw / 2, iw)) {
      frontPanel(out, m.door, s.x, KICK_H, BASE_TOP - KICK_H, s.w, iz - id / 2);
    }
    // барная стойка: столешница со свесом и два табурета — это «функция», а не декор
    out.add(boxOn(iw + 6, WORKTOP_H, 128, 0, BASE_TOP, iz + 16, mat(kctx, spec.worktopMaterialId, [iw, 128])));
    for (const sx of [-iw / 4, iw / 4]) {
      out.add(cylinder(16, 18, 66, sx, 0, iz + 88, METAL, 12));
      out.add(boxOn(36, 5, 34, sx, 66, iz + 88, m.door));
    }
    out.add(boxOn(iw, 0.6, 3, 0, UPPER_BOTTOM - 20, iz, LIGHT_STRIP));
  }

  // стеклянная перегородка фартука у премиума — тонкий блик
  if (spec.level === "premium") {
    out.add(boxOn(W, 1, 0.6, 0, SPLASH_TOP - 1, back + 1.6, GLASS));
  }
  if (lay.bar) {
    // барная стойка вместо острова: столешница со свесом на торце линии и табурет
    const bx = runX0 + runW - 20;
    out.add(boxOn(70, WORKTOP_H, D + 34, bx, BASE_TOP, 17, mat(kctx, spec.worktopMaterialId, [70, D + 34])));
    out.add(cylinder(16, 18, 66, bx, 0, front + 34, METAL, 12));
    out.add(boxOn(34, 5, 32, bx, 66, front + 34, m.door));
  }
  if (spec.level === "base") {
    // база: открытая полка вместо верхних шкафов
    out.add(boxOn(runW * 0.5, 4, 24, runX0 + runW * 0.5, UPPER_BOTTOM, back + 12, WHITE_GLOSS));
  }
  if (lay.level.shelves && lay.uppersW < runW - 88) {
    // открытые полки в свободном конце линии — только там, где нет верхних шкафов (иначе прятались внутри)
    const sx = runX0 + runW - 45;
    for (const y of [152, 186]) out.add(boxOn(86, 3.5, 26, sx, y, back + 13, WHITE_GLOSS));
  }
  if (lay.level.lighting) {
    // подсветка рабочей зоны под верхними шкафами
    out.add(boxOn(runW * Math.max(lay.level.uppers, 0.5) - 6, 1.2, 3, runX0 + runW * 0.5, UPPER_BOTTOM - 2, back + 30, LIGHT_STRIP));
  }
  return out;
}
