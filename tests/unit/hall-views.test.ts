import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { camfitFrom, pickHallViews, type HallItem, type HallViewsRule } from "@/tools/flat3d/hall-snap/views";

// ДВА ВИДА ПРИХОЖЕЙ ПО ПРАВИЛУ ДАННЫМИ (T-20261106-73): вид 1 — зеркало целиком и ближнее хранение, вид 2 — главное хранение целиком;
// в обоих ничего ближе 40 см и мебель не срезана больше чем наполовину. Расстановки — пять наборов банка стенда T-61
// (`compose_hall`, ref-hall 06.11), комната flat215-hall 153 × 620.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const rule = JSON.parse(readFileSync("tools/scout/rules/hall-views.json", "utf8")) as HallViewsRule;
const ROOM = { w: 153, d: 620, openings: [] };
const I = (role: string, x: number, y: number, rot: number, w: number, d: number, h: number, elev = 0): HallItem => ({ role, x, y, rot, w, d, h, elev });
const SETS: Record<string, HallItem[]> = {
  сканди: [I("шкаф-купе", 123, 530, 270, 180, 60, 220), I("обувница", 135.5, 110, 270, 60, 35, 113), I("банкетка", 130.5, 185, 270, 90, 45, 45),
    I("вешалка", 144.5, 23, 270, 46, 17, 92), I("зеркало", 1.5, 28, 90, 56, 3, 72, 114)],
  современный: [I("шкаф-купе", 123, 530, 270, 180, 60, 250), I("обувница", 134, 110, 270, 60, 38, 102), I("банкетка", 133, 195, 270, 110, 40, 45),
    I("консоль", 135, 295, 270, 90, 36, 81), I("вешалка", 141.5, 31, 270, 62, 23, 166), I("зеркало", 1.5, 25, 90, 50, 3, 50, 125)],
  минимализм: [I("шкаф-купе", 123, 530, 270, 180, 60, 250), I("обувница", 136.5, 108, 270, 56, 33, 115), I("банкетка", 130.5, 195, 270, 110, 45, 45),
    I("вешалка", 141.5, 31, 270, 62, 23, 166), I("зеркало", 2, 30, 90, 60, 4, 60, 120)],
  лофт: [I("шкаф-купе", 123, 530, 270, 180, 60, 250), I("вешалка", 13.5, 33.5, 90, 67, 27, 51.5), I("зеркало", 151.5, 30, 270, 60, 3, 102, 99)],
  джапанди: [I("обувница", 15.5, 25, 90, 50, 31, 99), I("банкетка", 130.5, 125, 270, 90, 45, 45), I("вешалка", 131, 195, 270, 50, 44, 144),
    I("зеркало", 1.5, 30, 90, 60, 3, 120, 109)],
};
const cf = camfitFrom(block, ROOM);
const picks = Object.fromEntries(Object.entries(SETS).map(([k, its]) => [k, pickHallViews(cf, rule, ROOM, its, 1440 / 900)]));

describe("виды прихожей: правило данными", () => {
  it.each(Object.keys(SETS))("%s: оба вида годны — обязательное целиком и не заслонено, ничего ближе 40 см, нет среза больше половины", (k) => {
    const [v1, v2] = picks[k]!;
    expect(v1!.why).toEqual([]);
    expect(v2!.why).toEqual([]);
    expect(v1!.need.map((n) => n.got)).toContain("зеркало");
    [v1!, v2!].forEach((v, k) => {
      expect(v.nearestCm).toBeGreaterThanOrEqual(rule.clear_cm);
      expect(v.cut).toEqual([]);
      // целиком — не заслонено на vis_min; «видно» — доля в кадре и не заслонённого не меньше min записи
      rule.views[k]!.need.forEach((nd, i) => {
        const min = nd.whole ? rule.vis_min : (nd.min ?? rule.shown_min);
        expect(v.need[i]!.visible).toBeGreaterThanOrEqual(min);
        if (!nd.whole) expect(v.need[i]!.inFrame).toBeGreaterThanOrEqual(min);
      });
    });
  });
  it("вид 2 — главное хранение: шкаф-купе, где он есть; в джапанди — самый крупный из ближнего (вешалка)", () => {
    for (const k of ["сканди", "современный", "минимализм", "лофт"]) expect(picks[k]![1]!.need[0]!.got).toBe("шкаф-купе");
    expect(picks["джапанди"]![1]!.need[0]!.got).toBe("вешалка");
  });
  it("виды смотрят в разные стороны (правило apart)", () => {
    for (const [v1, v2] of Object.values(picks)) {
      const ang = Math.abs((((v1!.pose.rot - v2!.pose.rot) % 360) + 540) % 360 - 180);
      expect(ang).toBeGreaterThanOrEqual(rule.apart.near_deg);
    }
  });
  it("годного вида нет — честный ответ с причинами, а не молчаливая плохая точка", () => {
    // зеркало за шкафом во всю стену: целиком его не видно ниоткуда
    const its = [I("шкаф", 20, 300, 90, 600, 40, 240), I("зеркало", 1.5, 300, 90, 56, 3, 72, 114)];
    const [v1] = pickHallViews(cf, rule, ROOM, its, 1440 / 900);
    expect(v1!.ok).toBe(false);
    expect(v1!.why.join(" ")).toMatch(/зеркало/);
  });
});
