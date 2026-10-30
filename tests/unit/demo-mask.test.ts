import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { addFavorite, emptyBasket, loadBasket, quoteRoom } from "@/lib/basket/basket";
import { maskedName, maskedRate, roleEn, styleEn } from "@/lib/configurator/demo-mask";
import { collectionAsVariant, fromDemoVariant } from "@/lib/configurator/fromDemo";
import { fxOf } from "@/lib/configurator/source";
import { apartmentCard, findApartment } from "@/lib/partners/registry";

// БРИТАНСКАЯ МАСКА АНГЛИЙСКОГО ДЕМО (demo-31, владелец 30.10): у квартиры-двойника товары витрины — цена × наценку, английские
// названия, без магазина. Функции страницы берём прямо из неё (блок DEMOMASK), мост /flat и карточку — из кода приложения.
type Flat = { currency: string; fx?: { from: string; to: string; rate: number; asOf: string } | null; demoMask?: { priceMarkup: number; englishNames: boolean; hideShops: boolean } | null };
type Names = { sid: Record<string, string>; name: Record<string, string> };
type Sku = { name?: string; name_en?: string; sid?: string; unavailable?: boolean };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// DEMOMASK START"), html.indexOf("// DEMOMASK END"));
const page = new Function(`${block};return {maskOf,fxRateOf,fxKeyOf,namesEnOf,maskName};`)() as {
  maskOf: (f: Flat | null) => Flat["demoMask"];
  fxRateOf: (f: Flat | null) => number;
  fxKeyOf: (f: Flat | null) => string;
  namesEnOf: (d: unknown) => Names;
  maskName: (p: Sku, role: string, m: Flat["demoMask"], names: Names, roleEn: (r: string) => string) => string;
};

const FX = { from: "RUB", to: "GBP", rate: 0.0089, asOf: "2026-10-16" };
const MASK = { priceMarkup: 1.5, englishNames: true, hideShops: true };
const UK: Flat = { currency: "GBP", fx: FX, demoMask: MASK };
const PLAIN: Flat = { currency: "GBP", fx: FX, demoMask: null };
const pageRoleEn = (r: string) => roleEn(r);

describe("маска: цена страницы", () => {
  it("множитель — только при маске; без маски курс как был", () => {
    expect(page.fxRateOf(UK)).toBeCloseTo(0.0089 * 1.5, 10);
    expect(page.fxRateOf(PLAIN)).toBe(0.0089);
    expect(page.fxRateOf({ currency: "RUB", fx: null, demoMask: MASK })).toBe(0);            // рублёвая витрина: курса нет — и маске нечего умножать
    expect(page.fxRateOf(null)).toBe(0);
    // диван 25 990 ₽: без маски £231, с маской £347 (= 231 × 1.5 ± £1 на округлении)
    expect(Math.round(25990 * page.fxRateOf(PLAIN))).toBe(231);
    expect(Math.round(25990 * page.fxRateOf(UK))).toBe(347);
  });

  it("ключ курса корзины: без маски — прежний «курс@дата», с маской — с наценкой", () => {
    expect(page.fxKeyOf(PLAIN)).toBe("0.0089@2026-10-16");
    expect(page.fxKeyOf(UK)).toBe("0.0089@2026-10-16x1.5");
    expect(page.fxKeyOf({ currency: "RUB" })).toBe("");
  });

  it("корзина, собранная до маски, пересчитывается; собранная с маской — нет", () => {
    const toCard = (r: number) => Math.round(r * 0.0089);
    const quote = quoteRoom({ roomId: "living", roomKind: "living", currency: "GBP", at: 1, fx: page.fxKeyOf(PLAIN), toCard,
      items: [{ role: "диван", sku: { sid: "s1", name: "Диван", price: 25990 } }], decor: [], developerOptions: {}, options: [] });
    const b = addFavorite(emptyBasket("demo-uk-215"), { favoriteId: `fav${"0".repeat(19)}`, editToken: null, roomId: "living",
      roomKind: "living", styleId: "scandi", stateId: "s1-x", sourceVariantId: "set1", displayName: "Living room #1", autoName: true,
      createdAt: 1, quote });
    const before = loadBasket(b, { apartmentId: "demo-uk-215", currency: "GBP", fx: page.fxKeyOf(PLAIN) }).favorites[0]!.quote;
    expect(before).toMatchObject({ status: "fresh", lines: [{ amount: 231 }] });
    const after = loadBasket(b, { apartmentId: "demo-uk-215", currency: "GBP", fx: page.fxKeyOf(UK) }).favorites[0]!.quote;
    expect(after).toMatchObject({ status: "pending", lines: [] });                             // £231 кэша не показываем — досчитает по £347
  });
});

