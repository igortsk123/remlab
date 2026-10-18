import { describe, expect, it } from "vitest";
import { baseSnapshotOf, fromDemoVariant, staleSlots } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";

const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };

const data = {
  room: { w: 439, d: 325, title: "Гостиная 14.4 м²", height_cm: 270,
    openings: [{ kind: "window", wall: "west", offset_cm: 70, width_cm: 150, sill_cm: 85, height_cm: 150 }] },
  variants: [{ id: "set16", title: "Джапанди", style: "джапанди", items: [
    { role: "диван", x: 166.1, y: 280, rot: 180, w: 162, d: 90, h: 79,
      sku: { name: "Диван X", price: 54990, msid: "112923_1", url: "https://xf.gdeslon.ru/cm/x", shop: "divan.ru" } },
    { role: "столик", x: 200, y: 180, rot: 0, w: 80, d: 80, h: 45, sku: { name: "Столик Y", msid: "99272_2", yaw: 180 } },
    { role: "ковёр", x: 200, y: 200, rot: 0, w: 200, d: 150, sku: { name: "Ковёр Z", price: 9291, sid: "r1", img: "img/rug.jpg" } },
    { role: "торшер", x: 40, y: 40, rot: 0, w: 30, d: 30, h: 160, sku: { name: "Без меша" } },
  ], decor: [{ role: "ваза", sku: { name: "Ваза V", price: 2490, msid: "99272_9", w: 20, d: 20, h: 30 } },
             { role: "ваза", sku: { name: "Без размеров", msid: "99272_8" } }] }],
};

