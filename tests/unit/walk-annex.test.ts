// T-20261112-36 (владелец TG 1737, 1791): закуток комнаты (пристройка за порталом-стыком) проходим, как вся комната; цель касания —
// ближайшее по лучу с приоритетом окно > предмет > пол. Данные — спальня 1 и гостиная тура «Этажи» (aOv8…), как на странице.
import { describe, expect, it } from "vitest";

import { room as roomSchema, type Apartment } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { buildRoom } from "@/lib/viewer3d/rooms";
import { canStand, walkArea, walkRoomAt, walkRooms } from "@/lib/viewer3d/walk";
import { chooseAim } from "@/lib/viewer3d/walk-aim";
import { planRoute } from "@/lib/viewer3d/walk-motion";

// спальня 1: ядро 330×390, портал 150 см на севере в тамбур 170×130 (три закрытые двери: коридор, ванная, гардеробная)
const BED1 = {
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
// гостиная: ядро 335×380, портал 255 см на севере в хвост 255×265 (дверь в коридор на западе)
const LIVING = {
  w: 335, d: 380, title: "Гостиная",
  openings: [{ kind: "window", wall: "south", offset_cm: 41.4, width_cm: 174, sill_cm: 85, height_cm: 150 },
             { kind: "opening", wall: "north", offset_cm: 80, width_cm: 255 }],
  annexes: [{ x: 80, y: 380, w: 255, d: 265, openings: [
    { kind: "opening", wall: "south", offset_cm: 0, width_cm: 255 },
    { kind: "door", wall: "west", offset_cm: 0, width_cm: 156.8, swing_cm: 78, hinge: "left", is_entrance: false },
  ] }],
};
const CTX = { apartmentId: "trial", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };

function flat(geo: typeof BED1 | typeof LIVING, id = "bedroom-1"): Apartment {
  const data = { rooms_geo: { [id]: geo }, apartment_rooms: [{ id, kind: id.startsWith("bed") ? "bedroom" : "living", ordinal: 1, titleRu: geo.title }],
    variants: [{ id: "v1", style: "сканди", room_id: id, items: [] }] };
  return fromDemoVariant(data, "v1", CTX)!.apartment;
}

describe("закуток комнаты проходим (T-20261112-36)", () => {
  it("зона прогулки — комната и пристройка; двери пристройки закрыты, балкон — не пол комнаты", () => {
    const a = flat(BED1);
    const rooms = walkRooms(a);
    expect(rooms.map((r) => r.id)).toEqual([a.rooms[0]!.id, `${a.rooms[0]!.id}~0`]);
    const sub = rooms[1]!;
    expect([sub.x - a.rooms[0]!.x, sub.y - a.rooms[0]!.y, sub.w, sub.d]).toEqual([180, 390, 170, 130]);
    expect(sub.openings.map((o) => o.kind)).toEqual(["opening"]);
    const withBalcony: Apartment = { ...a, rooms: [{ ...a.rooms[0]!, annexes: [...a.rooms[0]!.annexes!, { x: 0, y: -150, w: 330, d: 150, openings: [], outdoor: true, wall: "south" }] }] };
    expect(walkRooms(withBalcony)).toHaveLength(2);
  });

  it("спальня 1: в тамбур можно встать и дойти от окна; было — нельзя", () => {
    const a = flat(BED1);
    const r = a.rooms[0]!;
    const nook = { x: r.x + 265, y: r.y + 455 };           // середина тамбура
    const area = walkArea(a);
    expect(canStand(area, nook.x, nook.y)).toBe(true);
    expect(canStand({ ...area, rooms: a.rooms, passages: [] }, nook.x, nook.y), "прежняя зона — только ядро").toBe(false);
    const from = { x: r.x + 140, y: r.y + 120 };            // у окна
    const route = planRoute(area, from, nook)!;
    expect(route.at(-1)).toEqual(nook);
    // за закрытой дверью тамбура (север) — не пройти
    expect(canStand(area, r.x + 265, r.y + 540)).toBe(false);
    // в закутке «где я» — та же спальня
    expect(walkRoomAt(a, nook.x, nook.y)).toBe(r.id);
    expect(walkRoomAt(a, r.x + 265, r.y + 600)).toBeNull();
  });

  it("гостиная: весь хвост за порталом достижим, с мебелью у портала — в обход", () => {
    const a = flat(LIVING, "living");
    const r = a.rooms[0]!;
    const sofa = { x: r.x + 120, y: r.y + 330, w: 200, d: 90, rot: 0, h: 85 };   // диван у портала, частично перекрыл проход
    const area = walkArea(a, 28, [sofa]);
    const from = { x: r.x + 160, y: r.y + 100 };
    for (const p of [{ x: 130, y: 430 }, { x: 290, y: 600 }, { x: 200, y: 520 }]) {
      const t = { x: r.x + p.x, y: r.y + p.y };
      expect(canStand(area, t.x, t.y), `${p.x},${p.y}`).toBe(true);
      expect(planRoute(area, from, t)!.at(-1), `${p.x},${p.y}`).toEqual(t);
    }
  });

  it("пол пристройки — пол прогулки: `buildRoom.floors` — оба пола", () => {
    const r = roomSchema.parse({ ...flat(BED1).rooms[0]!, x: 0, y: 0 });
    const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;
    const { floor, floors } = buildRoom(createMaterialCtx(1, false), r, MAT, MAT);
    expect(floors.map((f) => f.name)).toEqual([floor.name, `floor:${r.id}~0`]);
  });
});

describe("цель касания и кольца — ближайшее по лучу (T-20261112-36)", () => {
  it("видно под курсором — то и цель", () => {
    expect(chooseAim({})).toBe("none");
    expect(chooseAim({ floor: 3 })).toBe("floor");
    expect(chooseAim({ item: 2, floor: 3 })).toBe("item");               // диван перед полом
    expect(chooseAim({ item: 2, window: 4 })).toBe("item");              // диван под окном — выбор дивана, не «к окну»
    expect(chooseAim({ window: 3, floor: 5 })).toBe("window");
    expect(chooseAim({ block: 2, floor: 4 })).toBe("none");              // пол закутка за стеной — не цель
    expect(chooseAim({ block: 2, item: 4 })).toBe("none");
    expect(chooseAim({ block: 4, floor: 3 })).toBe("floor");
  });

  it("в одном месте: окно > предмет (и картина-товар) > пол", () => {
    expect(chooseAim({ window: 3, item: 3.01 })).toBe("window");         // штора, растение вплотную к стеклу
    expect(chooseAim({ item: 3, floor: 3.005 })).toBe("item");           // предмет у самого пола
    expect(chooseAim({ window: 3, item: 3, floor: 3 })).toBe("window");
    expect(chooseAim({ item: 3, block: 3.01 })).toBe("item");            // картина на стене (плоскость в 1 см от стены)
  });
});
