// Мост «конфигурация → существующий photo-конвейер» (план apartment-3d-configurator).
//
// Конвейер НЕ переделываем: `tools/scout/draft_service.py` ждёт ОДНУ комнату в её локальных
// координатах (см) и список предметов с ролями по-русски. Здесь только перевод — ни одной
// новой сущности на той стороне. Контракт снят с живого запроса демо (`flat215-demo/index.html`
// payload(): room, items, cams, style, quality) — аудит 28.09.

import type { Apartment, Room } from "@/contracts/apartment";
import { findRoom, toRoomLocal } from "@/contracts/apartment";
import type { ResolvedScene } from "@/lib/configurator/resolve";

export interface PhotoOpening {
  kind: string;
  wall: string;
  offset_cm: number;
  width_cm: number;
  sill_cm?: number;
  height_cm?: number;
  swing_cm?: number;
}

export interface PhotoItem {
  role: string;
  x: number;
  y: number;
  rot: number;
  w: number;
  d: number;
  h: number;
  elev?: number;
  sid?: string;
  msid?: string;
  name?: string;
}

export interface PhotoCam {
  name: string;
  x: number;
  y: number;
  rot: number;
  fov: number;
}

export interface PhotoRequest {
  room: { w: number; d: number; title: string; openings: PhotoOpening[]; radiators: never[] };
  items: PhotoItem[];
  cams: PhotoCam[];
  style: string;
  variant: string;
  quality: "draft" | "realistic";
}

function openingsOf(r: Room): PhotoOpening[] {
  return r.openings.map((o) => ({
    kind: o.kind === "opening" ? "door" : o.kind,
    wall: o.wall,
    offset_cm: Math.round(o.offsetCm),
    width_cm: Math.round(o.widthCm),
    ...(o.sillCm === undefined ? {} : { sill_cm: Math.round(o.sillCm) }),
    ...(o.heightCm === undefined ? {} : { height_cm: Math.round(o.heightCm) }),
    // Дверь без створки: демо шлёт swing_cm=0, когда открывание наружу не показываем.
    ...(o.kind === "door" ? { swing_cm: 0 } : {}),
  }));
}

/**
 * Запрос кадра для одной комнаты. Встроенное (кухня/санузел) уходит без `msid` — конвейер
 * нарисует его глиняным блоком, и это честнее пустой комнаты: GPT дорисовывает по форме.
 */
export function toPhotoRequest(
  a: Apartment,
  scene: ResolvedScene,
  roomId: string,
  opts: { quality?: "draft" | "realistic"; style?: string } = {},
): PhotoRequest | null {
  const room = findRoom(a, roomId);
  if (!room) return null;

  const items: PhotoItem[] = [];
  for (const it of scene.items) {
    if (it.roomId !== roomId) continue;
    const p = it.placement;
    const local = toRoomLocal(room, p.x, p.y);
    const base: PhotoItem = {
      role: it.photoRole ?? it.titleRu,
      x: Math.round(local.x),
      y: Math.round(local.y),
      rot: Math.round(p.rot),
      w: Math.round(p.wCm),
      d: Math.round(p.dCm),
      h: Math.round(p.hCm),
      name: it.titleRu,
    };
    if (p.elevCm > 0) base.elev = Math.round(p.elevCm);
    if (it.asset.kind === "mesh") {
      base.msid = it.asset.meshId;
      base.sid = it.asset.meshId;
    }
    items.push(base);
  }

  return {
    room: {
      w: Math.round(room.w),
      d: Math.round(room.d),
      title: room.titleRu,
      openings: openingsOf(room),
      radiators: [],
    },
    items,
    cams: camsOf(a, room),
    style: opts.style ?? "современный",
    variant: room.titleRu,
    quality: opts.quality ?? "draft",
  };
}

/**
 * Камеры: берём заготовки квартиры для этой комнаты, иначе — диагональ из угла в центр
 * (правило демо ADR-0149: два вида обязаны быть диагональными, иначе кадр «в стену»).
 */
export function camsOf(a: Apartment, room: Room): PhotoCam[] {
  const preset = a.cameras.filter((c) => c.roomId === room.id);
  if (preset.length > 0) {
    return preset.slice(0, 2).map((c) => {
      const local = toRoomLocal(room, c.x, c.y);
      return {
        name: c.titleRu,
        x: Math.round(local.x),
        y: Math.round(local.y),
        rot: Math.round(c.rot),
        fov: c.fov,
      };
    });
  }
  const pad = 3;
  // У КАМЕР КОНВЕНЦИЯ УГЛА ДРУГАЯ, ЧЕМ У ПРЕДМЕТОВ: конвейер строит взгляд как
  // (sin a, −cos a) — это `aimAtCentre` демо (`flat215-demo/index.html:1197`) и
  // `draft_render.cams_from_request`. Поймано пустым кадром 28.09: с «предметной» формулой
  // камера смотрела ровно в противоположную стену.
  const aim = (x: number, y: number): number => {
    const dx = room.w / 2 - x;
    const dy = room.d / 2 - y;
    return Math.round(((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360);
  };
  return [
    { name: "вид 1", x: pad, y: pad, rot: aim(pad, pad), fov: 72 },
    {
      name: "вид 2",
      x: Math.round(room.w - pad),
      y: Math.round(room.d - pad),
      rot: aim(room.w - pad, room.d - pad),
      fov: 72,
    },
  ];
}
