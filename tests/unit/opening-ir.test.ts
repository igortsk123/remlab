import { describe, expect, it } from "vitest";
import * as THREE from "three";

import type { Room } from "@/contracts/apartment";
import { openings as demoOpenings } from "@/lib/configurator/fromDemo";
import { openingIR } from "@/lib/viewer3d/opening-ir";
import { joineryOf, wallRects } from "@/lib/viewer3d/rooms";
import golden from "@/tests/fixtures/opening-golden.json";

// ОДНО ОПИСАНИЕ ПРОЁМА — ОДНО МЕСТО В КОМНАТЕ (план demo-04). Эталон считает СЕРВЕРНЫЙ код (`tools/scout/opening_ir.py`)
// из описания, которое строит `opening-ir.ts`; здесь те же проёмы собираются браузерным путём — данные витрины →
// `fromDemo.openings` → `rooms.ts:joineryOf` (зеркало north/west, сторона петель) → меши three.js. Тест упал — окно или дверь
// на серверном кадре стоят не там, где в 3D. Эталон пересобирается: ~/venvs/scout/bin/python tools/assets/opening_golden.py

type GoldenBox = { role: string; min: number[]; max: number[] };
type GoldenOpening = { wall: string; kind: string; cut: { u0: number; u1: number; bottom: number; top: number }; boxes: GoldenBox[] };
type GoldenCase = {
  name: string;
  open: boolean;
  room: { w: number; d: number; height_cm: number; openings: Parameters<typeof demoOpenings>[0]["openings"] };
  openings: GoldenOpening[];
};

const CM = 0.01;
const SIDES = ["south", "north", "west", "east"] as const;

function roomOf(c: GoldenCase): Room {
  return {
    id: "t", kind: "living", titleRu: "т", titleEn: "t", x: 0, y: 0, w: c.room.w, d: c.room.d, heightCm: c.room.height_cm,
    openings: demoOpenings(c.room),
  } as unknown as Room;
}

/** Габариты деталей браузера, см, в осях сервера (x, высота, y плана): по стене — список проёмов, в проёме — по номеру коробки. */
function browserBoxes(room: Room, open: boolean): Map<string, { min: number[]; max: number[] }[][]> {
  const out = new Map<string, { min: number[]; max: number[] }[][]>();
  for (const side of SIDES) {
    const j = joineryOf(room, side, { doorsClosed: !open });
    if (!j) continue;
    j.updateMatrixWorld(true);
    const per = j.children.map((og) => {
      const list: { min: number[]; max: number[] }[] = [];
      og.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        const b = new THREE.Box3().setFromObject(o);
        list[o.userData.irIndex as number] = { min: b.min.toArray().map((v) => v / CM), max: b.max.toArray().map((v) => v / CM) };
      });
      return list;
    });
    out.set(side, per);
  }
  return out;
}

describe("проём: браузер ставит детали туда же, где их рисует серверный кадр", () => {
  for (const c of (golden as { cases: GoldenCase[] }).cases) {
    it(`${c.name}: каждая деталь совпадает с эталоном (допуск 0,01 см)`, () => {
      const got = browserBoxes(roomOf(c), c.open);
      const seen = new Map<string, number>();
      for (const g of c.openings) {
        const k = seen.get(g.wall) ?? 0;
        seen.set(g.wall, k + 1);
        const boxes = got.get(g.wall)?.[k];
        expect(boxes, `${g.wall} #${k}`).toBeDefined();
        expect(boxes!.length).toBe(g.boxes.length);
        g.boxes.forEach((want, i) => {
          const b = boxes![i]!;
          for (let a = 0; a < 3; a++) {
            expect(Math.abs(b.min[a]! - want.min[a]!), `${g.wall} ${g.kind} ${want.role}#${i} min[${a}]`).toBeLessThan(0.01);
            expect(Math.abs(b.max[a]! - want.max[a]!), `${g.wall} ${g.kind} ${want.role}#${i} max[${a}]`).toBeLessThan(0.01);
          }
        });
      }
    });
  }
});

describe("описание проёма", () => {
  const H = { wallHeightCm: 270 };

  it("вырез стены — из того же описания, что рама: стена браузера оставляет ровно `cut`", () => {
    const o = { kind: "window" as const, wall: "south" as const, offsetCm: 50, widthCm: 120, sillCm: 85, heightCm: 140 };
    const { cut } = openingIR(o, H);
    expect(cut).toEqual({ u0: 50, u1: 170, bottom: 85, top: 225 });
    const rects = wallRects(400, 270, [o]);
    expect(rects).toContainEqual({ u0: 50, u1: 170, v0: 0, v1: 85 });
    expect(rects).toContainEqual({ u0: 50, u1: 170, v0: 225, v1: 270 });
  });

  it("балкон — до пола, без подоконника; портал — без полотна", () => {
    const b = openingIR({ kind: "balcony", wall: "west", offsetCm: 0, widthCm: 90 }, H);
    expect(b.cut.bottom).toBe(0);
    expect(b.cut.top).toBe(220);
    expect(b.boxes.some((x) => x.role === "sill")).toBe(false);
    const p = openingIR({ kind: "opening", wall: "east", offsetCm: 0, widthCm: 100 }, H);
    expect(p.boxes.every((x) => x.role === "casing")).toBe(true);
  });

  it("распахнутая дверь уходит в комнату у своей петли; наружу — за стену; закрытая — в плоскости стены", () => {
    const leafTipZ = (o: Parameters<typeof openingIR>[0], entrance = false) => {
      const ir = openingIR(o, { ...H, entrance });
      const g = ir.groups.leaf!;
      const leafW = ir.boxes.find((x) => x.role === "leaf")!.w;
      const r = (g.rotYDeg * Math.PI) / 180;
      return { x: g.x + Math.cos(r) * leafW, z: g.z - Math.sin(r) * leafW };
    };
    const base = { kind: "door" as const, wall: "south" as const, offsetCm: 100, widthCm: 90 };
    const inLeft = leafTipZ(base);
    expect(inLeft.z).toBeGreaterThan(70);
    expect(inLeft.x).toBeLessThan(110);
    const inRight = leafTipZ({ ...base, hinge: "right" });
    expect(inRight.z).toBeGreaterThan(70);
    expect(inRight.x).toBeGreaterThan(180);
    expect(leafTipZ({ ...base, swingCm: 0 }).z).toBeLessThan(-70);
    expect(Math.abs(leafTipZ(base, true).z)).toBeLessThan(0.01);
  });
});
