import { test, expect } from "@playwright/test";

// ПОЛ ОТ ЗАСТРОЙЩИКА — ЖИВАЯ ПРОВЕРКА (план demo-06). В окне варианта — вход «Отделка и ремонт», пять образцов пола с ценой;
// выбор меняет номер состояния на s2, попадает в ссылку /flat (`opt=flooring:…`), а /flat показывает доплату отдельной строкой,
// не трогая сертификат. Без видеокарты сцена — запасной путь, поэтому проверяем состояние и деньги, а не картинку.

test("окно: «Отделка» → пять полов, выбор паркета — s2 и ссылка в 3D с полом", async ({ page }) => {
  test.setTimeout(120_000);
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await page.goto("/demo/?live=0&lang=ru");
  await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT", null, { timeout: 60_000 });
  await page.evaluate("openLiveWindow()");
  await page.locator("[data-opts]").click();
  const swatches = page.locator('#vfloor [data-fl^="flooring:"]');
  await expect(swatches).toHaveCount(5);
  const s1 = (await page.evaluate("curStateId()")) as string;
  expect(s1).toMatch(/^s1-/);
  await page.locator('[data-fl="flooring:parquet-herringbone"]').click();
  await expect(page.locator(".vfl-cur").first()).toContainText("Ёлочка");
  expect(await page.evaluate("curStateId()")).toMatch(/^s2-/);
  expect(await page.evaluate("JSON.stringify(DEVOPT)")).toBe('{"flooring":"parquet-herringbone"}');
  const href = (await page.locator("#vFlat").getAttribute("href")) ?? "";
  expect(href).toContain("opt=flooring:parquet-herringbone");
  // «назад» возвращает пол по умолчанию и номер s1
  await page.evaluate("histBack()");
  expect(await page.evaluate("curStateId()")).toBe(s1);
});

test("/flat с полом из ссылки: доплата застройщику отдельной строкой", async ({ page }) => {
  test.setTimeout(120_000);
  const demo = (await (await page.request.get("/demo/demo-data.json")).json()) as { variants?: { id: string }[] };
  const vid = demo.variants?.[0]?.id;
  await page.goto(`/flat?demo=${vid}&flat=flat215&opt=flooring:parquet-herringbone`);
  await expect(page.locator("body")).toContainText("доплата застройщику за отделку", { timeout: 60_000 });
  await expect(page.locator("body")).toContainText("+86 000");
});
