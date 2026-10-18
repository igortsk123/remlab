import { describe, expect, it } from "vitest";
import { alternatives, candidates, sameShape, type FeedItem } from "@/lib/configurator/demo-feeds";

// ленты замен витрины → «Варианты» в /flat (план demo-18 п.1): разные модели раньше цветов, диван — той же формы
const item = (sid: string, msid: string, w: number, extra: Partial<FeedItem> = {}): FeedItem =>
  ({ name: `Диван ${sid}`, sid, msid, img: `img/${sid}.jpg`, w, d: 90, h: 80, price: 10_000, ...extra });

describe("ленты замен: порядок и форма", () => {
  it("сперва по одному товару на модель (ближайший по размеру), потом цвета — и цвета текущей модели в конце", () => {
    const feed = [item("a1", "A", 170), item("a2", "A", 171), item("a3", "A", 172), item("b1", "B", 180), item("c1", "C", 190),
      item("cur2", "CUR", 170)];
    const got = alternatives(feed, { w: 170, d: 90, model: "CUR" }, new Set(["cur1"])).map((p) => p.sid);
    expect(got).toEqual(["a1", "b1", "c1", "cur2", "a2", "a3"]);
  });

  it("лимит полосы режет уже упорядоченный список: 11 цветов одной модели не вытесняют другие модели", () => {
    const feed = [...Array.from({ length: 11 }, (_, k) => item(`a${k}`, "A", 170 + k / 10)), item("b1", "B", 196)];
    const got = alternatives(feed, { w: 170, d: 90 }, new Set(), 3).map((p) => p.msid);
    expect(got).toEqual(["A", "B", "A"]);
    expect(candidates(feed, { w: 170, d: 90 }, new Set())).toHaveLength(12);
  });

  it("прямой диван не меняется на угловой и наоборот; угловой с названной стороной — только на ту же сторону", () => {
    const straight = item("s", "S", 180);
    const cornerAny = item("ca", "CA", 180, { corner: true });
    const cornerLeft = item("cl", "CL", 180, { corner: true, corner_left: true });
    const cornerRight = item("cr", "CR", 180, { corner: true, corner_left: false });
    const feed = [straight, cornerAny, cornerLeft, cornerRight];
    expect(alternatives(feed, { w: 180, d: 90 }, new Set()).map((p) => p.sid)).toEqual(["s"]);
    expect(alternatives(feed, { w: 180, d: 90, corner: true, cornerLeft: true }, new Set()).map((p) => p.sid)).toEqual(["ca", "cl"]);
    expect(alternatives(feed, { w: 180, d: 90, corner: true, cornerLeft: false }, new Set()).map((p) => p.sid)).toEqual(["ca", "cr"]);
    expect(sameShape(item("x", "X", 1), { w: 1, d: 1 })).toBe(true);    // не диван: пометки нет ни у места, ни у товара
  });
});
