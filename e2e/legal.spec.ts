import { test, expect } from "@playwright/test";

// Согласия (план b2b-04, ADR-0268): ссылки на политику живые; в английском режиме Метрика не грузится до согласия.
// Чистый браузер: остальные тесты стартуют с закрытым баннером (playwright.config.ts: storageState).
test.use({ storageState: { cookies: [], origins: [] } });

test("политика, cookie и условия открываются из подвала", async ({ page }) => {
  await page.goto("/");
  for (const [name, path] of [["Политика обработки данных", "/privacy"], ["Cookie", "/cookies"], ["Условия", "/terms"]] as const) {
    const link = page.locator("footer").getByRole("link", { name, exact: true });
    await expect(link).toHaveAttribute("href", path);
    const res = await page.request.get(path);
    expect(res.status()).toBe(200);
  }
  await page.goto("/privacy?lang=en");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Privacy notice");
});

test("английский режим: Метрика не грузится до согласия, после «Accept» — грузится", async ({ page }) => {
  const metrika: string[] = [];
  await page.route("https://mc.yandex.ru/**", (route) => { metrika.push(route.request().url()); return route.abort(); });
  await page.goto("/privacy?lang=en");
  await expect(page.getByRole("button", { name: "Accept" })).toBeVisible();
  await page.waitForTimeout(500);
  expect(metrika).toEqual([]);
  await page.getByRole("button", { name: "Accept" }).click();
  await expect.poll(() => metrika.length).toBeGreaterThan(0);
});

test("русский режим: уведомление о cookie закрывается «Понятно» и больше не показывается", async ({ page }) => {
  await page.goto("/calc");
  await page.getByRole("button", { name: "Понятно" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Понятно" })).toHaveCount(0);
});
