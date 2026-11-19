// Снимки локальной страницы /lab/cutout-check (T-20261119-104): телефон 375×667 и компьютер 1280×900. Зовёт cutout_check_preview.py.
// Аргументы: <база> <папка> <кука mesh_review>. Имя «Проба» кладётся в localStorage, чтобы не показывать окно «Кто проверяет?».
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const [base, out, cookie] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [name, vp, dsf] of [
  ["phone-375x667", { width: 375, height: 667 }, 2],
  ["desktop-1280x900", { width: 1280, height: 900 }, 1],
]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: dsf });
  await ctx.addCookies([{ name: "mesh_review", value: cookie, url: base }]);
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    try {
      localStorage.setItem("mesh-check-reviewer", "Проба");
    } catch {
      /* нет хранилища */
    }
  });
  await page.goto(`${base}/lab/cutout-check`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const cookieBtn = page.getByRole("button", { name: "Понятно" });
  if (await cookieBtn.count()) await cookieBtn.click(); // плашка Метрики закрывает низ экрана
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/${name}-top.png` });
  await page.screenshot({ path: `${out}/${name}-full.png`, fullPage: true });
  if (process.env.SHOT_BAD === "1") {
    await page.locator("button[aria-pressed]").nth(1).click(); // «Не ок» у первой карточки
    await page.locator("textarea").first().fill("остался кусок фона у ножки / background left near the leg");
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `${out}/${name}-marked.png` });
  }
  await ctx.close();
}
await browser.close();
