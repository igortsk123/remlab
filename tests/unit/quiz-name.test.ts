import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { cleanGreetName, linkWithName } from "@/lib/quiz/name";

// ИМЯ ДЛЯ ПРИВЕТСТВИЯ (onb-03 Т2, ADR-0330 п.4). Чистые функции страницы — блок QUIZNAME; пока опроса на странице нет, блок
// живёт в `tools/ops/quiz-name.mjs`, onb-03 переносит его дословно в `index.html` и меняет здесь только SRC (как QUIZPICK).
const SRC = "tools/ops/quiz-name.mjs";
const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// QUIZNAME START"), src.indexOf("// QUIZNAME END"));
const page = new Function(`${block};return {nameFromHash,quizCleanName};`)() as {
  nameFromHash: (hash: string) => { name: string; hash: string };
  quizCleanName: (s: string) => string;
};
const enc = encodeURIComponent;

describe("nameFromHash — имя из #n= и адрес без него", () => {
  it.each([
    ["кириллица", `#n=${enc("Анна")}`, "Анна", ""],
    ["кириллица без кодирования", "#n=Анна", "Анна", ""],
    ["латиница", "#n=Anna", "Anna", ""],
    ["двойное имя через дефис и пробел", `#n=${enc("Анна-Мария Петрова")}`, "Анна-Мария Петрова", ""],
    ["плюс — пробел", "#n=Anna+Maria", "Anna Maria", ""],
    ["лишние пробелы схлопываются", `#n=${enc("  Анна   Мария ")}`, "Анна Мария", ""],
    ["ё и диакритика", `#n=${enc("Пётр")}`, "Пётр", ""],
    ["телефон — отброс", `#n=${enc("+7 913 000-00-00")}`, "", ""],
    ["цифры в имени — отброс", "#n=Anna2", "", ""],
    ["31 символ — отброс целиком", `#n=${"а".repeat(31)}`, "", ""],
    ["30 символов — годится", `#n=${enc("а".repeat(30))}`, "а".repeat(30), ""],
    ["только дефисы — отброс", "#n=---", "", ""],
    ["разметка — отброс", `#n=${enc("<b>Анна</b>")}`, "", ""],
    ["битое %-кодирование — отброс", "#n=%E0%A4%A", "", ""],
    ["пустое", "#n=", "", ""],
    ["с вариантом после имени", `#n=${enc("Анна")}&v=s1-abc`, "Анна", "#v=s1-abc"],
    ["с вариантом до имени", `#v=s1-abc&n=${enc("Анна")}`, "Анна", "#v=s1-abc"],
    ["негодное имя всё равно стёрто, вариант цел", "#v=s1-abc&n=79130000000", "", "#v=s1-abc"],
  ])("%s", (_why, hash, name, rest) => {
    expect(page.nameFromHash(hash)).toEqual({ name, hash: rest });
  });

  it("без n= адрес не меняется: #v=, #c=, #fav, #plan, пусто", () => {
    for (const h of ["#v=s1-abc", "#c=AbCdEfGhIjKlMnOpQrStUv", "#fav", "#plan", "", "#"]) expect(page.nameFromHash(h)).toEqual({ name: "", hash: h === "#" ? "" : h });
  });

  it("повтор n= — берётся первое, оба стёрты", () => {
    expect(page.nameFromHash("#n=Anna&n=Olga")).toEqual({ name: "Anna", hash: "" });
  });
});

describe("ссылка менеджера с именем", () => {
  const URL0 = "https://remont-lab.online/demo/?s=AbCdEfGhIjKlMnOpQrStUv";

  it("правило имени одно у менеджера и у страницы", () => {
    for (const s of ["Анна", " Анна  Мария ", "Anna2", "+7 913", "а".repeat(31), "Jean-Luc", "", "Zoë"]) expect(cleanGreetName(s)).toBe(page.quizCleanName(s));
  });

  it("имя доходит до страницы как есть; пустое и негодное — ссылка без #n=", () => {
    for (const n of ["Анна", "Анна-Мария Петрова", "Anna Maria", "Пётр"]) {
      const link = linkWithName(URL0, n);
      expect(link.startsWith(`${URL0}#n=`)).toBe(true);
      expect(page.nameFromHash(link.slice(link.indexOf("#")))).toEqual({ name: n, hash: "" });
    }
    expect(linkWithName(URL0, "")).toBe(URL0);
    expect(linkWithName(URL0, "+7 913 000-00-00")).toBe(URL0);
  });

  it("прежнее имя заменяется, остальной фрагмент сохраняется", () => {
    expect(linkWithName(`${URL0}#n=Olga&v=s1`, "Anna")).toBe(`${URL0}#n=Anna&v=s1`);
    expect(linkWithName(`${URL0}#n=Olga`, "")).toBe(URL0);
  });
});