describe("мост витрина → конфигуратор", () => {
  it("собирает комнату и мебель того же варианта", () => {
    const r = fromDemoVariant(data, "set16", CTX);
    expect(r).not.toBeNull();
    expect(r!.apartment.rooms).toHaveLength(1);
    expect(r!.apartment.rooms[0]!.w).toBe(439);
    // предмет без меша в сцену не попадает: серая коробка хуже отсутствия; ковёр (фото товара) и ваза с габаритами — товары
    expect(r!.apartment.slots.filter((s) => s.kind === "furniture").map((s) => s.id)).toEqual(["диван#0", "столик#0", "ковёр#0", "decor:ваза#0"]);
    expect(r!.catalogue.options.filter((o) => o.category === "furniture")).toHaveLength(4);
    // стены и пол — свои материалы из паспорта отделки, ПЕРВЫМИ: оболочка не берёт фото ковра (/flat 15.10)
    expect(r!.apartment.slots.filter((s) => s.kind === "surface").map((s) => s.surface).sort()).toEqual(["floor", "wall"]);
    expect(r!.catalogue.materials[0]!.titleRu).toBe("Стены");
  });

  // demo-05 п.9: ковёр и ваза — в /flat так же, как в окне и в цене
  it("ковёр — плита с фото товара от адреса витрины, с ценой; ваза — настольный декор с ценой", () => {
    const r = fromDemoVariant(data, "set16", { ...CTX, assetBase: "/demo/demo-data.json" })!;
    const rug = r.catalogue.options.find((o) => o.id === "opt:ковёр#0")!;
    expect(rug.price).toBe(9291);
    expect(rug.asset.kind === "kit" && rug.asset.kit).toBe("rug");
    expect(r.catalogue.materials.find((m) => m.id.startsWith("rug:"))!.baseColorUrl).toBe("/demo/img/rug.jpg");
    const vase = r.apartment.slots.find((s) => s.id === "decor:ваза#0")!;
    expect(vase.tabletop).toBe(true);
    expect(r.catalogue.options.find((o) => o.id === "opt:decor:ваза#0")!.price).toBe(2490);
  });

  it("сохраняет координаты и поворот как есть — конвенции совпадают", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    const sofa = r.apartment.slots[0]!;
    expect(sofa.placement).toMatchObject({ x: 166.1, y: 280, rot: 180, wCm: 162, dCm: 90, hCm: 79 });
  });

  it("разворот фронта модели из витрины доезжает до 3D; нет — 0", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    const yaw = (i: number) => (r.catalogue.options[i]!.asset as { yawDeg?: number }).yawDeg;
    expect(yaw(0)).toBe(0);
    expect(yaw(1)).toBe(180);
  });

  it("ведёт в магазин партнёрской ссылкой", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    expect(r.catalogue.options[0]!.shopUrl).toContain("gdeslon.ru");
  });

  it("квартира — из реестра (id, застройщик, цена), набор — отдельным полем, цены товаров настоящие", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    expect(r.apartment).toMatchObject({ id: "flat215", baseVariant: "set16", style: "джапанди", developerId: "demo", basePrice: 9_578_200 });
    expect(r.catalogue.currency).toBe("RUB");
    expect(r.catalogue.options[0]!.price).toBe(54990);
  });

  it("имя места — роль и номер в роли: пересборка с другим порядком не сдвигает выбор", () => {
    const r1 = fromDemoVariant(data, "set16", CTX)!;
    const swapped = { ...data, variants: [{ ...data.variants[0]!, items: [...data.variants[0]!.items].reverse() }] };
    const r2 = fromDemoVariant(swapped, "set16", CTX)!;
    expect(r1.apartment.slots.map((s) => s.id).sort()).toEqual(r2.apartment.slots.map((s) => s.id).sort());
    expect(r1.apartment.slots[0]!.id).toBe("диван#0");
  });

  it("снимок набора: сменилась модель на месте — место помечается, а не подменяется молча", () => {
    const r = fromDemoVariant(data, "set16", CTX)!;
    const snap = baseSnapshotOf(r.apartment, r.catalogue);
    expect(snap).toEqual({ "диван#0": "112923_1", "столик#0": "99272_2", "ковёр#0": "rug:rug:0:r1", "decor:ваза#0": "99272_9" });
    const saved = { version: 3 as const, apartmentId: "flat215", developerId: "demo", selections: {}, placements: {}, baseSnapshot: snap };
    expect(staleSlots(saved, { ...snap, "диван#0": "777_1" })).toEqual(["диван#0"]);
    expect(staleSlots(saved, snap)).toEqual([]);
  });

  it("упаковка: два стула из упаковки «2 шт.» — одна покупка, как в списке витрины", () => {
    const chairs = { ...data, variants: [{ id: "set1", style: "сканди", items: [
      { role: "стул", x: 10, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А 2 шт.", price: 9000, pack: 2, msid: "1_1", url: "u" } },
      { role: "стул 2", x: 60, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А 2 шт.", price: 9000, pack: 2, msid: "1_1", url: "u" } },
    ] }] };
    const r = fromDemoVariant(chairs, "set1", CTX)!;
    expect(resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue)).totals.upgrades).toBe(9000);
    // стулья меняются вместе (владелец 30.09): одна группа, одна общая опция
    expect(r.apartment.slots.filter((s) => s.kind === "furniture").map((s) => [s.selectionGroup, s.defaultOptionId])).toEqual([["стул", "opt:стул"], ["стул", "opt:стул"]]);
  });

  // demo-05 п.9: в /flat у предмета — лента замен витрины, как в окне
  it("ленты замен: свой стиль, ближайшие по размеру, с моделью и фото; стулья — доля упаковки на место", () => {
    const feed = (n: number, extra: object) => Array.from({ length: n }, (_, k) => ({ name: `Ф${k}`, sid: `s${k}`, msid: `m${k}`, img: `img/${k}.jpg`,
      w: 150 + k * 10, d: 90, h: 80, price: 10000 + k, url: `u${k}`, shop: "divan.ru", src: "pool", styles: ["джапанди"], ...extra }));
    const withFeeds = { ...data, feeds: { диван: [...feed(14, {}), { name: "Чужой", sid: "x", msid: "mx", img: "i", w: 162, d: 90, h: 80, src: "pool", styles: ["лофт"] }],
      стул: [{ name: "Стул Б 2 шт.", sid: "c1", msid: "mc", img: "img/c.jpg", w: 45, d: 50, h: 85, price: 8000, pack: 2, src: "pool", styles: ["сканди"] }] } };
    const r = fromDemoVariant(withFeeds, "set16", { ...CTX, assetBase: "/demo/demo-data.json" })!;
    const sofa = r.apartment.slots.find((s) => s.id === "диван#0")!;
    expect(sofa.optionIds).toHaveLength(12);                   // текущий + 11 ближайших
    expect(sofa.optionIds).not.toContain("feed:диван:x");      // чужой стиль
    expect(sofa.optionIds[1]).toBe("feed:диван:s1");           // 160×90 — ближе всех к 162×90
    const alt = r.catalogue.options.find((o) => o.id === "feed:диван:s1")!;
    expect(alt).toMatchObject({ price: 10001, listPrice: 10001, previewUrl: "/demo/img/1.jpg", shopUrl: "u1" });
    const chairs = { ...withFeeds, variants: [{ id: "set1", style: "сканди", items: [
      { role: "стул", x: 10, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А", price: 5000, msid: "1_1", url: "u" } },
      { role: "стул 2", x: 60, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А", price: 5000, msid: "1_1", url: "u" } },
    ] }] };
    const c = fromDemoVariant(chairs, "set1", CTX)!;
    const cfg = defaultConfiguration(c.apartment, c.catalogue);
    expect(resolveScene(c.apartment, c.catalogue, cfg).totals.upgrades).toBe(10000);
    // замена на «2 шт.» обоим стульям — одна упаковка
    const swapped = { ...cfg, selections: { ...cfg.selections, "стул#0": "feed:стул:c1", "стул 2#0": "feed:стул:c1" } };
    expect(resolveScene(c.apartment, c.catalogue, swapped).totals.upgrades).toBe(8000);
    // убрал один стул — упаковку всё равно покупать (Codex 15.10); одна строка сметы на упаковку
    const oneHidden = resolveScene(c.apartment, c.catalogue, { ...swapped, hidden: ["стул 2#0"] });
    expect(oneHidden.totals.upgrades).toBe(8000);
    expect(resolveScene(c.apartment, c.catalogue, swapped).items.filter((i) => i.price > 0)).toHaveLength(1);
    // поддельный подбор с разными стульями в группе — сервер приводит группу к первому месту
    const mixed = { ...cfg, selections: { ...cfg.selections, "стул#0": "feed:стул:c1", "стул 2#0": "opt:стул" } };
    const fixed = resolveScene(c.apartment, c.catalogue, mixed);
    expect(fixed.selections["стул 2#0"]).toBe("feed:стул:c1");
    expect(fixed.totals.upgrades).toBe(8000);
  });

  // demo-18 п.1: форму места мост берёт из расстановки — замена Г-дивана только Г-диваном (той же стороны, если она названа)
  it("ленты замен: на месте углового дивана — только угловые той же стороны, разные модели раньше цветов", () => {
    const sofa = (sid: string, msid: string, extra: object) => ({ name: sid, sid, msid, img: "i", w: 186, d: 151, h: 80, price: 1, src: "pool",
      styles: ["джапанди"], ...extra });
    const corner = { ...data, variants: [{ ...data.variants[0]!, items: [{ ...data.variants[0]!.items[0]!, w: 186, d: 151, corner: true,
      corner_left: false, sku: { name: "Г", sid: "g0", msid: "G" } }] }],
      feeds: { диван: [sofa("п", "P", {}), sofa("г1", "G", { corner: true }), sofa("г2", "G2", { corner: true }),
        sofa("л", "L", { corner: true, corner_left: true }), sofa("пр", "R", { corner: true, corner_left: false })] } };
    const r = fromDemoVariant(corner, "set16", CTX)!;
    expect(r.apartment.slots.find((s) => s.id === "диван#0")!.optionIds.slice(1)).toEqual(["feed:диван:г2", "feed:диван:пр", "feed:диван:г1"]);
  });

  // demo-05 п.8: «Фото» в /flat снимает ракурсами окна — они приходят в данных варианта (`tools/flat3d/demo-cams.mjs`)
  it("ракурсы окна из данных варианта — камеры квартиры с позой v2", () => {
    const withCams = { ...data, variants: [{ ...data.variants[0]!, cams: [{ name: "C1", x: 436, y: 242, rot: -80, fov: 78, pose: 2 },
      { name: "C2", x: 3, y: 43, rot: 144, fov: 72, pose: 2 }] }] };
    const r = fromDemoVariant(withCams, "set16", CTX)!;
    expect(r.apartment.cameras).toEqual([
      { id: "cam1", roomId: "living", titleRu: "Ракурс 1", x: 436, y: 242, rot: -80, fov: 78, pose: 2 },
      { id: "cam2", roomId: "living", titleRu: "Ракурс 2", x: 3, y: 43, rot: 144, fov: 72, pose: 2 },
    ]);
    expect(fromDemoVariant(data, "set16", CTX)!.apartment.cameras).toEqual([]);
  });

  it("три стула из упаковки «2 шт.» — две покупки", () => {
    const three = { ...data, variants: [{ id: "set1", style: "сканди", items: [0, 1, 2].map((k) => ({ role: k ? `стул ${k + 1}` : "стул",
      x: 10 + k * 50, y: 10, rot: 0, w: 45, d: 50, h: 85, sku: { name: "Стул А 2 шт.", price: 9000, pack: 2, msid: "1_1", url: "u" } })) }] };
    const r = fromDemoVariant(three, "set1", CTX)!;
    expect(resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue)).totals.upgrades).toBe(18000);
  });

  it("неизвестный вариант — null, страница откроет обычную квартиру", () => {
    expect(fromDemoVariant(data, "setX", CTX)).toBeNull();
  });
});

