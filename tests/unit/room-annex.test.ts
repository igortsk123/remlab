// T-20261111-08 (владелец TG 1006: «когда 3D план делаешь — двери не вставляешь»). Комната тура — прямоугольник-ядро; остаток контура
// за порталом-стыком (тамбур спальни 1 «Этажей» с дверями в коридор, ванную и гардеробную) приходит пристройкой `annexes`
// (`tools/scout/trial_room.py:annexes`). Мост витрины переносит её в комнату квартиры, `rooms.ts:buildRoom` строит её коробку:
// пол, стены с вырезами, закрытые полотна дверей. Без неё за порталом была улица, а дверей не было вовсе.
import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { room as roomSchema, type Room } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { annexes, fromDemoVariant } from "@/lib/configurator/fromDemo";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { buildRoom } from "@/lib/viewer3d/rooms";

// спальня 1 тура «Этажи» (aOv8…, данные страницы после пересборки): ядро 330×390, портал в тамбур 170×130 на севере
const GEO = {
  w: 330, d: 390, title: "Спальня 1 14.9 м²",
  openings: [{ kind: "window", wall: "south", offset_cm: 65.6, width_cm: 149.5, sill_cm: 85, height_cm: 150 },
             { kind: "opening", wall: "north", offset_cm: 180, width_cm: 150 }],
  annexes: [{ x: 180, y: 390, w: 170, d: 130, openings: [
    { kind: "opening", wall: "south", offset_cm: 0, width_cm: 150 },
    { kind: "door", wall: "east", offset_cm: 12.2, width_cm: 100.2, swing_cm: 100, hinge: "left", is_entrance: false },
    { kind: "door", wall: "west", offset_cm: 23.8, width_cm: 77.5, swing_cm: 78, hinge: "left", is_entrance: false },
    { kind: "door", wall: "north", offset_cm: 5.3, width_cm: 156.2, swing_cm: 78, hinge: "left", is_entrance: false },
  ] }],
};
const CTX = { apartmentId: "trial", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;

const names = (g: THREE.Object3D): string[] => {
  const out: string[] = [];
  g.traverse((o) => { if (o.name) out.push(o.name); });
  return out;
};

describe("пристройка комнаты тура (остаток контура за порталом)", () => {
  it("мост витрины переносит пристройку с проёмами; кривая (без размера) отбрасывается", () => {
    expect(annexes({ annexes: [{ x: 0, y: 0, w: 0, d: 10 }, { y: 0, w: 10, d: 10 }] })).toEqual([]);
    const a = annexes(GEO);
    expect(a).toHaveLength(1);
    expect(a[0]!.openings.map((o) => [o.kind, o.wall])).toEqual([["opening", "south"], ["door", "east"], ["door", "west"], ["door", "north"]]);
    const data = { rooms_geo: { "bedroom-1": GEO }, apartment_rooms: [{ id: "bedroom-1", kind: "bedroom", ordinal: 2, titleRu: "Спальня 1" }],
      variants: [{ id: "v1", style: "сканди", room_id: "bedroom-1", items: [] }] };
    const r = fromDemoVariant(data, "v1", CTX)!.apartment.rooms[0]!;
    expect(r.annexes?.[0]).toMatchObject({ x: 180, y: 390, w: 170, d: 130 });
    expect(r.annexes?.[0]!.openings.filter((o) => o.kind === "door")).toHaveLength(3);
    // без пристроек — поля нет (витрина /demo и прежние туры не меняются)
    const plain = fromDemoVariant({ ...data, rooms_geo: { "bedroom-1": { ...GEO, annexes: undefined } } }, "v1", CTX)!.apartment.rooms[0]!;
    expect(plain.annexes).toBeUndefined();
  });

  it("коробка пристройки: свой пол, стены и потолок за порталом, двери с полотнами, люстры нет", () => {
    const r: Room = roomSchema.parse({ id: "bedroom-1", kind: "bedroom", titleRu: "Спальня 1", titleEn: "Bedroom 1", x: 0, y: 0, w: 330, d: 390,
      openings: [{ kind: "opening", wall: "north", offsetCm: 180, widthCm: 150 }],
      annexes: [{ x: 180, y: 390, w: 170, d: 130, openings: annexes(GEO)[0]!.openings }] });
    const { group, floor } = buildRoom(createMaterialCtx(1, false), r, MAT, MAT);
    const n = names(group);
    expect(floor.name).toBe("floor:bedroom-1");                     // пол ядра; пол прогулки — и пристройки (`floors`, T-36)
    expect(n).toContain("floor:bedroom-1~0");
    expect(n).toContain("ceiling:bedroom-1~0");                     // прячется в виде сверху вместе с потолком комнаты
    expect(n).not.toContain("ceiling:bedroom-1~0:lamp");
    for (const side of ["north", "east", "west", "south"]) expect(n).toContain(`wall:bedroom-1~0:${side}`);
    // пол пристройки — за северной стеной комнаты (сцена: x = план x, z = план y; см → м)
    const f = group.getObjectByName("floor:bedroom-1~0")!;
    expect(f.position.x).toBeCloseTo(2.65, 5);
    expect(f.position.z).toBeCloseTo(4.55, 5);
    // три двери пристройки — с полотнами (закрыты: ведут в комнаты, которых в сцене нет)
    const leaves: string[] = [];
    group.traverse((o) => { if (/^joinery:bedroom-1~0:(east|west|north)$/.test(o.name)) leaves.push(o.name); });
    expect(leaves.sort()).toEqual(["joinery:bedroom-1~0:east", "joinery:bedroom-1~0:north", "joinery:bedroom-1~0:west"]);
    for (const nm of leaves) {
      let leaf = 0;
      group.getObjectByName(nm)!.traverse((o) => { if (o.userData.part === "leaf") leaf++; });
      expect(leaf, nm).toBeGreaterThan(0);
    }
  });

  it("стык комнаты с пристройкой (`junction`) — без перемычки и наличника; обычный портал — как был (T-20261112-41)", () => {
    // кухня-гостиная «Этажей»: ядро 335×380, хвост 255×265 за стыком 80…335 на севере; перемычка 205…310 над стыком делила её на две
    const geo = { w: 335, d: 380, openings: [{ kind: "opening", wall: "north", offset_cm: 80, width_cm: 255, junction: true },
                                             { kind: "opening", wall: "east", offset_cm: 100, width_cm: 90 }] };
    const ops = fromDemoVariant({ rooms_geo: { living: geo }, variants: [{ id: "v1", style: "сканди", items: [] }] }, "v1", CTX)!
      .apartment.rooms[0]!.openings;
    expect(ops.map((o) => !!o.junction)).toEqual([true, false]);
    const r: Room = roomSchema.parse({ id: "living", kind: "living", titleRu: "Кухня-гостиная", titleEn: "Kitchen-living", x: 0, y: 0,
      w: 335, d: 380, heightCm: 310, openings: ops });
    const { group } = buildRoom(createMaterialCtx(1, false), r, MAT, MAT);
    const above = (side: string): number => {
      let n = 0;
      group.traverse((o) => { if (o.name === `wall:living:${side}` && o.position.y > 2.06) n++; });
      return n;
    };
    expect(above("north")).toBe(0);                                  // над стыком стены нет
    expect(above("east")).toBe(1);                                   // над обычным порталом — перемычка
    const casing = (side: string): number => {
      let n = 0;
      group.getObjectByName(`joinery:living:${side}`)?.traverse((o) => { if (o.userData.part === "casing") n++; });
      return n;
    };
    expect(casing("north")).toBe(0);
    expect(casing("east")).toBe(3);
  });
});