describe("маска: названия страницы", () => {
  const data = { variants: [{ items: [{ role: "диван", sku: { name: "Диван прямой divan.ru Викс", name_en: "Viks straight sofa", sid: "s1" } }] }],
    feeds: { "ваза": [{ name: "Ваза Х", name_en: "Vase X", sid: "s2", price: 990 }] }, sets: [{ roles: { "стул": { name: "Стул без sid", name_en: "Chair Y" } } }] };
  const names = page.namesEnOf(data);

  it("по sid — даже у копии без name_en; без sid — по исходному названию", () => {
    expect(page.maskName({ name: "Диван прямой divan.ru Викс", sid: "s1" }, "диван", MASK, names, pageRoleEn)).toBe("Viks straight sofa");
    expect(page.maskName({ name: "Стул без sid" }, "стул 2", MASK, names, pageRoleEn)).toBe("Chair Y");
    // подборка, сохранённая до маски: русское название из снимка → английское по sid текущей витрины
    expect(page.maskName({ name: "старое русское", sid: "s2" }, "ваза", MASK, names, pageRoleEn)).toBe("Vase X");
  });

  it("не нашлось или кириллица — нейтральное по роли; пропавший товар — с пометкой по-английски", () => {
    expect(page.maskName({ name: "Неизвестный торшер" }, "торшер", MASK, names, pageRoleEn)).toBe("Floor lamp");
    expect(page.maskName({ name: "X", name_en: "Диван" }, "диван 2", MASK, names, pageRoleEn)).toBe("Sofa");
    expect(page.maskName({ name: "Y" }, "роль-неизвестна", MASK, names, () => "")).toBe("Item");
    expect(page.maskName({ name: "Ваза Х — сейчас нет в витрине", unavailable: true }, "ваза", MASK, names, pageRoleEn))
      .toBe("Vase X — no longer in the showroom");
  });

  it("без маски — исходное название как было", () => {
    expect(page.maskName({ name: "Диван прямой divan.ru Викс", sid: "s1" }, "диван", null, names, pageRoleEn)).toBe("Диван прямой divan.ru Викс");
    expect(page.maskName({ name: "Z", sid: "s1" }, "диван", { ...MASK, englishNames: false }, names, pageRoleEn)).toBe("Z");
  });
});

