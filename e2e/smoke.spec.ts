import { test, expect } from "@playwright/test";

// Golden-path smoke (§12.7): каркас поднимается и отвечает.
test("лендинг рендерится", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Посчитайте ремонт",
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

test("/api/health отдаёт ok:true", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.service).toBe("remlab");
});
