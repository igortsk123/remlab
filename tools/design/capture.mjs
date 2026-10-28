// ОБХОД ЖИВОГО ДЕМО ДЛЯ ВЫГРУЗКИ В ФИГМУ (план design-01-figma-export, п.1): каждое состояние карты сценариев
// (`.memory_bank/domain/demo-scenario-map.md`) → PNG + статичный HTML (для html.to.design) + образцы компонентов (для кита и figma-spec).
// Ничего платного: «Сделать реалистичнее»/«улучшить фото» не нажимаются; всё, что пишет на сервер или может стоить денег,
// подменено ответом в браузере (`/api/render`, `/api/job`, `/api/draft/paid` → нет денег, `/api/collections` POST/PATCH,
// `/api/share`, `/api/warm`, `/api/render/frame`, `/api/events`). Сервер не трогается.
//   node tools/design/capture.mjs <OUT> <ru|en> <375x812|1440x900>
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const [OUT, LANG, VP] = process.argv.slice(2);
if (!OUT || !LANG || !VP) { console.error("usage: capture.mjs <OUT> <ru|en> <WxH>"); process.exit(2); }
const [W, H] = VP.split("x").map(Number); const PHONE = W <= 700; const DEV = PHONE ? "phone" : "desktop";
const BASE = process.env.BASE || "https://remont-lab.online/demo/";
const KEY = `${LANG}-${W}`;
const SCR = join(OUT, "screens", KEY); const ASSETS = join(OUT, "assets"); const CAP = join(OUT, "capture");
for (const d of [SCR, ASSETS, CAP]) mkdirSync(d, { recursive: true });
const FX = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fx-page.js"), "utf8");
const LOG = []; const note = (...a) => { const s = a.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" "); LOG.push(s); console.log(`[${KEY}] ${s}`); };
const SAMPLES = []; const SCREENS = []; const TEXTS = []; let PROBE = null;
const EN = LANG === "en";

const FAKE_ID = (n) => ("figmaexport" + n).padEnd(22, "x").slice(0, 22);
let favN = 0;
async function routes(ctx) {
  await ctx.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await ctx.route(/\/api\/warm/, (r) => r.fulfill({ status: 204, body: "" }));
  await ctx.route(/\/api\/draft\/paid/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ available: false }) }));
  await ctx.route(/\/api\/render\/frame/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "fx" }) }));
  await ctx.route(/\/api\/render(\?|$)/, (r) => r.request().method() === "POST" ? r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job: "fake-" + Date.now() }) }) : r.continue());
  await ctx.route(/\/api\/job\?/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "running", eta: 60 }) }));
  await ctx.route(/\/api\/share/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, id: "fx" }) }));
  await ctx.route(/\/api\/sends/, (r) => r.fulfill({ status: 404, body: "" }));
  await ctx.route(/\/api\/collections/, (r) => {
    const m = r.request().method();
    if (m === "POST") { favN++; return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, id: FAKE_ID(favN), editToken: "fx" }) }); }
    if (m === "PATCH" || m === "DELETE") return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    // выдуманных коллекций на сервере нет — чтение отвечает сбоем (не «нет такой»): корзина остаётся как есть
    return r.fulfill({ status: 503, body: "" });
  });
}

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
async function newPage(seed) {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: EN ? "en-GB" : "ru-RU" });
  await routes(ctx);
  await ctx.addInitScript(FX);
  if (seed) await ctx.addInitScript(([k, v]) => { try { if (!sessionStorage.getItem("fxseed")) { localStorage.setItem(k, v); sessionStorage.setItem("fxseed", "1"); } } catch (e) {} }, seed);
  const p = await ctx.newPage(); p.on("pageerror", (e) => note("pageerror", String(e).slice(0, 160)));
  return p;
}
const settle = (p) => p.waitForFunction(() => document.getAnimations().filter((a) => a.playState === "running" && !(a.effect && a.effect.target && a.effect.target.classList && a.effect.target.classList.contains("spin"))).length === 0, null, { timeout: 6000 }).catch(() => {});
const wait = (p, ms) => p.waitForTimeout(ms);

