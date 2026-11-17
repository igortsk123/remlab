import { existsSync } from "node:fs";
import { join } from "node:path";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import plantsJson from "@/data/flat3d/plants.json";
import {
  fitPlant, pickPlant, placePlant, plantKindOf, plantsFromUrl, plantUrl, plantYawDeg, PLANT_RULES, type PlantRules, throatOf,
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
    expect(R.plants.length).toBeGreaterThanOrEqual(4);
    expect(R.plants.length).toBeLessThanOrEqual(6);
    for (const kind of Object.values(R.hosts)) expect(R.plants.some((p) => p.kind === kind)).toBe(true);
    for (const p of R.plants) {
      expect(R.fit[p.kind]).toBeTruthy();
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
    const small = pickPlant("green", 10, "a")!;
    expect(small.kind).toBe("green");
    expect(small.minThroatCm).toBeLessThanOrEqual(10);
    expect(pickPlant("green", 30, "a")).toEqual(pickPlant("green", 30, "a"));
    const seeds = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"];
    expect(new Set(seeds.map((s) => pickPlant("green", 30, s)!.id)).size).toBeGreaterThan(1);   // не одно и то же везде
    expect(pickPlant("dry", 6, "v")!.kind).toBe("dry");
    expect(pickPlant("green", 30, "a", null, { ...R, plants: [] })).toBeNull();
  });

  it("стиль: у растения с «any» — подходит всем; со своим стилем — только ему; без стиля «чужие» не берутся", () => {
    const rules: PlantRules = { ...R, plants: [
      { id: "u", kind: "green", styles: ["any"], minThroatCm: 0 },
      { id: "s", kind: "green", styles: ["japandi"], minThroatCm: 0 },
    ] };
    const ids = (style?: string) => new Set(["a", "b", "c", "d", "e", "f", "g", "h"].map((s) => pickPlant("green", 20, s, style, rules)!.id));
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

  it("зелень: крона = горло × крона/горло, высота зажата в [min, max]; основание на крае с заглублением", () => {
    const f = R.fit.green;
    const fit = fitPlant("green", { w: 0.6, h: 0.42, d: 0.5 }, throat, 0.3);
    expect(fit.scale).toBeCloseTo((0.2 * f.crownOverThroat) / 0.6, 6);        // крона 0,38 м
    expect(0.42 * fit.scale).toBeGreaterThanOrEqual(f.minHeightCm / 100 - 1e-9);
    expect(0.42 * fit.scale).toBeLessThanOrEqual(f.maxHeightCm / 100 + 1e-9);
    expect(fit.x).toBe(0.04);
    expect(fit.z).toBe(-0.02);
    expect(fit.y).toBeCloseTo(0.3 - (f.sinkCm / 100 + f.sinkFracOfHeight * 0.42 * fit.scale), 6);
    // огромное горло — высота упирается в потолок типа; крошечное — в пол
    const big = fitPlant("green", { w: 0.6, h: 0.42, d: 0.5 }, { ...throat, diameterM: 0.8 }, 0.3);
    expect(0.42 * big.scale).toBeCloseTo(f.maxHeightCm / 100, 6);
    const tiny = fitPlant("green", { w: 0.6, h: 0.42, d: 0.5 }, { ...throat, diameterM: 0.05 }, 0.3);
    expect(0.42 * tiny.scale).toBeCloseTo(f.minHeightCm / 100, 6);
  });

  it("сухоцветы: высота — от носителя в [min, max], крона не шире горла × предел; стебель уходит в вазу", () => {
    const f = R.fit.dry;
    const fit = fitPlant("dry", { w: 0.13, h: 1.04, d: 0.15 }, { ...throat, diameterM: 0.06 }, 0.2);
    const h = 1.04 * fit.scale;
    expect(h).toBeGreaterThanOrEqual(f.minHeightCm / 100 - 1e-6);
    expect(h).toBeLessThanOrEqual(0.2 * (f.heightOverCarrier ?? 2) + 1e-6);
    expect(0.15 * fit.scale).toBeLessThanOrEqual(0.06 * f.crownOverThroat + 1e-9);
    expect(fit.y).toBeLessThan(throat.topY);                                   // основание ниже края горла
    // широкая ветка: масштаб режет предел кроны, а не высота
    const wide = fitPlant("dry", { w: 0.6, h: 1.0, d: 0.6 }, { ...throat, diameterM: 0.06 }, 0.2);
    expect(0.6 * wide.scale).toBeCloseTo(0.06 * f.crownOverThroat, 6);
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
