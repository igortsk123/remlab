import { test, expect } from "@playwright/test";

// Golden-path smoke (§12.7): каркас поднимается и отвечает.
test("лендинг рендерится", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Обновите комнату",
  );
});

test("/api/health отдаёт ok:true", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.service).toBe("remlab");
});
