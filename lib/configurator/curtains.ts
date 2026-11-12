// РАЗМЕРЫ ШТОР У ОКНА (T-20261111-22, владелец TG 1643 «Шторы ставь») — одно место для сцены (`viewer3d/window-light.ts:buildCurtains`),
// карниза (`viewer3d/fixtures-ir.ts`, через `rooms.ts`) и расстановки картин (`wall-art.ts`): картина у окна не должна прятаться за
// полотном (T-20261112-26/2, кровать к стене с окном). Модуль без three — его берёт и расчёт сцены на сервере.
//
// ШТОРА ПЕРЕД ПОДОКОННИКОМ, НА КАРНИЗЕ (T-20261112-34, снимок владельца 12.11 06:02): полотно висело в 8 см от стены, а подоконник
// выступает на 19 см (`opening-ir.ts:WINDOW_SILL_FRONT_CM`) — плита шла сквозь штору, откос и рама проступали белой полосой между
// складками; карниз (на 15 см шире проёма) кончался раньше полотна, верх полотна был выше штанги. Теперь плоскость шторы и карниза —
// перед подоконником с запасом на складки, карниз — по полотнам плюс концевики, верх полотна — на штанге; полотно не заходит в угол,
// на соседнюю дверь и в проход двери соседней стены у угла (места нет — уже или только с одной стороны).

import type { Opening, Room, WallSide } from "@/contracts/apartment";
import { WINDOW_SILL_FRONT_CM } from "@/lib/viewer3d/opening-ir";

/** Ширина полотна шторы, см: по одному с каждого края окна и балконного блока. */
export const CURTAIN_PANEL_CM = 55;
/** Сколько полотно заходит на проём, см. */
export const CURTAIN_ON_OPENING_CM = 12;
/** Сколько штора выступает на стену за край проёма, см (больше — никогда; меньше — если рядом угол или дверь). */
export const CURTAIN_OVERHANG_CM = CURTAIN_PANEL_CM - CURTAIN_ON_OPENING_CM;
/** Глубина складок (полуразмах волны), см. */
export const CURTAIN_PLEAT_CM = 3;
/** Плоскость шторы и карниза от стены, см: перед подоконником (самая выступающая часть окна) + складки + 2 см воздуха. */
export const CURTAIN_PLANE_CM = WINDOW_SILL_FRONT_CM + CURTAIN_PLEAT_CM + 2;
const ROD_END_CM = 5;          // концевик карниза за полотном
const PANEL_MIN_CM = 25;       // уже — не штора, а лента
const CORNER_CLEAR_CM = 3;     // до соседней стены
const DOOR_CLEAR_CM = 10;      // до двери своей стены

/** Высота штанги карниза (центр), см: 12 см над проёмом, не выше потолка − 6. Верх полотна — здесь же. */
export const curtainRodY = (topCm: number, wallHeightCm: number): number => Math.min(topCm + 12, wallHeightCm - 6);

export interface CurtainSpan {
  /** Полотна вдоль стены (в осях отступа проёма), см. */
  panels: { u0: number; u1: number }[];
  /** Штанга карниза. */
  rod: { u0: number; u1: number };
}

const passage = (o: Opening): boolean => o.kind === "door" || o.kind === "opening" || o.kind === "balcony";

/** Свободное место у краёв проёма вдоль стены: до угла, до соседней двери (с зазором), до середины простенка с соседним окном. */
function freeAround(o: Opening, same: Opening[], lengthCm: number, keep: { lo: number; hi: number }): { lo: number; hi: number } {
  const a = o.offsetCm, z = o.offsetCm + o.widthCm;
  let lo = a - Math.max(CORNER_CLEAR_CM, keep.lo), hi = lengthCm - z - Math.max(CORNER_CLEAR_CM, keep.hi);
  for (const p of same) {
    if (p === o) continue;
    const pa = p.offsetCm, pz = p.offsetCm + p.widthCm, share = (g: number) => (passage(p) ? g - DOOR_CLEAR_CM : g / 2 - 1);
    if (pz <= a) lo = Math.min(lo, share(a - pz));
    if (pa >= z) hi = Math.min(hi, share(pa - z));
  }
  return { lo, hi };
}

