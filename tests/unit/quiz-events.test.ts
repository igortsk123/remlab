import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { pageCounterKind, pageEventIn } from "@/contracts/analytics";
import { QUIZ_CHILD_RU, QUIZ_COLOUR_RU, QUIZ_HOUSEHOLD_RU, QUIZ_KIDS_RU, QUIZ_STYLE_RU, quizChildAge, quizColour, quizHousehold, quizKids, quizStyle } from "@/contracts/quiz";
import { buyerEvent } from "@/contracts/send";

// СОБЫТИЯ ОПРОСА (onb-03 Т6, ADR-0330 п.4): менеджеру и застройщику — только перечисления. Словари сервера совпадают с правилом
// опроса `quiz.json` и стилями страницы демо, иначе страница пришлёт значение, которое сервер отбросит целиком.

type Opt = { id: string; ru: string; ages?: { id: string; ru: string }[]; kids?: { id: string; ru: string }[] };
type Q = { id: string; options?: Opt[] };
const rule = JSON.parse(readFileSync("tools/scout/rules/quiz.json", "utf8")) as { questions: Q[] };
const opts = (id: string) => rule.questions.find((q) => q.id === id)?.options ?? [];
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");

describe("словари опроса совпадают с правилом и страницей", () => {
  it("кто живёт, возраст детей, цвета — те же id, что в quiz.json", () => {
    expect(opts("household").map((o) => o.id)).toEqual(quizHousehold.options);
    expect(opts("household").find((o) => o.id === "child")?.ages?.map((a) => a.id)).toEqual(quizChildAge.options);
    expect(opts("household").find((o) => o.id === "child")?.kids?.map((a) => a.id)).toEqual(quizKids.options);   // сколько детей (T-94)
    expect(opts("colours").map((o) => o.id)).toEqual(quizColour.options);
  });

  it("стили — те же id, что `STYLE_IDS` страницы; русские названия — как на её вкладках", () => {
    const m = html.match(/const STYLE_IDS=(\{[^}]+\})/);
    const ids = JSON.parse(m![1]!.replace(/'/g, '"')) as Record<string, string>;
    expect(Object.values(ids).sort()).toEqual([...quizStyle.options].sort());
    for (const [ru, id] of Object.entries(ids)) expect(QUIZ_STYLE_RU[id as keyof typeof QUIZ_STYLE_RU].toLowerCase()).toBe(ru);
  });

  it("слова сигнала есть для каждого значения; цвета — словами вопроса", () => {
    expect(Object.keys(QUIZ_HOUSEHOLD_RU)).toEqual(quizHousehold.options);
    expect(Object.keys(QUIZ_CHILD_RU)).toEqual(quizChildAge.options);
    expect(Object.keys(QUIZ_KIDS_RU)).toEqual(quizKids.options);
    for (const o of opts("colours")) expect(QUIZ_COLOUR_RU[o.id as keyof typeof QUIZ_COLOUR_RU]).toBe(o.ru.toLowerCase());
  });
});

describe("сервер принимает только перечисления", () => {
  it("событие менеджеру: значения вне словаря и лишние ответы — отказ", () => {
    expect(buyerEvent.safeParse({ kind: "quiz_done", picked: ["scandi"], household: ["couple", "child"], kids: "3plus", colours: ["warm"], result: ["scandi", "loft", "modern"], chosen: "scandi" }).success).toBe(true);
    expect(buyerEvent.safeParse({ kind: "quiz_done", chosen: "Анна" }).success).toBe(false);
    expect(buyerEvent.safeParse({ kind: "quiz_done", household: ["Анна, +7 913"] }).success).toBe(false);
    expect(buyerEvent.safeParse({ kind: "quiz_done", picked: ["scandi", "loft", "modern"] }).success).toBe(false);   // на фото — не больше двух
    expect(buyerEvent.safeParse({ kind: "quiz_done", colours: ["light", "warm", "cool"] }).success).toBe(false);
    expect(buyerEvent.safeParse({ kind: "quiz_done", kids: "5" }).success).toBe(false);   // сколько детей — только 1 / 2 / 3plus
  });

  it("лишнее поле (имя) отбрасывается, а не доходит до сервера", () => {
    const r = buyerEvent.safeParse({ kind: "quiz_done", chosen: "loft", name: "Анна" });
    expect(r.success && JSON.stringify(r.data)).not.toContain("Анна");
  });

  it("счётчики застройщику: 4 действия + по одному на значение словаря — 38 видов", () => {
    const quiz = pageCounterKind.options.filter((k) => k.startsWith("quiz_") || k === "style_change");
    expect(quiz).toHaveLength(38);
    expect(new Set(pageCounterKind.options).size).toBe(pageCounterKind.options.length);
    expect(pageEventIn.safeParse({ apartmentId: "flat215", kind: "quiz_photo:loft" }).success).toBe(true);
    expect(pageEventIn.safeParse({ apartmentId: "flat215", kind: "quiz_child:5" }).success).toBe(false);
    expect(pageEventIn.safeParse({ apartmentId: "flat215", kind: "quiz_kids:3plus" }).success).toBe(true);
    expect(pageEventIn.safeParse({ apartmentId: "flat215", kind: "quiz_household:Анна" }).success).toBe(false);
  });
});
