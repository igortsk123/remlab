import { defineConfig, devices } from "@playwright/test";

const PORT = 3000;
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  // в CI — по одному: 3D-тесты рисуют программным рендером (без видеокарты), параллельные вкладки душили процессор, и
  // проверки падали по таймауту то на одном, то на другом коммите (16.10); локально — параллельно, как было
  fullyParallel: !process.env.CI,
  workers: process.env.CI ? 1 : undefined,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // в CI ещё и отчёт GitHub: текст упавшей проверки попадает в аннотации запуска — их видно без токена (логи шагов закрыты)
  reporter: process.env.CI ? [["line"], ["github"]] : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
    // баннер cookie уже закрыт (b2b-04): он внизу экрана и перекрывал бы кнопки; e2e/legal.spec.ts проверяет его с чистого листа
    storageState: "e2e/cookies-seen.json",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "REMLAB_FAKE_AI=1 pnpm start",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
