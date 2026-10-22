// РЕАЛИСТИЧНЫЕ ФОТО ВАРИАНТОВ ДЕМО (план demo-09, дополнение 17.10). Фото нейросети на карточках были сняты 13.10 с прежних
// расстановок — страница их больше не показывает (`index.html:shotFits`). Этот шаг снимает новые: для каждого варианта без фото
// ЕГО расстановки — одно задание «realistic» функциями самой страницы (`pickVariant`, `makePhoto(..., {bg})`), обе точки одним
// листом, запись в реестре — с номером состояния. ПЛАТНО: запускать только после пополнения баланса сервиса картинок (владелец).
//   node tools/ops/demo-realistic.mjs              # сухой прогон: кому нужно фото и доступно ли улучшение — ничего не тратит
//   node tools/ops/demo-realistic.mjs --go         # пробная съёмка ОДНОГО варианта, проверка записи в реестре
//   node tools/ops/demo-realistic.mjs --go --all   # остальные — после того как пробное фото посмотрели глазами
//   node tools/ops/demo-realistic.mjs --force сканди [--go]   # переснять и у кого фото уже есть (demo-11: новая модель и промпт)
//   node tools/ops/demo-realistic.mjs --force all --go --all
//   --frames   кадры из браузера (живая 3D-сцена, как у покупателя: `vwCaptureViews`), а не серверный эскиз; не снялись — СТОП без оплаты
// Годна только НОВАЯ запись реестра (не из прежних id) этого стиля и состояния, с обеими точками, позами камер страницы,
// моделью и версией промпта, которых ждём (EXPECT_MODEL, EXPECT_PROMPT); `shots.json` не чистится — старое остаётся историей.
// Ошибка любого варианта останавливает прогон (деньги не тратятся вслепую); счётчик «снято / не вышло» — в конце.
import { chromium } from "@playwright/test";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const GO = process.argv.includes("--go"), ALL = process.argv.includes("--all"), FRAMES = process.argv.includes("--frames");
const fi = process.argv.indexOf("--force"), FORCE = fi >= 0 ? (process.argv[fi + 1] || "all") : "";
const EXPECT_MODEL = process.env.EXPECT_MODEL ?? "improve/openai/gpt-image-2.5-sunburst";
const EXPECT_PROMPT = process.env.EXPECT_PROMPT ?? "improve-v4.2";   // demo-14: + список товаров (ADR-0305); .1 — радиатор под окном (demo-20 Г3); .2 — люстра стиля (Г4)

async function main() {
  const paid = await (await fetch(`${BASE}/api/draft/paid`)).json().catch(() => ({ available: false, code: "нет ответа" }));
  const browser = await chromium.launch(FRAMES ? { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } : {});
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let done = 0, failed = 0;
  try {
    // без 3D-сцены (см. demo-warm.mjs); с --frames — со сценой: кадры снимает браузер
    await page.goto(`${BASE}/demo/?live=${FRAMES ? "force" : "0"}&lang=ru`, { waitUntil: FRAMES ? "load" : "domcontentloaded", timeout: 120_000 });
    await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
    await page.waitForTimeout(4000); // реестр кадров приезжает позже данных
    // кому нужно фото: у варианта нет реалистичного снимка его нынешней расстановки (то же правило, что у вкладки «Фото»)
    const todo = await page.evaluate(`((force) => { const c0 = cur, out = [];
      allVariants().forEach((v, i) => { pickVariant(i);
        // --force <стиль> — только он; --force all — все; без --force — у кого нет фото своей расстановки
        const want = force ? (force === "all" || force === v.style) : !vwRealShots().length;
        if (want) out.push({ i, style: v.style, stateId: curStateId(), cams: (cams || loadCams()).map((c) => [c.name, Math.round(c.x), Math.round(c.y), Math.round(c.rot || 0)].join(":")).join("|") }); });
      pickVariant(c0); return out; })(${JSON.stringify(FORCE)})`);
    const before = new Set((await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json()).map((r) => r.id));
    console.log(`фото нейросети: ${FORCE ? `переснять (--force ${FORCE})` : "без фото своей расстановки"} — ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
    console.log(`улучшение сейчас: ${paid.available ? "доступно" : "НЕДОСТУПНО (" + (paid.code ?? "?") + ")"}`);
    if (!GO) { console.log("сухой прогон — ничего не снято (для съёмки: --go, затем --go --all)"); return; }
    if (!paid.available) { console.log("STOP: улучшение недоступно — сначала пополнить баланс сервиса картинок"); process.exitCode = 1; return; }
    for (const t of ALL ? todo : todo.slice(0, 1)) {
      const t0 = Date.now();
      const res = await page.evaluate(async ([i, frames]) => {
        pickVariant(i);
        let extra = {};
        if (frames) {
          openLiveWindow(); if (VW.mode !== "walk") vwMode("walk");
          for (let k = 0; k < 600 && !(LIVE.scene && LIVE.state === "ready"); k++) await new Promise((ok) => setTimeout(ok, 300));
          const cap = await vwCaptureViews();
          if (!cap) return { error: "кадры из браузера не сняты — платный вызов не делаю" };
          extra = { views: cap.views, clay: cap.clay, sheet: cap.sheet };
        }
        return await new Promise((ok) => makePhoto("realistic", "", "", { bg: true, extra, progress: () => {}, fail: (m) => ok({ error: String(m) }),
          done: (n0) => ok({ n: shots.length - n0, frames: (shots[n0] || {}).timing?.frames }) }));
      }, [t.i, FRAMES]);
      if (FRAMES && !res.error && res.frames !== "browser") res.error = `снято не из кадров браузера (${res.frames ?? "?"})`;
      // проверка по реестру сервера, а не по странице: запись этого стиля с номером его состояния и обеими точками
      const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
      const sig = (r) => (r.cams ?? []).map((c) => [c.name, Math.round(c.x), Math.round(c.y), Math.round(c.rot || 0)].join(":")).join("|");
      const rec = reg.find((r) => !before.has(r.id) && r.style === t.style && r.quality === "realistic" && r.stateId === t.stateId);
      const why = !rec ? "в реестре нет новой записи с номером состояния"
        : rec.model !== EXPECT_MODEL ? `модель ${rec.model}, ждали ${EXPECT_MODEL}`
        : rec.prompt_version !== EXPECT_PROMPT ? `промпт ${rec.prompt_version ?? "—"}, ждали ${EXPECT_PROMPT}`
        : sig(rec) !== t.cams ? `позы камер ${sig(rec)} ≠ страницы ${t.cams}` : "";
      const sec = Math.round((Date.now() - t0) / 1000);
      if (!res.error && rec && !why && (rec.shots ?? []).length >= 2) {
        done += 1;
        console.log(`  ${t.style}: снято за ${sec} с — ${(rec.shots ?? []).map((s) => s.url).join(" , ")}`);
      } else {
        failed += 1;
        console.log(`  ${t.style}: НЕ ВЫШЛО за ${sec} с — ${res.error ?? why ?? "меньше двух кадров"}`);
        break;
      }
    }
    if (!ALL && todo.length > 1 && done) console.log("пробное фото снято — посмотреть глазами, затем --go --all");
  } finally {
    await browser.close();
  }
  console.log(`фото нейросети: снято ${done}, не вышло ${failed}`);
  if (failed) process.exitCode = 1;
}

await main();
