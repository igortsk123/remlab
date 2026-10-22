import { describe, expect, it } from "vitest";

import type { ApartmentRef, Complex, Partner } from "@/contracts/partner";
import { addFavorite, basketTotals, emptyBasket, evaluate, include, quoteRoom, type FavoriteRef, type QuoteOption, type RoomQuote } from "@/lib/basket/basket";
import { budgetBucket } from "@/lib/configurator/budget";
import { upgradeQuote } from "@/lib/configurator/repo";
import { settle, type BudgetPolicy } from "@/lib/configurator/settlement";
import { resolveIncentive } from "@/lib/partners/incentive";

// ДВА БЮДЖЕТА ПАКЕТА (demo-23, разбор Codex 22.10): «Мебель и техника» / «Улучшения», объединённые (pooled) или раздельные (split,
// перенос запрещён); перерасход — доплата покупателя, а не отказ; «вне пакета» (settlement не allowance) ≠ «лимит 0».

const SPLIT: BudgetPolicy = { mode: "split", limits: { furniture: 4500, fitout: 8000 } };
const POOLED: BudgetPolicy = { mode: "pooled", limits: { furniture: 600_000, fitout: 0 } };
const fur = (amount: number) => ({ amount, settlement: "allowance" as const, budgetBucket: "furniture" as const });
const fit = (amount: number) => ({ amount, settlement: "allowance" as const, budgetBucket: "fitout" as const });

describe("бюджет позиции — по таксономии, без списков", () => {
  it("товар магазина и техника — мебель; покрытие и встроенное — улучшения", () => {
    expect(budgetBucket({ source: "shop" })).toBe("furniture");
    expect(budgetBucket({ slotKind: "furniture" })).toBe("furniture");
    expect(budgetBucket({ slotKind: "surface", slotCategory: "flooring" })).toBe("fitout");
    expect(budgetBucket({ slotKind: "builtin", slotCategory: "kitchen" })).toBe("fitout");
    expect(budgetBucket({ slotKind: "builtin", slotCategory: "appliances" })).toBe("furniture");   // встроенная техника — к мебели
    expect(budgetBucket({ groupKind: "appliances" })).toBe("furniture");
    for (const k of ["kitchen", "wardrobe", "bathroom", "flooring", "walls"]) expect(budgetBucket({ groupKind: k })).toBe("fitout");
  });
});

describe("покрытие пакета", () => {
  it("split: остаток одного бюджета другой не покрывает — доплата при остатке", () => {
    const t = settle([fur(6000), fit(2000)], SPLIT);
    expect(t.budget.covered).toEqual({ furniture: 4500, fitout: 2000, total: 6500 });
    expect(t.budget.overage).toEqual({ furniture: 1500, fitout: 0, total: 1500 });
    expect(t.budget.left).toEqual({ total: 6000, furniture: 0, fitout: 6000 });
    expect(t).toMatchObject({ allowanceEligible: 8000, allowanceCovered: 6500, allowanceOverage: 1500 });
  });

  it("pooled: общий остаток на двоих, по бюджетам остатка нет", () => {
    const t = settle([fur(500_000), fit(80_000)], POOLED);
    expect(t.budget.covered.total).toBe(580_000);
    expect(t.budget.overage.total).toBe(0);
    expect(t.budget.left).toEqual({ total: 20_000, furniture: null, fitout: null });
    const over = settle([fur(500_000), fit(150_000)], POOLED);
    expect(over.budget.overage).toEqual({ furniture: 0, fitout: 50_000, total: 50_000 });  // сначала мебель, остаток — улучшениям
  });

  it("лимит 0 в split — всё в этом бюджете доплатой; «вне пакета» — не перерасход вовсе", () => {
    const noFitout: BudgetPolicy = { mode: "split", limits: { furniture: 4500, fitout: 0 } };
    const t = settle([fur(1000), fit(3000), { amount: 54_000, settlement: "developer_surcharge" }, { amount: 900, settlement: "property_price" }], noFitout);
    expect(t.budget.overage).toEqual({ furniture: 0, fitout: 3000, total: 3000 });
    expect(t.developerSurcharge).toBe(54_000);
    expect(t.propertyPriceDelta).toBe(900);
    expect(t.allowanceOverage).toBe(3000);
  });

  it("лимит числом — прежний контракт: одна сумма, строки без бюджета — мебель", () => {
    const t = settle([{ amount: 300_000, settlement: "allowance" }, fit(250_000)], 470_000);
    expect(t.budget.mode).toBe("pooled");
    expect(t.budget.limits).toEqual({ furniture: 470_000, fitout: 0, total: 470_000 });
    expect(t).toMatchObject({ allowanceEligible: 550_000, allowanceCovered: 470_000, allowanceOverage: 80_000 });
  });
});

