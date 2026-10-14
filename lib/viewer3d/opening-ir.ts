// ОПИСАНИЕ ПРОЁМА (IR) — ОДНО ДЛЯ БРАУЗЕРА И СЕРВЕРА (план demo-04 п.2, разбор Codex 14.10).
//
// Окно, дверь и портал — это наборы коробок: откосы, рама, средник, стекло, подоконник, наличник, полотно. Раньше их
// размеры жили формулами в двух местах (`openings.ts` для браузера, `draft_render._window_parts` для серверного кадра) и
// расходились: серверное окно другой глубины, дверь — чужая модель `kit-door`. Здесь — ЕДИНСТВЕННЫЙ генератор: чистая
// функция без three.js, выдаёт коробки в сантиметрах в осях стены (X — вдоль стены от её начала, Y — вверх от пола,
// Z — внутрь комнаты), материал и смысловой id детали. `openings.ts` строит из этого меши three.js, сервер — коробки numpy
// (`tools/scout/opening_ir.py`); IR комнаты демо считается при ночной сборке (`tools/flat3d/opening-ir.mjs`).

import type { Opening } from "@/contracts/apartment";

export const OPENING_IR_VERSION = 1;

export type OpeningMaterial = "frame" | "reveal" | "glass" | "leaf" | "panel" | "handle";
export type OpeningPartRole = "reveal" | "frame" | "mullion" | "glass" | "sill" | "casing" | "leaf" | "panel" | "handle";

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

export interface OpeningIR {
  schemaVersion: number;
  kind: Opening["kind"];
  /** Габарит самого проёма в стене (вырез): от u0 до u1 по стене, от bottom до top по высоте. */
  cut: { u0: number; u1: number; bottom: number; top: number };
  boxes: IrBox[];
  groups: Record<string, IrGroup>;
}

export interface OpeningIrOpts {
  /** Высота комнаты: верх проёма не выше потолка. */
  wallHeightCm: number;
  /** Входная дверь квартиры: полотно закрыто; межкомнатная — распахнута к стене. */
  entrance?: boolean;
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

/** Как стоит полотно: петли у u0 или у u1 (`hinge`), створка в комнату или наружу (`swingCm === 0`), входная — закрыта. */
interface LeafPose {
  hingeAtEnd: boolean;
  outward: boolean;
  closed: boolean;
}

function doorIR(u0: number, u1: number, top: number, pose: LeafPose): { boxes: IrBox[]; groups: Record<string, IrGroup> } {
  const w = u1 - u0;
  const cx = (u0 + u1) / 2;
  const P = 5;
  const DEPTH = 12;
  const leafW = w - P * 2 - 1;
  const leafH = top - P - 1;
  const handleY = 105;
  const boxes: IrBox[] = [
    b("reveal", "reveal", 4, top + 6, DEPTH, u0 - 2, (top + 6) / 2, 0),
    b("reveal", "reveal", 4, top + 6, DEPTH, u1 + 2, (top + 6) / 2, 0),
    b("reveal", "reveal", w + 8, 4, DEPTH, cx, top + 2, 0),
    b("casing", "frame", P, top, DEPTH, u0 + P / 2, top / 2, 0),
    b("casing", "frame", P, top, DEPTH, u1 - P / 2, top / 2, 0),
    b("casing", "frame", w, P, DEPTH, cx, top - P / 2, 0),
    // полотно с двумя филёнками и ручкой — в осях группы «leaf» (петля в начале)
    b("leaf", "leaf", leafW, leafH, 4, leafW / 2, leafH / 2, 0, "leaf"),
    b("panel", "panel", leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.28, 2.2, "leaf"),
    b("panel", "panel", leafW * 0.62, leafH * 0.34, 1, leafW / 2, leafH * 0.68, 2.2, "leaf"),
    b("handle", "handle", 12, 2.2, 2.2, leafW - 8, handleY, 3.2, "leaf"),
    b("handle", "handle", 2.4, 2.4, 4, leafW - 4, handleY, 2.6, "leaf"),
  ];
  // Полотно построено вдоль +X от петли. Входная — закрыта; межкомнатная распахнута на ~100° от плоскости стены: внутрь
  // комнаты (+Z) или наружу (−Z) и от проёма в сторону своей петли. Петли у u1 — тот же поворот, отражённый вдоль стены.
  const hx = pose.hingeAtEnd ? u1 - P / 2 : u0 + P / 2;
  const open = pose.outward ? 99 : -99;
  const rotYDeg = pose.closed ? (pose.hingeAtEnd ? 180 : 0) : pose.hingeAtEnd ? (pose.outward ? 81 : -81) : open;
  const leaf: IrGroup = { x: hx, y: 0, z: pose.closed ? 0 : pose.outward ? -2 : 2, rotYDeg };
  return { boxes, groups: { leaf } };
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
    return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut: { u0, u1, bottom: sill, top }, boxes, groups: {} };
  }
  const top = Math.min(opts.wallHeightCm - 5, o.heightCm ?? 205);
  if (o.kind === "opening") {
    return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut: { u0, u1, bottom: 0, top }, boxes: portalIR(u0, u1, top), groups: {} };
  }
  // `hinge` здесь — в осях стены (left = у u0): `rooms.ts:openingsOnSide` при зеркалировании north/west меняет сторону сам
  const d = doorIR(u0, u1, top, { hingeAtEnd: o.hinge === "right", outward: o.swingCm === 0, closed: !!opts.entrance });
  return { schemaVersion: OPENING_IR_VERSION, kind: o.kind, cut: { u0, u1, bottom: 0, top }, boxes: d.boxes, groups: d.groups };
}
