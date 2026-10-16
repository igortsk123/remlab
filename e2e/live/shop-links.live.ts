import { test, expect, type Page } from "@playwright/test";

// «В МАГАЗИН» — ВСЕГДА В НОВОЙ ВКЛАДКЕ (владелец 16.10, план demo-02 § «Приёмка владельцем 16.10» п.7). Покупатель, ушедший в
// магазин в той же вкладке, теряет свою расстановку. Инвариант: у каждой ссылки на магазин (чужой адрес или наш реф-переход
// `/go/…`) — `target="_blank"` и `rel` с `noopener`. Проверяем там, где ссылки есть: витрина, окно варианта, лента замен, /flat.

type Bad = { href: string; target: string; rel: string; text: string };

async function badShopLinks(page: Page): Promise<{ n: number; bad: Bad[] }> {
  return page.evaluate(() => {
    const own = location.origin;
    const shop = [...document.querySelectorAll<HTMLAnchorElement>("a[href]")].filter((a) => {
      const u = new URL(a.getAttribute("href") ?? "", location.href);
      return /^https?:$/.test(u.protocol) && (u.origin !== own || u.pathname.startsWith("/go/"));
    });
    const bad = shop.filter((a) => a.target !== "_blank" || !/\bnoopener\b/.test(a.rel))
      .map((a) => ({ href: a.href.slice(0, 120), target: a.target, rel: a.rel, text: (a.textContent ?? "").trim().slice(0, 40) }));
    return { n: shop.length, bad };
  });
}

test("витрина, окно варианта и лента замен: ссылки в магазин — в новой вкладке", async ({ page }) => {
  test.setTimeout(180_000);
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await page.goto("/demo/?live=0");
  // данные витрины — переменная страницы (`let D`), не свойство window
  await page.waitForFunction("typeof D !== 'undefined' && !!D", null, { timeout: 60_000 });
  const seen: Record<string, number> = {};
  const check = async (where: string) => {
    const r = await badShopLinks(page);
    seen[where] = r.n;
    expect(r.bad, `${where}: ссылки в магазин без новой вкладки`).toEqual([]);
  };
  await check("витрина");
  await page.evaluate(() => (window as unknown as { openLiveWindow(): void }).openLiveWindow());
  await page.waitForSelector("#shotbody [data-rep]", { timeout: 60_000 });
  await check("окно варианта");
  await page.evaluate(() => (document.querySelector("#shotbody [data-rep]") as HTMLElement).click());
  await page.waitForSelector("#grid .card", { timeout: 30_000 });
  await check("лента замен");
  console.log("ссылок в магазин:", JSON.stringify(seen));
  expect(seen["окно варианта"]).toBeGreaterThan(0);
  expect(seen["лента замен"]).toBeGreaterThan(0);
});

test("/flat: ссылки в магазин — в новой вкладке", async ({ page }) => {
  test.setTimeout(120_000);
  const card = await (await page.request.get("/api/apartments/flat215?lang=ru")).json() as { ok: boolean };
  expect(card.ok).toBe(true);
  const demo = await (await page.request.get("/demo/demo-data.json")).json() as { variants?: { id: string }[] };
  const vid = demo.variants?.[0]?.id;
  expect(vid).toBeTruthy();
  await page.goto(`/flat?demo=${vid}&flat=flat215`);
  // список мест и карточка выбранного предмета («смотреть в магазине»)
  await page.getByRole("button", { name: "диван", exact: true }).first().click({ timeout: 60_000 });
  await page.waitForTimeout(1500);
  const r = await badShopLinks(page);
  console.log("/flat ссылок в магазин:", r.n);
  expect(r.bad).toEqual([]);
  expect(r.n).toBeGreaterThan(0);
});
