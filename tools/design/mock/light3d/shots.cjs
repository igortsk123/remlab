/* eslint-disable @typescript-eslint/no-require-imports -- сценарий Node */
// T-20261111-22/2: снимки «было / стало / стало+шторы» на публичной странице демо БЕЗ вставки: «было» — движок прода, «стало» —
// движок из этой ветки (`tools/flat3d/build-scene-bundle.mjs --out .t22-out/s2`). Оба движка на компьютерном размере — с полным
// профилем (снята только проверка «программный рендер», как у человека с видеокартой). На прод ничего не пишет.
//   OUT=~/remlab-logs/t22-1111/s2/<HHMM>/ SIZE=1280x800 VAR=6 MOVE=1 node .t22-s2.cjs
const fs = require("fs"), path = require("path");
const { demoUrl } = require(path.join(process.cwd(), "tools/ops/demo-url.cjs"));
const pw = require(process.cwd() + "/node_modules/.pnpm/" + fs.readdirSync("node_modules/.pnpm").find((d) => d.startsWith("playwright-core@")) + "/node_modules/playwright-core");

const BASE = "https://remont-lab.online/demo/";
const OUT = (process.env.OUT || "/tmp/s2/").replace(/^~/, require("os").homedir()).replace(/\/?$/, "/");
const NEW = JSON.parse(fs.readFileSync(".t22-out/s2/scene.json", "utf8"));
const NEWJS = fs.readFileSync(".t22-out/s2/" + NEW.file, "utf8");
const [W, H] = (process.env.SIZE || "1280x800").split("x").map(Number), PHONE = W <= 700;
const VI = +(process.env.VAR || 6), MOVE = process.env.MOVE === "1";
const MODES = String(process.env.MODES || "bylo,stalo").split(",");
fs.mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const SOFT = "return/swiftshader|llvmpipe|software|microsoft basic/i.test(";
const full = (js) => (PHONE ? js : js.replace(SOFT, "return!globalThis.__FULL3D&&/swiftshader|llvmpipe|software|microsoft basic/i.test("));

async function one(b, mode) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: "ru-RU" });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e.stack || e).slice(0, 700)));
  await p.route("**/*", async (r) => {
    const q = r.request(), u = q.url();
    if (q.method() !== "GET" || /\/api\/(events|render|job)/.test(u)) return r.fulfill({ status: 204, body: "" });
    if (mode !== "bylo" && /\/demo\/lib\/scene\.json/.test(u)) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...NEW }) });
    if (mode !== "bylo" && u.includes("/demo/lib/" + NEW.file)) return r.fulfill({ status: 200, contentType: "text/javascript", body: full(NEWJS) });
    if (mode !== "bylo" && NEW.basket && u.includes("/demo/lib/" + NEW.basket.file)) {
      return r.fulfill({ status: 200, contentType: "text/javascript", body: fs.readFileSync(".t22-out/s2/" + NEW.basket.file, "utf8") });
    }
    if (mode === "bylo" && /\/demo\/lib\/scene\.[0-9a-f]{12}\.js/.test(u)) {
      const res = await r.fetch();
      return r.fulfill({ response: res, body: full(await res.text()) });
    }
    return r.continue();
  });
  await p.addInitScript(() => { window.__FULL3D = true; });
  await p.goto(demoUrl(BASE + "?live=force" + (mode === "shtory" ? "&curtains=1" : "")), { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
  await p.evaluate(() => Promise.all([sceneModule(), rtMeshes()]));
  const cold = await p.evaluate(async (i) => {
    const t0 = performance.now();
    pickVariant(i); VW.collapse = true; vwOpenVariant(i); if (VW.mode !== "walk") vwMode("walk");
    for (let k = 0; k < 2400 && !LIVE.scene && LIVE.ok !== false; k++) await new Promise((r) => setTimeout(r, 25));
    return { ms: performance.now() - t0, ok: !!LIVE.scene, why: LIVE.why || "" };
  }, VI);
  await p.waitForFunction("LIVE.canvas&&LIVE.canvas.isConnected&&LIVE.canvas.getBoundingClientRect().width>100", null, { timeout: 30000 });
  const tag = `v${VI}-${W}-${mode}`;
  for (const cam of [0, 1]) {
    await p.evaluate((k) => vwCamGo(k), cam);
    await p.waitForTimeout(2500);   // переход камеры и запекание тени в простое
    const cv = await p.evaluateHandle(() => LIVE.canvas);
    await cv.asElement().screenshot({ path: `${OUT}${tag}-c${cam}.png` });
  }
  let move = null;
  if (MOVE && mode !== "bylo") {
    // ПЕРЕНОС: кровать (или первый крупный предмет) на 80 см в сторону; снимки «в руке» и «после переноса» — старой тени быть не должно
    await p.evaluate(() => vwCamGo(1));
    await p.waitForTimeout(2200);
    move = await p.evaluate(async () => {
      const big = items.map((it, i) => ({ it, i })).filter(({ it }) => it.sku && it.sku.msid && it.w && it.d && it.h > 30);
      const pick = big.find(({ it }) => /кроват|диван/i.test(it.role)) || big[0];
      if (!pick || !LIVE.scene.moveBegin(pick.i)) return { ok: false };
      LIVE.scene.moveBy(-80, 0, true);
      return { ok: true, role: pick.it.role, index: pick.i };
    });
    await p.waitForTimeout(1500);
    const cv = await p.evaluateHandle(() => LIVE.canvas);
    await cv.asElement().screenshot({ path: `${OUT}${tag}-move-hand.png` });
    await p.evaluate(() => LIVE.scene.moveEnd(true));
    await p.waitForTimeout(2000);
    await cv.asElement().screenshot({ path: `${OUT}${tag}-move-after.png` });
  }
  const perf = await p.evaluate(async (ph) => {
    const sc = LIVE.scene, pr = sc.probe(20);
    let n = 0; const t0 = performance.now();
    await new Promise((res) => { const f = () => { sc.look(ph ? 4 : 6, 0); n++; if (performance.now() - t0 < 4000) requestAnimationFrame(f); else res(); }; requestAnimationFrame(f); });
    return { p95: pr.p95Ms, fps: n / ((performance.now() - t0) / 1000) };
  }, PHONE).catch((e) => ({ err: String(e) }));
  await ctx.close();
  const res = { vi: VI, W, mode, cold, perf, move, errs };
  fs.writeFileSync(`${OUT}${tag}.json`, JSON.stringify(res, null, 1));
  log(tag, "cold", Math.round(cold.ms), cold.ok ? "" : "НЕТ СЦЕНЫ " + cold.why, "p95", perf.p95 && perf.p95.toFixed(1), "fps", perf.fps && perf.fps.toFixed(1),
    move ? "move " + JSON.stringify(move) : "", errs.length ? "ОШИБКИ " + errs.join(" || ").slice(0, 900) : "");
}

(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  try { for (const m of MODES) await one(b, m); } finally { await b.close(); }
})().catch((e) => { console.error(e); process.exit(2); });
