/* eslint-disable @typescript-eslint/no-require-imports -- сценарий Node (CommonJS), как остальные tools/ops/*.cjs */
// СНИМКИ И ЗАМЕРЫ ПРОТОТИПА СВЕТА (T-20261111-22). Открывает публичное демо, подменяет движок сборкой прототипа (`build.mjs`),
// вставляет `inject.js` с вариантом света и для каждого варианта снимает 3D той же комнаты, меряет время до готовой сцены, p95 кадра,
// частоту кадров при повороте и цвет предметов (кадр / маска / альбедо — разбор `color.py`). На прод ничего не пишет: все запросы,
// кроме GET, и события/рендер/задания подменены ответом-заглушкой.
//   BUNDLE=.t22-out/scene-l3d.js OUT=~/remlab-logs/t22-1111/<HHMM>/ SIZE=1280x800 VAR=6 LIGHTS=v0,v1,v2 \
//   node tools/design/mock/light3d/shoot.cjs
const fs = require("fs"), path = require("path");
const { demoUrl } = require(path.join(process.cwd(), "tools/ops/demo-url.cjs"));
const pw = require(process.cwd() + "/node_modules/.pnpm/" + fs.readdirSync("node_modules/.pnpm").find((d) => d.startsWith("playwright-core@")) + "/node_modules/playwright-core");

const BASE = process.env.BASE || "https://remont-lab.online/demo/";
const OUT = (process.env.OUT || "/tmp/l3d/").replace(/^~/, require("os").homedir()).replace(/\/?$/, "/");
const BUNDLE = fs.readFileSync(process.env.BUNDLE || ".t22-out/scene-l3d.js", "utf8");
const INJECT = fs.readFileSync(path.join(__dirname, "inject.js"), "utf8");
const [W, H] = (process.env.SIZE || "1280x800").split("x").map(Number), PHONE = W <= 700;
const VARS = String(process.env.VAR || "6").split(",").map(Number);
const LIGHTS = String(process.env.LIGHTS || "v0,v1,v2,v3,v4").split(",");
const WARM = +(process.env.WARM ?? 2), FPS = process.env.FPS !== "0", MEASURE = process.env.MEASURE !== "0";
const CAMS = String(process.env.CAMS || "0,1").split(",").map(Number);
const EXTRA = process.env.CFG ? JSON.parse(process.env.CFG) : {};
fs.mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const png = (p, dataUrl) => fs.writeFileSync(p, Buffer.from(dataUrl.split(",")[1], "base64"));