// ——— снимок состояния: PNG + статичный HTML + холсты → assets ———
let stN = 0;
async function shoot(p, name, title, opts = {}) {
  stN++; const id = String(stN).padStart(2, "0") + "-" + name;
  await wait(p, 250);
  const png = `${id}.png`; await p.screenshot({ path: join(SCR, png), fullPage: !!opts.full });
  let full = null; if (opts.alsoFull) { full = `${id}-full.png`; await p.screenshot({ path: join(SCR, full), fullPage: true }); }
  const snap = await p.evaluate((m) => window.__fx.snapshot(m), { state: id, title, lang: LANG, device: DEV });
  let html = snap.html;
  for (const c of snap.canvases) {
    const f = `${KEY}-${id}-${c.id}.jpg`;
    try { await cvShot(p, c.id, join(ASSETS, f)); html = html.split(`data-fxcv-src="${c.id}"`).join(`src="../../assets/${f}"`); }
    catch (e) { note("canvas-fail", id, String(e).slice(0, 100)); }
  }
  writeFileSync(join(SCR, `${id}.html`), html);
  for (const t of await p.evaluate(() => window.__fx.texts())) TEXTS.push(t);
  SCREENS.push({ id, title, png, full, html: `${id}.html`, lang: LANG, device: DEV, w: W, h: H, bytes: html.length });
  note("screen", id);
  return id;
}
// ——— образец компонента ———
async function grab(p, figma, sel, variant, opts = {}) {
  try {
    const g = await p.evaluate(([s, o]) => window.__fx.grab(s, o), [sel, opts]);
    if (!g) { note("нет образца", figma, sel, variant); return null; }
    let html = g.html; const files = {};
    for (const c of g.canvases) {
      const f = `${KEY}-s${SAMPLES.length}-${c.id}.jpg`;
      try { await cvShot(p, c.id, join(ASSETS, f)); html = html.split(`data-fxcv-src="${c.id}"`).join(`data-asset="${f}"`); files["cv:" + c.id] = f; } catch (e) { note("canvas-fail", figma, String(e).slice(0, 100)); }
    }
    // картинки не с адреса (blob:/data:) — снимок самого элемента; дерево ссылается на файл в assets/
    const shots = []; (function w(n) { if (n.img && n.img.startsWith("shot:")) shots.push(n.img.slice(5)); (n.children || []).forEach(w); })(g.tree);
    for (const id of shots) { const f = `${KEY}-s${SAMPLES.length}-${id}.png`;
      try { await p.locator(`[data-fximg="${id}"]`).first().screenshot({ path: join(ASSETS, f), timeout: 5000 }); files["shot:" + id] = f; } catch (e) { note("img-shot-fail", figma, String(e).slice(0, 100)); } }
    g.files = files;
    const v = { state: variant.state || "default", device: DEV, lang: LANG, ...variant };
    SAMPLES.push({ figma, sel, variant: v, screen: SCREENS.length ? SCREENS[SCREENS.length - 1].id : null, ...g, html, tree: g.tree });
    return g;
  } catch (e) { note("grab-fail", figma, String(e).slice(0, 160)); return null; }
}
// холст (3D) — только его пиксели, без кнопок поверх: на время снимка всё прочее скрыто (visibility), снимок — по рамке холста
async function cvShot(p, id, path) {
  const r = await p.evaluate((id) => { const c = document.querySelector(`[data-fxcv="${id}"]`); if (!c) return null; const b = c.getBoundingClientRect();
    const st = document.createElement("style"); st.id = "fxhide"; st.textContent = `*{visibility:hidden!important;transition:none!important}[data-fxcv="${id}"]{visibility:visible!important}`; document.head.appendChild(st);
    return { x: Math.max(0, b.x), y: Math.max(0, b.y), width: Math.min(b.width, innerWidth), height: Math.min(b.height, innerHeight) }; }, id);
  if (!r || r.width < 2 || r.height < 2) throw new Error("холст вне экрана");
  try { await p.waitForTimeout(120); await p.screenshot({ path, type: "jpeg", quality: 82, clip: r }); }
  finally { await p.evaluate(() => { const s = document.getElementById("fxhide"); if (s) s.remove(); }); }
}
const step = async (name, fn) => { try { await fn(); } catch (e) { note("FAIL", name, String(e).split("\n")[0].slice(0, 220)); } };
const vis = (p, sel) => p.evaluate((s) => { const e = [...document.querySelectorAll(s)].find((x) => x.getClientRects().length && getComputedStyle(x).visibility !== "hidden"); return !!e; }, sel);
const clickJs = (p, sel) => p.evaluate((s) => { const e = [...document.querySelectorAll(s)].find((x) => x.getClientRects().length && getComputedStyle(x).visibility !== "hidden"); if (e) e.click(); return !!e; }, sel);