describe("пакет квартиры: квартира → ЖК → партнёр, ближайший — целиком", () => {
  const partner = (extra: Partial<Partner> = {}) => ({ currency: "GBP", certificateShare: 0.05, ...extra }) as Partner;
  const apt = (extra: Partial<ApartmentRef> = {}) => ({ price: 250_000, ...extra }) as ApartmentRef;
  const cx = (extra: Partial<Complex> = {}) => ({ ...extra }) as Complex;

  it("нет политики ни на одном уровне — прежний сертификат одной суммой в мебели", () => {
    expect(resolveIncentive(partner(), undefined, apt())).toEqual({ mode: "pooled", limits: { furniture: 12_500, fitout: 0 }, total: 12_500, source: "legacy" });
    expect(resolveIncentive(partner({ certificateShare: 0 }), undefined, apt())).toBeNull();
  });

  it("ближайший уровень заменяет политику целиком, поля не смешиваются", () => {
    const p = partner({ incentive: SPLIT });
    expect(resolveIncentive(p, undefined, apt())).toMatchObject({ mode: "split", limits: SPLIT.limits, total: 12_500, source: "partner" });
    const c = cx({ incentive: { mode: "pooled", limits: { furniture: 9000, fitout: 0 } } });
    expect(resolveIncentive(p, c, apt())).toEqual({ mode: "pooled", limits: { furniture: 9000, fitout: 0 }, total: 9000, source: "complex" });
    const a = apt({ incentive: { mode: "split", limits: { furniture: 0, fitout: 3000 } } });
    expect(resolveIncentive(p, c, a)).toEqual({ mode: "split", limits: { furniture: 0, fitout: 3000 }, total: 3000, source: "apartment" });
  });

  it("политика с нулями — пакета нет (не откат к прежнему сертификату)", () => {
    expect(resolveIncentive(partner({ incentive: { mode: "pooled", limits: { furniture: 0, fitout: 0 } } }), undefined, apt())).toBeNull();
  });
});

