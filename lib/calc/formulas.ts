// Формулы количества материала (К2). Чистые функции + golden-тест tests/unit/calc-formulas.test.ts.
// Вход: комната (геометрия из К1) + параметры материала; дефолты — lib/estimate/defaults.

import type { CalcKind, MaterialSpec, Room } from "@/contracts/calc";
import { floorGross, floorNet, roomAreas, surfaceGross, surfaceNet } from "./geometry";
import { DEF, PAINT_CONSUMPTION } from "@/lib/estimate/defaults";

const round1 = (n: number) => Math.round(n * 10) / 10;
const round2 = (n: number) => Math.round(n * 100) / 100;

export type CalcOutput = {
  areaGrossM2: number;
  areaNetM2: number;
  qty: number;
  unit: string;
  packs: number | null;
  note: string;
  costRub: number | null;
  // Плитка без заданного размера: штуки не посчитать. qty остаётся площадью (fallback для сметы),
  // но UI по этому флагу показывает «неизвестно», а не площадь комнаты в «Нужно».
  qtyUnknown?: boolean;
};

function wallpaper(perimeterM: number, heightM: number, m: MaterialSpec) {
  const rollW = m.rollWidthM ?? DEF.rollWidthM;
  const rollL = m.rollLengthM ?? DEF.rollLengthM;
  const rapport = m.rapportM ?? 0;
  const stripLen = heightM + rapport + 0.1 + (m.offset ? rapport / 2 : 0);
  const stripsPerRoll = Math.max(1, Math.floor(rollL / Math.max(0.01, stripLen)));
  const stripsNeeded = heightM > 0 && perimeterM > 0 ? Math.ceil(perimeterM / rollW) : 0;
  let rolls = stripsNeeded > 0 ? Math.ceil(stripsNeeded / stripsPerRoll) : 0;
  const reserve = m.reservePct ?? 0;
  if (reserve > 0) rolls = Math.ceil(rolls * (1 + reserve));
  const cost = m.pricePerRollRub != null ? Math.round(rolls * m.pricePerRollRub) : null;
  return { qty: rolls, unit: "рулон", packs: null as number | null, cost, note: `${stripsNeeded} полос, ${stripsPerRoll} из рулона${m.offset ? ", со смещением" : ""}. Проёмы — запас.` };
}

type TileResult = { qty: number; unit: string; packs: number | null; cost: number | null; note: string; qtyUnknown?: boolean };

function tile(areaNet: number, m: MaterialSpec): TileResult {
  const reserve = m.reservePct ?? DEF.tileCutReserve;
  const seam = (m.seamMm ?? DEF.seamMm) / 1000;
  if (!m.tileLengthMm || !m.tileWidthMm) {
    const area = round1(areaNet * (1 + reserve));
    const cost = m.pricePerM2Rub != null ? Math.round(area * m.pricePerM2Rub) : null;
    return { qty: area, unit: "м²", packs: null as number | null, cost, qtyUnknown: true, note: `${areaNet} м² + ${Math.round(reserve * 100)}% (задайте размер плитки для штук).` };
  }
  const moduleArea = (m.tileLengthMm / 1000 + seam) * (m.tileWidthMm / 1000 + seam);
  const tiles = Math.ceil((areaNet * (1 + reserve)) / moduleArea);
  const packs = m.tilesPerPack ? Math.ceil(tiles / m.tilesPerPack) : null;
  // Цена по выбранной единице: за м² / за шт / за упаковку (в форме одновременно задана одна).
  const cost = m.pricePerM2Rub != null ? Math.round(areaNet * (1 + reserve) * m.pricePerM2Rub)
    : m.pricePerPieceRub != null ? Math.round(tiles * m.pricePerPieceRub)
    : packs != null && m.pricePerPackRub != null ? Math.round(packs * m.pricePerPackRub) : null;
  return { qty: tiles, unit: "шт", packs, cost, note: `${areaNet} м² + ${Math.round(reserve * 100)}% подрезки, шов ${m.seamMm ?? DEF.seamMm} мм.` };
}

