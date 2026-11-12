// МЕСТО КАРТИНЫ НА СТЕНЕ — ОДНО ПРАВИЛО ДЛЯ АВТОРАСЧЁТА И ДЛЯ «✥ ПЕРЕМЕСТИТЬ» (T-20261112-97, владелец TG 865: «перемещать вдоль
// стены, повесить на любую стену»; TG 873/938 — одно правило для /demo, «Этажей» и туров). Отрезок стены [a0, a1] и высоты
// [низ, верх] проверяются одинаково, кто бы их ни предложил: над опорой (`wall-art.ts:hangOver`) или покупатель пальцем
// (`hangAt`). Нельзя: у края стены, под потолком, на окне/двери/проёме (± зазор, у окна — плюс свес шторы), в зоне створки двери,
// поверх мебели у стены по высоте (в т. ч. ниже верха спинки дивана или изголовья, если картина над ними), поверх другой картины
// или зеркала и поверх телевизора над тумбой (`scene-extras.autoTv`). Высоту центра при переносе держит норма
// `occupancy.json` → `distances_cm.mounting.wall_art.center_from_floor` (то же число, что `heights_cm.art_center`).

import type { Placement, Room, WallSide } from "@/contracts/apartment";
import { DEFAULT_CEILING_CM } from "@/contracts/apartment";
import { CURTAIN_OVERHANG_CM } from "@/lib/configurator/curtains";
import type { ResolvedItem } from "@/lib/configurator/resolve";
import { alongOf, footprint, onWall, overlaps, rightAngle, stripRect, swingZones, wallLength, WALL_INSET_CM, type Rect } from "@/lib/configurator/wall-art-geo";
import { autoTv } from "@/lib/viewer3d/scene-extras";
import { distances_cm as DIST } from "@/services/planner-solver/rules/occupancy.json";

/** Числа правил, нужные проверке (`data/flat3d/wall-art.json`). */
export interface SpanRules { ceiling_gap_cm: number; wall_edge_cm: number; opening_clear_cm: number }

/** Место картины: стена, центр вдоль неё от начала стены (`wall-art-geo.alongOf`) и низ от пола, см. */
export type ArtSpot = { wall: WallSide; along: number; elev: number };
/** Почему нельзя: край стены, потолок, пол, проём, створка двери, мебель, картина или зеркало, телевизор. */
export type ArtProblem = "edge" | "ceiling" | "floor" | "opening" | "swing" | "furniture" | "art" | "tv";
/** Что занимает стену: след на полу и высоты. */
export interface Blocker { rect: Rect; z0: number; z1: number; kind: "furniture" | "art" | "tv" }

/** Полоса у стены, в которой соседняя мебель «загораживает» картину (шкаф рядом с кроватью), см. */
export const NEAR_WALL_CM = 45;
/** Подпись места картины, повешенной покупателем (`ResolvedItem.hungOver`; страница — «на стене»). */
export const HUNG_FREE = "стена";
/** Центр картины от пола по норме, см — нижняя граница высоты при переносе (выше — пока не упрётся в потолок). */
export const ART_CENTRE_CM = DIST.mounting.wall_art.center_from_floor as [number, number];

/** Лицом в комнату: rot 0 смотрит на +y (спиной к южной стене) — как у опоры в `wall-art-geo.backWall`. */
const FACE: Record<WallSide, number> = { south: 0, west: 90, north: 180, east: 270 };
const SIDE: Record<number, WallSide> = { 0: "south", 90: "west", 180: "north", 270: "east" };

export const baseRole = (role?: string | null): string => String(role ?? "").replace(/\s+\d+$/, "").trim();

/** Отрезок стены [a0, a1] на высотах [bottom, top] свободен? → причина отказа или null. `depth` — полоса створки двери. */
export function spanProblem(room: Room, wall: WallSide, a0: number, a1: number, bottom: number, top: number, depth: number,
  blockers: readonly Blocker[], r: SpanRules): ArtProblem | null {
  if (a0 < r.wall_edge_cm || a1 > wallLength(room, wall) - r.wall_edge_cm) return "edge";
  if (top > (room.heightCm || DEFAULT_CEILING_CM) - r.ceiling_gap_cm) return "ceiling";
  if (bottom < 0) return "floor";
  // у окна и балконного блока висит штора — картина не должна уйти за полотно (T-20261112-26/2)
  const clear = (k: string): number => r.opening_clear_cm + (k === "window" || k === "balcony" ? CURTAIN_OVERHANG_CM : 0);
  if (room.openings.some((o) => o.wall === wall && o.offsetCm - clear(o.kind) < a1 && a0 < o.offsetCm + o.widthCm + clear(o.kind))) return "opening";
  if (swingZones(room).some((z) => overlaps(z, stripRect(room, wall, a0, a1, depth)))) return "swing";
  const near = stripRect(room, wall, a0, a1, NEAR_WALL_CM);
  return blockers.find((o) => overlaps(o.rect, near) && o.z0 < top && o.z1 > bottom)?.kind ?? null;
}

