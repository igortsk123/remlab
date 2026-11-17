import { existsSync } from "node:fs";
import { join } from "node:path";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import plantsJson from "@/data/flat3d/plants.json";
import {
  fitPlant, mountOf, pickPlant, placePlant, plantKindOf, plantsFromUrl, plantUrl, plantYawDeg, PLANT_RULES, type PlantRules, throatOf,
} from "@/lib/viewer3d/kits/plants";

// РАСТЕНИЯ В КАШПО И ВАЗАХ (T-20261117-07, владелец TG 1307): тип по роли носителя, подбор по размеру горла и стилю, горло — по мешу
// носителя, масштаб и посадка по правилам `plants.json`. Правила — данные, ID товаров и сцен в коде нет.

const R = PLANT_RULES;

/** Открытый сосуд: стенка-цилиндр без дна и крышки с радиусом `r` и высотой `h`, низ на нуле, смещён на (x, z). */
function vessel(r: number, h: number, x = 0, z = 0): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 0.7, h, 24, 1, true), new THREE.MeshBasicMaterial());
  m.position.set(x, h / 2, z);
  return m;
}

describe("растения кашпо и ваз: правила", () => {
  it("роль носителя → тип; «ваза 2» — как «ваза»; не носитель и пусто — нет", () => {
    expect(plantKindOf("кашпо")).toBe("green");
    expect(plantKindOf("Ваза 2")).toBe("dry");
    expect(plantKindOf("диван")).toBeNull();
    expect(plantKindOf(null)).toBeNull();
    expect(plantKindOf(undefined)).toBeNull();
    expect(plantKindOf("  ")).toBeNull();
  });

  it("реестр: 4–6 моделей, оба типа есть, файлы лежат; адрес — с версией набора", () => {
    expect(R.plants.length).toBeGreaterThanOrEqual(8);
    expect(R.plants.length).toBeLessThanOrEqual(16);
    for (const kind of Object.values(R.hosts)) expect(R.plants.some((p) => p.kind === kind)).toBe(true);
    for (const p of R.plants) {
      expect(R.fit[p.kind].floor && R.fit[p.kind].table).toBeTruthy();
      expect(existsSync(join(process.cwd(), "public", R.base, `${p.id}.glb`))).toBe(true);
    }
    expect(plantUrl("fern")).toBe(`/flat3d/plants/fern.glb?v=${plantsJson.rev}`);
  });

  it("выключатель в адресе: ?plants=0 — выкл, =1 — вкл, нет — решает движок", () => {
    expect(plantsFromUrl("?plants=0")).toBe(false);
    expect(plantsFromUrl("?a=1&plants=1")).toBe(true);
    expect(plantsFromUrl("?plants=2")).toBeUndefined();
    expect(plantsFromUrl("")).toBeUndefined();
  });

  it("подбор: тип по носителю; растение крупнее горла не берётся; один носитель — одно растение; нет подходящего — null", () => {
    const small = pickPlant("green", "table", 10, "a")!;
    expect(small.kind).toBe("green");
    expect(small.minThroatCm).toBeLessThanOrEqual(10);
    expect(pickPlant("green", "floor", 30, "a")).toEqual(pickPlant("green", "floor", 30, "a"));
    const seeds = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"];
    expect(new Set(seeds.map((s) => pickPlant("green", "floor", 30, s)!.id)).size).toBeGreaterThan(1);   // не одно и то же везде
    expect(pickPlant("dry", "table", 6, "v")!.kind).toBe("dry");
    expect(pickPlant("green", "floor", 30, "a", null, { ...R, plants: [] })).toBeNull();
  });

  it("напольное кашпо — только крупное растение, настольное малое — только мелкое (калатея/антуриум не в напольное D30)", () => {
    const seeds = Array.from({ length: 60 }, (_, i) => `m${i}`);
    const floor = new Set(seeds.map((s) => pickPlant("green", "floor", 30, s)!.id));
    for (const id of floor) expect(R.plants.find((p) => p.id === id)!.mounts).toContain("floor");
    expect(floor.has("calathea") || floor.has("anthurium") || floor.has("fern")).toBe(false);
    const table = new Set(seeds.map((s) => pickPlant("green", "table", 15, s)!.id));
    for (const id of table) expect(R.plants.find((p) => p.id === id)!.mounts).toContain("table");
    expect(pickPlant("green", "table", 30, "x")).toBeNull();                 // большое горло на столе — нечем заполнить, носитель пустой
  });

  it("мебель на полу или выше: порог от пола в данных", () => {
    expect(mountOf(0)).toBe("floor");
    expect(mountOf(null)).toBe("floor");
    expect(mountOf(R.floorMaxElevCm)).toBe("floor");
    expect(mountOf(R.floorMaxElevCm + 1)).toBe("table");
    expect(mountOf(72)).toBe("table");
  });

  it("букеты для ваз — свои, собраны кодом: источник и лицензия записаны", () => {
    const own = R.plants.filter((p) => p.kind === "dry");
    expect(own.length).toBeGreaterThanOrEqual(3);
    expect(own.every((p) => !p.mounts || p.mounts.includes("table"))).toBe(true);
  });

  it("стиль: у растения с «any» — подходит всем; со своим стилем — только ему; без стиля «чужие» не берутся", () => {
    const rules: PlantRules = { ...R, plants: [
      { id: "u", kind: "green", styles: ["any"], minThroatCm: 0 },
      { id: "s", kind: "green", styles: ["japandi"], minThroatCm: 0 },
    ] };
    const ids = (style?: string) => new Set(["a", "b", "c", "d", "e", "f", "g", "h"].map((s) => pickPlant("green", "table", 20, s, style, rules)!.id));
    expect(ids()).toEqual(new Set(["u"]));
    expect(ids("loft")).toEqual(new Set(["u"]));
    expect(ids("japandi")).toEqual(new Set(["u", "s"]));
  });
});

