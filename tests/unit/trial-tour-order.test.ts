import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ОБСТАВЛЕННАЯ ПЛИТКА ТУРА — ПЕРВОЙ (T-20261110-14). Чистая функция — блок TOURFIRST страницы демо (`trFurnishedFirst`, вызов —
// ветка тура `homeRooms`); тест читает блок из страницы, как REALSHOT.
const SRC = "tools/scout/flat215-demo/index.html";
type Room = { id: string; out?: string };

const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// TOURFIRST START"), src.indexOf("// TOURFIRST END"));
const trFurnishedFirst = new Function(`${block};return trFurnishedFirst;`)() as (list: Room[], outcomeOf: (r: Room) => string | undefined) => Room[];
const order = (...rooms: [string, string | undefined][]) =>
  trFurnishedFirst(rooms.map(([id, out]) => ({ id, out })), (r) => r.out).map((r) => r.id);

describe("trFurnishedFirst — порядок плиток тура", () => {
  it("первая — «нет товаров» / «нет входа» / «нет места», обставленная есть → первая обставленная вперёд, прочие по порядку", () => {
    expect(order(["pb", "no_products"], ["b2", "furnished"], ["b3", "furnished"], ["lv", "no_space"])).toEqual(["b2", "pb", "b3", "lv"]);
    expect(order(["pb", "not_readable"], ["k", "not_furnished"], ["b2", "furnished"])).toEqual(["b2", "pb", "k"]);
    expect(order(["lv", "no_space"], ["b2", "furnished"])).toEqual(["b2", "lv"]);
  });
  it("первая обставлена, подбирается, ждёт проверки или не обставляется — порядок как есть", () => {
    expect(order(["lv", "furnished"], ["pb", "no_products"])).toEqual(["lv", "pb"]);
    expect(order(["lv", "pending"], ["b2", "furnished"])).toEqual(["lv", "b2"]);
    expect(order(["lv", "awaiting"], ["b2", "furnished"])).toEqual(["lv", "b2"]);
    expect(order(["k", "not_furnished"], ["b2", "furnished"])).toEqual(["k", "b2"]);
    expect(order(["lv", undefined], ["b2", "furnished"])).toEqual(["lv", "b2"]);
  });
  it("обставленной нет — порядок как есть; пустой список — пустой", () => {
    expect(order(["pb", "no_products"], ["lv", "no_space"])).toEqual(["pb", "lv"]);
    expect(order()).toEqual([]);
  });
});
