// Проба 3: оба вида нового кадра + настоящее перетаскивание столика по подписи на плане.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage();
const L = (...a) => console.log(a.join(" ")); const text = async (s) => pg.locator(s).first().innerText().catch(() => "");
const shotState = async () => (await text("#shot")).replace(/\s+/g, " ").slice(0, 140);
const waitPhoto = async (label, timeout = 240000) => { const t = Date.now(); const before = await pg.evaluate(() => document.querySelector("#shot img")?.getAttribute("src") || "");
  await pg.waitForFunction((b0) => { const s = document.querySelector("#shot"); if (!s) return false; const img = s.querySelector("img"); const txt = s.innerText || ""; return (img && img.naturalWidth > 50 && img.getAttribute("src") !== b0 && !/Собираем|очереди|осталось/i.test(txt)) || /ошиб|не удалось|позже|нет денег/i.test(txt); }, before, { timeout });
  L(`  ${label}: ${Math.round((Date.now() - t) / 1000)} с; src=${(await pg.evaluate(() => document.querySelector("#shot img")?.getAttribute("src") || "")).slice(-60)}`); };
await pg.goto(BASE + "/demo/", { waitUntil: "networkidle", timeout: 60000 });
await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(1000);
L("исходный кадр src:", (await pg.evaluate(() => document.querySelector("#shot img")?.getAttribute("src") || "")).slice(-70));
await pg.locator("#shotPrev").click(); await pg.waitForTimeout(500); await pg.screenshot({ path: `${OUT}/P3-orig-view1.png` });
await pg.locator("#shotbody [data-rep]").first().click(); await pg.waitForTimeout(900); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click(); await pg.waitForTimeout(1200);
await pg.locator("#shReshoot:visible").first().click(); await waitPhoto("новый кадр"); await pg.screenshot({ path: `${OUT}/P3-new-view2.png` });
L("подпись:", JSON.stringify((await text("#shot")).match(/\d из \d/)?.[0]));
await pg.locator("#shotPrev").click(); await pg.waitForTimeout(600); await pg.screenshot({ path: `${OUT}/P3-new-view1.png` }); L("после ‹:", JSON.stringify((await text("#shot")).match(/\d из \d/)?.[0]));
const imgs = await pg.evaluate(() => [...document.querySelectorAll("#shot img")].map(i => i.getAttribute("src").slice(-60) + " " + i.naturalWidth + "x" + i.naturalHeight)); L("img в окне:", imgs.join(" | "));
// конструктор и перетаскивание столика по подписи
await pg.locator("#shEdit:visible").first().click(); await pg.waitForTimeout(1000);
const lbl = pg.locator("#stage text", { hasText: /^столик/ }).first(); const lb = await lbl.boundingBox(); L("подпись столика bbox:", JSON.stringify(lb));
const x = lb.x + lb.width / 2, y = lb.y - 60; const stateBefore = await text("#layoutState");
await pg.mouse.move(x, y); await pg.mouse.down(); await pg.waitForTimeout(400); for (let i = 1; i <= 15; i++) { await pg.mouse.move(x + 8 * i, y + 2 * i); await pg.waitForTimeout(20); } await pg.mouse.up(); await pg.waitForTimeout(600);
const lb2 = await lbl.boundingBox(); L("подпись после drag:", JSON.stringify(lb2), "| layoutState:", stateBefore, "→", await text("#layoutState"));
await pg.screenshot({ path: `${OUT}/P3-dragged.png` });
// поворот тапом (ADR-0140: тап — ±90°)
await pg.mouse.click(lb2.x + lb2.width / 2, lb2.y - 60); await pg.waitForTimeout(500); await pg.screenshot({ path: `${OUT}/P3-tap.png` }); L("после тапа — есть ли оверлей поворота:", await pg.locator("#rotOvl, [data-rot], .rotovl").count());
await pg.locator("#consShot:visible").first().click(); await waitPhoto("кадр после перетаскивания"); await pg.screenshot({ path: `${OUT}/P3-after-drag-view2.png` }); await pg.locator("#shotPrev").click().catch(() => {}); await pg.waitForTimeout(500); await pg.screenshot({ path: `${OUT}/P3-after-drag-view1.png` });
await b.close();
