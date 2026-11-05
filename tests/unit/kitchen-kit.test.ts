import { describe, expect, it } from "vitest";

import type { Material } from "@/contracts/configurator";
import { kitchenExamplesFile, type KitchenExample } from "@/contracts/kitchen-example";
import catalogue from "@/data/flat3d/catalogue-base.json";
import materials from "@/data/flat3d/materials.json";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
import { buildKitchen } from "@/lib/viewer3d/kits/kitchen";
import { KITCHEN_NORMS, checkAisles, checkKitchen, checkTriangle, pickWorkPoints } from "@/lib/viewer3d/kits/kitchen-checks";
import { kitchenSpecFromExample } from "@/lib/viewer3d/kits/kitchen-from-example";
import { WORK_AISLE_CM, kitchenLayout, type KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";
import { KITCHEN_MATERIALS, kitchenMaterial } from "@/lib/viewer3d/kits/kitchen-materials";
import { createMaterialCtx } from "@/lib/viewer3d/materials";

// НАБОР КУХНИ под примеры из магазина (план onb-09 часть А): точки треугольника, проходы, Г-форма, два цвета фасада, ряд во
// всю длину, духовка внизу при одной колонне; старые варианты застройщика (кухня demo-uk-1) раскладываются как раньше.

const examples: KitchenExample[] = [ru, uk].flatMap((f) => kitchenExamplesFile.parse(f).examples);
const known = new Map<string, string[]>([
  ...materials.materials.map((m) => [m.id, m.surfaces ?? []] as [string, string[]]),
  ...catalogue.materials.map((m) => [m.id, m.surfaces ?? []] as [string, string[]]),
]);
const surfacesOf = (id: string): string[] | undefined => known.get(id) ?? kitchenMaterial(id)?.surfaces;

/** Кухня demo-uk-1, как её склеивает `lib/viewer3d/build-scene.ts`: место 340×60, комната глубиной 180, колонны у конца. */
const legacy = (level: KitchenSpec["level"], features: string[]): KitchenSpec => ({
  level, features, doorMaterialId: "front-white", widthCm: 340, depthCm: 60, roomDepthCm: 180, columnsAt: "end",
});

describe("треугольник и проходы — числами", () => {
  const P = (x: number, z = 30): { x: number; z: number } => ({ x, z });

  it("стороны 120–270 и сумма ≤ 790 проходят; короткая, длинная сторона и большая сумма — с причиной", () => {
    expect(checkTriangle({ sink: P(0), hob: P(130), fridge: P(-130) })).toMatchObject({ ok: true, sumCm: 520 });
    const short = checkTriangle({ sink: P(0), hob: P(60), fridge: P(-130) });
    expect(short.ok).toBe(false);
    expect(short.problems[0]).toContain("мойка — варочная 60 см — меньше 120");
    const long = checkTriangle({ sink: P(0), hob: P(280), fridge: P(-130) });
    expect(long.problems.some((p) => p.includes("больше 270"))).toBe(true);
    const sum = checkTriangle({ sink: { x: 0, z: 0 }, hob: { x: 265, z: 0 }, fridge: { x: 132, z: 265 } });
    expect(sum.sides?.sinkHob).toBe(265);
    expect(sum.problems).toContain(`сумма сторон ${sum.sumCm} см — больше ${KITCHEN_NORMS.triangleSumMaxCm}`);
  });

  it("нет холодильника — треугольник не мерили (не нарушение)", () => {
    const t = checkTriangle({ sink: P(0), hob: P(130), fridge: null });
    expect(t).toMatchObject({ ok: null, sides: null });
    expect(t.problems[0]).toBe("треугольник не мерили: нет холодильника");
  });

  it("проход перед линией: 180 − 60 = 120 см — один повар да (107), двое нет (122)", () => {
    const lay = kitchenLayout(legacy("practical", ["uppers"]));
    expect(checkAisles(lay, 180, 1)).toEqual([{ where: "front", gapCm: 120, needCm: 107, ok: true }]);
    expect(checkAisles(lay, 180, 2)[0]).toMatchObject({ gapCm: 120, needCm: 122, ok: false });
    expect(checkAisles(lay, undefined)).toEqual([]);
  });

  it("остров встаёт с рабочим проходом 107 см перед линией и проходом 91 за ним — или не встаёт", () => {
    const deep = kitchenLayout({ ...legacy("premium", ["island"]), roomDepthCm: 350 });
    expect(deep.island).not.toBeNull();
    expect(checkAisles(deep, 350)).toEqual([
      { where: "front", gapCm: WORK_AISLE_CM, needCm: 107, ok: true },
      { where: "behind-island", gapCm: 350 - 60 - 107 - 90, needCm: 91, ok: true },
    ]);
    const tight = kitchenLayout({ ...legacy("premium", ["island"]), roomDepthCm: 340 });
    expect(tight.island).toBeNull();
    expect(tight.bar).toBe(true);
  });

  it("вытяжка у вентканала: расстояние по стене и порог", () => {
    const spec: KitchenSpec = { ...legacy("practical", ["uppers", "hob", "hood"]), fullRun: true, ventAtCm: 40 };
    const r = checkKitchen(spec);
    expect(r.vent?.ok).toBe(true);
    const far = checkKitchen({ ...spec, hobAtCm: 300 });
    expect(far.vent?.ok).toBe(false);
    expect(far.problems.some((p) => p.startsWith("вытяжка в"))).toBe(true);
  });
});

describe("раскладка набора", () => {
  it("старые варианты demo-uk-1 — те же модули, мойка, варочная, посудомойка и винный шкаф, что до onb-09", () => {
    // прежние формулы `buildKitchen`: ряд = доля стены по уровню, мойка в середине, варочная через модуль
    const cases: [KitchenSpec["level"], string[], number][] = [
      ["base", [], 0], ["practical", ["uppers"], 0], ["comfort", ["uppers", "tall-unit"], 1], ["premium", ["uppers", "tall-unit", "island"], 2],
    ];
    const run = { base: 0.62, practical: 0.84, comfort: 1, premium: 1 };
    for (const [level, f, cols] of cases) {
      const lay = kitchenLayout(legacy(level, [...f, "oven", "hob", "dishwasher", "wine-cooler"]));
      const runW = Math.max(120, (340 - cols * 60) * run[level]);
      const n = Math.max(1, Math.round(runW / 60));
      const sink = Math.min(n - 1, Math.floor(n / 2));
      expect(lay.runW, level).toBeCloseTo(runW, 6);
      expect(lay.slots).toHaveLength(n);
      expect([lay.sink, lay.hob, lay.dish, lay.wine]).toEqual([sink, sink - 2 >= 0 ? sink - 2 : sink + 2, Math.min(n - 1, sink + 1), Math.max(0, sink - 1)]);
      expect(lay.columns).toHaveLength(cols);
      expect(lay.leg).toBeNull();
    }
  });

  it("Premium без признака `island` острова не ставит (и барной стойки тоже)", () => {
    const lay = kitchenLayout({ ...legacy("premium", ["uppers", "tall-unit"]), roomDepthCm: 500 });
    expect(lay.island).toBeNull();
    expect(lay.bar).toBe(false);
  });

  it("духовка: при одной колонне (холодильник или кладовая) — под варочной, при двух — во второй колонне", () => {
    for (const f of [["tall-unit", "fridge"], ["tall-unit"]]) {
      const lay = kitchenLayout(legacy("comfort", [...f, "oven", "hob"]));
      expect(lay.oven).toBe(lay.hob);
      expect(lay.ovenInColumn).toBe(false);
    }
    const two = kitchenLayout(legacy("premium", ["tall-unit", "oven", "hob"]));
    expect(two.oven).toBe(-1);
    expect(two.ovenInColumn).toBe(true);
  });

  it("ряд во всю заданную длину (`fullRun`), а не доля стены", () => {
    expect(kitchenLayout({ ...legacy("practical", []), widthCm: 240, fullRun: true }).runW).toBe(240);
    expect(kitchenLayout({ ...legacy("comfort", ["tall-unit"]), widthCm: 300, fullRun: true }).runW).toBe(240);
    expect(kitchenLayout({ ...legacy("practical", []), widthCm: 240 }).runW).toBeCloseTo(240 * 0.84, 6);
  });

  it("Г: плечо у конца напротив колонн, угловой квадрат без фасада, путь по плечу дальше W", () => {
    const spec: KitchenSpec = { ...legacy("comfort", ["tall-unit", "uppers"]), columnsAt: "start", widthCm: 330, shape: "corner", cornerLegCm: 180 };
    const lay = kitchenLayout(spec);
    expect(lay.leg).toMatchObject({ at: "end", lengthCm: 180, runCm: 120 });
    expect(lay.corner).toEqual({ x0: 165 - 60, x1: 165 });
    const main = lay.slots.filter((s) => !s.leg);
    const leg = lay.slots.filter((s) => s.leg);
    expect(main.reduce((a, s) => a + s.w, 0)).toBeCloseTo(330 - 60 - 60, 6); // минус колонна и угол
    expect(leg.reduce((a, s) => a + s.w, 0)).toBeCloseTo(120, 6);
    expect(leg.every((s) => s.s > 330 && s.front.x === 165 - 60 && s.front.z > 30)).toBe(true);
    // колонна в углу не открывается: просили угол у колонн — он всё равно напротив
    expect(kitchenLayout({ ...spec, cornerAt: "start" }).leg?.at).toBe("end");
    expect(kitchenLayout({ ...spec, columnsAt: "end" }).leg?.at).toBe("start");
    // мойка на плече по точке пути
    const onLeg = kitchenLayout({ ...spec, sinkAtCm: 330 + 90 });
    expect(onLeg.slots[onLeg.sink]?.leg).toBe(true);
    // торец плеча — проход до стены напротив
    expect(checkAisles(lay, 300).find((a) => a.where === "leg-end")).toEqual({ where: "leg-end", gapCm: 120, needCm: 91, ok: true });
  });

  it("точки: мойка и варочная — к ближайшему модулю, варочная — к вентканалу, холодильник — из колонны или `fridgeAtCm`", () => {
    const base: KitchenSpec = { ...legacy("comfort", ["tall-unit", "fridge", "hob", "dishwasher"]), columnsAt: "start", widthCm: 300, fullRun: true };
    const lay = kitchenLayout({ ...base, sinkAtCm: 250, hobAtCm: 100 });
    expect(lay.slots[lay.sink]?.s).toBeCloseTo(270, 0);
    expect(lay.slots[lay.hob]?.s).toBeCloseTo(90, 0);
    expect(lay.points.fridge).toEqual({ x: -120, z: 30 });
    expect(lay.dish).not.toBe(lay.hob);
    const byVent = kitchenLayout({ ...base, ventAtCm: 200 });
    expect(byVent.slots[byVent.hob]?.s).toBeCloseTo(210, 0);
    expect(Math.abs(byVent.sink - byVent.hob)).toBeGreaterThanOrEqual(2);
    expect(byVent.points.vent).toEqual({ x: 50, z: -30 });
    const free = kitchenLayout({ ...legacy("practical", ["hob"]), fullRun: true, fridgeAtCm: -35 });
    expect(free.points.fridge).toEqual({ x: -205, z: 30 });
  });

  it("подбор точек: при холодильнике треугольник проходит, мойка и варочная не рядом, варочная не в крайнем модуле", () => {
    const spec: KitchenSpec = { ...legacy("comfort", ["tall-unit", "fridge", "hob"]), columnsAt: "start", widthCm: 304, fullRun: true };
    const w = pickWorkPoints(spec);
    expect(w).not.toBeNull();
    const lay = kitchenLayout({ ...spec, ...w });
    expect(checkTriangle(lay.points).ok).toBe(true);
    expect(Math.abs(lay.sink - lay.hob)).toBeGreaterThanOrEqual(2);
    expect([0, lay.slots.length - 1]).not.toContain(lay.hob);
  });
});

describe("паспорт → KitchenSpec", () => {
  const specs = examples.map((e) => [e, kitchenSpecFromExample(e, { roomDepthCm: 311 })] as const);

  it("все паспорта: паспортная длина во всю стену, форма, уровень и признаки — из паспорта", () => {
    expect(specs.length).toBeGreaterThanOrEqual(8);
    for (const [e, s] of specs) {
      expect(s.widthCm, e.id).toBe(e.lengthCm);
      expect(s.depthCm).toBe(e.depthCm);
      expect(s.fullRun).toBe(true);
      expect(s.shape).toBe(e.shape);
      expect(s.level).toBe(e.kitSpec.level);
      expect(s.features).toEqual(e.kitSpec.features);
      expect(kitchenLayout(s).runW).toBe(e.lengthCm - kitchenLayout(s).tallW);
    }
  });

  it("цвета: свой цвет набора вместо далёкого, второй цвет — на верх; каждый материал найден и годится слоту", () => {
    for (const [e, s] of specs) {
      const pr = e.colors.front.proposed;
      expect(s.doorMaterialId, e.id).toBe(pr && kitchenMaterial(pr.id) ? pr.id : e.kitSpec.doorMaterialId);
      if (e.colors.frontUpper && e.colors.frontUpper.materialId !== s.doorMaterialId) expect(s.doorUpperMaterialId, e.id).toBeDefined();
      if (!e.colors.frontUpper) expect(s.doorUpperMaterialId).toBeUndefined();
      const slots: [string | undefined, string][] = [
        [s.doorMaterialId, "front"], [s.doorUpperMaterialId, "front"], [s.worktopMaterialId, "worktop"], [s.splashbackMaterialId, "splashback"],
      ];
      for (const [id, surface] of slots) if (id) expect(surfacesOf(id), `${e.id}: ${id}`).toContain(surface);
    }
    const byId = Object.fromEntries(specs.map(([e, s]) => [e.id, s]));
    expect(byId["ru-sima-evropa-240"]).toMatchObject({ doorMaterialId: "front-concrete", doorUpperMaterialId: "front-oak" });
    expect(byId["ru-sima-eva-240"]).toMatchObject({ doorMaterialId: "front-graphite", doorUpperMaterialId: "front-white", splashbackMaterialId: "splashback-oak-light" });
    expect(byId["ru-sima-antracit-280"]).toMatchObject({ doorMaterialId: "front-anthracite", worktopMaterialId: "worktop-oak-votan" });
    expect(byId["uk-wickes-milton-sage"]).toMatchObject({ doorMaterialId: "front-sage", doorUpperMaterialId: "front-walnut", shape: "corner" });
  });

  it("свои цвета набора — ровно предложения паспортов, в общем каталоге их нет", () => {
    const proposed = new Set(examples.flatMap((e) => Object.values(e.colors).flatMap((c) => (c?.proposed ? [c.proposed.id] : []))));
    expect(new Set(KITCHEN_MATERIALS.map((m) => m.id))).toEqual(proposed);
    for (const m of KITCHEN_MATERIALS) {
      expect(known.has(m.id), m.id).toBe(false);
      const src = examples.flatMap((e) => Object.values(e.colors)).find((c) => c?.proposed?.id === m.id);
      expect(m.colorHex).toBe(src?.proposed?.hex);
    }
  });

  it("в кухне глубиной 3,11 м (flat215) каждый пример проходит проверки; где есть холодильник — и треугольник", () => {
    for (const [e, s] of specs) {
      const r = checkKitchen(s);
      expect(r.problems, e.id).toEqual([]);
      const lay = kitchenLayout(s);
      if (lay.points.fridge && lay.points.hob) expect(r.triangle.ok, e.id).toBe(true);
      if (lay.points.hob) expect(Math.abs(lay.sink - lay.hob), e.id).toBeGreaterThanOrEqual(2);
    }
  });

  it("холодильник вплотную к линии (его место задаст посадка): где треугольник проходит, а где модули не дают", () => {
    // В цену примеров холодильник не входит — ставим отдельно стоящий (70 см) у свободного конца линии (у Г — за торцом
    // плеча) и подбираем точки заново. НАХОДКА: модули набора — равные доли ряда, и у «Жемчуга»/«Антрацита» (2,8 м,
    // модули по 56 см) лучшая пара даёт стороны 112 и 119 см, у Wickes (плечо 150 см, модули по 52,5) — 105 при норме 120.
    // Решение — посадке (холодильник через модуль, другое плечо) или модули разной ширины (onb-09 Т2).
    const short: string[] = [];
    let measured = 0;
    for (const e of examples) {
      const s0 = kitchenSpecFromExample(e);
      if (!s0.features.includes("hob")) continue;
      const leg = kitchenLayout(s0).leg;
      const fridgeAtCm = leg ? s0.widthCm + leg.runCm + 35 : s0.columnsAt === "end" ? -35 : s0.widthCm + 35;
      const s = { ...s0, fridgeAtCm, sinkAtCm: undefined, hobAtCm: undefined };
      const t = checkKitchen({ ...s, ...pickWorkPoints(s) }).triangle;
      measured += 1;
      if (t.ok) continue;
      short.push(e.id);
      for (const v of Object.values(t.sides ?? {})) expect(v, e.id).toBeGreaterThanOrEqual(100);
      expect(t.problems.every((p) => p.includes("меньше 120")), t.problems.join("; ")).toBe(true);
    }
    expect(measured).toBe(6);
    expect(short.sort()).toEqual(["ru-sima-antracit-280", "ru-sima-zhemchug-280", "uk-wickes-milton-sage"]);
  });
});

describe("сборка three", () => {
  const ctx = {
    materials: createMaterialCtx(1, false),
    byId: (id: string): Material | undefined => [...materials.materials, ...catalogue.materials].find((m) => m.id === id) as Material | undefined,
    fallback: { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as Material,
  };

  it("собирается каждый пример и каждый старый вариант; у Г есть плечо, у двухцветной — свой материал верха", () => {
    for (const e of examples) {
      const s = kitchenSpecFromExample(e);
      const g = buildKitchen(ctx, s);
      expect(g.children.length, e.id).toBeGreaterThan(20);
      if (s.shape === "corner") expect(g.children.some((c) => c.type === "Group")).toBe(true);
    }
    for (const level of ["base", "practical", "comfort", "premium"] as const) {
      expect(buildKitchen(ctx, legacy(level, ["uppers", "oven", "hob", "hood"])).children.length).toBeGreaterThan(10);
    }
    const two = buildKitchen(ctx, { ...legacy("practical", ["uppers"]), doorMaterialId: "front-concrete", doorUpperMaterialId: "front-oak" });
    const colours = new Set(two.children.flatMap((c) => ("material" in c ? [(c.material as { color?: { getHexString(): string } }).color?.getHexString()] : [])));
    expect(colours.size).toBeGreaterThan(3);
  });
});
