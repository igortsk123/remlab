import { describe, expect, it } from "vitest";
import * as THREE from "three";

import type { Room } from "@/contracts/apartment";
import { buildRadiators, RADIATOR_RULES, radiatorSpots, radiatorsFromUrl } from "@/lib/viewer3d/kits/radiator";

const room = (openings: Room["openings"]): Room =>
  ({ id: "r1", name: "Комната", x: 0, y: 0, w: 400, d: 300, heightCm: 270, openings } as unknown as Room);
const win = (wall: string, offsetCm: number, widthCm: number, extra: object = {}) =>
  ({ kind: "window", wall, offsetCm, widthCm, ...extra }) as unknown as Room["openings"][number];

describe("radiator (T-20261117-11)", () => {
  it("ширина — от окна в пределах правил, место — по центру окна", () => {
    const [s] = radiatorSpots([room([win("south", 100, 150)])]);
    expect(s!.widthCm).toBe(Math.round(150 * RADIATOR_RULES.size.widthOfWindow));
    expect(s!.xCm).toBe(175);
    expect(s!.zCm).toBe(0);
    expect([s!.nx, s!.nz]).toEqual([0, 1]);
    const [wide] = radiatorSpots([room([win("south", 0, 400)])]);
    expect(wide!.widthCm).toBe(RADIATOR_RULES.size.maxWidthCm);
  });

  it("балкон, узкое окно и высокий подоконник-ограничение — без радиатора", () => {
    const rooms = [room([
      { kind: "balcony", wall: "north", offsetCm: 50, widthCm: 150 } as unknown as Room["openings"][number],
      win("west", 20, RADIATOR_RULES.size.minWidthCm - 1),
      win("east", 20, 120, { sillCm: 40 }),
    ])];
    expect(radiatorSpots(rooms)).toEqual([]);
  });

  it("группа стоит спиной к стене с отступом и лицом в комнату; ничего не перехватывает", () => {
    const g = buildRadiators([room([win("south", 100, 150)])]);
    expect(g.children).toHaveLength(1);
    const r = g.children[0]!;
    const back = 1 + RADIATOR_RULES.offset.fromWallCm + RADIATOR_RULES.size.depthCm / 2;
    expect(r.position.z).toBeCloseTo(back * 0.01, 5);
    const box = new THREE.Box3().setFromObject(r);
    expect(box.min.y).toBeCloseTo(0, 2);
    expect(box.max.y).toBeLessThan((RADIATOR_RULES.offset.fromFloorCm + RADIATOR_RULES.size.heightCm + 1) * 0.01);
    let hits = 0;
    r.traverse((o) => { if ((o as THREE.Mesh).isMesh) hits += new THREE.Raycaster(new THREE.Vector3(1.75, 1, 1), new THREE.Vector3(0, -1, 0)).intersectObject(o).length; });
    expect(hits).toBe(0);
  });

  it("флаг в адресе", () => {
    expect(radiatorsFromUrl("?radiators=0")).toBe(false);
    expect(radiatorsFromUrl("?a=1&radiators=1")).toBe(true);
    expect(radiatorsFromUrl("")).toBeUndefined();
  });
});
