import { test, expect } from "@playwright/test";

// Сквозной путь v0.4: калькулятор обоев → смета-чек-лист → добавить свою ссылку → переход через /go/.
test("калькулятор → смета → своя ссылка → /go/", async ({ page }) => {
  await page.goto("/calc/oboi");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("обои");

  await page.locator('input[name="width"]').fill("3.5");
  await page.locator('input[name="length"]').fill("4");
  await page.locator('input[name="height"]').fill("2.7");
  await page.getByRole("button", { name: /Посчитать и собрать смету/ }).click();

  // Страница сметы
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Смета", { timeout: 15_000 });
  await expect(page.getByText(/\d+ рулон/).first()).toBeVisible();
  await expect(page.getByText("Клей обойный")).toBeVisible(); // сопутствующее «предвосхищение»

  // Добавить свою ссылку
  await page.locator('input[name="url"]').fill("https://www.ozon.ru/product/oboi-123");
  await page.locator('input[name="title"]').fill("Обои флизелиновые");
  await page.locator('input[name="price"]').fill("1890");
  await page.getByRole("button", { name: "Добавить в список" }).click();

  await expect(page.getByText("Обои флизелиновые")).toBeVisible();
  // Внешняя ссылка идёт через наш /go/ (late-binding реф), не напрямую в магазин
  const goLink = page.getByRole("link", { name: /Открыть на ozon\.ru/ });
  await expect(goLink).toBeVisible();
  await expect(goLink).toHaveAttribute("href", /^\/go\//);
});

test("сколько стоит ремонт — вилка трёх бюджетов + регион", async ({ page }) => {
  await page.goto("/calc/remont?area=18&depth=update&region=million");
  // карточки вариантов (strong), exact чтобы «Средний» не совпал с опцией «Средний город»
  await expect(page.getByText("Эконом", { exact: true })).toBeVisible();
  await expect(page.getByText("Средний", { exact: true })).toBeVisible();
  await expect(page.getByText("Получше", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Собрать смету по этому варианту/ }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ремонт", { timeout: 15_000 });
  await expect(page.getByText(/Город-миллионник/)).toBeVisible(); // регион доехал в смету
});
