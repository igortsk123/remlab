// ПРОВЕРКА СОБРАННОЙ СТРАНИЦЫ ДЕМО (T-20261112-90, критика Codex к плану tour-page-split-01): страница едет в витрину сжатой
// (`tools/scout/page_build.mjs`), а тесты читают исходник — значит, поломку именно сжатой копии они не увидят. Здесь — настоящий браузер
// на папке сборки через `stage-proxy.mjs` (страница, данные и `lib/` — из папки; картинки и API — с прода, события не пишутся):
//   • страница открывается без ошибок (исключения страницы и `console.error`; не загрузившиеся картинки прода — отдельной строкой);
//   • поток ракурсов отвечает: `camWorker()` взял файл `lib/camfit.<хеш>.js` из `lib/scene.json`, пара ракурсов варианта — 2 точки;
//   • прогрев кадров (`tools/ops/demo-warm.mjs`) найдёт свои функции, и текст `shotCamOk`/`camAng` собирается в функцию, как у него;
//   • плашка замера `?perf=1` на месте; то же — с `lang=en`.
// Не прошло и задан `--src` — в папку сборки кладётся ИСХОДНИК как есть (несжатый, работает как до T-90), строка `WARN:page_check`,
// код 1: ночь (`refresh_daily.sh`) показывает FAIL шага, а публикуется рабочая страница.
//   node tools/ops/demo-walk/page-check.mjs [--stage <папка сборки>] [--src <исходник index.html>] [--out <папка отчёта>]
import { spawn } from "node:child_process";
import { copyFileSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const STAGE = arg("--stage", join(homedir(), "scout-scenes", "flat215-demo")), SRC = arg("--src", ""), OUT = arg("--out", "");
const PORT = Number(process.env.PAGE_CHECK_PORT ?? 8700 + (process.pid % 90));
const HERE = dirname(fileURLToPath(import.meta.url));
const WARM = ["D", "allVariants", "roomGeoOf", "roomIdOf", "pubStateOf", "shots", "POSE_VER", "shotCamOk", "camAng", "CAM_ID_TOL",
  "pickVariant", "makePhoto", "devCanon"];

async function up() {
  for (let i = 0; i < 100; i++) {
    try { await fetch(`http://127.0.0.1:${PORT}/demo/lib/scene.json`); return; } catch { await new Promise((r) => setTimeout(r, 100)); }
  }
  throw new Error(`stage-proxy не поднялся на ${PORT}`);
}

/** Один заход: ошибки страницы, поток ракурсов, функции прогрева, плашка. → { errs, net, checks: [имя, ок, подробно][] } */
async function visit(browser, query) {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 667 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "ru-RU" });
  const page = await ctx.newPage();
  const errs = [], net = [], checks = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 300)));
  page.on("console", (m) => { if (m.type() === "error") (/Failed to load resource/.test(m.text()) ? net : errs).push(m.text().slice(0, 300)); });
  try {
    await page.goto(`http://127.0.0.1:${PORT}/demo/${query}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
    await page.waitForFunction("typeof D !== 'undefined' && !!D && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
    const r = await page.evaluate(async () => {
      const w = await camWorker();
      const v = allVariants().find((x) => roomGeoOf(x) && (x.items || []).length);
      let pair = null;
      if (w && v) pair = await new Promise((ok) => { const n = ++CAMW.id; const t = setTimeout(() => ok({ err: "нет ответа за 60 с" }), 60_000);
        CAMW.wait.set(n, (x) => { clearTimeout(t); ok(x); });
        w.postMessage({ id: n, rid: roomIdOf(v), geo: JSON.parse(JSON.stringify(roomGeoOf(v))),
          its: v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 })) }); });
      const man = await sceneManifest();
      return { worker: !!w, file: man && man.camfit && man.camfit.file, pair, vid: v && v.id };
    });
    checks.push(["поток ракурсов", !!(r.worker && r.pair && Array.isArray(r.pair.cams) && r.pair.cams.length === 2),
      `файл ${r.file || "—"}, вариант ${r.vid}, ответ ${JSON.stringify(r.pair).slice(0, 160)}`]);
    const miss = await page.evaluate((names) => names.filter((n) => { try { return (0, eval)(`typeof ${n}`) === "undefined"; } catch { return true; } }), WARM);
    checks.push(["функции прогрева", miss.length === 0, miss.length ? `нет: ${miss.join(", ")}` : `${WARM.length} на месте`]);
    const camSrc = await page.evaluate("'const camAng=' + camAng.toString() + ';const CAM_ID_TOL=' + JSON.stringify(CAM_ID_TOL) + ';const POSE_VER=' + POSE_VER + ';' + shotCamOk.toString()");
    let warmOk = false;
    try { warmOk = typeof new Function(`${camSrc}\n;return typeof shotCamOk === "function" ? shotCamOk : null;`)() === "function"; } catch { /* ниже */ }
    checks.push(["текст shotCamOk для прогрева", warmOk, `${camSrc.length} знаков`]);
    await page.waitForTimeout(1500);
    const badge = await page.evaluate(() => (document.getElementById("perfBadge") || {}).textContent || "");
    checks.push(["плашка ?perf=1", /^HTML \d/.test(badge), badge.replace(/\n/g, " | ")]);
  } catch (e) {
    checks.push(["страница открылась", false, String(e).slice(0, 300)]);
  } finally {
    await ctx.close();
  }
  checks.unshift(["ошибок консоли нет", errs.length === 0, errs.length ? errs.slice(0, 3).join(" ‖ ") : "0"]);
  return { errs, net, checks };
}

async function main() {
  const proxy = spawn(process.execPath, [join(HERE, "stage-proxy.mjs")], { env: { ...process.env, STAGE, PORT: String(PORT), NO_EVENTS: "1" },
    stdio: ["ignore", "ignore", "inherit"] });
  let browser, res = {};
  try {
    await up();
    browser = await chromium.launch();
    for (const q of ["?quiz=0&lang=ru&perf=1", "?quiz=0&lang=en&perf=1"]) res[q] = await visit(browser, q);
  } finally {
    await browser?.close();
    proxy.kill();
  }
  const lines = [], bad = [];
  for (const [q, r] of Object.entries(res)) {
    for (const [n, ok, info] of r.checks) { lines.push(`${ok ? "OK  " : "FAIL"} ${q} · ${n}: ${info}`); if (!ok) bad.push(`${q} ${n}`); }
    if (r.net.length) lines.push(`инфо ${q} · не загрузилось с прода: ${r.net.length}`);
  }
  console.log(lines.join("\n"));
  if (OUT) { mkdirSync(OUT, { recursive: true }); writeFileSync(join(OUT, "page-check.json"), JSON.stringify(res, null, 1)); }
  if (!bad.length) { console.log(`page_check: OK — сжатая страница ${STAGE}: без ошибок, поток ракурсов, прогрев, плашка`); return 0; }
  if (SRC) {
    const t = join(STAGE, `index.html.${process.pid}.tmp`);
    copyFileSync(SRC, t); renameSync(t, join(STAGE, "index.html"));
  }
  console.log(`WARN:page_check: сжатая страница не прошла (${bad.join("; ").slice(0, 200)})` +
    (SRC ? " — в витрину положен исходник как есть" : ""));
  return 1;
}

main().then((rc) => process.exit(rc), (e) => { console.log(`WARN:page_check: проверка упала: ${String(e).slice(0, 200)}`); process.exit(1); });
