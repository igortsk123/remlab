import { describe, it, expect } from "vitest";
import { buildLlmInput, extractJsonLd, jsonLdProduct, relevantText } from "@/lib/calc/link-content";
import { missingAiFields } from "@/lib/calc/parse-product";

const LD_PRODUCT = `<script type="application/ld+json">{"@type":"Product","name":"Обои Мир 3738491194","offers":{"@type":"Offer","price":"2650","priceCurrency":"RUB"}}</script>`;

describe("extractJsonLd — товарные JSON-LD блоки", () => {
  it("берёт Product/offers, игнорирует прочие ld+json и обычные скрипты", () => {
    const html = `<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>${LD_PRODUCT}<script>var a=1;</script>`;
    const blocks = extractJsonLd(html);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toContain("Обои Мир");
  });

  it("нет товарных блоков → []", () => {
    expect(extractJsonLd("<html><body>просто текст</body></html>")).toEqual([]);
  });
});

describe("jsonLdProduct — детерминированные title/цена", () => {
  it("читает name и offers.price (строкой)", () => {
    expect(jsonLdProduct(extractJsonLd(LD_PRODUCT))).toEqual({ title: "Обои Мир 3738491194", priceRub: 2650 });
  });

  it("массив узлов и offers-массив", () => {
    const block = JSON.stringify([{ "@type": "WebPage" }, { "@type": "Product", name: "Плитка", offers: [{ price: 1190.5 }] }]);
    expect(jsonLdProduct([block])).toEqual({ title: "Плитка", priceRub: 1190.5 });
  });

  it("битый JSON → {} (не падает)", () => {
    expect(jsonLdProduct(["{оборванный"])).toEqual({});
  });
});

describe("relevantText — компактный вход LLM", () => {
  it("короткая страница — целиком", () => {
    expect(relevantText("<p>Обои 1,06х10 м</p>")).toBe("Обои 1,06х10 м");
  });

  it("длинная страница: начало + окно вокруг «Характеристики»", () => {
    const filler = "вода ".repeat(4000); // ~20k символов до блока характеристик
    const html = `<p>Заголовок товара</p><p>${filler}</p><h2>Характеристики</h2><p>Ширина рулона: 1,06 м</p>`;
    const out = relevantText(html);
    expect(out).toContain("Заголовок товара");
    expect(out).toContain("Ширина рулона");
    expect(out.length).toBeLessThanOrEqual(16_000);
  });
});

describe("buildLlmInput — JSON-LD вперёд + текст", () => {
  it("склеивает структурированные данные и текст страницы", () => {
    const input = buildLlmInput(`${LD_PRODUCT}<p>Ширина 1,06 м</p>`);
    expect(input).toContain("JSON-LD");
    expect(input).toContain("Обои Мир");
    expect(input).toContain("Ширина 1,06 м");
  });
});

describe("missingAiFields — что спрашивать у ИИ", () => {
  it("пустой spec → все поля вида", () => {
    expect(missingAiFields({}, "oboi")).toEqual(["rollWidthM", "rollLengthM", "rapportM", "pricePerRollRub"]);
  });

  it("цена найдена в одной единице → ценовую группу не спрашиваем (плитка)", () => {
    const missing = missingAiFields({ pricePerPackRub: 1500, tileLengthMm: 300 }, "plitka");
    expect(missing).toEqual(["tileWidthMm", "tilesPerPack"]);
  });

  it("всё заполнено → []", () => {
    expect(missingAiFields({ packVolumeL: 9, consumptionM2PerL: 10, pricePerPackRub: 4300 }, "kraska")).toEqual([]);
  });
});
