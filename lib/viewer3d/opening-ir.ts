// ОПИСАНИЕ ПРОЁМА (IR) — ОДНО ДЛЯ БРАУЗЕРА И СЕРВЕРА (план demo-04 п.2, разбор Codex 14.10).
//
// Окно, дверь и портал — это наборы коробок: откосы, рама, средник, стекло, подоконник, наличник, полотно. Раньше их
// размеры жили формулами в двух местах (`openings.ts` для браузера, `draft_render._window_parts` для серверного кадра) и
// расходились: серверное окно другой глубины, дверь — чужая модель `kit-door`. Здесь — ЕДИНСТВЕННЫЙ генератор: чистая
// функция без three.js, выдаёт коробки в сантиметрах в осях стены (X — вдоль стены от её начала, Y — вверх от пола,
// Z — внутрь комнаты), материал и смысловой id детали. `openings.ts` строит из этого меши three.js, сервер — коробки numpy
// (`tools/scout/opening_ir.py`); IR комнаты демо считается при ночной сборке (`tools/flat3d/opening-ir.mjs`).

import type { Opening } from "@/contracts/apartment";

export const OPENING_IR_VERSION = 2; // 2 — вид из окна (`backdrop`)

export type OpeningMaterial = "frame" | "reveal" | "glass" | "leaf" | "panel" | "handle" | "skirting" | "cornice" | "lamp";
export type OpeningPartRole = "reveal" | "frame" | "mullion" | "glass" | "sill" | "casing" | "leaf" | "panel" | "handle"
  | "skirting" | "cornice" | "lamp";

/** Коробка: размеры и центр в см. Если задана `group` — координаты в осях этой группы (полотно двери). */
export interface IrBox {
  role: OpeningPartRole;
  material: OpeningMaterial;
  w: number;
  h: number;
  d: number;
  x: number;
  y: number;
  z: number;
  group?: string;
}

/** Подвижная группа (полотно двери): позиция в осях стены и поворот вокруг вертикали, градусы. */
export interface IrGroup {
  x: number;
  y: number;
  z: number;
  rotYDeg: number;
}

/**
 * Вид из окна (demo-04 п.5, разбор Codex 14.10): плоскость с картинкой на `back` см за стеной, в осях стены. `u0…u1`,
 * `bottom…top` — сама плоскость (не дальше концов стены и середины простенка), `uv` — какая часть картинки на ней.
 * Картинка стоит так, что её горизонт — на уровне глаз (`VIEW_EYE_CM`). Оба рендера берут только `assetId` из нашего набора.
 */
export interface IrBackdrop {
  assetId: string;
  back: number;
  u0: number;
  u1: number;
  bottom: number;
  top: number;
  uv: { u0: number; u1: number; v0: number; v1: number };
}

export interface OpeningIR {
  schemaVersion: number;
  kind: Opening["kind"];
  /** Габарит самого проёма в стене (вырез): от u0 до u1 по стене, от bottom до top по высоте. */
  cut: { u0: number; u1: number; bottom: number; top: number };
  boxes: IrBox[];
  groups: Record<string, IrGroup>;
  backdrop?: IrBackdrop;
}

export interface OpeningIrOpts {
  /** Высота комнаты: верх проёма не выше потолка. */
  wallHeightCm: number;
  /** Входная дверь квартиры: полотно закрыто; межкомнатная — распахнута к стене. */
  entrance?: boolean;
  /** Вид за окном: id картинки, где на ней горизонт (доля от верха) и её пропорции. */
  view?: { assetId: string; horizon01: number; aspect: number };
  /** Сколько плоскости вида можно выпустить за края выреза вдоль стены (до конца стены / середины простенка), см. */
  viewRoomLo?: number;
  viewRoomHi?: number;
}

export const VIEW_BACK_CM = 30;
export const VIEW_EYE_CM = 155; // компромисс между прогулкой (162) и ракурсом (135) — плоскость неподвижна
const VIEW_SPREAD = Math.tan((70 * Math.PI) / 180); // запас вбок: виден под углом до 70° от нормали окна
const VIEW_SPREAD_V = Math.tan((55 * Math.PI) / 180);

