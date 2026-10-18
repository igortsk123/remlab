import { describe, expect, it } from "vitest";
import { safeParse } from "zod/mini";

import {
  addFavorite, basketTotals, basketV2, emptyBasket, evaluate, include, loadBasket, migrateV1, nextName, preview, quoteRoom,
  removeFavorite, type BasketV2, type FavoriteRef, type QuoteOption, type RoomQuote,
} from "@/lib/basket/basket";

// КОРЗИНА СЕРТИФИКАТА (demo-16 шаг 2, «Решения владельца 18.10», критика Codex 18.10): 0 на старте, первый вариант комнаты
// включается сам, если влезает; второй — вопрос «вместо?»; не влезает — в избранное без включения с суммой превышения;
// неизвестная цена — «неполный итог», не ноль; включение — только через ворота лимита.

const LIMIT = 470_000;
const id = (n: number) => `fav${String(n).padStart(19, "0")}`;
const q = (amount: number, extra: Partial<RoomQuote> = {}): RoomQuote => ({ status: "fresh", currency: "RUB", at: 1,
  lines: [{ chargeKey: "shop:1_a", roomId: "living", label: "диван", settlement: "allowance", amount, priceStatus: "known", source: "shop" }], ...extra });
const fav = (n: number, quote: RoomQuote, room = "living", at = n): FavoriteRef => ({ favoriteId: id(n), editToken: null, roomId: room,
  roomKind: room === "kitchen" ? "kitchen" : "living", styleId: "scandi", stateId: "s1-x", sourceVariantId: "set1",
  displayName: `Гостиная #${n}`, autoName: true, createdAt: at, quote });
const with_ = (...fs: FavoriteRef[]): BasketV2 => fs.reduce((b, f) => addFavorite(b, f), emptyBasket("flat215"));

describe("строки комнаты", () => {
  const OPTS: QuoteOption[] = [
    { id: "flooring", roomKind: "living", roomId: "living", title: "Пол", settlement: "developer_surcharge", defaultVariantId: "lam",
      variants: [{ id: "lam", price: { type: "included", amount: null } }, { id: "oak", price: { type: "surcharge", amount: 52_000 } }] },
    { id: "kitchen", roomKind: "kitchen", roomId: "kitchen", title: "Кухня", settlement: "allowance", defaultVariantId: "k1",
      variants: [{ id: "k1", price: { type: "on_request", amount: null } }] },
  ];
  const base = { roomId: "living", roomKind: "living", currency: "RUB", at: 5, toCard: (r: number) => r, options: OPTS };

  it("одинаковые товары — одна покупка с учётом упаковки, декор в счёте, неизвестная цена — не ноль", () => {
    const stool = { sid: "1_stool", name: "Табурет", price: 3000, pack: 2 };
    const r = quoteRoom({ ...base, developerOptions: {},
      items: [{ role: "стул", sku: stool }, { role: "стул 2", sku: stool }, { role: "стул 3", sku: stool }, { role: "диван", sku: { sid: "2_s", name: "Диван", price: 50_000 } },
        { role: "торшер", sku: { sid: "3_l", name: "Торшер" } }],
      decor: [{ role: "ваза", sku: { sid: "4_v", name: "Ваза", price: 900 } }] });
    expect(r.lines.find((l) => l.chargeKey === "shop:1_stool")?.amount).toBe(6000);           // 3 места, упаковка 2 → 2 упаковки
    expect(r.lines.find((l) => l.chargeKey === "shop:4_v")?.amount).toBe(900);
    expect(r.lines.find((l) => l.chargeKey === "shop:3_l")).toMatchObject({ amount: null, priceStatus: "unavailable" });
    expect(r.lines.some((l) => l.chargeKey === "dev:flooring")).toBe(false);                    // ламинат — в цене квартиры
    expect(r.lines.some((l) => l.chargeKey === "dev:kitchen")).toBe(false);                     // кухня — не эта комната
  });

  it("опция застройщика: доплата — строкой вне сертификата; исчезнувший вариант — unavailable, не «по умолчанию»", () => {
    const oak = quoteRoom({ ...base, items: [], decor: [], developerOptions: { flooring: "oak" } });
    expect(oak.lines).toEqual([expect.objectContaining({ chargeKey: "dev:flooring", amount: 52_000, settlement: "developer_surcharge", priceStatus: "known" })]);
    const gone = quoteRoom({ ...base, items: [], decor: [], developerOptions: { flooring: "marble" } });
    expect(gone.lines[0]).toMatchObject({ priceStatus: "unavailable", amount: null });
    const kitchen = quoteRoom({ ...base, roomId: "kitchen", roomKind: "kitchen", items: [], decor: [], developerOptions: {} });
    expect(kitchen.lines[0]).toMatchObject({ chargeKey: "dev:kitchen", priceStatus: "on_request" });
  });

  it("валюта карточки: рубли витрины переводятся один раз на строку", () => {
    const r = quoteRoom({ ...base, currency: "GBP", toCard: (rub) => rub / 100, developerOptions: {}, decor: [],
      items: [{ role: "диван", sku: { sid: "2_s", name: "Диван", price: 50_050 } }] });
    expect(r.lines[0]?.amount).toBe(501);
  });
});

