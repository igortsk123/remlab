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

  it("нечитаемый HTML → пустой spec, без падения", () => {
    const r = parseProductHtml("<html>no meta here</html>", "oboi");
    expect(r.spec).toEqual({});
    expect(r.priceRub).toBeUndefined();
  });
});
