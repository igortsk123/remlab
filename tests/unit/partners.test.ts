import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { apartmentCard, certificateAmount, findApartment, partners } from "@/lib/partners/registry";
import { resolveFlat } from "@/lib/configurator/source";
import { keepKnown, demoNames } from "@/lib/partners/demo-data";
import { optionGroup } from "@/contracts/partner";

// Квартира как данные (план b2b-06): застройщик, ЖК, цена и сертификат — из `data/partners/*.json`,
// и та же логика работает для квартиры под другим id без правки кода.

describe("реестр застройщиков", () => {
  it("все файлы data/partners проходят проверку, id квартир уникальны", () => {
    const list = partners();
    expect(list.map((p) => p.id).sort()).toEqual(["demo", "demo-uk"]);
    expect(findApartment("flat215")?.partner.market).toBe("ru");
    expect(findApartment("demo-uk-1")?.partner.currency).toBe("GBP");
  });

  it("сертификат — доля цены, округлённая ВНИЗ (не обещаем больше доли)", () => {
    const hit = findApartment("flat215")!;
    expect(certificateAmount(hit.partner, hit.apartment)).toBe(470_000); // 9 578 200 × 5 % = 478 910 → 470 000
    const uk = findApartment("demo-uk-1")!;
    expect(certificateAmount(uk.partner, uk.apartment)).toBe(11_400); // 285 000 × 4 %
  });

  it("карточка: тип, ЖК, срок сдачи и этаж собраны из данных; язык меняет только подписи", () => {
    const ru = apartmentCard(findApartment("flat215")!, "ru");
    expect(ru.meta).toBe("ЖК «Ольховый квартал» · сдача 4 кв. 2026 · эт. 6 из 17 · корп. 3");
    expect(ru.certificate?.title).toContain("470 000 ₽");
    const en = apartmentCard(findApartment("flat215")!, "en");
    expect(en.meta).toContain("completion Q4 2026");
    expect(en.currency).toBe("RUB"); // рынок задаёт застройщик, не язык (ADR-0254)
  });

  it("та же квартира под другим id работает без правки кода", () => {
    const raw = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    raw.id = "copy";
    raw.apartments[0].id = "flat-copy";
    const list = partners([raw]);
    const card = apartmentCard(findApartment("flat-copy", list)!);
    expect(card.kind).toBe("Трёхкомнатная 73,7\u00a0м²");
    expect(card.certificate?.amount).toBe(470_000);
  });

  it("повтор id квартиры между застройщиками — ошибка данных", () => {
    const raw = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    expect(() => partners([raw, { ...raw, id: "other" }])).toThrow(/дважды/);
  });
});

