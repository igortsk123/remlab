// СНИМКИ НАСТОЯЩЕЙ СТРАНИЦЫ ДЕМО С ЯРЛЫКАМИ (T-20261117-10): ярлык пледа — элемент страницы, а не холста, поэтому стенд `variant-snap` его не видит.
// Здесь — страница из исходника репо (собрана `page_build.mjs`) и движок из этого же репо (`build-scene-bundle.mjs`) в НОВОЙ папке-превью рядом с данными
// витрины (`demo-data.json`, картинки, лёгкие меши — ссылками на сборку), без записи в живую витрину. Браузер — программный рендер, как у стенда.
//   node tools/flat3d/page-snap.mjs --site <папка-превью> --variants bedroom-1-loft,set1 --sizes 375x667,1440x900 --out <НОВАЯ папка> [--click-label]
//     [--prices on|off] — «Показать/Скрыть цены» (T-20261117-17: при off ярлык ткани — кружок с фото без цены); [--dsf N] — плотность пикселей;
//     [--lang ru|en] — язык страницы (`?lang=`); [--clip-label] — крупный кадр вокруг каждого ярлыка (`<вариант>.<WxH>.label<k>.png`, с --dsf 3 — зум)
// Выход: <вариант>.<WxH>.jpg — кадр «3D» с ярлыками; `report.json` — по каждому ярлыку: рамка, размер пальца, читаемость, что под ним.
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";

import { chromium } from "@playwright/test";

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i < 0 ? d : process.argv[i + 1]; };
const SITE = arg("site"), OUT = arg("out"), CLICK = process.argv.includes("--click-label"), CLIP = process.argv.includes("--clip-label");
const PRICES = arg("prices", ""), DSF = Number(arg("dsf", "1"));
const LANG_Q = /^(ru|en)$/.test(arg("lang", "")) ? arg("lang", "") : "";   // [--lang ru|en] — язык страницы (по умолчанию — язык браузера стенда, английский)
const VARIANTS = (arg("variants", "set1")).split(",");
const SIZES = (arg("sizes", "375x667")).split(",").map((s) => s.split("x").map(Number));
if (!SITE || !OUT) throw new Error("нужны --site и --out");
if (existsSync(OUT)) throw new Error(`${OUT} уже есть — снимки только в новую папку`);
mkdirSync(OUT, { recursive: true });

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".jpg": "image/jpeg", ".png": "image/png",
  ".glb": "model/gltf-binary", ".webp": "image/webp", ".css": "text/css", ".svg": "image/svg+xml" };
