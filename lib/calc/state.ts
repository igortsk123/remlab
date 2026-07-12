// Чистая логика состояния калькулятора (CRUD комнат) — без побочек, покрыта тестами.
// Генератор id и текущее время передаются параметрами (тестируемость, без Date.now/random внутри).

import type { CalcKind, CalcProject, Room } from "@/contracts/calc";

type MkId = () => string;

export function emptyRoom(name: string, mkId: MkId): Room {
  return { id: mkId(), name, surfaces: [], material: {} };
}

export function emptyProject(kind: CalcKind, mkId: MkId, now: string): CalcProject {
  return { version: 1, kind, rooms: [emptyRoom("Комната 1", mkId)], updatedAt: now };
}

// Следующее имя «Комната N» по максимальному существующему номеру.
function nextRoomName(p: CalcProject): string {
  let max = 0;
  for (const r of p.rooms) {
    const m = /^Комната (\d+)$/.exec(r.name);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `Комната ${Math.max(max, p.rooms.length) + 1}`;
}

export function addRoom(p: CalcProject, mkId: MkId, now: string): CalcProject {
  return { ...p, rooms: [...p.rooms, emptyRoom(nextRoomName(p), mkId)], updatedAt: now };
}

export function removeRoom(p: CalcProject, roomId: string, now: string): CalcProject {
  return { ...p, rooms: p.rooms.filter((r) => r.id !== roomId), updatedAt: now };
}

export function renameRoom(p: CalcProject, roomId: string, name: string, now: string): CalcProject {
  return { ...p, rooms: p.rooms.map((r) => (r.id === roomId ? { ...r, name } : r)), updatedAt: now };
}

export function duplicateRoom(p: CalcProject, roomId: string, mkId: MkId, now: string): CalcProject {
  const idx = p.rooms.findIndex((r) => r.id === roomId);
  if (idx < 0) return p;
  const src = p.rooms[idx]!;
  const copy: Room = { ...src, id: mkId(), name: `${src.name} (копия)` };
  const rooms = [...p.rooms.slice(0, idx + 1), copy, ...p.rooms.slice(idx + 1)];
  return { ...p, rooms, updatedAt: now };
}

// Обновить одну комнату функцией-апдейтером (геометрия/параметры — К1–К2).
export function updateRoom(p: CalcProject, roomId: string, fn: (r: Room) => Room, now: string): CalcProject {
  return { ...p, rooms: p.rooms.map((r) => (r.id === roomId ? fn(r) : r)), updatedAt: now };
}