describe("решения корзины", () => {
  it("0 на старте; первый вариант комнаты влезает — включается", () => {
    expect(basketTotals(emptyBasket("flat215"), LIMIT).allowanceEligible).toBe(0);
    const b = with_(fav(1, q(168_000)));
    expect(evaluate(b, "living", q(168_000), LIMIT)).toEqual({ kind: "included" });
    const r = include(b, id(1), LIMIT);
    expect(r.result).toBe("included");
    expect(basketTotals(r.basket, LIMIT)).toMatchObject({ allowanceEligible: 168_000, allowanceComplete: true });
  });

  it("второй вариант той же комнаты — вопрос «вместо …?»; превышение считается от корзины БЕЗ этой комнаты", () => {
    let b = include(with_(fav(1, q(168_000)), fav(2, q(200_000))), id(1), LIMIT).basket;
    b = include(addFavorite(b, fav(3, q(250_000), "kitchen")), id(3), LIMIT).basket;   // кухня 250 000 включена
    expect(evaluate(b, "living", q(200_000), LIMIT)).toEqual({ kind: "ask_replace", currentId: id(1) });   // 250 + 200 ≤ 470
    expect(evaluate(b, "living", q(240_000), LIMIT)).toEqual({ kind: "over_limit", overBy: 20_000 });       // 250 + 240 − 470
  });

  it("не влезает — ворота не пускают и ручное включение; корзина не меняется", () => {
    const b = with_(fav(1, q(500_000)));
    const r = include(b, id(1), LIMIT);
    expect(r).toMatchObject({ result: "over_limit", overBy: 30_000 });
    expect(r.basket.includedByRoom).toEqual({});
  });

  it("цена не досчитана — включать нельзя (ни сам, ни вручную)", () => {
    const pending = q(100_000, { status: "pending" });
    expect(evaluate(emptyBasket("flat215"), "living", pending, LIMIT)).toEqual({ kind: "price_pending" });
    const unknownSofa = q(0, { lines: [{ chargeKey: "shop:x", roomId: "living", label: "диван", settlement: "allowance", amount: null, priceStatus: "unavailable", source: "shop" }] });
    expect(include(with_(fav(1, unknownSofa)), id(1), LIMIT).result).toBe("price_pending");
  });

  it("итог: неизвестная доплата застройщику не мешает лимиту, но итог неполный; кэш не досчитан — тоже неполный", () => {
    const withDev = q(100_000); withDev.lines.push({ chargeKey: "dev:kitchen", roomId: "living", label: "Кухня", settlement: "allowance", amount: 52_000, priceStatus: "known", source: "developer" },
      { chargeKey: "dev:flooring", roomId: "living", label: "Пол", settlement: "developer_surcharge", amount: null, priceStatus: "on_request", source: "developer" });
    const b = include(with_(fav(1, withDev)), id(1), LIMIT).basket;
    expect(basketTotals(b, LIMIT)).toMatchObject({ allowanceEligible: 152_000, allowanceComplete: true, complete: false, onRequest: ["Пол"] });
    const stale = { ...b, favorites: b.favorites.map((f) => ({ ...f, quote: { ...f.quote, status: "pending" as const } })) };
    expect(basketTotals(stale, LIMIT)).toMatchObject({ allowanceComplete: false, pendingRooms: ["living"] });
  });

  it("окно: «с этой гостиной» — корзина без комнаты плюс черновик, замена, а не сложение", () => {
    const b = include(with_(fav(1, q(168_000))), id(1), LIMIT).basket;
    const p = preview(b, "living", q(150_000), LIMIT);
    expect(p.base.allowanceEligible).toBe(0);
    expect(p.with.allowanceEligible).toBe(150_000);
  });

  it("удалили включённый — включается старейший оставшийся этой комнаты, если влезает; не влезает — комната пустая", () => {
    let b = with_(fav(1, q(100_000), "living", 10), fav(2, q(120_000), "living", 30), fav(3, q(110_000), "living", 20));
    b = include(b, id(2), LIMIT).basket;
    expect(removeFavorite(b, id(2), LIMIT).includedByRoom).toEqual({ living: id(1) });        // старейший по времени (10), а первым в списке стоит №3
    const big = include(with_(fav(1, q(100_000), "living", 10), fav(2, q(480_000), "living", 5)), id(1), LIMIT).basket;
    expect(removeFavorite(big, id(1), LIMIT).includedByRoom).toEqual({});                     // старейший не влезает — к следующему не прыгаем
  });
});