// чего нет в папке-превью (лёгкие меши `/rt/`, галерея `/test/`, текстуры отделки) — читаем с прода, только GET, как это делает стенд `variant-snap`
const PROD = "https://remont-lab.online";
const cache = new Map();
const server = createServer(async (req, res) => {
  const p = normalize(decodeURIComponent((req.url ?? "/").split("?")[0] ?? "/")).replace(/^(\.\.[/\\])+/, "");
  const f = join(SITE, p === "/" ? "index.html" : p);
  if (existsSync(f) && !statSync(f).isDirectory()) {
    res.setHeader("content-type", TYPES[extname(f)] ?? "application/octet-stream");
    res.end(readFileSync(f));
    return;
  }
  try {
    let hit = cache.get(req.url);
    if (!hit) {
      // картинки и прочее витрины лежат под /demo/ (адрес в данных — относительный «img/…»); сперва как есть, затем под /demo/
      let r = await fetch(PROD + req.url);
      if (!r.ok && !req.url.startsWith("/demo/")) { const alt = await fetch(PROD + "/demo" + req.url); if (alt.ok) r = alt; }
      hit = { status: r.status, type: r.headers.get("content-type") ?? "application/octet-stream", body: Buffer.from(await r.arrayBuffer()) };
      if (r.ok) cache.set(req.url, hit);
    }
    res.statusCode = hit.status;
    res.setHeader("content-type", hit.type);
    res.end(hit.body);
  } catch {
    res.statusCode = 502;
    res.end("нет");
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;

const launch = () => chromium.launch({ ignoreDefaultArgs: ["--disable-dev-shm-usage"], args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const browser = await launch();
const report = [];
try {
  for (const [w, h] of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: DSF, hasTouch: w < 700, isMobile: w < 700 });
    for (const id of VARIANTS) {
      const page = await ctx.newPage();
      if (PRICES) await page.addInitScript((v) => { try { sessionStorage.setItem("remlab-prices-off", v); } catch { /* без хранилища — по умолчанию */ } }, PRICES === "off" ? "1" : "0");
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.goto(`${base}/index.html?live=force&quiz=0${LANG_Q ? `&lang=${LANG_Q}` : ""}`, { waitUntil: "networkidle" });
      await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 60000 });
      const idx = await page.evaluate((v) => allVariants().findIndex((x) => x.id === v), id);
      if (idx < 0) { report.push({ id, size: `${w}x${h}`, error: "нет варианта" }); await page.close(); continue; }
      await page.evaluate((i) => vwOpenVariant(i), idx);
      await page.waitForSelector("#shot.on", { timeout: 30000 });
      await page.evaluate("vwMode('walk')");
      await page.waitForFunction("LIVE && LIVE.scene", null, { timeout: 90000 });
      await page.evaluate("LIVE.scene.ready");
      await page.waitForTimeout(6000);                       // модели и первый кадр; ярлыки ставит `vwPinsTick`
      const labels = await page.evaluate(() => [...document.querySelectorAll("#vpins .vpin-lab")].map((n) => {
        const r = n.getBoundingClientRect(), i = n.querySelector("img");
        const pin = LIVE.scene.pins().find((q) => String(q.index) === n.dataset.pi);
        return { text: n.textContent, hidden: n.hidden, spotBox: pin?.box ? pin.box.map(Math.round) : null, aria: n.getAttribute("aria-label"), box: [r.left, r.top, r.width, r.height].map(Math.round),
          img: i ? { w: i.naturalWidth, ok: i.complete && i.naturalWidth > 0 } : null };
      }));
      // ЗАЗОР ДО УПРАВЛЕНИЯ (T-20261117-17/2): расстояние от каждого видимого ярлыка/ценника до элементов управления поверх 3D (те же селекторы, что у
      // `PINS.busy` страницы, + подсказка «Потяните…»); правило — не меньше PIN_CTL_GAP (8 px); 0 — пересекаются
      const gaps = await page.evaluate(() => {
        const ctl = [...document.querySelectorAll("#shot #shotx, #shot .vmodes, #shot .vstyle, #shot .vprice, #shot .vhist, #shot .vzbtn, #vside, #vsum, #shot .vcams, #shot .vslots, #shot .vready, #vcarry:not([hidden])")]
          .map((e) => e.getBoundingClientRect());
        if (LIVE.badge && LIVE.badge.isConnected && liveHintOn()) ctl.push(LIVE.badge.getBoundingClientRect());
        const live = ctl.filter((r) => r.width > 0);
        const gap = (a, b) => Math.hypot(Math.max(0, b.left - a.right, a.left - b.right), Math.max(0, b.top - a.bottom, a.top - b.bottom));
        return [...document.querySelectorAll("#vpins .vpin")].filter((n) => !n.hidden).map((n) => {
          const r = n.getBoundingClientRect();
          return { lab: n.classList.contains("vpin-lab"), text: n.textContent, minGap: live.length ? Math.round(Math.min(...live.map((c) => gap(r, c))) * 10) / 10 : null };
        });
      });
      const tight = gaps.filter((g) => g.minGap !== null && g.minGap < 8);
      // УСТОЙЧИВОСТЬ: ярлык не мигает — 2 с по кадрам смотрим, сколько раз у каждого менялось «скрыт/виден» (0 — стоит)
      const flips = await page.evaluate(() => new Promise((res) => {
        const ns = [...document.querySelectorAll("#vpins .vpin-lab")], last = ns.map((n) => n.hidden), cnt = ns.map(() => 0); let t = 0;
        const iv = setInterval(() => { ns.forEach((n, k) => { if (n.hidden !== last[k]) { cnt[k]++; last[k] = n.hidden; } }); if (++t > 40) { clearInterval(iv); res(cnt); } }, 50);
      }));
      const shot = join(OUT, `${id}.${w}x${h}.jpg`);
      await page.screenshot({ path: shot, type: "jpeg", quality: 90 });
      if (CLIP) {
        const rects = labels.filter((l) => !l.hidden);
        for (const [k, l] of rects.entries()) {
          const [x, y, bw, bh] = l.box, pad = 60;
          await page.screenshot({ path: join(OUT, `${id}.${w}x${h}.label${k}.png`), type: "png",
            clip: { x: Math.max(0, x - pad), y: Math.max(0, y - pad), width: Math.min(w, bw + 2 * pad), height: Math.min(h, bh + 2 * pad) } });
        }
      }
      let card = null;
      if (CLICK && labels.some((l) => !l.hidden)) {
        await page.locator("#vpins .vpin-lab:not([hidden])").first().click();
        await page.waitForTimeout(1200);
        card = await page.evaluate(() => { const c = document.querySelector("#vpins .vcard .vcnm"); return c ? c.textContent : null; });
        await page.screenshot({ path: join(OUT, `${id}.${w}x${h}.card.jpg`), type: "jpeg", quality: 90 });
      }
      report.push({ id, size: `${w}x${h}`, labels, flips, pinGaps: gaps, tight: tight.length, card, errors: errors.slice(0, 3) });
      console.log(`${id} ${w}x${h}: ярлыков ${labels.filter((l) => !l.hidden).length}/${labels.length}`, labels.map((l) => l.box.join(",")).join(" | "), `· переключений видимости ${flips.join("/")} · зазор до управления: меньше 8 px у ${tight.length} из ${gaps.length}`, card ? `· карточка «${card}»` : "");
      await page.close();
    }
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
  writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 1));
}
