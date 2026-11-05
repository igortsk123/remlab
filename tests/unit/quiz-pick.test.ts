import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ПОДБОР ТРЁХ СТИЛЕЙ ОПРОСА-ЗНАКОМСТВА (onb-02 Т4, ADR-0330). Чистые функции — блок QUIZPICK; пока страницы опроса нет, блок живёт
// в скрипте аудита цветов, onb-03 переносит его дословно в `index.html` и меняет здесь только SRC (как блок DEMOMASK в demo-mask.test.ts).
const SRC = "tools/ops/quiz-colour-audit.mjs";
type Shares = Record<string, number>;
type Answers = { photos?: string[]; colours?: string[]; household?: string[] };
type Rule = { version: string; weights: Record<string, number>; pick: { count: number }; palettes: { families: string[] } & Record<string, unknown> };
type Case = { id: string; why: string; answers: Answers; available?: string[]; styleColours?: Record<string, Shares>; expect: string[] };
type Golden = { rule: string; available: string[]; styleColours: Record<string, Shares>; cases: Case[] };

const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// QUIZPICK START"), src.indexOf("// QUIZPICK END"));
const page = new Function(`${block};return {quizPick,quizColourOf,quizStyleColours};`)() as {
  quizPick: (rule: Rule, a: Answers, available: string[], sc: Record<string, Shares>) => string[];
  quizColourOf: (sku: { name?: string; colour_en?: string; swatch?: string }, pal: Rule["palettes"]) => Shares;
  quizStyleColours: (v: { items?: unknown[]; decor?: unknown[] }, pal: Rule["palettes"]) => Shares;
};
const rule = JSON.parse(readFileSync("tools/scout/rules/quiz.json", "utf8")) as Rule;
const golden = JSON.parse(readFileSync("tests/fixtures/quiz-golden.json", "utf8")) as Golden;

describe("quizPick — эталоны «ответы → 3 стиля»", () => {
  it("эталоны сняты с этой версии правила; их 15–20, у каждого причина", () => {
    expect(golden.rule).toBe(rule.version);
    expect(golden.cases.length).toBeGreaterThanOrEqual(15);
    expect(golden.cases.length).toBeLessThanOrEqual(20);
    golden.cases.forEach((c) => expect(c.why.length, c.id).toBeGreaterThan(10));
  });

  for (const c of golden.cases) {
    it(`${c.id}: ${c.why}`, () => {
      expect(page.quizPick(rule, c.answers, c.available ?? golden.available, c.styleColours ?? golden.styleColours)).toEqual(c.expect);
    });
  }

  it("всегда разные стили, только из доступных, ровно min(3, доступно)", () => {
    const av = golden.available, [a0, a1] = av as [string, string], [f0, f1, , f3] = rule.palettes.families as [string, string, string, string];
    for (const p of [[], ...av.map((a) => [a]), [a0, a1]]) for (const col of [[], [f0], [f1, f3]]) {
      const r = page.quizPick(rule, { photos: p, colours: col }, av, golden.styleColours);
      expect(new Set(r).size).toBe(3);
      r.forEach((id) => expect(av).toContain(id));
      p.forEach((id) => expect(r).toContain(id));      // выбранное на фото всегда в тройке
    }
  });

  it("больше двух фото и незнакомый цвет — не ломают подбор", () => {
    const av = golden.available, sc = golden.styleColours, [a0, a1, a2] = av as [string, string, string];
    expect(page.quizPick(rule, { photos: [a0, a1, a2] }, av, sc).slice(0, 2).sort()).toEqual([a0, a1].sort());
    expect(page.quizPick(rule, { colours: ["pink"] }, av, sc)).toEqual(av.slice(0, 3));
  });
});

describe("quizColourOf — цвет предмета → семейство вопроса 3", () => {
  const pal = rule.palettes;
  it.each([
    [{ colour_en: "graphite bouclé" }, "cool"],
    [{ colour_en: "light grey velour" }, "light"],
    [{ colour_en: "dark beige ceramic/walnut" }, "warm"],
    [{ colour_en: "olive velour" }, "warm"],
    [{ colour_en: "turquoise" }, "accent"],
    [{ name: "Стул Торвалль", swatch: "#fffffe" }, "light"],
    [{ name: "Ковер Котри Серый 160x230" }, "cool"],
  ])("%o → %s", (sku, fam) => {
    const c = page.quizColourOf(sku, pal);
    expect(Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0]).toBe(fam);
  });

  it("составной цвет делится долями (обивка — первая), предмет без цвета — пусто", () => {
    const c = page.quizColourOf({ colour_en: "beige/natural velour" }, pal);
    expect(c.light).toBeCloseTo(0.67, 2);
    expect(c.warm).toBeCloseTo(0.33, 2);
    expect(page.quizColourOf({ name: "Ваза Glasar 15х15х21см" }, pal)).toEqual({});
  });

  it("доли стиля — по весу роли, в сумме 1", () => {
    const s = page.quizStyleColours({ items: [{ role: "диван", sku: { name: "a", colour_en: "grey" } }, { role: "стул 2", sku: { name: "b", colour_en: "white" } }] }, pal);
    expect(s.cool).toBeCloseTo(0.75, 3);
    expect(s.light).toBeCloseTo(0.25, 3);
  });
});
