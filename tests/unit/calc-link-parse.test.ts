import { describe, it, expect } from "vitest";
import { parseProductHtml } from "@/lib/calc/link-parse";

describe("link parse — извлечение из HTML", () => {
  it("плитка: размеры и цена из OG-меты", () => {
    const html = `
      <meta property="og:title" content="Плитка керамическая 300x300 мм, белая" />
      <meta property="og:description" content="Керамогранит 300×300, упаковка 10 шт" />
      <meta property="product:price:amount" content="1290" />
      <title>Плитка — магазин</title>`;
    const r = parseProductHtml(html, "plitka");
    expect(r.title).toContain("Плитка");
    expect(r.priceRub).toBe(1290);
    expect(r.spec.tileLengthMm).toBe(300);
    expect(r.spec.tileWidthMm).toBe(300);
    expect(r.spec.pricePerPackRub).toBe(1290);
  });

  it("ламинат: размеры панели из текста", () => {
    const html = `<meta property="og:title" content="Ламинат 1285x192, 33 класс" /><meta property="og:price:amount" content="990">`;
    const r = parseProductHtml(html, "laminat");
    expect(r.spec.panelLengthMm).toBe(1285);
    expect(r.spec.panelWidthMm).toBe(192);
    expect(r.spec.pricePerPackRub).toBe(990);
  });

  it("ламинат: «Размер доски 1380х193 мм», шт/упак и цена за м² из таблицы (стройпарк)", () => {
    const html = `
      <meta property="og:title" content="Ламинат KASTAMONU Yellow Дуб Кантри классический" />
      <table><tr><td>Класс применения</td><td>32</td></tr>
      <tr><td>Размер доски</td><td>1380х193 мм</td></tr>
      <tr><td>Количество в упаковке</td><td>8 шт</td></tr>
      <tr><td>Площадь в упаковке</td><td>2,131 м²</td></tr></table>
      <div>832.48 ₽ за м<sup>2</sup></div><div>1 775.00 ₽ за упак</div>`;
    const r = parseProductHtml(html, "laminat");
    expect(r.spec.panelLengthMm).toBe(1380);
    expect(r.spec.panelWidthMm).toBe(193);
    expect(r.spec.panelsPerPack).toBe(8);
    expect(r.spec.pricePerM2Rub).toBe(832.48); // «за м²» приоритетнее «за упак»
  });

  it("ламинат: только цена упаковки + размеры и шт/упак → цена за м² выводится", () => {
    const html = `<div>Размер доски: 1380х193 мм</div><div>Количество в упаковке: 8</div><div>1 775 ₽ за упаковку</div>`;
    const r = parseProductHtml(html, "laminat");
    expect(r.spec.pricePerPackRub).toBe(1775);
    expect(r.spec.pricePerM2Rub).toBeCloseTo(833.05, 1); // 1775 ÷ (1.38 × 0.193 × 8)
  });

  it("обои: размеры рулона «1,06*10м» из og-title + раппорт «64 см» из таблицы", () => {
    const html = `
      <meta property="og:title" content="Обои R210139 Эдем/ Grandeco (1,06*10м обои винил, флизелин)" />
      <meta property="product:price:amount" content="1890" />
      <table><tr><td>Рапорт смещения рисунка:</td><td><span>64 см</span></td></tr>
      <tr><td>Тип:</td><td><span>Обои</span></td></tr></table>`;
    const r = parseProductHtml(html, "oboi");
    expect(r.spec.rollWidthM).toBe(1.06);
    expect(r.spec.rollLengthM).toBe(10);
    expect(r.spec.rapportM).toBeCloseTo(0.64);
    expect(r.spec.pricePerRollRub).toBe(1890);
  });

  it("обои: «0,53х10,05 м» (кириллическая х) → ширина/длина рулона", () => {
    const html = `<meta property="og:title" content="Обои флизелиновые 0,53х10,05 м" />`;
    const r = parseProductHtml(html, "oboi");
    expect(r.spec.rollWidthM).toBe(0.53);
    expect(r.spec.rollLengthM).toBe(10.05);
  });

  it("обои: пустой лейбл «раппорт (см)» без числа не даёт раппорт", () => {
    const html = `<label>раппорт (см)</label><input name="bias" />`;
    const r = parseProductHtml(html, "oboi");
    expect(r.spec.rapportM).toBeUndefined();
  });

  it("обои: артикул перед ценой НЕ склеивается («R210139 … 2650 ₽» ≠ 2101392650)", () => {
    const html = `<meta property="og:title" content="Обои R210139 Эдем (1,06*10м)" /><div>Артикул: R210139</div><div>2650 ₽</div>`;
    const r = parseProductHtml(html, "oboi");
    expect(r.priceRub).toBe(2650);
    expect(r.spec.pricePerRollRub).toBe(2650);
  });

  it("цена с пробелом-разделителем тысяч «2 650 ₽» → 2650", () => {
    const html = `<meta property="og:title" content="Обои тест 1,06*10м" /><span>2 650 ₽</span>`;
    expect(parseProductHtml(html, "oboi").priceRub).toBe(2650);
  });

  it("плитка: цена с пробелом-разделителем «2 220.00» → 2220 (pricePerPackRub)", () => {
    const html = `<strong class="carrot-product-price" itemprop="price" content="2 220.00">2 220.00 ₽</strong>`;
    const r = parseProductHtml(html, "plitka");
    expect(r.priceRub).toBe(2220);
    expect(r.spec.pricePerPackRub).toBe(2220);
  });

  it("плитка: размер в см «20х20см» → 200×200 мм", () => {
    const html = `<meta property="og:title" content="Плитка настенная VENETO Epica Beige 20х20см" />`;
    const r = parseProductHtml(html, "plitka");
    expect(r.spec.tileLengthMm).toBe(200);
    expect(r.spec.tileWidthMm).toBe(200);
  });

  it("плитка (Kerama): «Размер: 7,4*15 см» + «руб./кв.м» → 74×150 мм, цена за м²", () => {
    const html = `
      <meta property="og:title" content="16032 Граньяно белый грань 7.4*15 керамическая плитка" />
      <div class="key">Размер</div><div class="val">7,4*15 см</div>
      <div class="price"><div class="current">2 246.02 руб./кв.м</div></div>
      <div class="price"><div class="current">186.66 руб./шт</div></div>`;
    const r = parseProductHtml(html, "plitka");
    expect(r.spec.tileLengthMm).toBe(74);
    expect(r.spec.tileWidthMm).toBe(150);
    expect(r.spec.pricePerM2Rub).toBe(2246.02);
    expect(r.spec.pricePerPackRub).toBeUndefined();
    expect(r.spec.pricePerPieceRub).toBeUndefined();
  });

  it("плитка (Керамогранит): фильтр-список размеров игнорируется, берётся «Размер (см) 60x120» + «руб./м2»", () => {
    const html = `
      <meta name="og:title" content="Плитка CLOUD (Villa Ceramica)" />
      <meta name="og:description" content="Коллекция CLOUD, ценами от 4790 руб./м2." />
      <div class="filter">Размер 10х10 10х20 10х30 15х15 20х20</div>
      <div class="spec">Размер (см) 60x120 Цвет серый</div>`;
    const r = parseProductHtml(html, "plitka");
    expect(r.spec.tileLengthMm).toBe(600);
    expect(r.spec.tileWidthMm).toBe(1200);
    expect(r.spec.pricePerM2Rub).toBe(4790);
  });

  it("плитка: цена только «руб./шт» → pricePerPieceRub", () => {
    const html = `<meta property="og:title" content="Плитка настенная Rako" /><div class="price">Цена: 186.66 руб./шт</div>`;
    const r = parseProductHtml(html, "plitka");
    expect(r.spec.pricePerPieceRub).toBe(186.66);
    expect(r.spec.pricePerM2Rub).toBeUndefined();
  });

  it("плитка: «60x120» без единицы → 600×1200 мм (эвристика см), «300x300» → 300×300 мм", () => {
    const a = parseProductHtml(`<meta property="og:title" content="Плитка 60x120" />`, "plitka");
    expect(a.spec.tileLengthMm).toBe(600);
    expect(a.spec.tileWidthMm).toBe(1200);
    const b = parseProductHtml(`<meta property="og:title" content="Плитка 300x300" />`, "plitka");
    expect(b.spec.tileLengthMm).toBe(300);
    expect(b.spec.tileWidthMm).toBe(300);
  });

  it("нечитаемый HTML → пустой spec, без падения", () => {
    const r = parseProductHtml("<html>no meta here</html>", "oboi");
    expect(r.spec).toEqual({});
    expect(r.priceRub).toBeUndefined();
  });
});