/** Плоскость вида за вырезом: картинка целиком по пропорциям, горизонт на уровне глаз, обрезка по разрешённому месту. */
function backdropOf(cut: OpeningIR["cut"], opts: OpeningIrOpts): IrBackdrop | undefined {
  const v = opts.view;
  if (!v) return undefined;
  const back = VIEW_BACK_CM;
  const mU = back * VIEW_SPREAD;
  const mV = back * VIEW_SPREAD_V;
  const u0 = cut.u0 - Math.min(mU, opts.viewRoomLo ?? mU);
  const u1 = cut.u1 + Math.min(mU, opts.viewRoomHi ?? mU);
  const bottom = cut.bottom - mV;
  const top = cut.top + mV;
  // картинка: ширина ≥ плоскости, высота ≥ нужной над и под горизонтом
  const imgH = Math.max((u1 - u0) / v.aspect, (top - VIEW_EYE_CM) / v.horizon01, (VIEW_EYE_CM - bottom) / (1 - v.horizon01));
  const imgW = imgH * v.aspect;
  const iTop = VIEW_EYE_CM + v.horizon01 * imgH;
  const iBottom = iTop - imgH;
  const cx = (cut.u0 + cut.u1) / 2;
  const iU0 = cx - imgW / 2;
  const r = (x: number) => Math.round(x * 1000) / 1000; // см — до сотой миллиметра
  const q = (x: number) => Math.round(x * 1e6) / 1e6; // доли картинки: 1e-3 давало сдвиг горизонта на 3 мм
  return {
    assetId: v.assetId, back, u0: r(u0), u1: r(u1), bottom: r(bottom), top: r(top),
    uv: { u0: q((u0 - iU0) / imgW), u1: q((u1 - iU0) / imgW), v0: q((bottom - iBottom) / imgH), v1: q((top - iBottom) / imgH) },
  };
}

/** Сколько места вдоль стены у каждого проёма для плоскости вида: до конца стены и до середины простенка. */
export function viewRooms(openings: { offsetCm: number; widthCm: number }[], lengthCm: number): { lo: number; hi: number }[] {
  return openings.map((o) => {
    const a = o.offsetCm;
    const z = o.offsetCm + o.widthCm;
    let lo = a;
    let hi = lengthCm - z;
    for (const p of openings) {
      if (p === o) continue;
      const pa = p.offsetCm;
      const pz = p.offsetCm + p.widthCm;
      if (pz <= a) lo = Math.min(lo, (a - pz) / 2);
      if (pa >= z) hi = Math.min(hi, (pa - z) / 2);
    }
    return { lo: Math.max(0, lo), hi: Math.max(0, hi) };
  });
}

const b = (role: OpeningPartRole, material: OpeningMaterial, w: number, h: number, d: number, x: number, y: number, z: number,
  group?: string): IrBox => ({ role, material, w, h, d, x, y, z, ...(group ? { group } : {}) });

function windowIR(u0: number, u1: number, sill: number, top: number): IrBox[] {
  const w = u1 - u0;
  const h = top - sill;
  const cx = (u0 + u1) / 2;
  const cy = (sill + top) / 2;
  const P = 6; // профиль рамы
  const DEPTH = 12; // толщина оконного блока
  return [
    // откосы: без них проём выглядит бумажным
    b("reveal", "reveal", w + 2, 4, DEPTH, cx, top + 2, 0),
    b("reveal", "reveal", w + 2, 4, DEPTH, cx, sill - 2, 0),
    b("reveal", "reveal", 4, h + 8, DEPTH, u0 - 2, cy, 0),
    b("reveal", "reveal", 4, h + 8, DEPTH, u1 + 2, cy, 0),
    // коробка рамы
    b("frame", "frame", w, P, DEPTH, cx, top - P / 2, 0),
    b("frame", "frame", w, P, DEPTH, cx, sill + P / 2, 0),
    b("frame", "frame", P, h, DEPTH, u0 + P / 2, cy, 0),
    b("frame", "frame", P, h, DEPTH, u1 - P / 2, cy, 0),
    // средник: стандартное окно в две створки
    b("mullion", "frame", P * 0.8, h - P * 2, DEPTH * 0.9, cx, cy, 0),
    // стекло — чуть наружу от плоскости стены
    b("glass", "glass", w - P * 2, h - P * 2, 1.2, cx, cy, -3),
    // подоконник внутрь комнаты
    b("sill", "frame", w + 10, 3.5, 20, cx, sill - 1, 9),
  ];
}

/** Как стоит полотно: петли у u0 или у u1 (`hinge`), створка в комнату или наружу (`swingCm === 0`), входная — закрыта;
 *  `double` — двустворчатая (две створки по половине проёма). */
interface LeafPose {
  hingeAtEnd: boolean;
  outward: boolean;
  closed: boolean;
  double?: boolean;
}

