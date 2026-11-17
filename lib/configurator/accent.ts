// АКЦЕНТНАЯ СТЕНА «ЗА ДИВАНОМ» — ОДНА ФУНКЦИЯ ДЛЯ ОКНА ДЕМО, /flat И СЕРВЕРНОГО КАДРА (demo-07, разбор Codex 16.10). В данных
// варианта отделки — смысл (`anchor: "behind-sofa"`), а не сторона света: у каждой расстановки диван у своей стены, и после
// перестановки дивана акцент переезжает за ним. Сторону считает расчёт сцены (`resolve.resolveScene`) из итогового места дивана;
// страница и сервер получают готовую сторону и ничего не угадывают повторно.

import type { Placement, Room, WallSide } from "@/contracts/apartment";
import finishCc0 from "@/data/flat3d/finish-cc0.json";
import { frontDirection } from "@/lib/viewer3d/transform";

const NORMALS: [WallSide, number, number][] = [["south", 0, -1], ["north", 0, 1], ["west", -1, 0], ["east", 1, 0]];

/** Стена, к которой обращена спинка дивана: по направлению спинки (rot 0 — лицом в +y), спорное (угол, 45°) — ближняя. */
export function resolveAccentSide(room: Room, sofa: Pick<Placement, "x" | "y" | "rot">): WallSide {
  const f = frontDirection(sofa.rot);
  const back = { x: -f.x, y: -f.y };
  const dist: Record<WallSide, number> = {
    south: sofa.y - room.y, north: room.y + room.d - sofa.y, west: sofa.x - room.x, east: room.x + room.w - sofa.x,
  };
  let best: WallSide = "south";
  let bestScore = -Infinity;
  for (const [side, nx, ny] of NORMALS) {
    const dot = back.x * nx + back.y * ny;
    // направление решает; при почти равном направлении (диван под 45°, угловой) — ближняя стена
    const score = dot * 1000 - dist[side];
    if (score > bestScore) { bestScore = score; best = side; }
  }
  return best;
}

/** Роли главного предмета комнаты по порядку — за ним акцент `behind-focal` (данные: `finish-cc0.json` → `accentWalls.carriers`). */
export const ACCENT_CARRIERS: readonly string[] = (finishCc0 as { accentWalls: { carriers: string[] } }).accentWalls.carriers;

type CarrierItem<P> = { roomId: string; kind: string; photoRole?: string | null; slotId: string; placement: P };

/**
 * Предмет, за которым ставится акцентная стена: `behind-sofa` — диван; `behind-focal` — первый найденный в комнате из
 * `ACCENT_CARRIERS` (спальня — кровать, гостиная — диван, нет дивана — ТВ). Выбор — по роли предмета сцены, не по ID комнаты.
 */
export function accentCarrier<P>(items: CarrierItem<P>[], roomId: string, anchor: "behind-sofa" | "behind-focal"): CarrierItem<P> | undefined {
  const roles = anchor === "behind-sofa" ? ["диван"] : ACCENT_CARRIERS;
  for (const role of roles) {
    const hit = items.find((i) => i.roomId === roomId && (i.kind === "furniture" || anchor === "behind-focal") && new RegExp(`^${role}`).test(i.photoRole ?? i.slotId));
    if (hit) return hit;
  }
  return undefined;
}
