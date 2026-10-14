// Проба 8: новое окно варианта (demo-02) — Б на компьютере, В со шторкой на телефоне. Экраны для разбора тремя ролями.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch(); const L = (...a) => console.log(a.join(" "));
const snap = async (pg, n) => { await pg.screenshot({ path: `${OUT}/${n}.png` }); L("  экран", n); };
const txt = async (pg, s) => (await pg.locator(s).first().innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 200);
const shotBtn = (pg, t) => pg.locator(`#shot button:text-is("${t}"), #shot button:has-text("${t}")`).first();
async function desk() {
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage();
  const errs = []; pg.on("pageerror", e => errs.push(String(e).slice(0, 120))); let renders = 0; pg.on("request", r => { if (r.url().includes("/api/render")) renders++; });
  await pg.goto(BASE + "/demo/?live=force", { waitUntil: "networkidle", timeout: 60000 });
  for (const [i, name] of [[0, "сканди"], [3, "лофт"]]) {
    await pg.locator("button[data-swap]").nth(i).click(); await pg.waitForTimeout(9000); await snap(pg, `D-${name}-01-open`);
    L(`  ${name} шапка окна:`, JSON.stringify(await txt(pg, "#shot .sidehead, #shot h3, #shot")));
    L("  переключатели:", JSON.stringify(await pg.evaluate(() => [...document.querySelectorAll("#shot button")].map(e => e.innerText.trim()).filter(Boolean).slice(0, 30).join(" | "))));
    for (const [t, n] of [["Ракурс 2", "02-angle2"], ["3D", "03-3d"], ["Ракурс 1", "04-angle1"]]) { const bt = shotBtn(pg, t); if (await bt.count()) { await bt.click(); await pg.waitForTimeout(7000); await snap(pg, `D-${name}-${n}`); } else L("  нет кнопки", t); }
    await pg.keyboard.press("Escape"); await pg.waitForTimeout(500);
  }
  // замена с замером крутилки и истории
  await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(6000);
  const r0 = renders; await pg.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await pg.waitForTimeout(800); await snap(pg, "D-05-picker");
  await pg.locator("#sheet .mini:has-text('Заменить')").nth(2).click();
  for (const t of [300, 1200, 4000]) { await pg.waitForTimeout(t); L(`  +${t}мс после замены: крутилка=`, await pg.locator("#shot .spinner, #shot [class*=spin], #shot [class*=load]:visible").count(), "| история:", JSON.stringify(await txt(pg, "#shot [class*=hist], #shot [class*=state]"))); }
  await snap(pg, "D-06-after-swap"); L("  POST /api/render при замене:", renders - r0);
  const undo = pg.locator("#shot button[aria-label*='Отмен'], #shot button:has-text('↶')").first(); if (await undo.count()) { await undo.click(); await pg.waitForTimeout(3000); await snap(pg, "D-07-undo"); L("  после ↶:", JSON.stringify(await txt(pg, "#shot [class*=hist], #shot [class*=state]"))); } else L("  кнопки ↶ нет");
  const plan = shotBtn(pg, "План"); if (await plan.count()) { await plan.click(); await pg.waitForTimeout(1500); await snap(pg, "D-08-plan"); }
  L("  ошибки страницы:", errs.length, errs.slice(0, 3).join(" ; ")); await ctx.close();
}
async function phone() {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "ru-RU" }); const pg = await ctx.newPage();
  await pg.goto(BASE + "/demo/?live=force", { waitUntil: "networkidle", timeout: 60000 });
  await pg.locator("button[data-swap]").first().tap(); await pg.waitForTimeout(9000); await snap(pg, "P-01-open-peek");
  L("  шторка (текст):", JSON.stringify(await txt(pg, "#shot [class*=sheet], #shot [class*=drawer], #shot")));
  const chip = pg.locator("#shot [class*=handle], #shot [class*=grab], #shot button:has-text('Товары')").first(); L("  ручка/чип:", await chip.count(), JSON.stringify(await chip.innerText().catch(() => "")));
  if (await chip.count()) { await chip.tap(); await pg.waitForTimeout(1200); await snap(pg, "P-02-half"); await chip.tap(); await pg.waitForTimeout(1200); await snap(pg, "P-03-full"); }
  const sc = pg.locator("#shot canvas, #shot img").first(); const bb = await sc.boundingBox(); if (bb) { await pg.touchscreen.tap(bb.x + bb.width * 0.6, bb.y + bb.height * 0.6); await pg.waitForTimeout(1500); await snap(pg, "P-04-tap-scene"); L("  после тапа по сцене:", JSON.stringify(await txt(pg, "#shot"))); }
  const bt = shotBtn(pg, "3D"); if (await bt.count()) { await bt.tap(); await pg.waitForTimeout(7000); await snap(pg, "P-05-3d"); }
  const bt2 = shotBtn(pg, "Ракурс 2"); if (await bt2.count()) { await bt2.tap(); await pg.waitForTimeout(7000); await snap(pg, "P-06-angle2"); }
  L("  горизонтальный скролл:", await pg.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)); await ctx.close();
}
await desk(); await phone(); await b.close();