/**
 * ДВУСТВОРЧАТАЯ ДВЕРЬ (T-20261110-16/4): дуга в данных (`swing_cm`) — длина полотна; адаптер плана пишет её половиной ширины,
 * если проём не уже `trial-room.json:double_door_min_cm` (`trial_room.py:_place_opening` → `o.leaf`, `solver_openings`). Полотно,
 * которое короче 0,6 ширины проёма, одним не закрыть — рисуем две створки. У витрины дуга = ширине, там одна створка, как было.
 */
export const isDoubleDoor = (o: Pick<Opening, "kind" | "widthCm" | "swingCm">): boolean =>
  o.kind === "door" && !!o.swingCm && o.swingCm > 0 && o.swingCm <= o.widthCm * 0.6;

/** Полотно с двумя филёнками и ручкой в осях своей группы: построено вдоль +X от петли (x = 0), ручка — у свободного края
 *  (`handleAtStart` — у x = 0: закрытая створка с петлями справа стоит без разворота, см. `doorIR`). */
function leafBoxes(leafW: number, leafH: number, group: string, handleAtStart: boolean): IrBox[] {
  const handleY = 105;
  const hx = (v: number): number => (handleAtStart ? v : leafW - v);
  return [
    b("leaf", "leaf", leafW, leafH, 4, leafW / 2, leafH / 2, 0, group),
    b("panel", "panel", leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.28, 2.2, group),
    b("panel", "panel", leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.68, 2.2, group),
    b("handle", "handle", 12, 2.2, 2.2, hx(8), handleY, 3.2, group),
    b("handle", "handle", 2.4, 2.4, 4, hx(4), handleY, 2.6, group),
  ];
}

function doorIR(u0: number, u1: number, top: number, pose: LeafPose): { boxes: IrBox[]; groups: Record<string, IrGroup> } {
  const w = u1 - u0;
  const cx = (u0 + u1) / 2;
  const P = 5;
  const DEPTH = 12;
  // ПОЛОТНО ЗАХОДИТ ЗА КОРОБКУ (demo-20 Б6, снимок владельца 22.10): было `w − 2P − 1` и `top − P − 1` — у закрытой входной двери
  // между полотном и коробкой оставалась щель 3,5 см сбоку и 1 см сверху, сквозь неё была видна зелёная земля за домом.
  // Теперь края полотна — посередине профиля коробки: от петли (u0 + P/2) до u1 − P/2, верх — top − P/2
  const leafW = w - P;
  const leafH = top - P / 2;
  const boxes: IrBox[] = [
    b("reveal", "reveal", 4, top + 6, DEPTH, u0 - 2, (top + 6) / 2, 0),
    b("reveal", "reveal", 4, top + 6, DEPTH, u1 + 2, (top + 6) / 2, 0),
    b("reveal", "reveal", w + 8, 4, DEPTH, cx, top + 2, 0),
    b("casing", "frame", P, top, DEPTH, u0 + P / 2, top / 2, 0),
    b("casing", "frame", P, top, DEPTH, u1 - P / 2, top / 2, 0),
    b("casing", "frame", w, P, DEPTH, cx, top - P / 2, 0),
  ];
  // Полотно построено вдоль +X от петли. Входная — закрыта; межкомнатная распахнута на ~100° от плоскости стены: внутрь
  // комнаты (+Z) или наружу (−Z) и от проёма в сторону своей петли. Петли у u1 — тот же поворот, отражённый вдоль стены.
  // ЗАКРЫТАЯ С ПЕТЛЯМИ У u1 — БЕЗ РАЗВОРОТА НА 180° (T-20261110-16/4, «в спальне двери нет»): разворот уводил филёнки и ручку
  // на обратную сторону, в комнату смотрела гладкая белая плита — на белой стене двери не видно (все двери north/west без
  // петель в данных: зеркало `rooms.ts:openingsOnSide`). Закрытое полотно занимает тот же проём при любых петлях — ставим его
  // от u0, а ручку переносим к свободному краю.
  const z = pose.closed ? 0 : pose.outward ? -2 : 2;
  const swingStart = pose.outward ? 99 : -99;
  const swingEnd = pose.outward ? 81 : -81;
  if (pose.double) {
    // две створки по половине проёма, петли у обоих краёв, ручки — у середины; распахнуты — каждая к своей петле
    const half = leafW / 2;
    boxes.push(...leafBoxes(half, leafH, "leaf", false), ...leafBoxes(half, leafH, "leaf2", pose.closed));
    return {
      boxes,
      groups: {
        leaf: { x: u0 + P / 2, y: 0, z, rotYDeg: pose.closed ? 0 : swingStart },
        leaf2: pose.closed ? { x: cx, y: 0, z, rotYDeg: 0 } : { x: u1 - P / 2, y: 0, z, rotYDeg: swingEnd },
      },
    };
  }
  const flipFree = pose.closed && pose.hingeAtEnd;
  boxes.push(...leafBoxes(leafW, leafH, "leaf", flipFree));
  const hx = pose.hingeAtEnd && !pose.closed ? u1 - P / 2 : u0 + P / 2;
  const rotYDeg = pose.closed ? 0 : pose.hingeAtEnd ? swingEnd : swingStart;
  return { boxes, groups: { leaf: { x: hx, y: 0, z, rotYDeg } } };
}

