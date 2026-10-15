import { describe, expect, it } from "vitest";
import * as THREE from "three";

import type { Room } from "@/contracts/apartment";
import { openings as demoOpenings } from "@/lib/configurator/fromDemo";
import { openingIR, viewRooms, wallRects as irWallRects } from "@/lib/viewer3d/opening-ir";
import { ceilingLampIR, wallFixturesIR } from "@/lib/viewer3d/fixtures-ir";
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

describe("вид из окна (demo-04 п.5)", () => {
  const view = { assetId: "yard", horizon01: 0.35, aspect: 1600 / 1072 };
  const win = { kind: "window" as const, wall: "west" as const, offsetCm: 105, widthCm: 150, sillCm: 85, heightCm: 150 };

  it("плоскость вида перекрывает вырез с запасом, не выходит за конец стены и середину простенка", () => {
    const ir = openingIR(win, { wallHeightCm: 270, view, viewRoomLo: 105, viewRoomHi: 20 });
    const bd = ir.backdrop!;
    expect(bd.assetId).toBe("yard");
    expect(bd.u0).toBeLessThan(ir.cut.u0);
    expect(bd.u1).toBeCloseTo(ir.cut.u1 + 20, 3); // справа — только до середины простенка
    expect(bd.bottom).toBeLessThan(ir.cut.bottom);
    expect(bd.top).toBeGreaterThan(ir.cut.top);
    for (const k of ["u0", "u1", "v0", "v1"] as const) {
      expect(bd.uv[k]).toBeGreaterThanOrEqual(0);
      expect(bd.uv[k]).toBeLessThanOrEqual(1);
    }
  });

  it("горизонт картинки — на уровне глаз 155 см", () => {
    const bd = openingIR(win, { wallHeightCm: 270, view }).backdrop!;
    // высота точки картинки с v = 1 − horizon01 (горизонт): по линейной развёртке uv → высота плоскости
    const vH = 1 - view.horizon01;
    const y = bd.bottom + ((vH - bd.uv.v0) / (bd.uv.v1 - bd.uv.v0)) * (bd.top - bd.bottom);
    expect(y).toBeCloseTo(155, 1);
  });

  it("у двери и портала вида нет; без вида в опциях — нет плоскости", () => {
    expect(openingIR({ kind: "door", wall: "east", offsetCm: 0, widthCm: 90 }, { wallHeightCm: 270, view }).backdrop).toBeUndefined();
    expect(openingIR(win, { wallHeightCm: 270 }).backdrop).toBeUndefined();
  });

  it("места для вида: до концов стены и середины простенка между окнами", () => {
    const r = viewRooms([{ offsetCm: 50, widthCm: 100 }, { offsetCm: 250, widthCm: 100 }], 400);
    expect(r[0]).toEqual({ lo: 50, hi: 50 });
    expect(r[1]).toEqual({ lo: 50, hi: 50 });
  });
});

describe("обжитая коробка (demo-04 п.6)", () => {
  it("плинтус идёт по низу кусков стены и прерывается у двери; карниз — над окном, шире его", () => {
    const door = { kind: "door" as const, wall: "south" as const, offsetCm: 100, widthCm: 90 };
    const win = { kind: "window" as const, wall: "south" as const, offsetCm: 250, widthCm: 120, sillCm: 85, heightCm: 140 };
    const rects = irWallRects(400, 270, [door, win]);
    const cut = openingIR(win, { wallHeightCm: 270 }).cut;
    const boxes = wallFixturesIR(rects, [cut], 270);
    const sk = boxes.filter((b) => b.role === "skirting");
    // куски с низом: до двери, между дверью и окном, под окном, после окна — у двери плинтуса нет
    expect(sk.length).toBe(4);
    expect(sk.every((b) => b.x + b.w / 2 <= 100 + 0.01 || b.x - b.w / 2 >= 190 - 0.01)).toBe(true);
    const rod = boxes.find((b) => b.role === "cornice" && b.w > 50)!;
    expect(rod.w).toBeGreaterThan(cut.u1 - cut.u0);
    expect(rod.y).toBeGreaterThan(cut.top);
    expect(rod.y).toBeLessThan(270);
  });
  it("светильник — по центру комнаты у потолка", () => {
    const [lamp] = ceilingLampIR(439, 325, 270);
    expect(lamp!.x).toBeCloseTo(219.5, 3);
    expect(lamp!.z).toBeCloseTo(162.5, 3);
    expect(lamp!.y + lamp!.h / 2).toBeLessThanOrEqual(270);
  });
});