async function one(b, vi, light) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: "ru-RU" });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e.stack || e).slice(0, 900)));
  p.on("console", (m) => { if (/L3D|живая сцена/.test(m.text())) errs.push("console: " + m.text()); });
  await p.route("**/*", (r) => {
    const q = r.request(), u = q.url();
    if (q.method() !== "GET" || /\/api\/(events|render|job)/.test(u)) return r.fulfill({ status: 204, body: "" });
    if (/\/demo\/lib\/scene\.json/.test(u)) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ file: "scene-l3d.js", build: "l3d", bytes: BUNDLE.length }) });
    if (/\/demo\/lib\/scene-l3d\.js/.test(u)) return r.fulfill({ status: 200, contentType: "text/javascript", body: BUNDLE });
    return r.continue();
  });
  await p.addInitScript(({ cfg, full }) => { window.__L3D = cfg; window.__L3D_FULL = full; }, { cfg: { variant: light, ...EXTRA }, full: !PHONE });
  await p.addInitScript(INJECT);
  await p.goto(demoUrl(BASE + "?live=force"), { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
  await p.evaluate(() => Promise.all([sceneModule(), rtMeshes()]));   // модуль движка и таблица моделей — вне замера (одинаковы у всех)
  // ХОЛОДНОЕ ОТКРЫТИЕ: окно варианта → «3D»; время — от команды до готовой сцены (модели в сцене, проба кадра пройдена)
  const cold = await p.evaluate(async (i) => {
    const t0 = performance.now();
    pickVariant(i); VW.collapse = true; vwOpenVariant(i); if (VW.mode !== "walk") vwMode("walk");
    for (let k = 0; k < 2400 && !LIVE.scene && LIVE.ok !== false; k++) await new Promise((r) => setTimeout(r, 25));
    return { ms: performance.now() - t0, ok: !!LIVE.scene, why: LIVE.why || "", room: curRoom && curRoom(), probe: LIVE.probe };
  }, vi);
  // ТЁПЛОЕ: та же комната заново (модели в кэше браузера) — меряем только работу движка и вставки
  const warm = [];
  for (let k = 0; k < WARM; k++) {
    warm.push(await p.evaluate(async () => {
      liveDrop(); const t0 = performance.now(); vwMode("walk");   // путь страницы: показ окна → `liveEngine`
      for (let k = 0; k < 2400 && !LIVE.scene && LIVE.ok !== false; k++) await new Promise((r) => setTimeout(r, 25));
      return { ms: performance.now() - t0, ok: !!LIVE.scene, probe: LIVE.probe };
    }));
  }
  await p.waitForFunction("LIVE.canvas&&LIVE.canvas.isConnected&&LIVE.canvas.getBoundingClientRect().width>100", null, { timeout: 30000 })
    .catch(async (e) => { log("нет холста", JSON.stringify(await p.evaluate(() => ({ ok: LIVE.ok, why: LIVE.why, state: LIVE.state }))), errs.join(" | ").slice(0, 600)); throw e; });
  await p.waitForFunction("!['v3','v4'].includes(__L3D.variant)||(__L3D_VIEWER&&__L3D_VIEWER.__l3dCS)", null, { timeout: 30000 }).catch(() => undefined);
  const tag = `v${vi}-${W}-${light}`;
  // ОБА ВИДА ОКНА («Со стороны двери», «Другой ракурс»): в одном виде видно 3–4 предмета, для мерки цвета нужно больше
  const meas = [];
  for (const cam of CAMS) {
    await p.evaluate((k) => vwCamGo(k), cam);
    await p.waitForTimeout(2200);   // переход камеры к позе вида
    const ct = `${tag}-c${cam}`;
    if (cam === CAMS[0]) await p.screenshot({ path: OUT + tag + "-page.png" });
    const cv = await p.evaluateHandle(() => LIVE.canvas);
    await cv.asElement().screenshot({ path: OUT + ct + "-3d.png" });
    if (MEASURE) {
      const m = await p.evaluate(() => window.__L3D_measure());
      if (m) {
        for (const k of ["beauty", "ids", "albedo"]) png(OUT + ct + "-m-" + k + ".png", m[k]);
        meas.push({ cam, w: m.w, h: m.h, legend: m.legend });
      }
    }
  }
  const items = await p.evaluate(() => items.map((it) => ({ role: it.role, msid: it.sku && it.sku.msid, img: it.sku && it.sku.img, swatch: it.sku && it.sku.swatch, name: it.sku && it.sku.name })));
  let perf = null;
  if (FPS) {
    perf = await p.evaluate(async (ph) => {
      const sc = LIVE.scene, pr = sc.probe(20);
      let n = 0; const t0 = performance.now();
      await new Promise((res) => { const f = () => { sc.look(ph ? 4 : 6, 0); n++; if (performance.now() - t0 < 4000) requestAnimationFrame(f); else res(); }; requestAnimationFrame(f); });
      return { p95: pr.p95Ms, fps: n / ((performance.now() - t0) / 1000) };
    }, PHONE).catch((e) => ({ err: String(e) }));
  }
  const stat = await p.evaluate(() => ({ ...window.__L3D_STAT, debug: window.__L3D_debug && window.__L3D_debug(), quality: window.__L3D_VIEWER && window.__L3D_VIEWER.quality && window.__L3D_VIEWER.quality.name,
    dbuf: (() => { const g = window.__L3D_VIEWER && window.__L3D_VIEWER.renderer.getContext(); return g ? [g.drawingBufferWidth, g.drawingBufferHeight] : null; })() }));
  await ctx.close();
  const res = { vi, light, W, H, cold, warm, perf, stat, meas, items, errs: errs.slice(0, 8) };
  fs.writeFileSync(OUT + tag + ".json", JSON.stringify(res, null, 1));
  log(tag, "cold", Math.round(cold.ms), cold.ok ? "" : "НЕТ СЦЕНЫ " + cold.why, "warm", warm.map((x) => Math.round(x.ms)).join("/"),
    "p95", perf && perf.p95 && perf.p95.toFixed(1), "fps", perf && perf.fps && perf.fps.toFixed(1), "bake", JSON.stringify(stat.bakeMs), stat.quality, JSON.stringify(stat.dbuf), errs.length ? "ОШИБКИ " + errs.join(" | ").slice(0, 300) : "");
  return res;
}

(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  try {
    for (const vi of VARS) for (const light of LIGHTS) await one(b, vi, light);
  } finally { await b.close(); }
})().catch((e) => { console.error(e); process.exit(2); });
