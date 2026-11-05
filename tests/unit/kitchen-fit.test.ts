import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { kitchenExamplesFile, type KitchenExample } from "@/contracts/kitchen-example";
import { kitchenFitFile, type KitchenFitOk } from "@/contracts/kitchen-fit";
import fitFile from "@/data/partners/kitchen-fit/flat215.json";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
import { KITCHEN_NORMS, checkKitchen } from "@/lib/viewer3d/kits/kitchen-checks";
import { kitchenSpecFromExample } from "@/lib/viewer3d/kits/kitchen-from-example";
import { KITCHEN_LEVELS, WALKWAY_CM, WORK_AISLE_CM, kitchenLayout } from "@/lib/viewer3d/kits/kitchen-layout";
import rules from "@/services/planner-solver/rules/kitchen.json";

// ПОСАДКА КУХНИ НА КВАРТИРУ (план onb-09 Т2–Т3, T-20261105-33): файл `data/partners/kitchen-fit/flat215.json` (солвер
// `planner/kitchen.py` через `tools/scout/kitchen_fit.py`) сходится с набором — те же колонны, верх, холодильник в колонне,
// что у `kitchenLayout`; набор по посадке проходит нормы без допущений; нормы TS и солвера — одно число.

const fits = kitchenFitFile.parse(fitFile);
const examples = new Map<string, KitchenExample & { market: string }>(
  [ru, uk].flatMap((f) => {
    const file = kitchenExamplesFile.parse(f);
    return file.examples.map((e) => [e.id, { ...e, market: file.market }] as const);
  }),
);
const okFits = Object.entries(fits.fits).filter((kv): kv is [string, KitchenFitOk] => kv[1].ok);

describe("kitchen fit (flat215)", () => {
  it("каждый пример рынка, кроме запрещённых квартире, посажен; запрещённых нет", () => {
    for (const [id, e] of examples) {
      const banned = e.notFor?.flats.includes("flat215") ?? false;
      expect(id in fits.fits, id).toBe(!banned);
    }
    expect(okFits.length).toBeGreaterThanOrEqual(6);
    expect(okFits.some(([, f]) => f.market === "ru") && okFits.some(([, f]) => f.market === "uk")).toBe(true);
  });

  it("параметры набора в посадке — те же, что у kitchenLayout (зеркало kitchen_fit.py)", () => {
    for (const [id, f] of Object.entries(fits.fits)) {
      if (!f.ok) continue;
      const e = examples.get(id);
      expect(e, id).toBeDefined();
      if (!e) continue;
      expect(f.market).toBe(e.market);
      const lay = kitchenLayout(kitchenSpecFromExample(e));
      const level = KITCHEN_LEVELS[e.kitSpec.level];
      expect(f.kit.length_cm, id).toBe(e.kitSpec.widthCm);
      expect(f.kit.depth_cm, id).toBe(e.kitSpec.depthCm);
      expect(f.kit.tall_cm, id).toBe(lay.tallW);
      expect(f.kit.fridge_in_column, id).toBe(lay.columns.some((c) => c.fridge));
      expect(f.kit.uppers, id).toBe(level.uppers > 0 || e.kitSpec.features.includes("uppers"));
    }
  });

  it("набор по посадке: без допущения о холодильнике, проходы по нормам, треугольник не хуже, чем без посадки, варочная не под окном", () => {
    for (const [id, f] of okFits) {
      const e = examples.get(id) as KitchenExample;
      const spec = kitchenSpecFromExample(e, { fit: f });
      expect(spec.fridgeAssumed, id).toBeUndefined();
      expect(spec.roomDepthCm, id).toBe(f.room_depth_cm);
      if (f.columns_at) expect(spec.columnsAt, id).toBe(f.columns_at);
      if (f.vent_at_cm !== null) expect(spec.ventAtCm, id).toBe(f.vent_at_cm);
      const rep = checkKitchen(spec);
      expect(rep.aisles.every((a) => a.ok), id).toBe(true);
      // треугольник — свойство паспорта (ширины модулей): 240 с модулями 60/80/60/40 не проходит и без квартиры
      if (checkKitchen(kitchenSpecFromExample(e)).triangle.ok) expect(rep.triangle.ok, id).toBe(true);
      const lay = kitchenLayout(spec);
      const hob = lay.slots[lay.hob];
      if (hob && e.kitSpec.features.includes("hob")) {
        for (const [a, b] of spec.noHobCm ?? []) expect(Math.min(b, hob.s + hob.w / 2) - Math.max(a, hob.s - hob.w / 2), id).toBeLessThanOrEqual(1);
      }
    }
  });

  it("кухня 215: ряд по наружной глухой стене к вентканалу (допущение помечено), обеденная группа на 4", () => {
    expect(fits.room.vent_assumed).toBe(true);
    for (const [id, f] of okFits) {
      expect(f.wall, id).toBe("south");
      expect(f.u0_cm + f.length_cm, id).toBe(fits.room.w);
      expect(f.dining.max_seats, id).toBeGreaterThanOrEqual(4);
    }
  });

  it("нормы — одно число: TS читает rules/kitchen.json, проход 91 — зеркало occupancy.json", () => {
    expect(KITCHEN_NORMS.triangleSideMinCm).toBe(rules.triangle.side_min_cm.v);
    expect(KITCHEN_NORMS.triangleSumMaxCm).toBe(rules.triangle.sum_max_cm.v);
    expect(KITCHEN_NORMS.aisleTwoCooksCm).toBe(rules.aisle.work_two_cooks_cm.v);
    expect(WORK_AISLE_CM).toBe(rules.aisle.work_one_cook_cm.v);
    const occ = JSON.parse(readFileSync("services/planner-solver/rules/occupancy.json", "utf8")) as { distances_cm: { passage_main: number[] } };
    expect(WALKWAY_CM).toBe(occ.distances_cm.passage_main[0]);
  });
});
