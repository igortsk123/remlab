// T-20261111-20/2 (владелец TG 1624: «все элементы, как на плане, должны быть сделаны»). Балкон за наружной стеной комнаты приходит
// пристройкой `outdoor: true` (`tools/scout/trial_bundle.py:outdoor_of`). Мост витрины переносит флаг и сторону комнаты,
// `rooms.ts:buildRoom` рисует его плитой с ограждением (`outdoor.ts`): без стен, потолка и люстры, у стены дома ограждения нет,
// за окнами этой стены — сама сцена, а не картинка вида.
import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { room as roomSchema, type Room } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { annexes, fromDemoVariant } from "@/lib/configurator/fromDemo";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { railingBoxes, RAIL_H_CM, touchesOutdoor } from "@/lib/viewer3d/outdoor";
import { buildRoom } from "@/lib/viewer3d/rooms";

// спальня 2 тура «Этажи» (aOv8…, пересборка с балконом): ядро 345×380, балконная дверь и окно на юге, балкон 273,7×184,5 за ними
const GEO = {
  w: 345, d: 380, title: "Спальня 2",
  openings: [{ kind: "window", wall: "south", offset_cm: 127.8, width_cm: 74.5, sill_cm: 85, height_cm: 150 },
             { kind: "door", wall: "north", offset_cm: 103.4, width_cm: 106.8, swing_cm: 100, hinge: "right", is_entrance: false },
             { kind: "door", wall: "south", offset_cm: 52.7, width_cm: 75, swing_cm: 75, hinge: "left", is_entrance: false }],
  annexes: [{ x: 34.6, y: -184.5, w: 273.7, d: 184.5, outdoor: true, wall: "south", openings: [] }],
};
const CTX = { apartmentId: "trial", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;

const names = (g: THREE.Object3D): string[] => {
  const out: string[] = [];
  g.traverse((o) => { if (o.name) out.push(o.name); });
  return out;
};
const room = (): Room => roomSchema.parse({
  id: "bedroom-2", kind: "bedroom", titleRu: "Спальня 2", titleEn: "Bedroom 2", x: 0, y: 0, w: 345, d: 380,
  openings: [{ kind: "window", wall: "south", offsetCm: 127.8, widthCm: 74.5, sillCm: 85, heightCm: 150 },
             { kind: "door", wall: "south", offsetCm: 52.7, widthCm: 75 }],
  annexes: annexes(GEO),
});

describe("балкон в 3D комнаты тура", () => {
  it("мост витрины переносит флаг балкона и сторону комнаты; у обычной пристройки их нет", () => {
    const a = annexes(GEO);
    expect(a).toEqual([{ x: 34.6, y: -184.5, w: 273.7, d: 184.5, openings: [], outdoor: true, wall: "south" }]);
    expect(annexes({ annexes: [{ x: 0, y: 380, w: 100, d: 100, openings: [] }] })[0]).not.toHaveProperty("outdoor");
    const data = { rooms_geo: { "bedroom-2": GEO }, apartment_rooms: [{ id: "bedroom-2", kind: "bedroom", ordinal: 3, titleRu: "Спальня 2" }],
      variants: [{ id: "v1", style: "сканди", room_id: "bedroom-2", items: [] }] };
    const r = fromDemoVariant(data, "v1", CTX)!.apartment.rooms[0]!;
    expect(r.annexes?.[0]).toMatchObject({ outdoor: true, wall: "south", w: 273.7, d: 184.5 });
  });

  it("плита и ограждение без стен, потолка и люстры; прогулка по полу комнаты", () => {
    const { group, floor } = buildRoom(createMaterialCtx(1, false), room(), MAT, MAT);
    const n = names(group);
    expect(floor.name).toBe("floor:bedroom-2");
    expect(n).toContain("outdoor:bedroom-2~0:slab");
    expect(n).toContain("outdoor:bedroom-2~0:railing");
    expect(n.filter((x) => x.includes("bedroom-2~0") && /^(wall|ceiling|floor):/.test(x))).toEqual([]);
    // плита — за южной стеной комнаты, верх на уровне пола (сцена: x = план x, z = план y; см → м)
    const slab = group.getObjectByName("outdoor:bedroom-2~0:slab")!;
    expect(slab.position.x).toBeCloseTo((34.6 + 273.7 / 2) / 100, 5);
    expect(slab.position.z).toBeCloseTo((-184.5 / 2) / 100, 5);
    const bb = new THREE.Box3().setFromObject(slab);
    expect(bb.max.y).toBeCloseTo(0, 5);
  });

  it("ограждение по трём сторонам, высотой 1 м, не входит в стену дома", () => {
    const boxes = railingBoxes(0, -184.5, 273.7, 0, "north");
    const top = Math.max(...boxes.map((b) => b.z + b.sz / 2));
    expect(top).toBeCloseTo(RAIL_H_CM, 5);
    // ни один брус не доходит до стены дома (y = 0): стойка в стене прошла бы сквозь неё в комнату
    expect(Math.max(...boxes.map((b) => b.y + b.sy / 2))).toBeLessThan(-3);
    // поручень по южной стороне — во всю ширину; по северной (стена дома) поручня нет
    const rails = boxes.filter((b) => b.sx > 200);
    expect(rails.length).toBeGreaterThan(0);
    expect(rails.every((b) => b.y < -150)).toBe(true);
  });

  it("за окном стены, выходящей на балкон, нет картинки вида; у остальных стен она есть", () => {
    const outs = [{ x: 34.6, y: -184.5, w: 273.7, d: 184.5 }];
    const box = { x: 0, y: 0, w: 345, d: 380 };
    expect(touchesOutdoor(box, "south", outs)).toBe(true);
    expect(touchesOutdoor(box, "north", outs)).toBe(false);
    expect(touchesOutdoor(box, "west", outs)).toBe(false);
    // плита дальше толщины касания — не та стена
    expect(touchesOutdoor(box, "south", [{ ...outs[0]!, y: -200 }])).toBe(false);
    const r = room();
    const { group } = buildRoom(createMaterialCtx(1, false), { ...r, openings: [...r.openings, { kind: "window", wall: "north", offsetCm: 100, widthCm: 100, sillCm: 85, heightCm: 150 }] } as Room, MAT, MAT);
    const views = (side: string): number => {
      let k = 0;
      group.getObjectByName(`joinery:bedroom-2:${side}`)!.traverse((o) => { if (/backdrop|view/i.test(o.name)) k++; });
      return k;
    };
    expect(views("south")).toBe(0);
    expect(views("north")).toBeGreaterThan(0);
  });
});
