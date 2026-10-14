// Живой прогон демо как пользователь: все кнопки, все сценарии, экраны и ошибки. Временный скрипт сессии d8.
import { chromium } from "@playwright/test";
const OUT = process.argv[2]; const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" });
const pg = await ctx.newPage(); const errs = []; const fails = []; const log = [];
pg.on("console", m => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
pg.on("pageerror", e => errs.push("PAGEERROR " + String(e).slice(0, 200)));
pg.on("response", r => { if (r.status() >= 400) fails.push(r.status() + " " + r.url().slice(0, 140)); });
const L = (...a) => { const s = a.join(" "); log.push(s); console.log(s); };
const vis = `(e)=>{const r=e.getBoundingClientRect();const st=getComputedStyle(e);return r.width>0&&r.height>0&&st.visibility!=='hidden'&&st.display!=='none'&&st.opacity!=='0';}`;
async function controls(scope = "body") {
  return pg.evaluate(([sel, visSrc]) => { const vis = eval(visSrc); const root = document.querySelector(sel); if (!root) return [];
    return [...root.querySelectorAll("button,a,[role=button],input,select")].filter(vis).map(e => ({ tag: e.tagName, id: e.id, text: (e.innerText || e.value || e.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 50), href: e.getAttribute("href") || "", dis: e.disabled || false })).filter(x => x.text || x.href); }, [scope, vis]);
}
async function shot(name) { await pg.screenshot({ path: `${OUT}/${name}.png`, fullPage: false }); }
async function step(name, fn) { const t = Date.now(); try { await fn(); L(`✓ ${name} (${Date.now() - t} ms)`); } catch (e) { L(`✗ ${name}: ${String(e).split("\n")[0].slice(0, 180)}`); await shot("err-" + name.replace(/\W+/g, "_")).catch(() => {}); } }
const dumpC = async (label, scope) => { const c = await controls(scope); L(`  [${label}] ${c.length} controls: ` + c.map(x => `${x.text || x.href}${x.dis ? "(off)" : ""}`).join(" | ").slice(0, 900)); return c; };
const visibleText = async (sel) => pg.locator(sel).first().innerText().catch(() => "");

await step("S1 загрузка", async () => { await pg.goto(BASE + "/demo/", { waitUntil: "networkidle", timeout: 60000 }); await shot("01-load"); });
await step("S2 открыть карточку (Открыть)", async () => {
  await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(1500); await shot("02-open-card");
  for (const s of ["#sheet", "#swapBox", "#shot", "#stage"]) L(`  ${s} visible=`, await pg.locator(s).first().isVisible().catch(() => false));
  await dumpC("после Открыть", "body");
  const stage = await pg.evaluate(() => { const st = document.querySelector("#stage"); if (!st) return "no #stage"; return [...st.querySelectorAll("*")].filter(e => e.getBoundingClientRect().width > 20).slice(0, 25).map(e => e.tagName + (e.id ? "#" + e.id : "") + (e.className && typeof e.className === "string" ? "." + e.className.split(" ")[0] : "") + " " + Object.keys(e.dataset).join(",")).join(" ; "); });
  L("  stage children:", stage);
});
await step("S3 клик по предмету на плане", async () => {
  const el = pg.locator("#stage [data-id], #stage [data-slot], #stage [data-role], #stage g[data-i], #stage .item").first();
  if (await el.count()) { await el.click({ force: true }); await pg.waitForTimeout(800); await shot("03-item-click"); await dumpC("после клика по предмету", "body"); }
  else L("  предмет на плане не найден по известным селекторам");
});
await step("S4 замена из ленты ([data-pick])", async () => {
  const sumBefore = await visibleText("#sum, .sum, [id*=total], [class*=total]");
  const pick = pg.locator("[data-pick]").first(); L("  pick count:", await pg.locator("[data-pick]").count());
  await pick.click({ force: true }); await pg.waitForTimeout(1200); await shot("04-after-swap");
  const sumAfter = await visibleText("#sum, .sum, [id*=total], [class*=total]"); L("  sum before/after:", JSON.stringify(sumBefore.slice(0, 60)), "→", JSON.stringify(sumAfter.slice(0, 60)));
  for (const s of ["#swapShot", "#consShot", "#shotNow", "#swap3d"]) L(`  ${s} visible=`, await pg.locator(s).isVisible().catch(() => false), "text=", JSON.stringify(await visibleText(s)));
});
await step("S5 перетащить предмет", async () => {
  const el = pg.locator("#stage [data-id], #stage [data-slot], #stage g[data-i], #stage .item").first();
  const bb = await el.boundingBox(); if (!bb) throw new Error("нет bbox предмета");
  await pg.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await pg.mouse.down(); await pg.mouse.move(bb.x + bb.width / 2 + 40, bb.y + bb.height / 2 + 25, { steps: 8 }); await pg.mouse.up();
  await pg.waitForTimeout(800); await shot("05-after-drag"); await dumpC("после перетаскивания", "body");
  for (const s of ["#swapShot", "#consShot", "#shotNow"]) L(`  ${s} visible=`, await pg.locator(s).isVisible().catch(() => false));
});
await step("S6 Посмотреть фото с изменениями", async () => {
  const btn = pg.locator("#swapShot:visible, #consShot:visible, #shotNow:visible").first(); L("  кнопка:", JSON.stringify(await btn.innerText().catch(() => "нет")));
  const t = Date.now(); await btn.click(); await pg.waitForTimeout(2500); await shot("06a-shot-waiting"); L("  ожидание показывает:", JSON.stringify((await visibleText("#shot")).slice(0, 300)));
  await pg.waitForFunction(() => { const s = document.querySelector("#shot"); if (!s) return false; const img = s.querySelector("img"); const txt = s.innerText || ""; return (img && img.naturalWidth > 50) || /ошиб|не удалось|error|позже/i.test(txt); }, null, { timeout: 180000 });
  L("  кадр готов за", Date.now() - t, "ms"); await shot("06b-shot-ready"); L("  текст модалки:", JSON.stringify((await visibleText("#shot")).slice(0, 400))); await dumpC("модалка кадра", "#shot");
});
await step("S7 листание кадров ‹ ›", async () => { for (const id of ["#shotPrev", "#shotNext"]) { const l = pg.locator(id); L(`  ${id} count=${await l.count()} disabled=${await l.isDisabled().catch(() => "-")}`); if (await l.count() && !(await l.isDisabled())) { await l.click(); await pg.waitForTimeout(600); } } await shot("07-shot-nav"); });
await step("S8 Улучшить фото", async () => {
  const btn = pg.locator("#shImprove:visible, [data-up]:visible").first(); if (!(await btn.count())) throw new Error("кнопки «Улучшить фото» нет на экране");
  const t = Date.now(); await btn.click(); await pg.waitForTimeout(4000); await shot("08-improve-wait"); L("  через 4с:", JSON.stringify((await visibleText("#shot")).slice(0, 300)));
  await pg.waitForFunction(() => /улучш|ошиб|не удалось|нет денег|позже|готов/i.test(document.querySelector("#shot")?.innerText || ""), null, { timeout: 90000 }).catch(() => L("  за 90с состояние не изменилось"));
  L("  итог через", Date.now() - t, "ms:", JSON.stringify((await visibleText("#shot")).slice(0, 300))); await shot("08b-improve-result");
});
await step("S9 закрыть кадр, Посмотреть в 3D (href)", async () => { await pg.locator("#shotclose, #shotx").first().click().catch(() => {}); await pg.waitForTimeout(500); L("  swap3d href:", await pg.locator("#swap3d").getAttribute("href")); L("  pc3d href:", await pg.locator("#pc3d").getAttribute("href")); });
await step("S10 Сохранить коллекцию", async () => {
  const btn = pg.locator("button:has-text('Сохранить коллекцию'):visible").first(); await btn.click(); await pg.waitForTimeout(2500); await shot("10-save-collection");
  L("  url:", pg.url()); L("  текст после сохранения:", JSON.stringify((await visibleText("#sheet, body")).slice(0, 200)));
});
await step("S11 3D страница из варианта", async () => {
  const href = await pg.locator("#swap3d").getAttribute("href"); const p2 = await ctx.newPage(); const t = Date.now();
  await p2.goto(BASE + href, { waitUntil: "domcontentloaded", timeout: 60000 }); await p2.waitForSelector("canvas", { timeout: 90000 }); L("  canvas появился за", Date.now() - t, "ms");
  await p2.waitForTimeout(6000); await p2.screenshot({ path: `${OUT}/11-flat3d.png` }); L("  3D controls:", (await p2.evaluate(() => [...document.querySelectorAll("button,a")].map(e => (e.innerText || e.getAttribute("aria-label") || "").trim()).filter(Boolean).slice(0, 30).join(" | "))).slice(0, 600)); await p2.close();
});
await step("S12 закрыть вариант, кнопка Ссылка на карточке", async () => {
  await pg.keyboard.press("Escape"); await pg.locator("#swapClose:visible, #sh-close:visible, .close:visible").first().click().catch(() => {}); await pg.waitForTimeout(600);
  await pg.locator("button[data-link]").first().click(); await pg.waitForTimeout(1200); await shot("12-link"); L("  url:", pg.url()); await dumpC("после Ссылка", "body");
});
await step("S13 сердечко и Избранное", async () => { await pg.keyboard.press("Escape"); await pg.locator("button.heart").first().click(); await pg.waitForTimeout(500); await pg.locator("#feedShare").click(); await pg.waitForTimeout(1500); await shot("13-favorites"); await dumpC("Избранное", "body"); });
await step("S14 вкладки", async () => { await pg.keyboard.press("Escape"); for (const id of ["#tab-plan", "#tab-kitchen", "#tab-bedroom", "#tab-room"]) { await pg.locator(id).click(); await pg.waitForTimeout(900); await shot("14-tab-" + id.slice(5)); L(`  ${id}:`, JSON.stringify((await visibleText("main, body")).slice(0, 160))); } const soon = pg.locator(".tab.soon").first(); await soon.click(); await pg.waitForTimeout(600); L("  soon tab text after click:", JSON.stringify((await visibleText("body")).slice(0, 120))); });
await step("S15 EN", async () => { await pg.locator("[data-lang='en'], a:has-text('EN')").first().click(); await pg.waitForTimeout(1200); await shot("15-en"); const txt = await pg.evaluate(() => document.body.innerText); const cyr = (txt.match(/[А-Яа-яЁё]{3,}/g) || []); L("  кириллических слов на EN-экране:", cyr.length, cyr.slice(0, 12).join(", ")); await pg.locator("[data-lang='ru'], a:has-text('RU')").first().click().catch(() => {}); await pg.waitForTimeout(500); });
await step("S16 консультация / ипотека", async () => { await pg.locator("#pcCons").click(); await pg.waitForTimeout(900); await shot("16-cons"); await dumpC("консультация", "body"); await pg.keyboard.press("Escape"); await pg.locator("#pcMort").click(); await pg.waitForTimeout(900); await shot("16b-mort"); L("  текст:", JSON.stringify((await visibleText("body")).slice(0, 10))); await pg.keyboard.press("Escape"); });
await step("S17 Добавить новую расстановку", async () => { await pg.locator("text=Добавить новую расстановку").first().click(); await pg.waitForTimeout(1500); await shot("17-new"); await dumpC("новая расстановка", "body"); await pg.keyboard.press("Escape"); });
await step("S18 Посмотреть варианты интерьера", async () => { await pg.locator("#budgetGo").click(); await pg.waitForTimeout(800); await shot("18-budgetGo"); });
await step("S19 мобильный экран", async () => { const m = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }); const mp = await m.newPage(); await mp.goto(BASE + "/demo/", { waitUntil: "networkidle", timeout: 60000 }); await mp.screenshot({ path: `${OUT}/19a-mobile.png`, fullPage: true }); await mp.locator("button[data-swap]").first().click(); await mp.waitForTimeout(1500); await mp.screenshot({ path: `${OUT}/19b-mobile-card.png` }); const sw = await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth); L("  горизонтальный скролл на телефоне:", sw); await m.close(); });
L("=== console errors", errs.length); errs.slice(0, 10).forEach(e => L("  " + e)); L("=== http fails", fails.length); fails.slice(0, 10).forEach(e => L("  " + e));
await b.close();
