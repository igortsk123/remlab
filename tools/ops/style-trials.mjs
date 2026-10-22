// ПРОБНЫЕ ФОТО ГАЙДОВ СТИЛЕЙ (план demo-13) — ПЛАТНО: по одному фото нейросети на стиль (обе точки одним листом). Пять стилей — на
// своих демо-вариантах, неоклассика — на расстановке «Сканди» со стилем «неоклассика». Снимки НЕ попадают в общий реестр (`no_registry`):
// карточки и вкладка «Фото» вариантов до приёмки владельцем не меняются. Итог — `~/scout-scenes/style-trials.json` для страницы
// `/test/share/style-guides/` (`tools/ops/style-guides-page.py`).
//   node tools/ops/style-trials.mjs                 # сухой прогон: что будет снято, версия промпта у рисующего процесса
//   node tools/ops/style-trials.mjs --go [стиль…]   # снять (все шесть или перечисленные); ошибка останавливает
import { chromium } from "@playwright/test";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const GO = process.argv.includes("--go");
const ONLY = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const WANT_PROMPT = process.env.EXPECT_PROMPT ?? "improve-v3.2";
const OUT = `${homedir()}/scout-scenes/style-trials.json`;
const STYLES = ["сканди", "современный", "минимализм", "лофт", "джапанди", "неоклассика"];

const dry = await (await fetch(`${BASE}/api/render`, { method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ async: 1, quality: "realistic", dry_run: 1, style: "сканди", room: { w: 439, d: 325 }, items: [{ role: "диван", x: 1, y: 1 }] }) })).json().catch(() => ({}));
const pv = dry?.render?.prompt_version;
console.log(`рисующий процесс: ${dry?.render_from ?? "?"} · модель ${dry?.render?.realistic_model ?? "?"} · промпт ${pv ?? "?"} · улучшение ${dry.dry_run ? "доступно" : "НЕДОСТУПНО " + (dry.code ?? "")}`);
const todo = STYLES.filter((s) => !ONLY.length || ONLY.includes(s));
console.log(`к съёмке: ${todo.join(", ")}`);
if (!GO) { console.log("сухой прогон — ничего не снято (съёмка: --go)"); process.exit(0); }
if (!dry.dry_run || pv !== WANT_PROMPT) { console.log(`STOP: нужен промпт ${WANT_PROMPT} и доступное улучшение`); process.exit(1); }

const res = existsSync(OUT) ? JSON.parse(readFileSync(OUT, "utf8")) : {};
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
let done = 0, failed = 0;
try {
  await page.goto(`${BASE}/demo/?live=force&lang=ru`, { waitUntil: "load", timeout: 120000 });
  await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT && shots.length > 0", null, { timeout: 90000 });
  await page.waitForTimeout(3000);
  for (const st of todo) {
    const t0 = Date.now();
    const r = await page.evaluate(async (st) => {
      // вариант этого стиля; у неоклассики своего нет — расстановка «Сканди», стиль в запросе — неоклассика
      const vs = allVariants(); let i = vs.findIndex((v) => v.style === st); const as = i < 0 ? st : null; if (i < 0) i = vs.findIndex((v) => v.style === "сканди");
      pickVariant(i); openLiveWindow(); if (VW.mode !== "walk") vwMode("walk");
      for (let k = 0; k < 600 && !(LIVE.scene && LIVE.state === "ready"); k++) await new Promise((ok) => setTimeout(ok, 300));
      const cap = await vwCaptureViews();
      if (!cap) return { error: "кадры из браузера не сняты — платный вызов не делаю" };
      return await new Promise((ok) => makePhoto("realistic", "", "", { bg: true,
        extra: { views: cap.views, clay: cap.clay, no_registry: 1, ...(as ? { style: as } : {}) },
        progress: () => {}, fail: (m) => ok({ error: String(m) }),
        done: (n0) => ok({ shots: shots.slice(n0).map((s) => ({ camera: s.camera, url: s.url, thumb: s.url.replace(/\.jpg$/, ".t.jpg") })),
          timing: (shots[n0] || {}).timing, model: (shots[n0] || {}).model, variant: vs[i].style }) }));
    }, st);
    const sec = Math.round((Date.now() - t0) / 1000);
    if (r.error || !(r.shots || []).length) { failed += 1; console.log(`  ${st}: НЕ ВЫШЛО за ${sec} с — ${r.error ?? "нет кадров"}`); break; }
    res[st] = { shots: r.shots, timing: r.timing, model: r.model, on: r.variant, prompt: pv, ts: Date.now() };
    writeFileSync(OUT, JSON.stringify(res, null, 1));
    done += 1;
    console.log(`  ${st}: снято за ${sec} с (на расстановке «${r.variant}») · ${JSON.stringify(r.timing)} · ${r.shots.map((s) => s.url).join(" , ")}`);
  }
} finally {
  await browser.close();
}
console.log(`пробные фото стилей: снято ${done}, не вышло ${failed} → ${OUT}`);
if (failed) process.exitCode = 1;
