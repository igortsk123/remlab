// КАРТИНЫ НАД МЕБЕЛЬЮ (viz-decor-01 шаг 3, T-20261112-26; владелец TG 1645/1656: картины — только товары каталога). Место
// картины — не данные, а следствие ИТОГОВОЙ расстановки (как ваза на столике, `resolve.placeTabletop`): над изголовьем кровати,
// иначе над диваном, иначе над комодом; по центру опоры, низ на 20–25 см выше её верха. Опору заменили, повернули, убрали —
// место считается заново; свободного куска стены нет — картина в составе и цене, но в 3D не висит (`unplaced`).
// Числа — ОДНО МЕСТО с подбором товара сборкой витрины: `data/flat3d/wall-art.json` (`tools/scout/wall_art.py`).

import type { Apartment, Room } from "@/contracts/apartment";
import { DEFAULT_CEILING_CM } from "@/contracts/apartment";
import rulesJson from "@/data/flat3d/wall-art.json";
import { CURTAIN_OVERHANG_CM } from "@/lib/configurator/curtains";
import type { ResolvedItem } from "@/lib/configurator/resolve";
import { alongOf, backWall, footprint, onWall, overlaps, stripRect, swingZones, wallLength, WALL_INSET_CM } from "@/lib/configurator/wall-art-geo";

export interface WallArtRules {
  enabled: boolean;
  supports: string[];
  share_range: number[];
  max_count: number;
  pair_gap_cm: number;
  above_cm: Record<string, number>;
  ceiling_gap_cm: number;
  back_gap_cm: number;
  wall_edge_cm: number;
  opening_clear_cm: number;
}

export const WALL_ART_RULES: WallArtRules = rulesJson;

/** Полоса у стены, в которой соседняя мебель «загораживает» картину (шкаф рядом с кроватью), см. */
const NEAR_WALL_CM = 45;

const baseRole = (role?: string | null): string => String(role ?? "").replace(/\s+\d+$/, "").trim();

type Spot = { x: number; y: number; rot: number; elev: number };

/**
 * Повесить группу картин над опорой: ряд по центру опоры с зазором, низ — над верхом опоры, центры по одной линии. Любая
 * помеха — null: край стены, проём той же стены (± зазор), створка двери любой стены, высокая мебель у стены, потолок,
 * группа шире опоры (верх коридора доли).
 */
function hangOver(room: Room, sup: ResolvedItem, art: ResolvedItem[], others: ResolvedItem[], r: WallArtRules): Spot[] | null {
  const back = backWall(room, sup.placement);
  if (!back || back.gap > r.back_gap_cm || back.gap < -WALL_INSET_CM - 1) return null;
  const { wall } = back;
  const total = art.reduce((s, i) => s + i.placement.wCm, 0) + r.pair_gap_cm * (art.length - 1);
  if (total > sup.placement.wCm * (r.share_range[1] ?? 0.85)) return null;
  const centre = alongOf(room, wall, sup.placement.x, sup.placement.y);
  const [a0, a1] = [centre - total / 2, centre + total / 2];
  if (a0 < r.wall_edge_cm || a1 > wallLength(room, wall) - r.wall_edge_cm) return null;
  const tallest = Math.max(...art.map((i) => i.placement.hCm));
  const bottom = (sup.placement.elevCm ?? 0) + sup.placement.hCm + (r.above_cm[baseRole(sup.photoRole)] ?? r.above_cm["*"] ?? 22);
  if (bottom + tallest > (room.heightCm || DEFAULT_CEILING_CM) - r.ceiling_gap_cm) return null;
  // у окна и балконного блока висит штора — картина не должна уйти за полотно (T-20261112-26/2)
  const clear = (k: string): number => r.opening_clear_cm + (k === "window" || k === "balcony" ? CURTAIN_OVERHANG_CM : 0);
  if (room.openings.some((o) => o.wall === wall && o.offsetCm - clear(o.kind) < a1 && a0 < o.offsetCm + o.widthCm + clear(o.kind))) return null;
  const depth = Math.max(...art.map((i) => i.placement.dCm)) + WALL_INSET_CM;
  const strip = stripRect(room, wall, a0, a1, depth);
  if (swingZones(room).some((z) => overlaps(z, strip))) return null;
  const near = stripRect(room, wall, a0, a1, NEAR_WALL_CM);
  const top = bottom + tallest;
  const blocked = others.some((o) => o !== sup && !o.unplaced && !(o.asset.kind === "kit" && o.asset.kit === "rug")
    && overlaps(footprint(o.placement), near)
    && (o.placement.elevCm ?? 0) < top && (o.placement.elevCm ?? 0) + o.placement.hCm > bottom);
  if (blocked) return null;
  let at = a0;
  return art.map((i) => {
    const mid = at + i.placement.wCm / 2;
    at += i.placement.wCm + r.pair_gap_cm;
    const p = onWall(room, wall, mid, i.placement.dCm);
    return { x: p.x, y: p.y, rot: sup.placement.rot, elev: bottom + (tallest - i.placement.hCm) / 2 };
  });
}

/**
 * Картины комнаты встают над ТЕКУЩЕЙ опорой (порядок `supports`): сначала все (до `max_count`) рядом, не влезли — одна первая,
 * остальные `unplaced`; ни одной опоры с местом — все `unplaced`. `enabled: false` — картины не висят нигде.
 */
export function placeWallArt(a: Apartment, items: ResolvedItem[], rules: WallArtRules = WALL_ART_RULES): void {
  const artIds = new Set(a.slots.filter((s) => s.wallArt).map((s) => s.id));
  if (!artIds.size) return;
  for (const roomId of new Set(items.map((i) => i.roomId))) {
    const art = items.filter((i) => i.roomId === roomId && artIds.has(i.slotId));
    if (!art.length) continue;
    art.forEach((i) => { i.unplaced = true; });
    const room = a.rooms.find((x) => x.id === roomId);
    if (!room || !rules.enabled) continue;
    const others = items.filter((i) => i.roomId === roomId && !artIds.has(i.slotId) && i.kind === "furniture");
    const full = art.slice(0, Math.max(1, rules.max_count));
    const groups = full.length > 1 ? [full, full.slice(0, 1)] : [full];
    rules.supports.some((role) => others.filter((o) => !o.unplaced && baseRole(o.photoRole) === role)
      .some((sup) => groups.some((g) => {
        const spots = hangOver(room, sup, g, others, rules);
        if (!spots) return false;
        g.forEach((i, k) => {
          const s = spots[k]!;
          i.placement = { ...i.placement, x: s.x, y: s.y, rot: s.rot, elevCm: s.elev };
          i.hungOver = role;   // подпись страницы «над кроватью» — отсюда (`demo-scene.ts:wallArtWhere`)
          delete i.unplaced;
        });
        return true;
      })));
  }
}
