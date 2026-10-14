// Проба 7: прогулка по 3D (/flat) глазами пользователя + живая сцена демо (?live=force). Экраны для разбора.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch();
const L = (...a) => console.log(a.join(" "));
const snap = async (pg, name) => { await pg.screenshot({ path: `${OUT}/${name}.png` }); L("  экран", name); };
const clickText = async (pg, t, timeout = 8000) => { const l = pg.locator(`button:has-text("${t}"), a:has-text("${t}"), [role=tab]:has-text("${t}")`).first(); await l.click({ timeout }); };
async function flat(view, name) {
  const ctx = await b.newContext({ viewport: view, locale: "ru-RU", isMobile: view.width < 500, hasTouch: view.width < 500 }); const pg = await ctx.newPage();
  const errs = []; pg.on("pageerror", e => errs.push(String(e).slice(0, 120)));
  const t = Date.now(); await pg.goto(BASE + "/flat?demo=set2&flat=flat215", { waitUntil: "domcontentloaded", timeout: 60000 }); await pg.waitForSelector("canvas", { timeout: 90000 }).catch(async () => { await snap(pg, `${name}-00-nocanvas`); L("  canvas не появился; текст:", (await pg.evaluate(() => document.body.innerText)).replace(/\s+/g, " ").slice(0, 200)); });
  await pg.waitForFunction(() => !/\d+ ?%/.test(document.body.innerText) || /100 ?%/.test(document.body.innerText), null, { timeout: 120000 }).catch(() => L("  прогресс не дождался"));
  await pg.waitForTimeout(6000); L(`${name}: загрузка ${Math.round((Date.now() - t) / 1000)} с`); await snap(pg, `${name}-01-start`);
  L("  кнопки:", (await pg.evaluate(() => [...document.querySelectorAll("button,a,[role=tab]")].map(e => (e.innerText || e.getAttribute("aria-label") || "").trim()).filter(Boolean).join(" | "))).slice(0, 500));
  for (const [m, n] of [["Сверху", "02-top"], ["План", "03-plan"], ["Фото", "04-photo"], ["Бродилка", "05-walk"]]) { try { await clickText(pg, m); await pg.waitForTimeout(3500); await snap(pg, `${name}-${n}`); } catch (e) { L("  нет режима", m); } }
  // прогулка: вперёд, поворот, вперёд
  const cv = pg.locator("canvas").first(); const bb = await cv.boundingBox();
  await pg.mouse.click(bb.x + bb.width / 2, bb.y + bb.height / 2); await pg.keyboard.down("KeyW"); await pg.waitForTimeout(1500); await pg.keyboard.up("KeyW"); await pg.waitForTimeout(800); await snap(pg, `${name}-06-walk-forward`);
  await pg.keyboard.down("KeyA"); await pg.waitForTimeout(700); await pg.keyboard.up("KeyA"); await pg.waitForTimeout(800); await snap(pg, `${name}-07-turn-left`);
  await pg.keyboard.down("KeyW"); await pg.waitForTimeout(2500); await pg.keyboard.up("KeyW"); await pg.waitForTimeout(800); await snap(pg, `${name}-08-walk-more`);
  // клик по предмету в центре
  await pg.mouse.click(bb.x + bb.width / 2, bb.y + bb.height * 0.62); await pg.waitForTimeout(1200); await snap(pg, `${name}-09-click-item`);
  L("  после клика:", (await pg.evaluate(() => [...document.querySelectorAll("button")].map(e => (e.innerText || e.getAttribute("aria-label") || "").trim()).filter(Boolean).slice(0, 40).join(" | "))).slice(0, 400));
  // комнаты
  for (const r of ["Кухня", "Спальня", "Санузел", "Прихожая", "Вся квартира"]) { try { await clickText(pg, r, 4000); await pg.waitForTimeout(4000); await snap(pg, `${name}-10-room-${r}`); } catch (e) { L("  нет комнаты/кнопки", r); } }
  L("  ошибки страницы:", errs.length, errs.slice(0, 3).join(" ; ")); await ctx.close();
}
await flat({ width: 1280, height: 900 }, "flat-desk");
await flat({ width: 390, height: 844 }, "flat-phone");
// живая сцена демо принудительно
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" }); const pg = await ctx.newPage();
await pg.goto(BASE + "/demo/?live=force", { waitUntil: "networkidle", timeout: 60000 }); await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(12000); await snap(pg, "live-01-open");
L("  canvas:", await pg.locator("#shot canvas").count(), "| бейдж:", JSON.stringify(await pg.locator(".livebadge").first().innerText().catch(() => "")));
await pg.locator("#shotbody [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click(); await pg.waitForTimeout(12000); await snap(pg, "live-02-after-swap");
for (const [m, n] of [["3D", "03-3d"], ["Ракурс", "04-angle"], ["План", "05-plan"]]) { try { await pg.locator(`#shot button:has-text("${m}")`).first().click({ timeout: 3000 }); await pg.waitForTimeout(6000); await snap(pg, `live-${n}`); } catch (e) { L("  нет переключателя", m); } }
await b.close();