async function openHome(p, extra = "") {
  await p.goto(BASE + "?lang=" + LANG + extra, { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!document.getElementById('hmCert').hidden", null, { timeout: 90000 });
  await wait(p, 1500);
  // ленивые картинки — прокрутить вниз и обратно
  await p.evaluate(() => scrollTo(0, document.body.scrollHeight)); await wait(p, 700); await p.evaluate(() => scrollTo(0, 0)); await wait(p, 600);
}

// ═══ 1. ОСНОВНОЙ ОБХОД: главная → окно варианта → замена → избранное ═══
{
  const p = await newPage();
  await openHome(p, "&live=force");
  PROBE = await p.evaluate(() => window.__fx.tokenProbe());
  await step("home-top", async () => {
    await shoot(p, "home-top", EN ? "Home — first screen" : "Главная — первый экран", { alsoFull: true });
    await grab(p, "Header/Flat row", "#hmHd", { state: "top" });
    await grab(p, "Header/Fav button", "#hmFav", { state: "empty" });
    await grab(p, "Header/Meta row", "#flatMetaRow", { state: "collapsed" });
    await grab(p, "Header/Actions", ".hm-acts", { state: "default" });
    await grab(p, "Buttons/Pill", "#pcMort", { state: "default" });
    await grab(p, "Buttons/CTA pill", "#pcCons", { state: "default" });
    await grab(p, "Budget/Cert scale", "#hmCert .cs", { state: "empty", budget: EN ? "split" : "pooled" });
    await grab(p, "Budget/Cert bar", "#hmCert .cs-bar", { state: "empty", budget: EN ? "split" : "pooled" });
    await grab(p, "Budget/Info button", "#hmCert .vpl-i", { state: "default" });
    await grab(p, "Home/Hint", "#hmHint", { state: "default" });
    await grab(p, "Tabs/Style tabs bar", "#styleTabs", { state: "top" });
    await grab(p, "Tabs/Style tab", "#styleTabs .hm-tab.on", { state: "selected" });
    await grab(p, "Tabs/Style tab", "#styleTabs .hm-tab:not(.on)", { state: "default" });
    await grab(p, "Room/Card", "#hmRooms .hm-room", { state: "default" });
    await grab(p, "Room/Heart", "#hmRooms .hm-heart", { state: "off" });
    await grab(p, "Room/Stub", "#hmRooms .hm-stub:not(.hm-plan-tile)", { state: "soon" });
    await grab(p, "Room/Plan tile", "#hmRooms .hm-plan-tile, .hm-plan-bot", { state: "default" });
    await grab(p, "Buttons/Primary", "#hmRooms .hm-room .rb .btn", { state: "default" });
    await grab(p, "Buttons/Icon", "#hmRooms .hm-room .rb .iconbtn", { state: "default" });
    await grab(p, "Header/Plan link", "#planLink", { state: "default" });
    await grab(p, "Home/Lang switch", "#langSw", { state: "default" });
  });
  await step("home-more", async () => {
    await p.click("#flatMoreBtn"); await wait(p, 500);
    await shoot(p, "home-more", EN ? "Home — «Details» expanded" : "Главная — «Подробнее» раскрыто");
    await grab(p, "Header/Meta row", "#flatMetaRow", { state: "expanded" });
    await grab(p, "Header/More box", "#flatMore", { state: "open" });
    await p.click("#flatMoreBtn"); await wait(p, 300);
  });
  await step("home-cert-i", async () => {
    await p.click("#hmCert .vpl-i"); await wait(p, 450);
    await shoot(p, "home-cert-i", EN ? "Home — allowance (i) bubble" : "Главная — пузырь (i) сертификата");
    await grab(p, "Budget/Info bubble", "#hmCert .vpl-bub", { state: "open", place: "home" });
    await p.click("#hmCert .vpl-i"); await wait(p, 300);
  });
  await step("home-sticky", async () => {
    const t = await p.evaluate(() => { const e = document.getElementById("styleTabs"); return Math.round(e.getBoundingClientRect().top + scrollY); });
    await p.evaluate((y) => scrollTo(0, y), t + 80); await wait(p, 800);
    await shoot(p, "home-sticky", EN ? "Home — scrolled, sticky header" : "Главная — прокрутка, липкая шапка");
    await grab(p, "Header/Flat row", "#hmHd", { state: "stuck" });
    await grab(p, "Budget/Cert scale", "#hmCert .cs", { state: "stuck", budget: EN ? "split" : "pooled" });
    await grab(p, "Tabs/Style tabs bar", "#styleTabs", { state: "stuck" });
    await p.evaluate((y) => scrollTo(0, y), t + 700); await wait(p, 700);
    await shoot(p, "home-scrolled-deep", EN ? "Home — scrolled to rooms" : "Главная — прокрутка к комнатам");
    await p.evaluate(() => scrollTo(0, document.body.scrollHeight)); await wait(p, 700);
    await shoot(p, "home-bottom", EN ? "Home — bottom (language)" : "Главная — низ (язык)");
    await p.evaluate(() => scrollTo(0, 0)); await wait(p, 400);
  });
  await step("style-tab", async () => {
    const n = await p.evaluate(() => document.querySelectorAll("#styleTabs .hm-tab").length);
    if (n > 1) { await p.locator("#styleTabs .hm-tab").nth(2 % n).click(); await wait(p, 1500); await settle(p); }
    await shoot(p, "home-style-tab", EN ? "Home — another style tab" : "Главная — другая вкладка стиля");
    await grab(p, "Room/Card", "#hmRooms .hm-room", { state: "default", style: "other" });
    await p.locator("#styleTabs .hm-tab").first().click(); await wait(p, 1200);
    await p.evaluate(() => scrollTo(0, 0)); await wait(p, 300);
  });
  await step("plan-screen", async () => {
    const ok = await clickJs(p, "[data-plan]");
    if (!ok) { note("плана нет"); return; }
    await wait(p, 1500);
    await shoot(p, "flat-plan", EN ? "Flat plan" : "План квартиры");
    await grab(p, "Plan/Panel", "#screen-plan .panel", { state: "default" });
    await grab(p, "Plan/Flat plan", "#flatRooms", { state: "default" }, { depth: 3, nodes: 40 });
    await grab(p, "Home/Back link", "#planBack", { state: "default" });
    await clickJs(p, "#planBack"); await wait(p, 900); await p.evaluate(() => scrollTo(0, 0));
  });
  // ОКНО ВАРИАНТА
  await step("window", async () => {
    await p.evaluate(() => { try { localStorage.removeItem("remlab-sheet-hint-v1"); } catch (e) {} });
    await p.locator("#hmRooms .hm-room .rb .btn").first().click();
    await wait(p, 900);
    if (await vis(p, "#shot .vload.on")) { await shoot(p, "win-loading", EN ? "Variant window — loading" : "Окно варианта — загрузка"); await grab(p, "Window/Loader", "#shot .vload.on", { state: "loading" }); }
    // подсказка шторки «Потяните или нажмите» — сама, в первые ~20 с, если не идёт загрузка; живёт несколько секунд
    const tip = await p.waitForSelector("#shot .vtip", { timeout: 25000 }).catch(() => null);
    if (tip) { await wait(p, 300); await grab(p, "Window/Tip", "#shot .vtip", { state: "shown", mode: await p.evaluate(() => VW.mode) }); await shoot(p, "win-hint", EN ? "Variant window — hint" : "Окно варианта — подсказка"); }
    else note("подсказки окна нет (окно занято загрузкой первые 20 с)");
    await p.waitForFunction(() => !document.querySelector("#shot .vtip"), null, { timeout: 12000 }).catch(() => {});
    note("mode", await p.evaluate(() => VW.mode));
    if (await p.evaluate(() => VW.mode !== "walk")) { await p.evaluate(() => vwMode("walk")); await wait(p, 2500); }
    await p.waitForFunction(() => typeof LIVE !== "undefined" && LIVE.state === "ready" && !document.querySelector("#vload.on"), null, { timeout: 120000 }).catch(async () => note("3D не дождались", await p.evaluate(() => typeof LIVE !== "undefined" && LIVE.state)));
    await settle(p); await wait(p, 1500);
    await shoot(p, "win-3d", EN ? "Variant window — 3D" : "Окно варианта — 3D");
    await grab(p, "Window/Frame", "#shot .box", { state: "3d", sheet: PHONE ? "collapsed" : "n/a" }, { depth: 3, nodes: 40 });
    await grab(p, "Window/Mode switch", "#shot .vmodes", { state: "3d" });
    await grab(p, "Window/Camera switch", "#shot .vcams", { state: "default" });
    await grab(p, "Window/Price pin", "#shot .vpin:not(.sel)", { state: "default" });
    await grab(p, "Buttons/Window top", "#vShare", { state: "default", icon: "share" });
    await grab(p, "Buttons/Window top", "#vFav", { state: "off", icon: "fav" });
    await grab(p, "Buttons/Close round", "#shotx", { state: "default" });
    await grab(p, "Window/CTA realistic", "#shot .vcta", { state: "default" });
    await grab(p, "Budget/Window plate", "#shot .vplate", { state: "default" });
    if (PHONE) { await grab(p, "Sheet/Grip", "#shot .vpill", { state: "default" }); await grab(p, "Sheet/Chip", "#shot .vgrip", { state: "default" }); }
    else await grab(p, "Window/Side panel", "#shot .vside", { state: "default" }, { depth: 3, nodes: 40 });
  });
  if (PHONE) await step("sheet", async () => {
    for (const [n, nm] of [[0, "collapsed"], [2, "mid"], [3, "full"]]) {
      await p.evaluate((n) => vwSheet(n), n); await wait(p, 800); await settle(p);
      await shoot(p, "sheet-" + nm, (EN ? "Sheet — " : "Шторка — ") + nm);
      await grab(p, "Sheet/Panel", "#shot .vside", { state: nm }, { depth: 3, nodes: 40 });
    }
    await p.evaluate(() => { const s = document.getElementById("vscroll"); s.scrollTop = 300; }); await wait(p, 600);
    await shoot(p, "sheet-full-scrolled", EN ? "Sheet — full, scrolled" : "Шторка — полная, прокручена");
    await p.evaluate(() => { document.getElementById("vscroll").scrollTop = 0; vwSheet(3); }); await wait(p, 600);
  });
  await step("rows", async () => {
    await grab(p, "Sheet/Item row", "#shot .pinlist .row:not(.hl)", { state: "default" });
    await grab(p, "Sheet/Item row", "#shot .pinlist .row:has(.sws)", { state: "default", colours: "yes" });
    await grab(p, "Swatch/Colour", "#shot .pinlist .sws .sw.on", { state: "selected", size: "22" });
    await grab(p, "Swatch/Colour", "#shot .pinlist .sws .sw:not(.on)", { state: "default", size: "22" });
    await grab(p, "Buttons/Link", "#shot .pinlist .lnk", { state: "default" });
    await grab(p, "Sheet/Group entry row", "#shot .vopts-row", { state: "default" });
    await p.evaluate(() => { const f = (i) => String(i.role || "").replace(/\s+\d+$/, ""); let k = items.findIndex((i) => /столик|журнальн/i.test(f(i))); if (k < 0) k = 0; vwHighlight(k); });
    await wait(p, 1500); await settle(p);
    await shoot(p, "win-selected-row", EN ? "Window — selected item" : "Окно — выбран предмет");
    await grab(p, "Sheet/Item row", "#shot .pinlist .row.hl", { state: "selected" });
    if (PHONE) { await p.evaluate(() => vwSheet(0)); await wait(p, 1200); }
    await grab(p, "Window/Price pin", "#shot .vpin.sel:not([hidden])", { state: "selected" });
    await p.evaluate(() => vwSelect(null)); await wait(p, 500);
  });
  await step("win-cert-i", async () => {
    if (PHONE) { await p.evaluate(() => vwSheet(2)); await wait(p, 700); }
    await p.click("#shot .vpl-i"); await wait(p, 450);
    await shoot(p, "win-cert-i", EN ? "Window — allowance (i) bubble" : "Окно — пузырь (i) сертификата");
    await grab(p, "Budget/Info bubble", "#shot .vpl-bub", { state: "open", place: "window" });
    await p.click("#shot .vpl-i"); await wait(p, 300);
  });
  await step("win-plan", async () => {
    await p.evaluate(() => vwMode("plan")); await wait(p, 1800);
    if (PHONE) { await p.evaluate(() => vwSheet(0)); await wait(p, 700); }
    await shoot(p, "win-plan", EN ? "Window — Plan" : "Окно — План");
    await grab(p, "Window/Mode switch", "#shot .vmodes", { state: "plan" });
    await grab(p, "Window/Plan box", "#shot .vplanbox", { state: "default" }, { depth: 2, nodes: 12 });
  });
  await step("win-photo", async () => {
    const ph = await p.evaluate(() => typeof vwRealShots === "function" && vwRealShots().length > 0);
    if (!ph) { note("вкладки «Фото» нет — для этой расстановки нет готового фото"); return; }
    await p.evaluate(() => vwMode("photo")); await wait(p, 3000);
    await shoot(p, "win-photo", EN ? "Window — Photo" : "Окно — Фото");
    await grab(p, "Window/Mode switch", "#shot .vmodes", { state: "photo" });
    await grab(p, "Window/Zoom button", "#vzBtn", { state: "default" });
    await grab(p, "Window/Frame", "#shot .box", { state: "photo", sheet: PHONE ? "collapsed" : "n/a" }, { depth: 3, nodes: 40 });
    if (await vis(p, "#vzBtn")) {
      await p.evaluate(() => document.getElementById("vzBtn").click()); await wait(p, 2000);
      await shoot(p, "photo-fullscreen", EN ? "Photo — full screen" : "Фото — во весь экран");
      await grab(p, "Zoom/Fullscreen", "#vzoom", { state: "open" }, { depth: 2, nodes: 20 });
      await grab(p, "Zoom/Camera switch", "#vzoom .vzcams", { state: "default" });
      await p.evaluate(() => { const x = document.querySelector("#vzoom .vzx"); if (x) x.click(); }); await wait(p, 700);
    }
    await p.evaluate(() => vwMode("walk")); await wait(p, 2000);
  });
  await step("group-finish", async () => {
    const has = await p.evaluate(() => !!document.querySelector('#shot .vopts-row[data-group="finish"]'));
    if (!has) { note("строки «Отделка» нет"); return; }
    await p.evaluate(() => vwGroupOpen("finish")); await wait(p, 1500); await settle(p);
    await shoot(p, "win-finish", EN ? "Window — Finish & renovation" : "Окно — «Отделка и ремонт»");
    await grab(p, "Sheet/Group header", "#shot .vgsec", { state: "default" });
    await grab(p, "Sheet/Floor picker", "#shot .vfloor", { state: "default" });
    await grab(p, "Swatch/Floor", "#shot .vfl.on", { state: "selected" });
    await grab(p, "Swatch/Floor", "#shot .vfl:not(.on)", { state: "default" });
    await p.evaluate(() => vwGroupOpen(null)); await wait(p, 800);
  });
  await step("item-card", async () => {
    if (PHONE) { await p.evaluate(() => vwSheet(3)); await wait(p, 800); }
    const ok = await clickJs(p, "#shot .pinlist .row:has(.sws) .t b, #shot .pinlist .row .t b");
    if (!ok) { note("строки для карточки товара нет"); return; }
    await p.waitForSelector("#itemCard.on", { timeout: 8000 }); await wait(p, 1500);
    await shoot(p, "item-card", EN ? "Product card" : "Карточка товара");
    await grab(p, "ItemCard/Sheet", "#itemCard .ic-box", { state: "default" }, { depth: 4, nodes: 40 });
    await grab(p, "Swatch/Colour", "#itemCard .ic-swr .sw.on", { state: "selected", size: "34" });
    await grab(p, "Buttons/Close round", "#itemCard .ic-x", { state: "item-card" });
    await p.evaluate(() => { const x = document.querySelector("#itemCard .ic-x"); if (x) x.click(); }); await wait(p, 600);
    if (await vis(p, "#itemCard.on")) await p.keyboard.press("Escape");
  });
  await step("picker", async () => {
    if (PHONE) { await p.evaluate(() => vwSheet(3)); await wait(p, 800); await settle(p); }
    await p.locator("#vside .vitems [data-rep]").first().click(); await wait(p, 1800); await settle(p);
    await shoot(p, "picker-top", EN ? "Replacement sheet" : "Лист замены");
    await grab(p, "Picker/Sheet", "#sheet", { state: "open" }, { depth: 3, nodes: 40 });
    await grab(p, "Picker/Header", "#sheet header", { state: "default" });
    await grab(p, "Buttons/Chip", "#filters .chip.on", { state: "selected" });
    await grab(p, "Buttons/Chip", "#filters .chip:not(.on)", { state: "default" });
    await grab(p, "Picker/Product card", "#grid .card.cur", { state: "current" });
    await grab(p, "Picker/Product card", "#grid .card:not(.cur)", { state: "default" });
    await grab(p, "Picker/Colour chip", "#grid .colchip.on", { state: "selected" });
    await grab(p, "Picker/Colour chip", "#grid .colchip:not(.on)", { state: "default" });
    for (const b of ["b-ok", "b-tight", "b-no"]) await grab(p, "Badges/Fit", `#grid .badge.${b}`, { state: b.slice(2) });
    await grab(p, "Buttons/Mini", "#grid .mini:not(.link)", { state: "default" });
    await grab(p, "Buttons/Mini", "#grid .mini.link", { state: "link" });
    await p.evaluate(() => { const s = document.getElementById("sheetscroll"); if (s) s.scrollTop = 520; }); await wait(p, 700);
    await shoot(p, "picker-scrolled", EN ? "Replacement sheet — scrolled" : "Лист замены — прокручен");
    await p.evaluate(() => { const s = document.getElementById("sheetscroll"); if (s) s.scrollTop = 0; }); await wait(p, 300);
    await p.locator("#grid .card:not(.cur) .acts button.mini").first().click(); await wait(p, 700);
    if (await vis(p, "#toast:not([hidden])")) { await grab(p, "Toast/Message", "#toast", { state: "default" }); await shoot(p, "toast-replaced", EN ? "Toast — replaced" : "Сообщение — «Заменено»"); }
    else note("сообщения о замене не поймали");
    await wait(p, 3500); await settle(p);
    await shoot(p, "after-replace", EN ? "Window after replacement" : "Окно после замены");
    await grab(p, "Window/History", "#shot .vhist:not([hidden])", { state: "after-change" });
  });
  await step("cons", async () => {
    const has = await p.evaluate(() => typeof openCons === "function");
    if (!has) return;
    await p.evaluate(() => openCons("edit")); await wait(p, 2000);
    if (!(await vis(p, "#cons.on"))) { note("конструктор не открылся"); return; }
    await shoot(p, "constructor", EN ? "Layout editor" : "Конструктор планировки");
    await grab(p, "Constructor/Top bar", "#cons .top", { state: "default" });
    await grab(p, "Constructor/Bottom bar", "#cons .bar", { state: "default" });
    await grab(p, "Constructor/Hint", "#cons .cons-hint", { state: "default" });
    await grab(p, "Badges/State", "#layoutState", { state: "default" });
    await p.evaluate(() => closeCons()); await wait(p, 2500);
    if (await vis(p, "#cons.on")) note("конструктор не закрылся");
  });
  await step("fav", async () => {
    if (!(await vis(p, "#shot.on"))) { await p.locator("#hmRooms .hm-room .rb .btn").first().click(); await wait(p, 4000); }
    await p.click("#vFav"); await p.waitForSelector("#favPop", { timeout: 8000 }); await wait(p, 400);
    await shoot(p, "fav-name-popup", EN ? "Save to favourites — name" : "Избранное — окошко имени");
    await grab(p, "Dialog/Name", "#favPop .favbox", { state: "new" });
    await grab(p, "Dialog/Overlay", "#favPop", { state: "default" }, { depth: 1, nodes: 4 });
    await p.click("#favOk"); await p.waitForFunction("!document.getElementById('favPop')", null, { timeout: 20000 }).catch(() => {}); await wait(p, 900);
    if (await vis(p, "#toast:not([hidden])")) { await grab(p, "Toast/Message", "#toast", { state: "action" }); await shoot(p, "toast-fav-saved", EN ? "Toast — added to favourites" : "Сообщение — добавлено в избранное"); }
    await grab(p, "Buttons/Window top", "#vFav", { state: "on", icon: "fav" });
    await wait(p, 2500);
    await p.evaluate(() => document.getElementById("shotx").click()); await wait(p, 1200);
    await p.evaluate(() => scrollTo(0, 0)); await wait(p, 400);
    await shoot(p, "home-with-fav", EN ? "Home — with favourites" : "Главная — есть избранное");
    await grab(p, "Header/Fav button", "#hmFav", { state: "count" });
    await grab(p, "Home/Fav row", "#favHead", { state: "default" });
    await grab(p, "Room/Heart", "#hmRooms .hm-heart", { state: "on" });
    if (!(await clickJs(p, "#favRowBtn"))) await clickJs(p, "#hmFav");
    await wait(p, 1500);
    await shoot(p, "fav-screen", EN ? "Favourites screen" : "Экран «Избранное»");
    await grab(p, "Fav/Screen header", "#screen-fav .fv-top", { state: "default" });
    await grab(p, "Fav/Room chip", "#favChips .hm-fav-chip.on", { state: "selected" });
    await grab(p, "Fav/Room chip", "#favChips .hm-fav-chip:not(.on)", { state: "default" });
    await grab(p, "Fav/Card", "#favGrid .favcard.inc", { state: "included" }, { depth: 5, nodes: 48 });
    await grab(p, "Fav/Card", "#favGrid .favcard:not(.inc)", { state: "default" }, { depth: 5, nodes: 48 });
    await grab(p, "Fav/Photo wait", "#favGrid .pwait", { state: "waiting" });
    const fi = await p.$("#favGrid .favcard .incw .vpl-i");
    if (fi) { await fi.click(); await wait(p, 450); await shoot(p, "fav-card-i", EN ? "Favourites — (i) on card" : "Избранное — (i) на карточке"); await grab(p, "Budget/Info bubble", "#favGrid .vpl-bub", { state: "open", place: "fav-card" }); await fi.click(); await wait(p, 300); }
    await p.click("#favGrid [data-fmore]").catch(() => {}); await wait(p, 500);
    if (await vis(p, "#favPop")) { await shoot(p, "fav-more", EN ? "Favourites — rename / remove" : "Избранное — переименовать / убрать"); await grab(p, "Dialog/Name", "#favPop .favbox", { state: "edit" });
      await p.mouse.click(3, 3); await wait(p, 400); }
  });
  writeFileSync(join(CAP, `probe-${KEY}.json`), JSON.stringify(PROBE, null, 1));
  await p.context().close();
}

// ═══ 2. ПОЛОСА БЮДЖЕТА: корзина задаётся в хранилище браузера (выдуманные варианты, без сервера) — как budget-bar-check.cjs ═══
{
  const FX_UK = "0.0089@2026-10-16";
  const fid = (n) => ("figmabudget" + n).padEnd(22, "x").slice(0, 22);
  const fav = (n, room, kind, lines, cur, fx) => ({ favoriteId: fid(n), editToken: null, roomId: room, roomKind: kind, styleId: "scandi", stateId: "", sourceVariantId: "",
    displayName: (EN ? (room === "living" ? "Living room" : room === "kitchen" ? "Kitchen" : "Bedroom") : (room === "living" ? "Гостиная" : room === "kitchen" ? "Кухня" : "Спальня")) + " #" + n, autoName: true, createdAt: 1760000000000 + n,
    quote: { status: "fresh", currency: cur, at: Date.now(), lines: lines.map(([b, a], k) => ({ chargeKey: "shop:t" + n + "-" + k, roomId: room, label: "позиция " + k, settlement: "allowance", amount: a, priceStatus: "known", source: "shop", budgetBucket: b })), ...(fx ? { fx } : {}) } });
  const basket = (apt, cur, fx, favs, inc) => ({ v: 2, apartmentId: apt, favorites: favs.map((f) => fav(...f, cur, fx)), includedByRoom: Object.fromEntries(inc.map((n) => [favs.find((f) => f[0] === n)[1], fid(n)])) });
  const S = EN ? {
    "uk-part": [[[1, "living", "living", [["furniture", 1200]]], [2, "kitchen", "kitchen", [["fitout", 3000]]]], [1, 2]],
    "uk-over": [[[1, "living", "living", [["furniture", 5300]]], [2, "kitchen", "kitchen", [["fitout", 3000]]]], [1, 2]],
    "uk-zero": [[[1, "living", "living", [["furniture", 1200]]], [2, "kitchen", "kitchen", [["fitout", 600]]]], [1, 2], { furniture: 4500, fitout: 0 }],
  } : {
    "ru-part": [[[1, "living", "living", [["furniture", 250000]]]], [1]],
    "ru-over": [[[1, "living", "living", [["furniture", 450000]]], [2, "kitchen", "kitchen", [["fitout", 230000]]]], [1, 2]],
  };
  const apt = EN ? "demo-uk-215" : "flat215", cur = EN ? "GBP" : "RUB", fx = EN ? FX_UK : null;
  for (const [name, [favs, inc, limits]] of Object.entries(S)) await step("budget-" + name, async () => {
    const p = await newPage(["remlab-basket:v2:" + apt, JSON.stringify(basket(apt, cur, fx, favs, inc))]);
    await p.context().addInitScript(() => { try { localStorage.setItem("remlab-sheet-hint-v1", "1"); } catch (e) {} });
    if (limits) await p.route(/\/api\/apartments\//, async (r) => { const res = await r.fetch(); const j = await res.json();
      if (j.card && j.card.incentive) { j.card.incentive.limits = limits; j.card.incentive.total = limits.furniture + limits.fitout; j.card.certificate.amount = j.card.incentive.total; }
      await r.fulfill({ response: res, body: JSON.stringify(j), headers: { ...res.headers(), "content-type": "application/json" } }); });
    await p.goto(BASE + "?lang=" + LANG + "&live=0", { waitUntil: "load", timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!!window.__basket&&!!window.__basket.totals()&&!document.getElementById('hmCert').hidden", null, { timeout: 90000 });
    await wait(p, 1200);
    const mode = await p.evaluate(() => document.getElementById("hmCert").dataset.mode);
    const kind = name.replace(/^(ru|uk)-/, "");
    await shoot(p, "budget-" + name, (EN ? "Budget bar — " : "Полоса бюджета — ") + name);
    await grab(p, "Budget/Cert scale", "#hmCert .cs", { state: kind, budget: mode });
    await grab(p, "Budget/Cert bar", "#hmCert .cs-bar", { state: kind, budget: mode });
    await grab(p, "Budget/Legend", "#hmCert .cs-lg", { state: kind, budget: mode });
    if (kind === "over") await grab(p, "Budget/Overspend line", "#hmCert .cs-ov", { state: "over", budget: mode });
    await p.click("#hmCert .vpl-i"); await wait(p, 450);
    await shoot(p, "budget-" + name + "-i", (EN ? "Budget (i) — " : "Пузырь (i) бюджета — ") + name);
    await grab(p, "Budget/Info bubble", "#hmCert .vpl-bub", { state: "open", place: "home", budget: mode + "-" + kind });
    await p.click("#hmCert .vpl-i"); await wait(p, 300);
    if (kind !== "zero") {
      await p.evaluate(() => scrollTo(0, document.documentElement.scrollHeight)); await wait(p, 700);
      await shoot(p, "budget-" + name + "-sticky", (EN ? "Budget bar sticky — " : "Полоса бюджета липкая — ") + name);
      await grab(p, "Budget/Cert scale", "#hmCert .cs", { state: kind + "-stuck", budget: mode });
      await p.evaluate(() => scrollTo(0, 0)); await wait(p, 300);
    }
    if (kind === "part") {   // окно варианта — «выйдет за лимит» и плашка; избранное — диалог доплаты; пустой экран избранного
      await p.evaluate(() => vwOpenVariant(0)); await p.waitForFunction(() => !!document.querySelector("#vsum .cs"), null, { timeout: 60000 }).catch(() => {}); await wait(p, 1800);
      await shoot(p, "budget-" + name + "-window", (EN ? "Window plate — " : "Плашка окна — ") + name);
      await grab(p, "Budget/Window plate", "#shot .vplate", { state: "preview", budget: mode });
      await p.evaluate(() => document.getElementById("shotx").click()); await wait(p, 800);
      await p.evaluate(() => window.__basket.open("living")); await p.waitForSelector("#favGrid .favcard", { timeout: 20000 }).catch(() => {}); await wait(p, 800);
      await shoot(p, "budget-" + name + "-fav", (EN ? "Favourites — " : "Избранное — ") + name);
      await grab(p, "Fav/Card", "#favGrid .favcard.inc", { state: "included", budget: mode }, { depth: 5, nodes: 48 });
    }
    await p.context().close();
  });
  // пустое избранное и диалог доплаты
  await step("fav-empty-and-dialog", async () => {
    const favs = EN ? [[1, "living", "living", [["furniture", 1200]]], [4, "living", "living", [["furniture", 5000]]], [2, "kitchen", "kitchen", [["fitout", 3000]]]]
      : [[1, "living", "living", [["furniture", 200000]]], [4, "living", "living", [["furniture", 520000]]], [2, "kitchen", "kitchen", [["fitout", 150000]]]];
    const p = await newPage(["remlab-basket:v2:" + apt, JSON.stringify(basket(apt, cur, fx, favs, [1, 2]))]);
    await p.goto(BASE + "?lang=" + LANG + "&live=0", { waitUntil: "load", timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!window.__basket&&!!window.__basket.totals()", null, { timeout: 90000 }); await wait(p, 1000);
    await p.evaluate(() => window.__basket.open("living")); await p.waitForSelector("#favGrid [data-finc]", { timeout: 30000 }); await wait(p, 600);
    await shoot(p, "fav-screen-cards", EN ? "Favourites — several cards" : "Избранное — несколько карточек");
    await grab(p, "Fav/Card", "#favGrid .favcard:not(.inc)", { state: "default", photo: "none" }, { depth: 5, nodes: 48 });
    await p.click(`#favGrid [data-finc="${fid(4)}"]`); await p.waitForSelector("#favPop", { timeout: 10000 }); await wait(p, 400);
    await shoot(p, "fav-topup-dialog", EN ? "Dialog — top-up confirm" : "Диалог — доплата, подтвердить?");
    await grab(p, "Dialog/Choice", "#favPop .favbox", { state: "top-up" });
    await p.mouse.click(3, 3); await wait(p, 400);
    await p.context().close();
    const q = await newPage();
    await q.goto(BASE + "?lang=" + LANG + "&live=0", { waitUntil: "load", timeout: 120000 });
    await q.waitForFunction("typeof D!=='undefined'&&!!D&&!!window.__basket", null, { timeout: 90000 }); await wait(q, 1000);
    await q.evaluate(() => window.__basket.open()); await wait(q, 1000);
    await shoot(q, "fav-empty", EN ? "Favourites — empty" : "Избранное — пусто");
    await grab(q, "Fav/Empty", "#favEmpty", { state: "empty" });
    await q.context().close();
  });
}

await browser.close();
writeFileSync(join(CAP, `samples-${KEY}.json`), JSON.stringify(SAMPLES));
writeFileSync(join(CAP, `computed-${KEY}.json`), JSON.stringify({ texts: TEXTS }, null, 0));
writeFileSync(join(CAP, `screens-${KEY}.json`), JSON.stringify(SCREENS, null, 1));
writeFileSync(join(CAP, `log-${KEY}.txt`), LOG.join("\n") + "\n");
console.log(`[${KEY}] готово: экранов ${SCREENS.length}, образцов ${SAMPLES.length}`);
