import { test, expect } from "@playwright/test";

// Golden-path smoke (§12.7): каркас поднимается и отвечает.
test("лендинг рендерится", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Сделайте ремонт",
  );
});

test("хаб калькуляторов открывается", async ({ page }) => {
  await page.goto("/calc");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Сколько нужно материалов");
});

test("/rooms открывается у нового посетителя (без cookie) — пустой стейт", async ({ page }) => {
  await page.goto("/rooms");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Мои комнаты");
});

test("/lab: вкладки лаборатории у нового посетителя — пустые состояния и тизеры", async ({ page }) => {
  await page.goto("/lab");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Мои расчёты и проекты");
  // Материалы (по умолчанию): пустое состояние.
  await expect(page.getByText("Пока пусто")).toBeVisible();
  const tabs = page.getByRole("navigation", { name: "Разделы лаборатории" });
  // Вкладка «Ремонт» — тизер раздела.
  await tabs.getByRole("link", { name: /Ремонт/ }).click();
  await expect(page.getByRole("heading", { name: /сколько стоит ремонт/i })).toBeVisible();
  // Вкладка «Дизайны» — тизер дизайна по фото.
  await tabs.getByRole("link", { name: /Дизайны/ }).click();
  await expect(page.getByRole("heading", { name: /дизайн вашей комнаты/i })).toBeVisible();
});

test("/api/health отдаёт ok:true", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.service).toBe("remlab");
});
