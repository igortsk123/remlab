import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { apartmentCard, certificateAmount, findApartment, partners } from "@/lib/partners/registry";
import { resolveFlat } from "@/lib/configurator/source";
import { keepKnown, demoNames } from "@/lib/partners/demo-data";

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
    expect(card.kind).toBe("Трёхкомнатная 73,7 м²");
    expect(card.certificate?.amount).toBe(470_000);
  });

  it("повтор id квартиры между застройщиками — ошибка данных", () => {
    const raw = JSON.parse(readFileSync("data/partners/demo.json", "utf8"));
    expect(() => partners([raw, { ...raw, id: "other" }])).toThrow(/дважды/);
  });
});

describe("в коде витрины нет зашитой квартиры", () => {
  it.each(["tools/scout/flat215-demo/index.html", "tools/scout/flat215_demo.py"])("%s", (f) => {
    const src = readFileSync(f, "utf8");
    for (const s of ["Ольховый", "9 624 990", "9624990", "800 000", "2 кв. 2029"]) expect(src).not.toContain(s);
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
    expect(await resolveFlat("flat215", "nope", async () => demo)).toEqual({ ok: false, reason: "unknown" });
    expect(await resolveFlat("ghost", undefined, async () => demo)).toEqual({ ok: false, reason: "unknown" });
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