/**
 * Полотна и карниз одного проёма в осях его отступа. `free` — место у краёв для полотна (минус — край проёма сам занят: угол,
 * дверь, проход двери соседней стены — полотно сдвигается на стекло), `rodFree` — для штанги (она под потолком, проход ей не помеха).
 */
export function curtainSpan(o: Pick<Opening, "offsetCm" | "widthCm">, free: { lo: number; hi: number },
  rodFree: { lo: number; hi: number } = free): CurtainSpan {
  const a = o.offsetCm, z = o.offsetCm + o.widthCm;
  const side = (f: number, rf: number) => {
    const over = Math.min(CURTAIN_OVERHANG_CM, f);
    const width = Math.max(PANEL_MIN_CM, CURTAIN_ON_OPENING_CM + Math.max(0, over));
    return { over, width, on: width - over, rod: Math.min(Math.max(0, over) + ROD_END_CM, rf) };
  };
  let L: ReturnType<typeof side> | null = side(free.lo, rodFree.lo), R: ReturnType<typeof side> | null = side(free.hi, rodFree.hi);
  // узкое окно, зажатое углом или дверью: два полотна закрыли бы больше 60 % стекла — остаётся одно, с той стороны, где места больше
  if (L.on + R.on > o.widthCm * 0.6) { if (free.lo >= free.hi) R = null; else L = null; }
  if (L && L.on > o.widthCm * 0.6) L = null;
  if (R && R.on > o.widthCm * 0.6) R = null;
  const panels: CurtainSpan["panels"] = [];
  if (L) panels.push({ u0: a - L.over, u1: a - L.over + L.width });
  if (R) panels.push({ u0: z + R.over - R.width, u1: z + R.over });
  const end = (s: typeof L, rf: number) => (s ? s.rod : Math.min(ROD_END_CM, rf));
  return { panels, rod: { u0: a - end(L, rodFree.lo), u1: z + end(R, rodFree.hi) } };
}

const NEAR_CORNER_CM = CURTAIN_PLANE_CM + CURTAIN_PLEAT_CM + 5;

/** Проход двери соседней стены у угла: полотно не встаёт ближе к углу, чем её ширина (+5 см), — иначе висит в проходе. */
function cornerKeep(room: Room, wall: WallSide): { lo: number; hi: number } {
  // концы стены в осях отступа: south/north — запад→восток, west/east — юг→север (`contracts/apartment.ts:opening`)
  const ns = wall === "south" || wall === "north";
  const [loWall, hiWall]: [WallSide, WallSide] = ns ? ["west", "east"] : ["south", "north"];
  const nearMin = wall === "south" || wall === "west";   // наша стена — у начала отступов соседней
  const span = ns ? room.d : room.w;
  const keep = (adj: WallSide) => Math.max(0, ...room.openings.filter((p) => p.wall === adj && passage(p)).map((p) => {
    const dist = nearMin ? p.offsetCm : span - p.offsetCm - p.widthCm;
    return dist < NEAR_CORNER_CM ? p.widthCm + 5 : 0;
  }));
  return { lo: keep(loWall), hi: keep(hiWall) };
}

/** Шторы комнаты: по индексу `room.openings` — у окна и балконного блока полотна и карниз (оси отступа), у остального null. */
export function roomCurtains(room: Room): (CurtainSpan | null)[] {
  const keep: Partial<Record<WallSide, { lo: number; hi: number }>> = {};
  return room.openings.map((o) => {
    if (o.kind !== "window" && o.kind !== "balcony") return null;
    const same = room.openings.filter((p) => p.wall === o.wall);
    const len = o.wall === "south" || o.wall === "north" ? room.w : room.d;
    const k = (keep[o.wall] ??= cornerKeep(room, o.wall));
    return curtainSpan(o, freeAround(o, same, len, k), freeAround(o, same, len, { lo: 0, hi: 0 }));
  });
}