// КОМНАТЫ КВАРТИРЫ (demo-16, Codex 18.10 п.1): главная строит «стиль → комнаты» из карточки, а не из заголовков чертежа
describe("комнаты квартиры", () => {
  it("карточка: комнаты в порядке плана, подписи на языке; опции знают свою комнату", () => {
    const ru = apartmentCard(findApartment("flat215")!, "ru");
    expect(ru.rooms.map((r) => r.title)).toEqual(["Гостиная", "Кухня", "Спальня 1", "Спальня 2", "Санузел", "Прихожая"]);
    expect(ru.rooms.map((r) => r.ordinal)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(ru.rooms.filter((r) => r.contentState === "ready").map((r) => r.id)).toEqual(["living"]);
    expect(ru.rooms.find((r) => r.id === "bedroom-1")?.areaM2).toBe(17.5);
    expect(apartmentCard(findApartment("flat215")!, "en").rooms[0]?.title).toBe("Living room");
    expect(Object.fromEntries(ru.options.map((g) => [g.id, g.roomId]))).toEqual({ kitchen: "kitchen", flooring: "living" });   // стены выключены у застройщика — в карточке их нет
    // британский двойник английского демо — тот же состав
    expect(apartmentCard(findApartment("demo-uk-215")!, "en").rooms.map((r) => r.id)).toEqual(ru.rooms.map((r) => r.id));
  });

  it("строка квартиры первого экрана: короткий тип и дом без корпуса", () => {
    const ru = apartmentCard(findApartment("flat215")!, "ru");
    expect(ru.kindShort).toBe("3-комн. · 73,7\u00a0м²");
    expect(ru.metaShort).toBe("ЖК «Ольховый квартал» · сдача 4 кв. 2026 · эт. 6/17");
    expect(apartmentCard(findApartment("flat215")!, "en").kindShort).toBe("2-bed · 73.7\u00a0m²");
  });

  it("квартира без комнат — пустой список, не ошибка", () => {
    expect(apartmentCard(findApartment("demo-uk-1")!).rooms).toEqual([]);
  });

  it("ошибки данных: повтор id комнаты, ordinal не по порядку, опция с несуществующей комнатой", () => {
    const base = () => JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    const dup = base(); dup.apartments[0].rooms[1].id = "living";
    expect(() => partners([dup])).toThrow(/id комнат/);
    const ord = base(); ord.apartments[0].rooms[1].ordinal = 5;
    expect(() => partners([ord])).toThrow(/ordinal/);
    const opt = base(); opt.apartments[0].options[0].roomId = "attic";
    expect(() => partners([opt])).toThrow(/roomId/);
    const kind = base(); kind.apartments[0].options[0].roomId = "living";       // кухня застройщика — к гостиной
    expect(() => partners([kind])).toThrow(/roomKind/);
  });

  it("английский двойник — с тем же составом комнат", () => {
    const ru = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    const uk = JSON.parse(readFileSync("data/partners/demo-uk.json", "utf8"));
    uk.apartments.find((a: { id: string }) => a.id === "demo-uk-215").rooms.pop();
    expect(() => partners([ru, uk])).toThrow(/двойника/);
  });
});

describe("опции квартиры: кухня (b2b-10 этап 0)", () => {
  it("UK: цена из 3D-каталога — один источник; базовая — «входит в цену»", () => {
    const k = apartmentCard(findApartment("demo-uk-1")!, "en").options.find((g) => g.kind === "kitchen")!;
    expect(k.variants.find((v) => v.id === "kitchen-base")!.price).toMatchObject({ type: "included" });
    expect(k.variants.find((v) => v.id === "kitchen-practical")!.price).toMatchObject({ type: "surcharge", amount: 2450, text: "+£2,450" });
  });

  it("РФ-демо: без фиктивного пересчёта фунтов — «цена уточняется у менеджера», варианты помечены демонстрационными", () => {
    const k = apartmentCard(findApartment("flat215")!, "ru").options[0]!;
    expect(k.variants.every((v) => v.demo)).toBe(true);
    expect(k.variants.find((v) => v.id === "kitchen-comfort")!.price.text).toBe("цена уточняется у менеджера");
    expect(k.variants.find((v) => v.id === k.defaultVariantId)!.price.type).toBe("included");
  });

  it("контракт: вариант по умолчанию обязан существовать, id не повторяются", () => {
    const raw = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    raw.apartments[0].options[0].defaultVariantId = "nope";
    expect(() => partners([raw])).toThrow();
  });
});

describe("в коде витрины нет зашитой квартиры", () => {
  it.each(["tools/scout/flat215-demo/index.html", "tools/scout/flat215_demo.py"])("%s", (f) => {
    const src = readFileSync(f, "utf8");
    for (const s of ["Ольховый", "9 624 990", "9624990", "800 000", "2 кв. 2029", "Квартира 215", "№215"]) expect(src).not.toContain(s);
  });
});

describe("откуда квартира 3D", () => {
  const demo = { room: { w: 439, d: 325, title: "Гостиная" }, variants: [{ id: "set16", style: "джапанди", items: [
    { role: "диван", x: 100, y: 100, rot: 0, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "1_1" } }] }] };

  it("квартира с витриной собирается из её данных по набору; витрина молчит — unavailable, не подмена", async () => {
    const ok = await resolveFlat("flat215", "set16", async () => demo);
    expect(ok.ok && ok.apartment.id).toBe("flat215");
    expect(ok.ok && ok.catalogue.currency).toBe("RUB");
    expect(await resolveFlat("flat215", "set16", async () => null)).toEqual({ ok: false, reason: "unavailable" });
    expect(await resolveFlat("ghost", undefined, async () => demo)).toEqual({ ok: false, reason: "unknown" });
  });

  // demo-05 п.10: номер варианта меняется при пересборке, ссылки менеджеров живут дольше (14.10 `?demo=set2` → 404)
  it("устаревший номер варианта — текущий вариант того же стиля с пометкой, не 404", async () => {
    const two = { ...demo, variants: [{ ...demo.variants[0]!, id: "set1", style: "сканди" }, demo.variants[0]!],
      variant_aliases: { set2: "джапанди", set3: "бохо" } };
    const same = await resolveFlat("flat215", "set2", async () => two);
    expect(same.ok && same.apartment.baseVariant).toBe("set16");
    expect(same.ok && same.replaced).toEqual({ from: "set2", style: "джапанди" });
    // стиля больше нет — первый вариант, замена названа без стиля
    const gone = await resolveFlat("flat215", "set3", async () => two);
    expect(gone.ok && gone.apartment.baseVariant).toBe("set1");
    expect(gone.ok && gone.replaced).toEqual({ from: "set3" });
    // живой номер — без пометки
    const live = await resolveFlat("flat215", "set16", async () => two);
    expect(live.ok && live.replaced).toBeUndefined();
  });

  it("3D-квартира берёт цену и застройщика из реестра", async () => {
    const r = await resolveFlat("demo-uk-1");
    expect(r.ok && r.apartment.basePrice).toBe(285_000);
    expect(r.ok && r.catalogue.developerId).toBe("demo-uk");
  });
});