function paint(areaNet: number, m: MaterialSpec) {
  const coats = m.coats ?? DEF.coats;
  const consumption = m.consumptionM2PerL ?? (m.paintType ? PAINT_CONSUMPTION[m.paintType] : undefined) ?? DEF.paintConsumption;
  const liters = round1((areaNet * coats) / consumption);
  const packs = m.packVolumeL ? Math.ceil(liters / m.packVolumeL) : null;
  const cost = packs != null && m.pricePerPackRub != null ? Math.round(packs * m.pricePerPackRub) : null;
  return { qty: liters, unit: "л", packs, cost, note: `${areaNet} м² × ${coats} слоя ÷ ${consumption} м²/л.` };
}

function laminate(areaNet: number, m: MaterialSpec) {
  const diag = m.direction === "diag45" || m.direction === "diag135";
  const reserve = (m.reservePct ?? DEF.laminateReserve) + (diag ? DEF.laminateDiagExtra : 0);
  const packArea = m.panelLengthMm && m.panelWidthMm && m.panelsPerPack
    ? (m.panelLengthMm / 1000) * (m.panelWidthMm / 1000) * m.panelsPerPack
    : DEF.packAreaLaminate;
  const withReserve = areaNet * (1 + reserve);
  const packs = withReserve > 0 ? Math.ceil(withReserve / Math.max(0.01, packArea)) : 0;
  const cost = m.pricePerPackRub != null ? Math.round(packs * m.pricePerPackRub)
    : m.pricePerM2Rub != null ? Math.round(withReserve * m.pricePerM2Rub) : null;
  return { qty: packs, unit: "упаковка", packs, cost, note: `${areaNet} м² + ${Math.round(reserve * 100)}%${diag ? " (диагональ)" : ""} ÷ ${round1(packArea)} м²/упак.` };
}

export function computeRoom(room: Room, kind: CalcKind): CalcOutput {
  const { grossM2, netM2 } = roomAreas(room, kind);
  const m = room.material;
  // Стеновые виды (плитка/краска): проёмы вычитаются только по галочке «Учесть окна и двери».
  const wallArea = room.countOpenings ? netM2 : grossM2;
  const r =
    kind === "oboi"
      ? wallpaper(room.surfaces.reduce((s, x) => s + x.lengthM, 0), room.surfaces.reduce((h, x) => Math.max(h, x.heightM), 0), m)
      : kind === "plitka"
        ? tile(wallArea, m)
        : kind === "kraska"
          ? paint(wallArea, m)
          : laminate(netM2, m);
  const areaNet = kind === "plitka" || kind === "kraska" ? wallArea : netM2;
  const qtyUnknown = (r as { qtyUnknown?: boolean }).qtyUnknown;
  return { areaGrossM2: grossM2, areaNetM2: areaNet, qty: r.qty, unit: r.unit, packs: r.packs, note: r.note, costRub: r.cost, qtyUnknown };
}

// Часть комнаты со своим материалом и результатом. Плитка может дать две части — стены и пол
// (каждая своей плиткой); прочие виды — одну часть на всю комнату.
export type RoomPart = { key: "main" | "walls" | "floor"; label: string; out: CalcOutput; material: MaterialSpec; productUrl?: string };

function tileOut(grossM2: number, netM2: number, m: MaterialSpec): CalcOutput {
  const r = tile(round2(netM2), m);
  return { areaGrossM2: round2(grossM2), areaNetM2: round2(netM2), qty: r.qty, unit: r.unit, packs: r.packs, note: r.note, costRub: r.cost, qtyUnknown: r.qtyUnknown };
}

export function computeRoomParts(room: Room, kind: CalcKind): RoomPart[] {
  if (kind !== "plitka") {
    return [{ key: "main", label: "", out: computeRoom(room, kind), material: room.material, productUrl: room.productUrl }];
  }
  const hasFloor = !!room.floor;
  const wallGross = room.surfaces.reduce((s, x) => s + surfaceGross(x), 0);
  const wallNet = room.surfaces.reduce((s, x) => s + surfaceNet(x), 0);
  const wallArea = room.countOpenings ? wallNet : wallGross; // проёмы — только по галочке
  const parts: RoomPart[] = [
    { key: "walls", label: hasFloor ? "Стены" : "", out: tileOut(wallGross, wallArea, room.material), material: room.material, productUrl: room.productUrl },
  ];
  if (room.floor) {
    const fm = room.floorMaterial ?? {};
    parts.push({ key: "floor", label: "Пол", out: tileOut(floorGross(room.floor), floorNet(room.floor), fm), material: fm, productUrl: room.floorProductUrl });
  }
  return parts;
}