// demo-06: пол от застройщика в /flat — варианты группы карточки опциями пола; доплата — застройщику, не в сертификат
describe("пол от застройщика в /flat", () => {
  it("из карточки flat215: 5 вариантов пола, по умолчанию «в цене», выбор паркета — доплата застройщику отдельно", async () => {
    const { findApartment } = await import("@/lib/partners/registry");
    const { floorChoiceOf, developerSelections, parseOptParam } = await import("@/lib/configurator/source");
    const hit = findApartment("flat215")!;
    const fc = floorChoiceOf(hit)!;
    expect(fc.variants).toHaveLength(5);
    expect(fc.settlement).toBe("developer_surcharge");
    const r = fromDemoVariant(data, "set16", { ...CTX, floorChoice: fc })!;
    const floor = r.apartment.slots.find((s) => s.id === "floor")!;
    expect(floor.optionIds).toHaveLength(5);
    expect(floor.defaultOptionId).toBe("opt:floor:laminate-oak-light");
    // оболочка красится материалом пола по умолчанию — он среди первых материалов каталога
    expect(r.catalogue.materials[1]!.id).toBe("laminate-oak-light");
    const base = resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue));
    expect(base.totals.bySettlement.developer_surcharge).toBe(0);
    const sel = developerSelections(hit, r.apartment, parseOptParam("flooring:parquet-herringbone,bad,x:"));
    expect(sel).toEqual({ floor: "opt:floor:parquet-herringbone" });
    const cfg = defaultConfiguration(r.apartment, r.catalogue);
    const sc = resolveScene(r.apartment, r.catalogue, { ...cfg, selections: { ...cfg.selections, ...sel } });
    expect(sc.surfaces.find((s) => s.slotId === "floor")!.material.id).toBe("parquet-herringbone");
    expect(sc.totals.bySettlement.developer_surcharge).toBe(86000);
    expect(sc.totals.bySettlement.allowance).toBe(base.totals.bySettlement.allowance);   // сертификат не тронут
    expect(sc.totals.upgrades).toBe(base.totals.upgrades + 86000);
    // чужая группа или вариант — не применяются
    expect(developerSelections(hit, r.apartment, { flooring: "nope" })).toEqual({});
  });

  it("UK-квартира 3D: пол — к цене квартиры, мебель — в сертификат", async () => {
    const { resolveFlat } = await import("@/lib/configurator/source");
    const f = await resolveFlat("demo-uk-1");
    expect(f.ok).toBe(true);
    if (!f.ok) return;
    const floors = f.catalogue.options.filter((o) => o.category === "flooring");
    expect(floors.length).toBeGreaterThan(0);
    expect(floors.every((o) => o.settlement === "property_price")).toBe(true);
    expect(f.catalogue.options.filter((o) => o.category === "furniture").every((o) => !o.settlement)).toBe(true);
  });
});