describe("имена из витрины", () => {
  it("находит товары в лентах замен, не только в варианте", () => {
    const names = demoNames({ variants: [{ style: "лофт", items: [] }], sets: [{ items: [{ name: "Кресло Б", price: 1 }] }] });
    expect(keepKnown(names, "Лофт", ["Кресло Б", "чужой текст"])).toEqual({ variant: "Лофт", items: ["Кресло Б"] });
  });
});

// demo-06: пол от застройщика — группа опций с материалами; доплата вне сертификата (RF); выключенная группа не видна
describe("опции отделки: пол", () => {
  const mats = new Set((JSON.parse(readFileSync("data/flat3d/materials.json", "utf8")) as { materials: { id: string }[] }).materials.map((m) => m.id));
  it("у демо-квартиры 5 полов с материалами из манифеста, первый — в цене, доплата застройщику", () => {
    const g = apartmentCard(findApartment("flat215")!, "ru").options.find((o) => o.kind === "flooring")!;
    expect(g.variants).toHaveLength(5);
    expect(g.settlement).toBe("developer_surcharge");
    expect(g.slotIds).toEqual(["floor"]);
    expect(g.variants.every((v) => v.materialId && mats.has(v.materialId))).toBe(true);
    // материал едет в карточке целиком, адреса карт — от корня сайта (окно демо живёт в /demo/)
    expect(g.variants.every((v) => v.material?.id === v.materialId && String(v.material?.baseColorUrl).startsWith("/flat3d/materials/"))).toBe(true);
    expect(g.variants[0]!.price.type).toBe("included");
    expect(g.variants[1]!.price).toMatchObject({ type: "surcharge", amount: 18000 });
  });
  it("выключенная группа не попадает в карточку; у варианта пола без материала — ошибка данных", () => {
    const raw = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    const fl = raw.apartments[0].options.find((o: { id: string }) => o.id === "flooring");
    fl.enabled = false;
    const hit = findApartment("flat215", partners([raw]))!;
    expect(apartmentCard(hit, "ru").options.some((o) => o.kind === "flooring")).toBe(false);
    fl.enabled = true;
    delete fl.variants[1].materialId;
    expect(() => partners([raw])).toThrow();
  });
});

// ADR-0298: английское анонимное демо — британский двойник витрины; по ссылке менеджера/партнёра — та же квартира
describe("британский профиль английского демо", () => {
  it("flat215 + en → demo-uk-215 (£, поощрение 4 %, курс в карточке); ru — без подмены", async () => {
    const { demoProfile } = await import("@/lib/partners/registry");
    const hit = findApartment("flat215")!;
    expect(demoProfile(hit, "ru").apartment.id).toBe("flat215");
    const twin = demoProfile(hit, "en");
    expect(twin.apartment.id).toBe("demo-uk-215");
    const card = apartmentCard(twin, "en");
    expect(card.currency).toBe("GBP");
    expect(card.certificate?.amount).toBe(Math.round(425000 * 0.04));
    expect(card.fx).toMatchObject({ from: "RUB", to: "GBP" });
    const fl = card.options.find((o) => o.kind === "flooring")!;
    expect(fl.settlement).toBe("property_price");
    expect(fl.variants.every((v) => !v.price.text.includes("₽"))).toBe(true);
    expect(card.options.find((o) => o.kind === "kitchen")!.settlement).toBe("property_price");
    expect(card.sources.demoData).toBe(hit.apartment.sources.demoData);   // та же витрина
  });
});

describe("встраиваемое застройщика (шторка v5)", () => {
  it("шкафы и техника — допустимые виды группы опций, без материала отделки", () => {
    for (const kind of ["wardrobe", "appliances"]) {
      const g = optionGroup.safeParse({ id: "fit-" + kind, kind, roomKind: "bedroom", titleRu: "Шкафы", titleEn: "Wardrobes",
        defaultVariantId: "base", variants: [{ id: "base", nameRu: "Base", nameEn: "Base", pricing: { type: "included" } }] });
      expect(g.success).toBe(true);
    }
  });
});
