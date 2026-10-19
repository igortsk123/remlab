import { describe, expect, it } from "vitest";
import { alternatives, candidates, feedForStyle, placeOf, sameShape, type FeedItem } from "@/lib/configurator/demo-feeds";

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

// demo-18 п.2: ковёр — плита, сравнение длинной с длинной; длинная сторона не короче дивана расстановки
describe("ленты замен: ковёр", () => {
  const rug = (sid: string, w: number, d: number): FeedItem => ({ name: `Ковёр ${sid}`, sid, msid: sid, img: "i", w, d, h: 1, price: 1 });

  it("место ковра: длинная сторона не короче дивана той же расстановки; без дивана — без условия", () => {
    const items = [{ role: "диван", w: 186, d: 90 }, { role: "ковёр", w: 160, d: 230, sku: { msid: "r0" } }];
    expect(placeOf(items[1]!, items)).toEqual({ w: 160, d: 230, model: "r0", corner: false, cornerLeft: false, rug: true, minLong: 186 });
    expect(placeOf(items[1]!, [items[1]!])).not.toHaveProperty("minLong");
    expect(placeOf(items[0]!, items)).not.toHaveProperty("rug");
  });

  it("порядок — по длинной и короткой стороне независимо от записи w/d; короче дивана — мимо", () => {
    const feed = [rug("long", 300, 200), rug("same", 230, 160), rug("turned", 160, 230), rug("short", 180, 140)];
    const place = { w: 160, d: 230, rug: true, minLong: 186 };
    expect(alternatives(feed, place, new Set()).map((p) => p.sid)).toEqual(["same", "turned", "long"]);
    expect(alternatives(feed, { ...place, minLong: undefined }, new Set()).map((p) => p.sid)).toEqual(["same", "turned", "short", "long"]);
  });
});

// demo-18 п.2: товар чужого набора виден в стиле, только если пул отобрал его и для этого стиля (`styles`)
describe("ленты замен: стиль", () => {
  it("свой набор и подтверждённые пулом стили — да, чужой набор без балла стиля — нет; без `styles` — по стилю набора", () => {
    const feed: FeedItem[] = [
      { sid: "own", src: "set", style: "джапанди", styles: ["джапанди"] },
      { sid: "other", src: "set", style: "сканди", styles: ["сканди"] },
      { sid: "both", src: "set", style: "сканди", styles: ["сканди", "джапанди"] },
      { sid: "pool", src: "pool", style: "джапанди", styles: ["джапанди"] },
      { sid: "old", src: "set", style: "джапанди" },
    ];
    expect(feedForStyle(feed, "джапанди").map((p) => p.sid)).toEqual(["own", "both", "pool", "old"]);
  });
});
