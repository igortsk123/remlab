import { defineConfig, devices } from "@playwright/test";

import { LIVE_BROWSER_ARGS, LIVE_CHECK_HEADERS } from "./e2e/live/browser";

// Живые проверки ПРОДА (план b2b-12): демо `/demo` — статическая страница, её отдаёт Caddy, в CI её нет. Запуск —
// ночной шаг `demo_live` (`tools/scout/refresh_daily.sh`) после публикации демо; вручную:
//   pnpm exec playwright test -c playwright.live.config.ts
export default defineConfig({
  testDir: "./e2e/live",
  testMatch: "**/*.live.ts",
  timeout: 60_000,
  retries: 1,
  // один браузер за раз (demo-03, 14.10): на DEV проверки идут рядом с рендером демо, а 7,6 ГБ на всё —
  // параллельные headless-браузеры вместе с рендером дважды вызывали earlyoom
  workers: 1,
  reporter: "line",
  // проверки — не покупатели (T-20261018-18): метка убирает их из счётчиков застройщика и событий, Метрика не грузится
  use: {
    baseURL: process.env.LIVE_BASE_URL ?? "https://remont-lab.online", trace: "off",
    extraHTTPHeaders: LIVE_CHECK_HEADERS, launchOptions: { args: LIVE_BROWSER_ARGS },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], locale: "ru-RU" } }],
});
