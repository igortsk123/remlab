// Раскладка разрешённой конфигурации на объекты сцены — ЧИСТАЯ функция (без three.js),
// поэтому её гоняет vitest: именно здесь живёт склейка «кухня = корпус + техника + столешница
// + фартук», из-за которой раньше всего легче всего разъехаться 3D и фото.

import type { Apartment, Placement } from "@/contracts/apartment";
import { findRoom } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import type { ResolvedScene, ResolvedSurface } from "@/lib/configurator/resolve";
import { meshUrl } from "@/lib/configurator/data";

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
      kind: "bed" | "wardrobe";
      slotId: string;
      roomId: string;
      titleRu: string;
      placement: Placement;
      level: "base" | "practical" | "comfort" | "premium";
      features: string[];
      materialId?: string;
    };

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
export function planObjects(a: Apartment, _c: Catalogue, scene: ResolvedScene): ObjectSpec[] {
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
        url: meshUrl(asset.meshId, asset.runtimeUrl),
        yawDeg: asset.yawDeg,
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
      kind: asset.kit === "bed" ? "bed" : "wardrobe",
      slotId: item.slotId,
      roomId: item.roomId,
      titleRu: item.titleRu,
      placement: item.placement,
      level: asset.level,
      features: [...asset.features],
      materialId: asset.materials.body ?? asset.materials.door,
    });
  }
  return out;
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