// demo-02 приёмка 16.10 п.11б: цветовой вариант на модели семейства — подкраской; мусор в данных подкраску не включает
describe("подкраска цветового варианта", () => {
  it("sku.tint → asset.tintRgb у предмета; неверные значения отбрасываются", async () => {
    const { tintOf } = await import("@/lib/configurator/fromDemo");
    expect(tintOf([0.6, 0.61, 0.59])).toEqual({ tintRgb: [0.6, 0.61, 0.59] });
    expect(tintOf([0.6, 9, 0.5])).toEqual({});
    expect(tintOf("x")).toEqual({});
    const d = structuredClone(data) as unknown as { variants: { items: { sku: Record<string, unknown> }[] }[] };
    d.variants[0]!.items[0]!.sku = { ...d.variants[0]!.items[0]!.sku, tint: [0.6, 0.61, 0.59] };
    const r = fromDemoVariant(d as unknown as typeof data, "set16", CTX)!;
    const sofa = r.catalogue.options.find((o) => o.id === "opt:диван#0")!;
    expect(sofa.asset.kind === "mesh" && sofa.asset.tintRgb).toEqual([0.6, 0.61, 0.59]);
  });
});

// ADR-0298: британский двойник — цены витрины (рубли) пересчитываются по курсу один раз, в мосту
describe("курс показа в мосту", () => {
  it("fxRate пересчитывает цены товаров, лент, ковра и декора с округлением", () => {
    const r = fromDemoVariant(data, "set16", { ...CTX, currency: "GBP", fxRate: 0.0089 })!;
    const sofa = r.catalogue.options.find((o) => o.id === "opt:диван#0")!;
    expect(sofa.price).toBe(Math.round(54990 * 0.0089));
    expect(r.catalogue.options.find((o) => o.id === "opt:ковёр#0")!.price).toBe(Math.round(9291 * 0.0089));
    expect(r.catalogue.currency).toBe("GBP");
  });
  it("/flat британского двойника: каталог в £, пол — к цене квартиры", async () => {
    const { resolveFlat } = await import("@/lib/configurator/source");
    const f = await resolveFlat("demo-uk-215", "set16", async () => data);
    expect(f.ok).toBe(true);
    if (!f.ok) return;
    expect(f.catalogue.currency).toBe("GBP");
    expect(f.catalogue.options.find((o) => o.id === "opt:диван#0")!.price).toBe(Math.round(54990 * 0.0089));
    expect(f.catalogue.options.filter((o) => o.id.startsWith("opt:floor:")).every((o) => o.settlement === "property_price")).toBe(true);
  });
});