function portalIR(u0: number, u1: number, top: number): IrBox[] {
  const w = u1 - u0;
  const cx = (u0 + u1) / 2;
  return [
    b("casing", "frame", 5, top, 14, u0 + 2.5, top / 2, 0),
    b("casing", "frame", 5, top, 14, u1 - 2.5, top / 2, 0),
    b("casing", "frame", w, 5, 14, cx, top - 2.5, 0),
  ];
}

/** IR одного проёма. `o.offsetCm` — уже в координатах «вдоль стены от её начала» (`rooms.ts:openingsOnSide`). */
export function openingIR(o: Opening, opts: OpeningIrOpts): OpeningIR {
  const u0 = o.offsetCm;
  const u1 = o.offsetCm + o.widthCm;
  if (o.kind === "window" || o.kind === "balcony") {
    // балконная дверь — остеклённый блок до пола (подоконника нет); полотно-«дверь» у неё стеклянное
    const sill = o.kind === "balcony" ? 0 : o.sillCm ?? 90;
    const top = Math.min(opts.wallHeightCm, o.kind === "balcony" ? o.heightCm ?? 220 : sill + (o.heightCm ?? 140));
    const boxes = windowIR(u0, u1, sill, top).filter((x) => o.kind !== "balcony" || x.role !== "sill");
    const cut = { u0, u1, bottom: sill, top };
    const backdrop = backdropOf(cut, opts);
    return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut, boxes, groups: {}, ...(backdrop ? { backdrop } : {}) };
  }
  const top = Math.min(opts.wallHeightCm - 5, o.heightCm ?? 205);
  if (o.kind === "opening") {
    return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut: { u0, u1, bottom: 0, top }, boxes: portalIR(u0, u1, top), groups: {} };
  }
  // `hinge` здесь — в осях стены (left = у u0): `rooms.ts:openingsOnSide` при зеркалировании north/west меняет сторону сам
  const d = doorIR(u0, u1, top, { hingeAtEnd: o.hinge === "right", outward: o.swingCm === 0, closed: !!opts.entrance, double: isDoubleDoor(o) });
  return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut: { u0, u1, bottom: 0, top }, boxes: d.boxes, groups: d.groups };
}

/** Куски стены, оставшиеся от полотна после вырезания проёмов (координаты вдоль стены, см). */
export interface WallRect {
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

export function wallRects(lengthCm: number, heightCm: number, openings: Opening[]): WallRect[] {
  const sorted = [...openings].sort((a, b) => a.offsetCm - b.offsetCm);
  const out: WallRect[] = [];
  let cursor = 0;
  for (const o of sorted) {
    const u0 = Math.max(0, Math.min(lengthCm, o.offsetCm));
    const u1 = Math.max(0, Math.min(lengthCm, o.offsetCm + o.widthCm));
    if (u1 <= u0) continue;
    if (u0 > cursor) out.push({ u0: cursor, u1: u0, v0: 0, v1: heightCm });
    // вырез — из того же описания проёма, что рама и откосы (`opening-ir.ts`), иначе вырез и рама разъезжаются
    const { bottom: sill, top } = openingIR(o, { wallHeightCm: heightCm }).cut;
    if (sill > 0) out.push({ u0, u1, v0: 0, v1: sill });
    if (top < heightCm) out.push({ u0, u1, v0: top, v1: heightCm });
    cursor = Math.max(cursor, u1);
  }
  if (cursor < lengthCm) out.push({ u0: cursor, u1: lengthCm, v0: 0, v1: heightCm });
  return out.filter((r) => r.u1 - r.u0 > 0.5 && r.v1 - r.v0 > 0.5);
}