const boxOf = (p: Placement): { rect: Rect; z0: number; z1: number } =>
  ({ rect: footprint(p), z0: p.elevCm ?? 0, z1: (p.elevCm ?? 0) + p.hCm });

/**
 * Что занимает стены комнаты: мебель (без ковра и неразмещённого), повешенные картины и зеркала (`kit: wall-plane`) и
 * телевизор над тумбой, если своего «тв» в расстановке нет (`autoTv` — тот же расчёт, что рисует сцена). `skip` — опора картины:
 * сама себе не помеха (ТВ при этом считается по всей расстановке).
 */
export function blockersOf(items: readonly ResolvedItem[], skip?: ResolvedItem): Blocker[] {
  const live = items.filter((o) => o.kind === "furniture" && !o.unplaced && !(o.asset.kind === "kit" && o.asset.kit === "rug"));
  const out: Blocker[] = live.filter((o) => o !== skip).map((o) => ({ ...boxOf(o.placement),
    kind: o.asset.kind === "kit" && o.asset.kit === "wall-plane" ? "art" : baseRole(o.photoRole) === "тв" ? "tv" : "furniture" }));
  const tv = autoTv(live.map((o) => ({ role: o.photoRole ?? "", x: o.placement.x, y: o.placement.y, rot: o.placement.rot,
    w: o.placement.wCm, d: o.placement.dCm, h: o.placement.hCm, name: o.titleRu })));
  if (tv) out.push({ ...boxOf({ x: tv.x, y: tv.y, rot: tv.rot, wCm: tv.wCm, dCm: tv.dCm, hCm: tv.hCm, elevCm: tv.elevCm }), kind: "tv" });
  return out;
}

/** Повесить картину габаритом `p` в место `spot` → место в квартире или причина отказа. */
export function hangAt(room: Room, p: Pick<Placement, "wCm" | "dCm" | "hCm">, spot: ArtSpot, blockers: readonly Blocker[], r: SpanRules):
  { x: number; y: number; rot: number; elev: number } | { problem: ArtProblem } {
  const a0 = spot.along - p.wCm / 2, a1 = spot.along + p.wCm / 2;
  const problem = spanProblem(room, spot.wall, a0, a1, spot.elev, spot.elev + p.hCm, p.dCm + WALL_INSET_CM, blockers, r);
  return problem ? { problem } : placeOn(room, p, spot);
}

/** Место в квартире картины глубиной `p.dCm`, повешенной в `spot`: центр следа у стены, лицом в комнату, низ — `spot.elev`. */
export function placeOn(room: Room, p: Pick<Placement, "dCm">, spot: ArtSpot): { x: number; y: number; rot: number; elev: number } {
  const at = onWall(room, spot.wall, spot.along, p.dCm);
  return { x: at.x, y: at.y, rot: FACE[spot.wall], elev: spot.elev };
}

/** Где висит картина (её место в квартире) → стена, центр вдоль неё, низ; косо (не лицом в комнату) — null. */
export function spotOf(room: Room, p: Placement): ArtSpot | null {
  const r = rightAngle(p.rot);
  if (r === null) return null;
  const wall = SIDE[r]!;
  return { wall, along: alongOf(room, wall, p.x, p.y), elev: p.elevCm ?? 0 };
}

/**
 * Желаемое место при переносе → место в пределах стены: центр вдоль стены — так, чтобы картина целиком была на ней; низ — не ниже
 * `minElev` (норма центра или исходная высота, если картина висела ниже) и верх не выше потолка с зазором. Проверку правил не
 * делает — её делает `hangAt` (красное место показываем, а не прячем).
 */
export function clampSpot(room: Room, p: Pick<Placement, "wCm" | "hCm">, want: ArtSpot, minElev: number, r: Pick<SpanRules, "ceiling_gap_cm">): ArtSpot {
  const len = wallLength(room, want.wall);
  const along = Math.min(Math.max(want.along, p.wCm / 2), Math.max(p.wCm / 2, len - p.wCm / 2));
  const maxElev = (room.heightCm || DEFAULT_CEILING_CM) - r.ceiling_gap_cm - p.hCm;
  const elev = Math.min(Math.max(want.elev, minElev), Math.max(minElev, maxElev));
  const r1 = (v: number): number => Math.round(v * 10) / 10;
  return { wall: want.wall, along: r1(along), elev: r1(elev) };
}
