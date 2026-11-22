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
  await page.waitForFunction(() => [...document.images].slice(0, 6).every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 15000 }); // первые картинки загружены
  await page.waitForTimeout(800);
  const cookieBtn = page.getByRole("button", { name: "Понятно" });
  if (await cookieBtn.count()) await cookieBtn.click(); // плашка Метрики закрывает низ экрана
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/${name}-top.png` });
  await page.screenshot({ path: `${out}/${name}-full.png`, fullPage: true });
  // «просмотрено»: листаем карточки, каждая стоит на экране > 1 с — счётчик вверху растёт без единого клика
  const cards = page.locator("section[data-sku]");
  for (let i = 0; i < (await cards.count()); i++) {
    await cards.nth(i).scrollIntoViewIfNeeded();
    await page.waitForTimeout(1500);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/${name}-viewed.png` });
  if (process.env.SHOT_BAD === "1") {
    const bad = page.locator("button[aria-pressed]").first(); // единственная кнопка «Не ок» у первой карточки
    if ((await bad.getAttribute("aria-pressed")) !== "true") await bad.click(); // отметка с прошлого прогона уже стоит — не снимать
    await page.locator("textarea").first().fill("остался кусок фона у ножки / background left near the leg");
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `${out}/${name}-marked.png` });
  }
  // зум: открыть вид «шахматка» и увеличить КРОМКУ — левая ножка дивана (фон рядом с товаром), как будет смотреть владелец
  await page.locator("section[data-sku] button[aria-label*='шахматка']").first().click();
  await page.waitForTimeout(400);
  const pt = await page.evaluate(() => {
    const dlg = document.querySelector("[role=dialog]");
    const img = dlg?.querySelector("img");
    if (!dlg || !img) return null;
    const r = img.getBoundingClientRect();
    const k = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
    const w = img.naturalWidth * k;
    const h = img.naturalHeight * k;
    return { x: r.left + (r.width - w) / 2 + w * 0.075, y: r.top + (r.height - h) / 2 + h * 0.8 };
  });
  if (pt) {
    await page.mouse.move(pt.x, pt.y);
    for (let i = 0; i < 5; i++) await page.mouse.wheel(0, -300);
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/${name}-zoom.png` });
  await ctx.close();
}
await browser.close();
