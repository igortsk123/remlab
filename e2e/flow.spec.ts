import { test, expect } from "@playwright/test";

// Сквозной happy-path Stage 1 на фейковом ИИ (REMLAB_FAKE_AI=1):
// старт → бриф+фото → стиль → AI-превью → paywall → оплата(демо) → «Мои комнаты».

// Валидный 1x1 PNG для загрузки фото.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

test("полный путь: фото → превью → оплата → мои комнаты", async ({ page }) => {
  await page.goto("/start");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Что хотите сделать");
  await page.getByRole("button", { name: "Продолжить" }).click();

  // Бриф + фото
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Фото и короткий бриф");
  await page.setInputFiles('input[type="file"]', { name: "room.png", mimeType: "image/png", buffer: PNG });
  await page.getByRole("button", { name: "К выбору стиля" }).click();

  // Стиль
  await expect(page.getByRole("heading", { level: 1 })).toContainText("визуальное направление");
  await page.locator('input[value="scandinavian"]').check();
  await page.getByRole("button", { name: "Показать AI-превью" }).click();

  // AI-превью (генерация на фейковом ИИ — быстро)
  await expect(page.getByRole("heading", { level: 1 })).toContainText("обновлённая", { timeout: 30_000 });
  await expect(page.locator("img.preview")).toBeVisible();
  await expect(page.getByText("Товары и материалы")).toBeVisible();

  // Paywall
  await page.getByRole("link", { name: "Открыть полный план" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("полный план");
  await page.getByRole("button", { name: /Оплатить/ }).click();

  // Оплачено (демо) → сохранить
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Полный план комнаты");
  await page.getByRole("link", { name: /Мои комнаты/ }).click();

  // Workspace
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Мои комнаты");
  await expect(page.getByText("полный план")).toBeVisible();
});