describe("растения кашпо и ваз: горло носителя по мешу", () => {
  it("диаметр и центр — по верхней полосе, верх — высота края; смещение носителя в группе учтено", () => {
    const frame = new THREE.Group();
    frame.add(vessel(0.1, 0.3, 0.04, -0.02));
    const t = throatOf(frame, frame)!;
    expect(t.diameterM).toBeCloseTo(0.2, 2);
    expect(t.topY).toBeCloseTo(0.3, 3);
    expect(t.x).toBeCloseTo(0.04, 2);
    expect(t.z).toBeCloseTo(-0.02, 2);
  });

  it("поворот и положение группы носителя в расчёт не входят (оси группы)", () => {
    const frame = new THREE.Group();
    frame.position.set(3, 0, -2);
    frame.rotation.y = 0.9;
    frame.add(vessel(0.05, 0.2));
    const t = throatOf(frame, frame)!;
    expect(t.diameterM).toBeCloseTo(0.1, 2);
    expect(t.x).toBeCloseTo(0, 2);
    expect(t.z).toBeCloseTo(0, 2);
  });

  it("узкая ваза: горло — шейка наверху, а не тело (по верхней полосе)", () => {
    const frame = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.09, 0.3, 24, 6, true), new THREE.MeshBasicMaterial());
    body.position.y = 0.15;
    frame.add(body);
    const t = throatOf(frame, frame)!;
    expect(t.diameterM).toBeCloseTo(0.06, 2);
  });

  it("пустой меш и горло уже 3 см — null (растение не ставим)", () => {
    expect(throatOf(new THREE.Group(), new THREE.Group())).toBeNull();
    const frame = new THREE.Group();
    frame.add(vessel(0.012, 0.2));
    expect(throatOf(frame, frame)).toBeNull();
  });
});

