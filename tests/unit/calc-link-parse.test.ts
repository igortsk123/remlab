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

  it("нечитаемый HTML → пустой spec, без падения", () => {
    const r = parseProductHtml("<html>no meta here</html>", "oboi");
    expect(r.spec).toEqual({});
    expect(r.priceRub).toBeUndefined();
  });
});
