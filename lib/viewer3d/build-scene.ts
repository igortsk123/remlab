// Раскладка разрешённой конфигурации на объекты сцены — ЧИСТАЯ функция (без three.js),
// поэтому её гоняет vitest: именно здесь живёт склейка «кухня = корпус + техника + столешница
// + фартук», из-за которой раньше всего легче всего разъехаться 3D и фото.

import type { Apartment, Placement } from "@/contracts/apartment";
import { findRoom } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import type { ResolvedScene, ResolvedSurface } from "@/lib/configurator/resolve";
import { meshUrl } from "@/lib/configurator/mesh-url";
import { autoTv, baseRole } from "@/lib/viewer3d/scene-extras";

export interface RoomSurfaces {
  floor?: ResolvedSurface;
  wall?: ResolvedSurface;
  worktop?: ResolvedSurface;
  splashback?: ResolvedSurface;
}

export type ObjectSpec =
  | {
      kind: "mesh";
      slotId: string;
      roomId: string;
      titleRu: string;
      meshId: string;
      url: string;
      yawDeg: number;
      tintRgb?: [number, number, number];
      placement: Placement;
    }
  | {
      kind: "kitchen";
      slotId: string;
      roomId: string;
      titleRu: string;
      placement: Placement;
      level: "base" | "practical" | "comfort" | "premium";
      features: string[];
      doorMaterialId?: string;
      worktopMaterialId?: string;
      splashbackMaterialId?: string;
    }
  | {
      kind: "bathroom";
      slotId: string;
      roomId: string;
      titleRu: string;
      placement: Placement;
      level: "base" | "practical" | "comfort" | "premium";
      features: string[];
      vanityMaterialId?: string;
    }
  | {
      kind: "bed" | "wardrobe" | "rug";
      slotId: string;
      roomId: string;
      titleRu: string;
      placement: Placement;
      level: "base" | "practical" | "comfort" | "premium";
      features: string[];
      materialId?: string;
    }
  | {
      /** Телевизор над тумбой — производный объект, не слот: не выбирается, не препятствие (`sceneExtras`). */
      kind: "tv";
      slotId: string;
      roomId: string;
      titleRu: string;
      placement: Placement;
      hung: boolean;
    };

/** Производные объекты сцены (ТВ над тумбой): своего слота нет — не выбираются кликом и не мешают прогулке. */
export const EXTRA_PREFIX = "@extra:";
export const isExtra = (slotId: string): boolean => slotId.startsWith(EXTRA_PREFIX);

export function surfacesByRoom(scene: ResolvedScene): Map<string, RoomSurfaces> {
  const out = new Map<string, RoomSurfaces>();
  for (const s of scene.surfaces) {
    const cur = out.get(s.roomId) ?? {};
    cur[s.surface] = s;
    out.set(s.roomId, cur);
  }
  return out;
}

/**
 * Объекты сцены. Кухня собирается из НЕСКОЛЬКИХ слотов: корпус (категория kitchen),
 * техника (appliances) и материалы столешницы/фартука — это разные покупки у застройщика,
 * но одна вещь в комнате.
 */