// demo-07: стены застройщика в /flat — опции места `wall`, акцентная стена «за диваном» считается расчётом сцены
describe("стены от застройщика в /flat", () => {
  it("группа стен (включённая) → 5 опций места wall; ?opt=walls:accent-sage — акцент за диваном, доплата застройщику", async () => {
    const { readFileSync } = await import("node:fs");
    const { findApartment, partners } = await import("@/lib/partners/registry");
    const { finishChoiceOf, developerSelections } = await import("@/lib/configurator/source");
    const raw = [JSON.parse(readFileSync("data/partners/demo.json", "utf8")), JSON.parse(readFileSync("data/partners/demo-uk.json", "utf8"))];
    for (const p of raw) for (const a of p.apartments) for (const g of a.options ?? []) if (g.id === "walls") g.enabled = true;
    const hit = findApartment("flat215", partners(raw))!;
    const wc = finishChoiceOf(hit, "wall")!;
    expect(wc.variants).toHaveLength(5);
    const r = fromDemoVariant(data, "set16", { ...CTX, wallChoice: wc })!;
    expect(r.apartment.slots.find((s) => s.id === "wall")!.optionIds).toHaveLength(5);
    const sel = developerSelections(hit, r.apartment, { walls: "accent-sage" });
    expect(sel).toEqual({ wall: "opt:wall:accent-sage" });
    const cfg = defaultConfiguration(r.apartment, r.catalogue);
    const sc = resolveScene(r.apartment, r.catalogue, { ...cfg, selections: { ...cfg.selections, ...sel } });
    const wall = sc.surfaces.find((s) => s.slotId === "wall")!;
    expect(wall.accent?.material.id).toBe("wall-paint-sage");
    expect(wall.accent?.side).toBe("north");          // диван тестовой расстановки — rot 180 у дальней стены
    expect(sc.totals.bySettlement.developer_surcharge).toBe(15000);
  });
  it("по умолчанию группа стен выключена — в /flat стены по паспорту", async () => {
    const { findApartment } = await import("@/lib/partners/registry");
    const { finishChoiceOf } = await import("@/lib/configurator/source");
    expect(finishChoiceOf(findApartment("flat215")!, "wall")).toBeUndefined();
  });
});
