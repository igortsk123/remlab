import { test, expect } from "@playwright/test";

import { LIVE_CHECK_HEADER } from "../../lib/http/live-check";

// 0.1 ПРОВЕРКИ — НЕ ПОКУПАТЕЛИ (T-20261018-18). Ночной прогон ходит по проду как человек; чтобы он не попадал в отчёт
// застройщика и аналитику, все запросы страницы несут служебную метку (`e2e/live/browser.ts`), а Метрика не грузится.
// Тест сторожит саму настройку: событие страницы уходит с меткой, скрипт Метрики не загружен. Событие перехватывается —
// на сервер не идёт.
test("0.1 запросы страницы несут служебную метку, Метрика не грузится", async ({ page }) => {
  const marks: (string | undefined)[] = [];
  await page.route(/\/api\/events/, async (r) => {
    marks.push((await r.request().allHeaders())[LIVE_CHECK_HEADER]);
    await r.fulfill({ status: 204, body: "" });
  });
  const metrika: string[] = [];
  page.on("requestfinished", (r) => { if (/mc\.yandex\./.test(r.url())) metrika.push(r.url()); });
  await page.goto("/flat?flat=flat215", { waitUntil: "load" });
  // событие из браузера (тот же путь, что у кнопок страницы) — метку добавляет браузер, не тест
  await page.evaluate(() => navigator.sendBeacon("/api/events", new Blob([JSON.stringify({ apartmentId: "flat215", kind: "designer_open", lang: "ru" })], { type: "application/json" })));
  await expect.poll(() => marks.length).toBeGreaterThan(0);
  expect(marks.every((m) => m === "1"), `метка у событий: ${JSON.stringify(marks)}`).toBe(true);
  await page.waitForTimeout(1500);
  expect(metrika, "скрипт Метрики загрузился — визиты проверок попадут в её отчёты").toEqual([]);
  expect(await page.evaluate(() => typeof (window as unknown as { Ya?: unknown }).Ya)).toBe("undefined");
});