describe("растения кашпо и ваз: масштаб и посадка", () => {
  const throat = { x: 0.04, z: -0.02, topY: 0.3, diameterM: 0.2 };

  it("настольная зелень: крона = горло × крона/горло, высота в [min, max]; основание на крае с заглублением", () => {
    const f = R.fit.green.table;
    const fit = fitPlant("green", "table", { w: 0.6, h: 0.42, d: 0.5 }, throat, 0.3);
    expect(fit.scale).toBeCloseTo((0.2 * f.crownOverThroat) / 0.6, 6);
    expect(0.42 * fit.scale).toBeGreaterThanOrEqual(f.minHeightCm / 100 - 1e-9);
    expect(0.42 * fit.scale).toBeLessThanOrEqual(f.maxHeightCm / 100 + 1e-9);
    expect(fit.x).toBe(0.04);
    expect(fit.z).toBe(-0.02);
    expect(fit.y).toBeCloseTo(0.3 - (f.sinkCm / 100 + f.sinkFracOfHeight * 0.42 * fit.scale), 6);
    // огромное горло — высота упирается в потолок типа; крошечное — в пол
    const big = fitPlant("green", "table", { w: 0.6, h: 0.42, d: 0.5 }, { ...throat, diameterM: 0.8 }, 0.3);
    expect(0.42 * big.scale).toBeCloseTo(f.maxHeightCm / 100, 6);
    const tiny = fitPlant("green", "table", { w: 0.6, h: 0.42, d: 0.5 }, { ...throat, diameterM: 0.05 }, 0.3);
    expect(0.42 * tiny.scale).toBeCloseTo(f.minHeightCm / 100, 6);
  });

  it("напольное кашпо D30: растение «в рост» — 80–130 см, высота ≈ 3–4 диаметра (не рассада); крона не шире предела", () => {
    const f = R.fit.green.floor;
    const t30 = { ...throat, diameterM: 0.28 };
    for (const size of [{ w: 0.59, h: 0.93, d: 0.63 }, { w: 0.7, h: 0.63, d: 0.64 }, { w: 1.05, h: 1.9, d: 1.0 }, { w: 0.74, h: 1.3, d: 0.65 }]) {
      const fit = fitPlant("green", "floor", size, t30, 0.28);
      const h = size.h * fit.scale;
      expect(h).toBeGreaterThanOrEqual(0.8);
      expect(h).toBeLessThanOrEqual(f.maxHeightCm / 100 + 1e-9);
      expect(Math.max(size.w, size.d) * fit.scale).toBeLessThanOrEqual(t30.diameterM * f.crownOverThroat + 1e-9);
      expect(h / t30.diameterM).toBeGreaterThan(2.5);
      expect(h / t30.diameterM).toBeLessThan(4.7);
    }
  });

  it("букет в вазу: высота — от носителя в [min, max], крона не шире горла × предел; ствол уходит в вазу", () => {
    const f = R.fit.dry.table;
    const fit = fitPlant("dry", "table", { w: 0.46, h: 0.76, d: 0.5 }, { ...throat, diameterM: 0.07 }, 0.2);
    const h = 0.76 * fit.scale;
    expect(h).toBeLessThanOrEqual(0.2 * (f.heightOverCarrier ?? 2) + 1e-6);
    expect(0.5 * fit.scale).toBeLessThanOrEqual(0.07 * f.crownOverThroat + 1e-9);
    expect(fit.y).toBeLessThan(throat.topY);                                   // основание ниже края горла
    // широкий букет: масштаб режет предел кроны, а не высота
    const wide = fitPlant("dry", "table", { w: 1.2, h: 1.0, d: 1.2 }, { ...throat, diameterM: 0.06 }, 0.2);
    expect(1.2 * wide.scale).toBeCloseTo(0.06 * f.crownOverThroat, 6);
  });

  it("посадка: копия модели с масштабом и положением, помечена как растение; исходная модель не тронута", () => {
    const src = new THREE.Group();
    src.add(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.4, 0.2), new THREE.MeshBasicMaterial()));
    const fit = { scale: 0.5, x: 0.04, y: 0.28, z: -0.02 };
    const g = placePlant(src, fit, "seed");
    expect(g.userData.plant).toBe(true);
    expect(g.scale.x).toBe(0.5);
    expect(g.position.toArray()).toEqual([0.04, 0.28, -0.02]);
    expect(placePlant(src, fit, "seed").rotation.y).toBe(g.rotation.y);        // разворот устойчив по seed
    expect(g.rotation.y).toBeCloseTo((plantYawDeg("seed") * Math.PI) / 180, 12);   // тот же разворот берёт экспорт сцены в рендер
    expect(plantYawDeg("seed")).toBeGreaterThanOrEqual(0);
    expect(plantYawDeg("seed")).toBeLessThan(360);
    expect(src.children).toHaveLength(1);
    const meshes: THREE.Mesh[] = [];
    g.traverse((o) => { if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh); });
    expect(meshes.every((m) => m.castShadow && m.receiveShadow)).toBe(true);
  });
});
