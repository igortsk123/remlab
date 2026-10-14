// Проба 10: demo-02 блокеры (а)–(и) + demo-04 п.4 — по списку «смотреть» сессии Opus.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch(); const L = (...a) => console.log(a.join(" "));
const snap = async (pg, n) => { await pg.screenshot({ path: `${OUT}/${n}.png` }); L("  экран", n); };
const btn = (pg, t) => pg.locator(`#shot button:text-is("${t}")`).first();
const pinsInfo = async (pg) => pg.evaluate(() => { const box = document.querySelector("#shot canvas, #shot .shotwrap"); const r0 = box ? box.getBoundingClientRect() : null; const pins = [...document.querySelectorAll("#shot [class*=pin]")].filter(e => /₽/.test(e.innerText)).map(e => { const r = e.getBoundingClientRect(); return { t: e.innerText.trim(), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; }); let overlaps = 0, outside = 0; for (let i = 0; i < pins.length; i++) { const a = pins[i]; if (r0 && (a.x < r0.x || a.x + a.w > r0.x + r0.width || a.y < r0.y || a.y + a.h > r0.y + r0.height)) outside++; for (let j = i + 1; j < pins.length; j++) { const c = pins[j]; if (a.x < c.x + c.w && c.x < a.x + a.w && a.y < c.y + c.h && c.y < a.y + a.h) overlaps++; } } return { n: pins.length, overlaps, outside, list: pins.map(p => p.t).join(",") }; });
async function run(view, tag, idx, extra = "") {
  const ctx = await b.newContext({ viewport: view, locale: "ru-RU", isMobile: view.width < 500, hasTouch: view.width < 500 }); const pg = await ctx.newPage();
  await pg.goto(BASE + "/demo/?live=force" + extra, { waitUntil: "networkidle", timeout: 60000 });
  await pg.locator("button[data-swap]").nth(idx).click(); await pg.waitForTimeout(10000); await snap(pg, `${tag}-a1`); L(`  ${tag} пины ракурс1:`, JSON.stringify(await pinsInfo(pg)));
  L("  подписи/бейджи:", JSON.stringify(await pg.evaluate(() => [...document.querySelectorAll("#shot [class*=badge], #shot [class*=live], #shot [class*=cap]")].filter(e => e.innerText.trim()).map(e => { const r = e.getBoundingClientRect(); return e.innerText.trim().slice(0, 40) + "@" + Math.round(r.x) + "," + Math.round(r.y); }).slice(0, 4))));
  L("  переключатель:", JSON.stringify(await pg.evaluate(() => { const t = [...document.querySelectorAll("#shot button")].find(e => e.innerText.trim() === "Ракурс 1"); const r = t && t.getBoundingClientRect(); return r ? Math.round(r.x) + "," + Math.round(r.y) + " " + Math.round(r.width) + "x" + Math.round(r.height) : "?"; })));
  await btn(pg, "Ракурс 2").click(); await pg.waitForTimeout(7000); await snap(pg, `${tag}-a2`); L(`  пины ракурс2:`, JSON.stringify(await pinsInfo(pg)));
  await btn(pg, "3D").click(); await pg.waitForTimeout(8000); await snap(pg, `${tag}-3d`);
  await ctx.close();
}
await run({ width: 1280, height: 900 }, "desk-set1", 0);
await run({ width: 1280, height: 900 }, "desk-loft", 3);
await run({ width: 390, height: 844 }, "phone-set1", 0);
// телефон: раскрытая шторка
{ const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "ru-RU" }); const pg = await ctx.newPage(); await pg.goto(BASE + "/demo/?live=force", { waitUntil: "networkidle", timeout: 60000 }); await pg.locator("button[data-swap]").first().tap(); await pg.waitForTimeout(8000);
  const chip = pg.locator("#shot button:has-text('Товары')").first(); if (await chip.count()) { await chip.tap(); await pg.waitForTimeout(1200); await snap(pg, "phone-sheet-half"); await chip.tap().catch(() => {}); await pg.waitForTimeout(1200); await snap(pg, "phone-sheet-full"); } else L("  чип шторки не найден"); await ctx.close(); }
// EN
{ const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "en-GB" }); const pg = await ctx.newPage(); await pg.goto(BASE + "/demo/?live=0&lang=en", { waitUntil: "networkidle", timeout: 60000 }); await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(3000); await pg.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini").nth(1).click(); await pg.waitForTimeout(1500); L("  EN текст окна:", JSON.stringify((await pg.locator("#shot").innerText()).replace(/\s+/g, " ").slice(0, 260))); await snap(pg, "en-after-swap"); await ctx.close(); }
// запасной путь: ракурс 2 = серверный C2
{ const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage(); await pg.goto(BASE + "/demo/?live=0", { waitUntil: "networkidle", timeout: 60000 }); await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(3000); await pg.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click();
  await pg.waitForFunction(() => { const s = document.querySelector("#shot"); const img = s && s.querySelector(".shotwrap img"); return img && img.naturalWidth > 300 && !/Собираем|очереди|Считаем/i.test(s.innerText); }, null, { timeout: 240000 }).catch(() => L("  эскиз не дождался"));
  await snap(pg, "fallback-a1"); await btn(pg, "Ракурс 2").click(); await pg.waitForTimeout(3000); await snap(pg, "fallback-a2"); L("  fallback кадры:", JSON.stringify(await pg.evaluate(() => [...document.querySelectorAll("#shot img")].map(i => i.getAttribute("src")).filter(s => /frames|scene3d|improve/.test(s || "")).slice(0, 3)))); L("  fallback текст:", JSON.stringify((await pg.locator("#shot").innerText()).replace(/\s+/g, " ").slice(0, 160))); await ctx.close(); }
await b.close();