describe("хранилище и имена", () => {
  it("контракт: включён вариант другой комнаты или повтор id — ошибка; загрузка чинит поштучно", () => {
    const b = include(with_(fav(1, q(1)), fav(2, q(1), "kitchen")), id(1), LIMIT).basket;
    expect(safeParse(basketV2, { ...b, includedByRoom: { kitchen: id(1) } }).success).toBe(false);
    expect(safeParse(basketV2, { ...b, favorites: [...b.favorites, b.favorites[0]] }).success).toBe(false);
    const broken = { ...b, favorites: [...b.favorites, { favoriteId: "плохой" }], includedByRoom: { living: id(1), kitchen: id(1) } };
    const l = loadBasket(broken, { apartmentId: "flat215", currency: "RUB" });
    expect(l.favorites.map((f) => f.favoriteId).sort()).toEqual([id(1), id(2)]);
    expect(l.includedByRoom).toEqual({ living: id(1) });
  });

  it("корзина другой квартиры — пустая этой; другая валюта — строки к пересчёту", () => {
    const b = with_(fav(1, q(1)));
    expect(loadBasket(b, { apartmentId: "demo-uk-215", currency: "GBP" }).favorites).toEqual([]);
    expect(loadBasket(b, { apartmentId: "flat215", currency: "GBP" }).favorites[0]?.quote.status).toBe("pending");
  });

  it("имя «<Комната> #N» — по комнате, N = наибольший + 1", () => {
    const b = with_(fav(1, q(1)), fav(3, q(1)), { ...fav(4, q(1), "kitchen"), displayName: "Кухня #7" });
    expect(nextName(b, "living", "Гостиная")).toBe("Гостиная #4");
    expect(nextName(b, "kitchen", "Кухня")).toBe("Кухня #8");
    expect(nextName(b, "bedroom-1", "Спальня 1")).toBe("Спальня 1 #1");
  });

  it("перенос demo-15: автоимена «<Стиль> #N» → «Гостиная #k» по порядку создания, свои имена — как были, ничего не включено", () => {
    const old = [
      { collectionId: id(7), displayName: "Сканди #2", createdAt: 20, styleId: "scandi" },
      { collectionId: id(8), displayName: "Гостиная мечты", createdAt: 30, styleId: "loft" },
      { collectionId: id(9), displayName: "Лофт #1", createdAt: 10, styleId: "loft" },
      // своё имя той же формы неотличимо от автоимени — переписывается (эвристика, Codex 18.10 п.12)
      { collectionId: id(10), displayName: "Минимализм #5", createdAt: 40, styleId: "minimal" },
    ];
    const b = migrateV1(emptyBasket("flat215"), old, { id: "living", kind: "living", title: "Гостиная" }, ["Сканди", "Лофт", "Минимализм"], "RUB");
    const name = (n: number) => b.favorites.find((f) => f.favoriteId === id(n))?.displayName;
    expect([name(9), name(7), name(8), name(10)]).toEqual(["Гостиная #1", "Гостиная #2", "Гостиная мечты", "Гостиная #3"]);
    expect(b.includedByRoom).toEqual({});
    expect(b.favorites.every((f) => f.quote.status === "pending")).toBe(true);
    expect(migrateV1(b, old, { id: "living", kind: "living", title: "Гостиная" }, [], "RUB").favorites.length).toBe(4);   // повтор — без дублей
  });
});
