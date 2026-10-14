// Проба 9: окна и двери (demo-04 п.1–3) — живая сцена (ракурс 1/2, десктоп и телефон), серверный кадр, /flat.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch(); const L = (...a) => console.log(a.join(" "));
const snap = async (pg, n) => { await pg.screenshot({ path: `${OUT}/${n}.png` }); L("  экран", n); };
const btn = (pg, t) => pg.locator(`#shot button:has-text("${t}")`).first();
async function live(view, tag, idx) {
  const ctx = await b.newContext({ viewport: view, locale: "ru-RU", isMobile: view.width < 500, hasTouch: view.width < 500 }); const pg = await ctx.newPage();
  await pg.goto(BASE + "/demo/?live=force", { waitUntil: "networkidle", timeout: 60000 });
  await pg.locator("button[data-swap]").nth(idx).click(); await pg.waitForTimeout(10000); await snap(pg, `${tag}-angle1`);
  await btn(pg, "Ракурс 2").click(); await pg.waitForTimeout(7000); await snap(pg, `${tag}-angle2`);
  await ctx.close();
}
await live({ width: 1280, height: 900 }, "live-desk-set2", 0);
await live({ width: 1280, height: 900 }, "live-desk-loft", 3);
await live({ width: 390, height: 844 }, "live-phone-set2", 0);
// серверный кадр: без live=force на программном рендере окно само запрашивает эскиз через 1,5 с после замены
{
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage();
  let jobs = 0; pg.on("request", r => { if (r.url().includes("/api/render")) jobs++; });
  await pg.goto(BASE + "/demo/", { waitUntil: "networkidle", timeout: 60000 }); await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(3000);
  await pg.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click(); await pg.waitForTimeout(2500);
  L("  запросов кадра после замены:", jobs); const t = Date.now();
  await pg.waitForFunction(() => { const s = document.querySelector("#shot"); const img = s && s.querySelector(".shotwrap img, img.frame, img"); const txt = (s && s.innerText) || ""; return img && img.naturalWidth > 300 && !/Собираем|очереди|осталось|Считаем/i.test(txt); }, null, { timeout: 240000 }).catch(() => L("  серверный кадр не дождался"));
  L("  серверный кадр за", Math.round((Date.now() - t) / 1000), "с; текст:", JSON.stringify(((await pg.locator("#shot").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 160)));
  await snap(pg, "server-view-a"); const nav = pg.locator("#shotNext, #shotPrev, #shot button:has-text('›'), #shot button:has-text('‹')").first(); if (await nav.count()) { await nav.click(); await pg.waitForTimeout(800); await snap(pg, "server-view-b"); }
  const src = await pg.evaluate(() => [...document.querySelectorAll("#shot img")].map(i => i.getAttribute("src")).filter(s => /frames|scene3d/.test(s || "")).slice(0, 2)); L("  кадры:", src.join(" | "));
  await ctx.close();
}
// /flat
{
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage();
  await pg.goto(BASE + "/flat?demo=set2&flat=flat215", { waitUntil: "domcontentloaded", timeout: 60000 }); await pg.waitForSelector("canvas", { timeout: 90000 }); await pg.waitForTimeout(12000); await snap(pg, "flat-start");
  await pg.locator("button:has-text('Сверху')").first().click(); await pg.waitForTimeout(5000); await snap(pg, "flat-top");
  await pg.locator("button:has-text('Бродилка')").first().click(); await pg.waitForTimeout(3000); await pg.keyboard.down("KeyD"); await pg.waitForTimeout(900); await pg.keyboard.up("KeyD"); await pg.waitForTimeout(2500); await snap(pg, "flat-turn-right");
  await ctx.close();
}
await b.close();
