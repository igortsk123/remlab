// РЕАЛИСТИЧНЫЕ ФОТО ВАРИАНТОВ ДЕМО (план demo-09, дополнение 17.10). Фото нейросети на карточках были сняты 13.10 с прежних
// расстановок — страница их больше не показывает (`index.html:shotFits`). Этот шаг снимает новые: для каждого варианта без фото
// ЕГО расстановки — одно задание «realistic» функциями самой страницы (`pickVariant`, `makePhoto(..., {bg})`), обе точки одним
// листом, запись в реестре — с номером состояния. ПЛАТНО: запускать только после пополнения баланса сервиса картинок (владелец).
//   node tools/ops/demo-realistic.mjs              # сухой прогон: кому нужно фото и доступно ли улучшение — ничего не тратит
//   node tools/ops/demo-realistic.mjs --go         # пробная съёмка ОДНОГО варианта, проверка записи в реестре
//   node tools/ops/demo-realistic.mjs --go --all   # остальные — после того как пробное фото посмотрели глазами
// Ошибка любого варианта останавливает прогон (деньги не тратятся вслепую); счётчик «снято / не вышло» — в конце.
import { chromium } from "@playwright/test";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const GO = process.argv.includes("--go"), ALL = process.argv.includes("--all");

async function main() {
  const paid = await (await fetch(`${BASE}/api/draft/paid`)).json().catch(() => ({ available: false, code: "нет ответа" }));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let done = 0, failed = 0;
  try {
    await page.goto(`${BASE}/demo/`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
    await page.waitForTimeout(4000); // реестр кадров приезжает позже данных
    // кому нужно фото: у варианта нет реалистичного снимка его нынешней расстановки (то же правило, что у вкладки «Фото»)
    const todo = await page.evaluate(`(() => { const c0 = cur, out = [];
      allVariants().forEach((v, i) => { pickVariant(i); if (!vwRealShots().length) out.push({ i, style: v.style, stateId: curStateId() }); });
      pickVariant(c0); return out; })()`);
    console.log(`фото нейросети: вариантов без фото своей расстановки — ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
    console.log(`улучшение сейчас: ${paid.available ? "доступно" : "НЕДОСТУПНО (" + (paid.code ?? "?") + ")"}`);
    if (!GO) { console.log("сухой прогон — ничего не снято (для съёмки: --go, затем --go --all)"); return; }
    if (!paid.available) { console.log("STOP: улучшение недоступно — сначала пополнить баланс сервиса картинок"); process.exitCode = 1; return; }
    for (const t of ALL ? todo : todo.slice(0, 1)) {
      const t0 = Date.now();
      const res = await page.evaluate((i) => new Promise((ok) => {
        pickVariant(i);
        makePhoto("realistic", "", "", { bg: true, progress: () => {}, fail: (m) => ok({ error: String(m) }), done: (n0) => ok({ n: shots.length - n0 }) });
      }), t.i);
      // проверка по реестру сервера, а не по странице: запись этого стиля с номером его состояния и обеими точками
      const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
      const rec = reg.find((r) => r.style === t.style && r.quality === "realistic" && r.stateId === t.stateId);
      const sec = Math.round((Date.now() - t0) / 1000);
      if (!res.error && rec && (rec.shots ?? []).length >= 2) {
        done += 1;
        console.log(`  ${t.style}: снято за ${sec} с — ${(rec.shots ?? []).map((s) => s.url).join(" , ")}`);
      } else {
        failed += 1;
        console.log(`  ${t.style}: НЕ ВЫШЛО за ${sec} с — ${res.error ?? "в реестре нет записи с номером состояния"}`);
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
