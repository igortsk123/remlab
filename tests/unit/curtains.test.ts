import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { room as roomSchema } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { CURTAIN_PANEL_CM, CURTAIN_PLANE_CM, CURTAIN_PLEAT_CM, curtainRodY, roomCurtains } from "@/lib/configurator/curtains";
import { wallFixturesIR } from "@/lib/viewer3d/fixtures-ir";
import { openingIR } from "@/lib/viewer3d/opening-ir";
import { buildRoom } from "@/lib/viewer3d/rooms";
import { buildCurtains } from "@/lib/viewer3d/window-light";

// ШТОРА ПЕРЕД ПОДОКОННИКОМ, НА КАРНИЗЕ (T-20261112-34, снимок владельца 12.11 06:02): подоконник шёл сквозь штору, откос — белой
// полосой между складками, карниз кончался раньше полотна, верх полотна — выше штанги.

const room = (openings: unknown[], w = 400, d = 300) =>
  roomSchema.parse({ id: "r", kind: "living", titleRu: "Г", titleEn: "L", x: 0, y: 0, w, d, openings });
const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;
const win = (wall: string, offsetCm: number, widthCm = 150) => ({ kind: "window", wall, offsetCm, widthCm, sillCm: 85, heightCm: 150 });

describe("шторы у окна", () => {
  it("плоскость шторы — перед подоконником, откосом и рамой с учётом складок", () => {
    const ir = openingIR(win("south", 100) as never, { wallHeightCm: 270 });
    const front = Math.max(...ir.boxes.map((b) => b.z + b.d / 2));
    expect(front).toBe(19);                                          // подоконник — самое выступающее
    expect(CURTAIN_PLANE_CM - CURTAIN_PLEAT_CM).toBeGreaterThan(front);
  });

  it("свободная стена: два полотна по 55 см, карниз шире полотен с обеих сторон", () => {
    const [s] = roomCurtains(room([win("south", 100)]));
    expect(s!.panels).toEqual([{ u0: 57, u1: 112 }, { u0: 238, u1: 293 }]);
    expect(s!.rod.u0).toBeLessThan(57);
    expect(s!.rod.u1).toBeGreaterThan(293);
  });

  it("окно в углу: полотно не заходит в соседнюю стену — у угла уже или одно", () => {
    const [s] = roomCurtains(room([win("west", 10)]));
    expect(Math.min(...s!.panels.map((p) => p.u0))).toBeGreaterThanOrEqual(3);
    expect(s!.rod.u0).toBeGreaterThanOrEqual(3);
    const [c] = roomCurtains(room([win("east", 0, 50)]));
    expect(c!.panels.length).toBe(1);                                  // узкое окно в углу — одно полотно, с открытой стороны
    expect(c!.panels[0]!.u1).toBeGreaterThan(50);
    expect(c!.rod.u0).toBeGreaterThanOrEqual(3);
    expect(c!.panels.every((p) => p.u1 - p.u0 <= CURTAIN_PANEL_CM)).toBe(true);
  });

  it("дверь рядом на той же стене и дверь соседней стены у угла — полотно их не закрывает", () => {
    const door = { kind: "door", wall: "south", offsetCm: 0, widthCm: 80 };
    const [, s] = roomCurtains(room([door, win("south", 110)]));
    expect(Math.min(...s!.panels.map((p) => p.u0))).toBeGreaterThanOrEqual(80 + 10);
    // дверь западной стены в 10 см от южной: полотно у этого угла не встаёт в её проход
    const side = { kind: "door", wall: "west", offsetCm: 10, widthCm: 80 };
    const [, t] = roomCurtains(room([side, win("south", 60)]));
    expect(Math.min(...t!.panels.map((p) => p.u0))).toBeGreaterThanOrEqual(85);
    expect(t!.rod.u0).toBeLessThanOrEqual(60);                         // штанга под потолком — на всё окно
  });

  it("сцена: полотна висят от штанги до пола в плоскости карниза, штанга — по полотнам", () => {
    const r = room([win("south", 100)]);
    const g = buildCurtains([r]);
    expect(g.children.length).toBe(2);
    for (const m of g.children as THREE.Mesh[]) {
      const bb = new THREE.Box3().setFromObject(m);
      expect(bb.min.z * 100).toBeGreaterThan(1 + 19);                // перед подоконником (стена вдвинута на 1 см)
      expect(bb.max.y * 100).toBeCloseTo(curtainRodY(235, 270), 3);  // верх — на штанге
      expect(bb.min.y * 100).toBeCloseTo(1, 3);
    }
    const cut = openingIR(win("south", 100) as never, { wallHeightCm: 270 }).cut;
    const [s] = roomCurtains(r);
    const rod = wallFixturesIR([], [{ ...cut, rod: s!.rod }], 270).find((b) => b.role === "cornice" && b.w > 50)!;
    expect(rod.z).toBe(CURTAIN_PLANE_CM);
    expect(rod.x - rod.w / 2).toBeLessThan(s!.panels[0]!.u0);
    expect(rod.x + rod.w / 2).toBeGreaterThan(s!.panels[1]!.u1);
  });

  it.each(["south", "north", "west", "east"])("карниз в комнате (%s, у угла): штанга накрывает полотна, стоит в их плоскости", (wall) => {
    const r = room([win(wall, 25)]);
    const { group } = buildRoom(createMaterialCtx(1, false), r, MAT, MAT);
    group.updateMatrixWorld(true);
    const fx = group.children.find((c) => c.name === `fixtures:r:${wall}`)!;
    const bar = fx.children.filter((m) => m.userData.part === "cornice").map((m) => new THREE.Box3().setFromObject(m))
      .reduce((a, b) => (b.getSize(new THREE.Vector3()).length() > a.getSize(new THREE.Vector3()).length() ? b : a));
    const ns = wall === "south" || wall === "north";
    const panels = buildCurtains([r]).children.map((m) => new THREE.Box3().setFromObject(m));
    const lo = (b: THREE.Box3) => (ns ? b.min.x : b.min.z), hi = (b: THREE.Box3) => (ns ? b.max.x : b.max.z);
    expect(lo(bar)).toBeLessThan(Math.min(...panels.map(lo)));
    expect(hi(bar)).toBeGreaterThan(Math.max(...panels.map(hi)));
    expect(lo(bar)).toBeGreaterThan(0);                                // не в соседней стене
    const depth = (b: THREE.Box3) => (ns ? (b.min.z + b.max.z) / 2 : (b.min.x + b.max.x) / 2);
    for (const p of panels) expect(depth(p)).toBeCloseTo(depth(bar), 2);  // полотно и штанга — в одной плоскости
    expect(Math.max(...panels.map((p) => p.max.y))).toBeLessThanOrEqual(bar.max.y);  // верх полотна не выше штанги
  });
});