describe("маска: карточка квартиры и /flat", () => {
  it("маска — у британского двойника; русская квартира и вторая британская — без неё", () => {
    expect(apartmentCard(findApartment("demo-uk-215")!, "en").demoMask).toEqual(MASK);
    expect(apartmentCard(findApartment("flat215")!, "ru").demoMask).toBeNull();
    expect(apartmentCard(findApartment("demo-uk-1")!, "en").demoMask).toBeNull();
  });

  it("курс /flat: × наценку только у квартиры с маской", () => {
    const uk = findApartment("demo-uk-215")!;
    expect(fxOf(uk).fxRate).toBeCloseTo(maskedRate(uk.partner.fx!.rate, MASK), 10);
    expect(fxOf(uk).mask).toEqual({ englishNames: true, hideShops: true });
    const off = { ...uk, apartment: { ...uk.apartment, demoMask: undefined } };
    expect(fxOf(off)).toEqual({ fxRate: uk.partner.fx!.rate });
    expect(fxOf(findApartment("flat215")!)).toEqual({});
  });

  const data = {
    room: { w: 439, d: 325, title: "Гостиная" },
    variants: [{ id: "set1", title: "Сканди", style: "сканди", items: [
      { role: "диван", x: 166, y: 280, rot: 180, w: 198, d: 90, h: 83,
        sku: { name: "Диван прямой divan.ru Викс", name_en: "Viks straight sofa", price: 25990, msid: "m1", sid: "s1", url: "https://xf.gdeslon.ru/x", shop: "divan.ru" } },
      { role: "ковёр", x: 200, y: 200, rot: 0, w: 230, d: 160, sku: { name: "Ковер divan.ru Руффи", price: 8991, sid: "r1", url: "https://xf.gdeslon.ru/r", shop: "divan.ru" } },
    ], decor: [{ role: "ваза", sku: { name: "Ваза V", name_en: "Vase V", price: 2490, msid: "m9", w: 20, d: 20, h: 30, shop: "divan.ru", url: "https://u" } }] }],
    feeds: { "диван": [{ name: "Диван Б", name_en: "Sofa B", price: 30000, msid: "m2", sid: "s3", img: "img/b.jpg", w: 200, d: 92, h: 80, url: "https://u2", shop: "divan.ru" }] },
  };
  const CTX = { apartmentId: "demo-uk-215", partnerId: "demo-uk", currency: "GBP" as const, basePrice: 425000 };
  const cyr = /[А-Яа-яЁё]/;

  it("с маской: английские названия, роль и стиль, без магазина; цена × наценку", () => {
    const r = fromDemoVariant(data, "set1", { ...CTX, fxRate: maskedRate(0.0089, MASK), mask: { englishNames: true, hideShops: true } })!;
    const furn = r.catalogue.options.filter((o) => o.category === "furniture");
    expect(furn.map((o) => o.titleEn)).toEqual(expect.arrayContaining(["Viks straight sofa", "Rug", "Vase V", "Sofa B"]));
    expect(furn.every((o) => !cyr.test(o.titleEn) && !o.shopUrl && !o.shopName)).toBe(true);
    expect(r.apartment.slots.every((s) => !cyr.test(s.titleEn))).toBe(true);
    expect(r.apartment.titleEn).toBe("Scandi — living room");
    expect(r.catalogue.titleEn).toBe("Scandi set");
    expect(furn.find((o) => o.titleEn === "Viks straight sofa")!.price).toBe(347);
  });

  it("без маски: названия и ссылки в магазин как были", () => {
    const r = fromDemoVariant(data, "set1", { ...CTX, fxRate: 0.0089 })!;
    const sofa = r.catalogue.options.find((o) => o.id === "opt:диван#0")!;
    expect(sofa).toMatchObject({ titleEn: "Диван прямой divan.ru Викс", shopUrl: "https://xf.gdeslon.ru/x", shopName: "divan.ru", price: 231 });
  });

  it("коллекция /flat: английское название по sid текущей витрины", () => {
    const coll = { baseVariant: "set1", style: "сканди", items: [{ ...data.variants[0]!.items[0]!, sku: { name: "Диван прямой divan.ru Викс", sid: "s1", msid: "m1", price: 25990 } }] };
    const v = collectionAsVariant(data, coll, {}, new Map([["s1", "Viks straight sofa"]]));
    const r = fromDemoVariant(v, "set1", { ...CTX, mask: { englishNames: true, hideShops: true } })!;
    expect(r.catalogue.options.find((o) => o.id === "opt:диван#0")!.titleEn).toBe("Viks straight sofa");
  });

  it("помощники мостa: роль, стиль, нейтральное название", () => {
    expect(roleEn("стул 2")).toBe("chair");
    expect(roleEn("неведомое")).toBe("item");
    expect(styleEn("джапанди")).toBe("Japandi");
    expect(maskedName({ name_en: "Диван" }, "кресло")).toBe("Armchair");
    expect(maskedRate(0.01, null)).toBe(0.01);
  });
});