describe("корзина: перерасход — доплата с подтверждением", () => {
  const id = (n: number) => `fav${String(n).padStart(19, "0")}`;
  const q = (lines: RoomQuote["lines"]): RoomQuote => ({ status: "fresh", currency: "GBP", at: 1, lines });
  const line = (amount: number, bucket: "furniture" | "fitout" | undefined, key = "shop:1_a"): RoomQuote["lines"][number] => ({
    chargeKey: key, roomId: "living", label: "x", settlement: "allowance", amount, priceStatus: "known", source: "shop",
    ...(bucket ? { budgetBucket: bucket } : {}) });
  const fav = (n: number, quote: RoomQuote, room = "living"): FavoriteRef => ({ favoriteId: id(n), editToken: null, roomId: room,
    roomKind: "living", styleId: "scandi", stateId: "s1-x", sourceVariantId: "set1", displayName: `#${n}`, autoName: true, createdAt: n, quote });

  it("split: мебель сверх лимита при остатке улучшений — included_with_topup, без подтверждения корзина та же", () => {
    const b = addFavorite(emptyBasket("flat"), fav(1, q([line(5000, "furniture")])));
    expect(evaluate(b, "living", b.favorites[0]!.quote, SPLIT)).toEqual({ kind: "included_with_topup", overBy: 500, topup: { overBy: 500, furniture: 500, fitout: 0 } });
    const no = include(b, id(1), SPLIT);
    expect(no).toMatchObject({ result: "topup_unconfirmed", overBy: 500 });
    expect(no.basket).toBe(b);
    const yes = include(b, id(1), SPLIT, { confirmTopup: true });
    expect(yes.result).toBe("included_with_topup");
    expect(yes.basket.includedByRoom.living).toBe(id(1));
    expect(basketTotals(yes.basket, SPLIT).budget.left).toEqual({ total: 8000, furniture: 0, fitout: 8000 });
  });

  it("занятое место и перерасход — вопрос «вместо?» с доплатой", () => {
    let b = addFavorite(emptyBasket("flat"), fav(1, q([line(1000, "furniture")])));
    b = include(b, id(1), SPLIT).basket;
    b = addFavorite(b, fav(2, q([line(9000, "fitout")])));
    expect(evaluate(b, "living", b.favorites.find((f) => f.favoriteId === id(2))!.quote, SPLIT)).toEqual({ kind: "ask_replace", currentId: id(1), topup: { overBy: 1000, furniture: 0, fitout: 1000 } });
  });

  it("лимит числом — прежний отказ over_limit (страница демо до шага 3)", () => {
    const b = addFavorite(emptyBasket("flat"), fav(1, q([line(5000, undefined)])));
    expect(include(b, id(1), 4500, { confirmTopup: true })).toMatchObject({ result: "over_limit", overBy: 500 });
  });

  it("строки комнаты: товар — мебель, опция застройщика — по виду группы, вне пакета — без бюджета", () => {
    const opts: QuoteOption[] = [
      { id: "kit", roomKind: "living", roomId: "living", title: "Кухня", settlement: "allowance", kind: "kitchen", defaultVariantId: "k",
        variants: [{ id: "k", price: { type: "surcharge", amount: 7000 } }] },
      { id: "app", roomKind: "living", roomId: "living", title: "Техника", settlement: "allowance", kind: "appliances", defaultVariantId: "a",
        variants: [{ id: "a", price: { type: "surcharge", amount: 900 } }] },
      { id: "floor", roomKind: "living", roomId: "living", title: "Пол", settlement: "property_price", kind: "flooring", defaultVariantId: "f",
        variants: [{ id: "f", price: { type: "surcharge", amount: 1150 } }] },
    ];
    const r = quoteRoom({ roomId: "living", roomKind: "living", currency: "GBP", at: 1, toCard: (x: number) => x, options: opts, developerOptions: {},
      items: [{ role: "диван", sku: { sid: "2_s", name: "Диван", price: 800 } }], decor: [] });
    const by = Object.fromEntries(r.lines.map((l) => [l.chargeKey, l.budgetBucket]));
    expect(by).toEqual({ "shop:2_s": "furniture", "dev:kit": "fitout", "dev:app": "furniture", "dev:floor": undefined });
  });
});

describe("снимок цены из базы", () => {
  it("разбивка доплат, бюджеты и пакет не теряются; кривые поля — как у старого снимка", () => {
    const qt = upgradeQuote({ basePrice: 1, upgrades: 2, total: 3, currency: "GBP", lines: [], computedAt: "x",
      bySettlement: { allowance: 10, developer_surcharge: 0, property_price: 5 }, byBudget: { furniture: 7, fitout: 3 },
      incentive: { mode: "split", limits: { furniture: 4500, fitout: 8000 } } });
    expect(qt.bySettlement).toEqual({ allowance: 10, developer_surcharge: 0, property_price: 5 });
    expect(qt.byBudget).toEqual({ furniture: 7, fitout: 3 });
    expect(qt.incentive).toEqual({ mode: "split", limits: { furniture: 4500, fitout: 8000 } });
    const old = upgradeQuote({ basePrice: 1, upgrades: 0, total: 1, lines: [], bySettlement: { allowance: "x" }, incentive: { mode: "other" } });
    expect(old).not.toHaveProperty("bySettlement");
    expect(old).not.toHaveProperty("byBudget");
    expect(old).not.toHaveProperty("incentive");
  });
});
