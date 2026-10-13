import { describe, expect, it } from "vitest";

import { POST } from "@/app/api/collections/route";
import { GET } from "@/app/api/collections/[id]/route";
import { currentPrices, priceIndex } from "@/lib/collections/prices";

// Коллекции (план b2b-05): сохранил → открыл по ссылке → те же предметы; цены при открытии — текущие,
// пропавший товар помечен, а не подменён (ADR-0254 п.6).

const body = {
  apartmentId: "flat215", baseVariant: "set2", style: "сканди", lang: "ru",
  items: [{ role: "диван", x: 120, y: 80, rot: 180, w: 200, d: 90, h: 80, sku: { sid: "112923_1", name: "Диван А", price: 50000 } }],
};
const post = (b: unknown) => new Request("http://x/api/collections", { method: "POST", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" }, body: JSON.stringify(b) });

describe("коллекции", () => {
  it("сохранение → ссылка → тот же снимок", async () => {
    const r = await POST(post(body));
    expect(r.status).toBe(200);
    const { id } = (await r.json()) as { id: string };
    const g = await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) });
    const { collection } = (await g.json()) as { collection: { items: { x: number; sku: { sid: string } }[]; partnerId: string } };
    expect(collection.items[0]).toMatchObject({ x: 120, sku: { sid: "112923_1" } });
    expect(collection.partnerId).toBe("demo");
  });

  it("чужая квартира, мусор и слишком большое тело — отказ", async () => {
    expect((await POST(post({ ...body, apartmentId: "ghost" }))).status).toBe(400);
    expect((await POST(post({ ...body, items: [] }))).status).toBe(400);
    const big = { sid: "1_1", name: "я".repeat(200), url: "https://a.ru/" + "a".repeat(580) };
    const huge = { ...body, items: Array.from({ length: 60 }, () => ({ ...body.items[0], sku: big })),
      decor: Array.from({ length: 30 }, () => ({ role: "ваза", sku: big })) };
    expect((await POST(post(huge))).status).toBe(413);
  });

  it("текущие цены: из витрины; нет в витрине — помечен, старая цена не выдаётся за текущую", () => {
    const idx = priceIndex({ variants: [{ items: [{ sku: { sid: "1_a", price: 1000, price_at: "2026-10-13" } }] }], feeds: { диван: [{ sid: "1_b", price: 500 }] } });
    const cur = currentPrices(["1_a", "1_b", "1_gone"], idx);
    expect(cur["1_a"]).toEqual({ price: 1000, priceAt: "2026-10-13", unavailable: false });
    expect(cur["1_b"]!.price).toBe(500);
    expect(cur["1_gone"]).toEqual({ price: null, priceAt: null, unavailable: true });
    expect(currentPrices(["1_a"], null)["1_a"]!.unavailable).toBe(false); // витрина не ответила — не «пропал»
  });
});
