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

// ШТОРКА v5 (demo-02, владелец 17.10): под кнопкой — строки-входы по комнате окна, под ними список мебели; в гостиной
// «Встраиваемое» нет (кухня — `roomKind: kitchen`); механизм проверяем подменой комнаты `?debug=1&vroom=kitchen`
test("2.23 окно: строки-входы по комнате — «Отделка» в гостиной, «Встраиваемое» с карточками кухни; «← Назад» — к списку", async ({ page }) => {
  test.setTimeout(150_000);
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await page.goto("/demo/?live=0&lang=ru");
  await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT", null, { timeout: 60_000 });
  await page.evaluate("openLiveWindow()");
  await expect(page.locator("#vGroups .vopts-row b")).toHaveText(["Отделка и ремонт"]);
  await expect(page.locator("#vlist .vitems .row").first()).toBeVisible();
  await page.locator("#vGroups [data-opts]").click();
  await expect(page.locator("#vgTitle")).toHaveText("Отделка и ремонт");
  await expect(page.locator("#vlist .vitems")).toBeHidden();
  await page.locator("#vOptsBack").click();
  await expect(page.locator("#vlist .vitems .row").first()).toBeVisible();

  await page.goto("/demo/?live=0&lang=ru&debug=1&vroom=kitchen");
  await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT", null, { timeout: 60_000 });
  await page.evaluate("openLiveWindow()");
  await page.locator('#vGroups [data-group="fitted"]').click();
  await expect(page.locator("#vfitted .vfit")).toHaveCount(4);
  await expect(page.locator("#vfitted .vfit.on .vfit-p")).toHaveText("в цене");
  await page.locator('#vfitted [data-fl="kitchen:kitchen-practical"]').click();
  expect(await page.evaluate("curStateId()")).toMatch(/^s2-/);
  expect((await page.locator("#vFlat").getAttribute("href")) ?? "").toContain("kitchen:kitchen-practical");
  await page.locator("#vOptsBack").click();
  await expect(page.locator('#vGroups [data-group="fitted"] span')).toContainText("Practical · по запросу");
});
