import { readFileSync } from "node:fs";
import path from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { floorplanResult } from "@/contracts/trial";
import { buildGreyScene, fitView, inside, labelPoint, polyArea, roomView } from "@/lib/trial/grey-scene";

// Серый тур пробы (agent-trial-01, T-C): сцена из фикстуры результата (план D, два этажа) без WebGL — полы по `contour`,
// стены полосами, флаги → штриховка, подписи внутри комнат, камеры «3D» / «сверху» / к комнате.
const A = floorplanResult.parse(JSON.parse(readFileSync(path.join(process.cwd(), "tests/fixtures/trial-result-A.json"), "utf8")));
const ground = A.panels[0]!;

describe("фикстура trial-result-A", () => {
  it("проходит схему результата и похожа на квартиру D: два этажа, комнаты с флагами и без", () => {
    expect(A.panels.map((p) => p.title)).toEqual(["Ground Floor", "First Floor"]);
    const rooms = A.panels.flatMap((p) => p.rooms);
    expect(rooms.length).toBeGreaterThanOrEqual(8);
    expect(rooms.some((r) => r.flags.length > 0)).toBe(true);
    expect(rooms.some((r) => r.flags.length === 0 && r.dims)).toBe(true);
  });
});

describe("buildGreyScene", () => {
  const hatch = new THREE.Texture();
  const gs = buildGreyScene(ground, { hatch });

  it("пол — по одному мешу на комнату, площадь меша = площадь контура (см² → м²)", () => {
    expect(gs.floors.size).toBe(ground.rooms.length);
    for (const r of ground.rooms) {
      const g = gs.floors.get(r.id)!.geometry;
      const pos = g.getAttribute("position");
      const idx = g.getIndex()!;
      let area = 0;
      const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
      for (let i = 0; i < idx.count; i += 3) {
        a.fromBufferAttribute(pos, idx.getX(i)); b.fromBufferAttribute(pos, idx.getX(i + 1)); c.fromBufferAttribute(pos, idx.getX(i + 2));
        area += new THREE.Triangle(a, b, c).getArea();
      }
      expect(area).toBeCloseTo(polyArea(r.contour) / 1e4, 2);
    }
  });

  it("план y (вниз по листу) → сцена Z без переворота; пол на 5 мм над нулём", () => {
    const r = ground.rooms[0]!;
    const bb = new THREE.Box3().setFromObject(gs.floors.get(r.id)!);
    expect(bb.min.x).toBeCloseTo(r.bbox.x / 100, 3);
    expect(bb.min.z).toBeCloseTo(r.bbox.y / 100, 3);
    expect(bb.max.z).toBeCloseTo((r.bbox.y + r.bbox.d) / 100, 3);
    expect(bb.min.y).toBeCloseTo(0.005, 4);
  });

  it("стены — меш на каждый многоугольник полосы, высота полосы z0…z1", () => {
    const polys = ground.walls.reduce((n, w) => n + w.polys.length, 0);
    expect(gs.walls.length).toBe(polys);
    const top = ground.walls.find((w) => w.z0 > 0)!;
    const i = ground.walls.indexOf(top);
    const first = ground.walls.slice(0, i).reduce((n, w) => n + w.polys.length, 0);
    const bb = new THREE.Box3().setFromObject(gs.walls[first]!);
    expect(bb.min.y).toBeCloseTo(top.z0 / 100, 3);
    expect(bb.max.y).toBeCloseTo(top.z1 / 100, 3);
  });

  it("комнаты с флагами — штриховка (map), без флагов — гладкий пол; подсветка и снятие", () => {
    const flagged = ground.rooms.find((r) => r.flags.length)!;
    const plain = ground.rooms.find((r) => !r.flags.length)!;
    const mat = (id: string) => gs.floors.get(id)!.material as THREE.MeshStandardMaterial;
    expect(mat(flagged.id).map).toBe(hatch);
    expect(mat(plain.id).map).toBeNull();
    expect(gs.rooms.find((r) => r.id === flagged.id)!.flagged).toBe(true);
    const before = mat(plain.id);
    gs.highlight(plain.id);
    expect(mat(plain.id)).not.toBe(before);
    expect(mat(flagged.id).map).toBe(hatch);
    gs.highlight(null);
    expect(mat(plain.id)).toBe(before);
  });

  it("подпись каждой комнаты — внутри её контура (и у Г-образных)", () => {
    for (const r of A.panels.flatMap((p) => p.rooms)) {
      const [x, y] = labelPoint(r.contour);
      expect(inside(r.contour, x, y)).toBe(true);
    }
    const L: [number, number][] = [[0, 0], [400, 0], [400, 100], [100, 100], [100, 400], [0, 400]];
    const [x, y] = labelPoint(L);
    expect(inside(L, x, y)).toBe(true);
  });

  it("сверху — камера над центром; 3D — наискосок с нижнего края листа; к комнате — ближе, чем весь лист", () => {
    const top = fitView(gs.center, gs.size.x, gs.size.z, 1.5, "top");
    expect(top.position.x).toBeCloseTo(gs.center.x, 3);
    expect(top.position.y).toBeGreaterThan(5);
    const ob = fitView(gs.center, gs.size.x, gs.size.z, 1.5, "oblique");
    expect(ob.position.z).toBeGreaterThan(gs.center.z);
    expect(ob.position.x).toBeLessThan(gs.center.x);
    const r = gs.rooms[0]!;
    const rv = roomView(r, 1.5);
    expect(rv.target.x).toBeCloseTo(r.center.x, 3);
    expect(rv.position.distanceTo(rv.target)).toBeLessThan(ob.position.distanceTo(ob.target));
  });

  it("пустой лист не падает: рамка по умолчанию", () => {
    const empty = buildGreyScene({ id: "e", title: "", rooms: [], walls: [], openings: [] });
    expect(empty.size.x).toBeGreaterThan(0);
    empty.dispose();
  });
});
