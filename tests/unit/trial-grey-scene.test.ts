import { readFileSync } from "node:fs";
import path from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { floorplanResult } from "@/contracts/trial";
import { DIRS, dirsFor, frameView, MARGIN, pickTurn, roomBox } from "@/lib/trial/grey-camera";
import { buildGreyScene, CUT_H } from "@/lib/trial/grey-scene";
import { inside, labelPoint, polyArea } from "@/lib/trial/plan-geom";

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

  /** Экранные координаты (-1…1) углов рамки при этой камере — как в браузере. */
  const ndc = (v: { position: THREE.Vector3; target: THREE.Vector3 }, box: THREE.Box3, aspect: number) => {
    const cam = new THREE.PerspectiveCamera(35, aspect, 0.05, 400);
    cam.position.copy(v.position);
    cam.lookAt(v.target);
    cam.updateMatrixWorld();
    const out: THREE.Vector3[] = [];
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
      out.push(new THREE.Vector3(x, y, z).project(cam));
    }
    return out;
  };

  it("обзор вписан по рамке модели: все углы в кадре с отступом ~8 %, край — у отступа (модель не «полхолста»)", () => {
    for (const aspect of [16 / 10.5, 0.85]) {
      for (const mode of ["oblique", "top"] as const) {
        const v = frameView(gs.bounds, DIRS[mode], aspect);
        const pts = ndc(v, gs.bounds, aspect);
        const lim = 1 - 2 * MARGIN + 1e-3;
        for (const p of pts) { expect(Math.abs(p.x)).toBeLessThanOrEqual(lim); expect(Math.abs(p.y)).toBeLessThanOrEqual(lim); }
        // хотя бы по одной оси рамка доходит до отступа — модель вписана плотно
        const spanX = Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x));
        const spanY = Math.max(...pts.map((p) => p.y)) - Math.min(...pts.map((p) => p.y));
        expect(Math.max(spanX, spanY)).toBeGreaterThan(2 * (1 - 2 * MARGIN) - 0.02);
      }
    }
    const top = frameView(gs.bounds, DIRS.top, 1.5);
    expect(top.position.y).toBeGreaterThan(5);
    const ob = frameView(gs.bounds, DIRS.oblique, 1.5);
    expect(ob.position.z).toBeGreaterThan(gs.center.z);
    expect(ob.position.x).toBeLessThan(gs.center.x);
  });

  it("поворот «3D»: длинный план на широком холсте — сбоку, на телефоне — с нижнего края; точки модели в кадре", () => {
    expect(gs.size.z).toBeGreaterThan(gs.size.x * 1.3); // фикстура — вытянутый вглубь лист
    const wide = pickTurn(gs.points, 16 / 10.5);
    expect(wide).not.toBe(0);
    expect(pickTurn(gs.points, 0.85)).toBe(0);
    const v = frameView(gs.points, dirsFor(wide).oblique, 16 / 10.5);
    const bb = new THREE.Box3().setFromPoints(gs.points);
    const cam = new THREE.PerspectiveCamera(35, 16 / 10.5, 0.05, 400);
    cam.position.copy(v.position); cam.lookAt(v.target); cam.updateMatrixWorld();
    const pts = gs.points.map((p) => p.clone().project(cam));
    for (const p of pts) { expect(Math.abs(p.x)).toBeLessThanOrEqual(1 - 2 * MARGIN + 1e-3); expect(Math.abs(p.y)).toBeLessThanOrEqual(1 - 2 * MARGIN + 1e-3); }
    // вписан плотнее, чем по рамке с нижнего края
    const base = frameView(bb, DIRS.oblique, 16 / 10.5);
    expect(v.position.distanceTo(v.target)).toBeLessThan(base.position.distanceTo(base.target) * 0.85);
  });

  it("срез — со стороны камеры при повороте", () => {
    const r = gs.rooms.find((x) => x.name === "Lounge")!;
    gs.cutaway(r, dirsFor(1).toward);
    const mat = gs.walls[0]!.material as THREE.MeshStandardMaterial;
    const clipped = (p: THREE.Vector3) => mat.clippingPlanes!.every((pl) => pl.distanceToPoint(p) < 0);
    const near = new THREE.Vector3(r.center.x, 1.5, r.center.z).addScaledVector(dirsFor(1).toward, 1);
    const far = new THREE.Vector3(r.center.x, 1.5, r.center.z).addScaledVector(dirsFor(1).toward, -1);
    expect(clipped(near)).toBe(true);
    expect(clipped(far)).toBe(false);
    gs.cutaway(null);
  });

  it("панель кнопок сверху: рамка ниже неё", () => {
    const ins = { top: 0.2, right: 0.08, bottom: 0.08, left: 0.08 };
    const pts = ndc(frameView(gs.bounds, DIRS.oblique, 1.5, ins), gs.bounds, 1.5);
    for (const p of pts) expect(p.y).toBeLessThanOrEqual(1 - 2 * 0.2 + 1e-3);
  });

  it("к комнате: комната целиком в кадре и ближе общего вида; ближние стены срезаны, дальние — целиком", () => {
    const r = gs.rooms.find((x) => x.name === "Lounge")!;
    const rb = roomBox(r.center, r.size, CUT_H);
    const rv = frameView(rb, DIRS.room, 1.5);
    for (const p of ndc(rv, rb, 1.5)) { expect(Math.abs(p.x)).toBeLessThanOrEqual(0.85); expect(Math.abs(p.y)).toBeLessThanOrEqual(0.85); }
    const ob = frameView(gs.bounds, DIRS.oblique, 1.5);
    expect(rv.position.distanceTo(rv.target)).toBeLessThan(ob.position.distanceTo(ob.target));
    gs.cutaway(r);
    const mat = gs.walls[0]!.material as THREE.MeshStandardMaterial;
    expect(mat.clipIntersection).toBe(true);
    const clipped = (p: THREE.Vector3) => mat.clippingPlanes!.every((pl) => pl.distanceToPoint(p) < 0);
    expect(clipped(new THREE.Vector3(r.center.x, 1.5, r.center.z + 1))).toBe(true); // ближняя стена выше среза
    expect(clipped(new THREE.Vector3(r.center.x, 0.2, r.center.z + 1))).toBe(false); // низ ближней стены остаётся
    expect(clipped(new THREE.Vector3(r.center.x, 1.5, r.center.z - 1))).toBe(false); // дальняя — целиком
    gs.cutaway(null);
    expect(mat.clippingPlanes).toHaveLength(0);
  });

  it("пустой лист не падает: рамка по умолчанию", () => {
    const empty = buildGreyScene({ id: "e", title: "", rooms: [], walls: [], openings: [] });
    expect(empty.size.x).toBeGreaterThan(0);
    empty.dispose();
  });
});