export function planObjects(
  a: Apartment,
  _c: Catalogue,
  scene: ResolvedScene,
  opts: { lite?: boolean } = {},
): ObjectSpec[] {
  const surfaces = surfacesByRoom(scene);
  const out: ObjectSpec[] = [];
  const kitchenByRoom = new Map<string, ObjectSpec>();

  for (const item of scene.items) {
    const room = findRoom(a, item.roomId);
    if (!room) continue;
    const asset = item.asset;

    if (asset.kind === "mesh") {
      out.push({
        kind: "mesh",
        slotId: item.slotId,
        roomId: item.roomId,
        titleRu: item.titleRu,
        meshId: asset.meshId,
        url: meshUrl(asset.meshId, asset.runtimeUrl, opts.lite === true),
        yawDeg: asset.yawDeg,
        tintRgb: asset.tintRgb,
        placement: item.placement,
      });
      continue;
    }
    if (asset.kind !== "kit") continue;

    if (asset.kit === "kitchen") {
      const s = surfaces.get(item.roomId) ?? {};
      const existing = kitchenByRoom.get(item.roomId);
      if (existing && existing.kind === "kitchen") {
        // второй слот той же кухни (техника): доливаем признаки и материалы, не плодим корпус
        existing.features = [...new Set([...existing.features, ...asset.features])];
        existing.doorMaterialId = existing.doorMaterialId ?? asset.materials.door;
        if (item.category === "kitchen") existing.level = asset.level;
        continue;
      }
      const spec: ObjectSpec = {
        kind: "kitchen",
        slotId: item.slotId,
        roomId: item.roomId,
        titleRu: item.titleRu,
        placement: item.placement,
        level: asset.level,
        features: [...asset.features],
        doorMaterialId: asset.materials.door,
        worktopMaterialId: s.worktop?.material.id,
        splashbackMaterialId: s.splashback?.material.id,
      };
      kitchenByRoom.set(item.roomId, spec);
      out.push(spec);
      continue;
    }

    if (asset.kit === "bathroom") {
      out.push({
        kind: "bathroom",
        slotId: item.slotId,
        roomId: item.roomId,
        titleRu: item.titleRu,
        placement: item.placement,
        level: asset.level,
        features: [...asset.features],
        vanityMaterialId: asset.materials.vanity,
      });
      continue;
    }

    out.push({
      kind: asset.kit === "bed" ? "bed" : asset.kit === "rug" ? "rug" : "wardrobe",
      slotId: item.slotId,
      roomId: item.roomId,
      titleRu: item.titleRu,
      placement: item.placement,
      level: asset.level,
      features: [...asset.features],
      materialId: asset.materials.body ?? asset.materials.door,
    });
  }
  return [...out, ...sceneExtras(scene, out)];
}

/**
 * Авто-ТВ над тумбой — тем же правилом, что серверный кадр (`scene-extras.ts`, план demo-05 п.9). Считается из ТЕКУЩЕЙ
 * расстановки после выбора покупателя: передвинул, заменил или убрал тумбу — телевизор следует за ней без своего
 * состояния. Подвесная тумба (по названию товара) поднимается на 40 см, как на серверном кадре.
 */
export function sceneExtras(scene: ResolvedScene, specs: ObjectSpec[]): ObjectSpec[] {
  const extras: ObjectSpec[] = [];
  const rooms = [...new Set(scene.items.map((i) => i.roomId))];
  for (const roomId of rooms) {
    const items = scene.items.filter((i) => i.roomId === roomId && i.photoRole);
    const tv = autoTv(items.map((i) => ({ role: i.photoRole ?? undefined, x: i.placement.x, y: i.placement.y, rot: i.placement.rot,
      w: i.placement.wCm, d: i.placement.dCm, h: i.placement.hCm, elev: i.placement.elevCm, name: i.titleRu })));
    if (!tv) continue;
    if (tv.standElevCm !== undefined) {
      const stand = items.find((i) => baseRole(i.photoRole ?? undefined) === "тв-тумба");
      const spec = specs.find((sp) => sp.slotId === stand?.slotId);
      if (spec && !spec.placement.elevCm) spec.placement = { ...spec.placement, elevCm: tv.standElevCm };
    }
    extras.push({ kind: "tv", slotId: `${EXTRA_PREFIX}tv:${roomId}`, roomId, titleRu: `Телевизор ${tv.inch}″`, hung: tv.hung,
      placement: { x: tv.x, y: tv.y, rot: tv.rot, wCm: tv.wCm, dCm: tv.dCm, hCm: tv.hCm, elevCm: tv.elevCm } });
  }
  return extras;
}

/** Сколько мешей грузится для комнаты — нужен для бюджета мобильной версии. */
export function meshCountByRoom(specs: ObjectSpec[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of specs) {
    if (s.kind !== "mesh") continue;
    out[s.roomId] = (out[s.roomId] ?? 0) + 1;
  }
  return out;
}
