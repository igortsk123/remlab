// РЕАЛИСТИЧНЫЕ ФОТО ВАРИАНТОВ ДЕМО (план demo-09, дополнение 17.10). Фото нейросети на карточках были сняты 13.10 с прежних
// расстановок — страница их больше не показывает (`index.html:shotFits`). Этот шаг снимает новые: для каждого варианта без фото
// ЕГО расстановки — одно задание «realistic» функциями самой страницы (`pickVariant`, `makePhoto(..., {bg})`), обе точки одним
// листом, запись в реестре — с номером состояния. ПЛАТНО: запускать только после пополнения баланса сервиса картинок (владелец).
//   node tools/ops/demo-realistic.mjs              # сухой прогон: кому нужно фото и доступно ли улучшение — ничего не тратит
//   node tools/ops/demo-realistic.mjs --go         # пробная съёмка ОДНОГО варианта, проверка записи в реестре
//   node tools/ops/demo-realistic.mjs --go --all   # остальные — после того как пробное фото посмотрели глазами
//   node tools/ops/demo-realistic.mjs --force сканди [--go]   # переснять и у кого фото уже есть (demo-11: новая модель и промпт)
//   node tools/ops/demo-realistic.mjs --force all --go --all
//   node tools/ops/demo-realistic.mjs --night [--cap-rub 50] [--dry]   # ночной шаг demo_real (demo-29), см. ниже
//   node tools/ops/demo-realistic.mjs --selftest   # ночной учёт и потолок на заглушках — без браузера и денег
//   --frames   кадры из браузера (живая 3D-сцена, как у покупателя: `vwCaptureViews`), а не серверный эскиз; не снялись — СТОП без оплаты
//   DEMO_LOCAL=<папка сборки>   страница и данные витрины — из локальной сборки (`FLAT215_DEMO_OUT`), сервер и реестр — прода: фото
//              новых ракурсов снимаются ДО публикации (demo-22: опубликованная страница их сразу показывает — номер состояния тот же)
// Годна только НОВАЯ запись реестра (не из прежних id) этого стиля и состояния, с обеими точками, позами камер страницы,
// моделью и версией промпта, которых ждём (EXPECT_MODEL, EXPECT_PROMPT); `shots.json` не чистится — старое остаётся историей.
// Ошибка любого варианта останавливает прогон (деньги не тратятся вслепую); счётчик «снято / не вышло» — в конце.
//
// НОЧЬ (план demo-29, владелец 23.10 «а»): `--night` снимает всех без фото своей расстановки, пока трата ночи не дойдёт до потолка
// (`rules/demo-realistic.json:night_cap_rub`, 50 ₽; `--cap-rub` — перекрыть). Трата — ФАКТ: прирост счётчика шлюза `total_used`
// (GET /v1/credits, бесплатно) после задания; не пришёл за `bill_wait_s` или ключа нет — задание по оценке `est_rub_per_job`.
// Прерванное («результат неизвестен») считается потраченным. Ошибка — стоп без повторов; улучшение недоступно — 0 ₽ и WARN.
// Итог — строка `DIGEST:` в утреннюю сводку; сбой — `WARN:demo_real:`. Код выхода 0 у обработанных исходов (шаг — warn, не FAIL).
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const NIGHT = process.argv.includes("--night"), DRY = process.argv.includes("--dry");
const GO = process.argv.includes("--go") || (NIGHT && !DRY), ALL = process.argv.includes("--all") || NIGHT, FRAMES = process.argv.includes("--frames");
const fi = process.argv.indexOf("--force"), FORCE = fi >= 0 ? (process.argv[fi + 1] || "all") : "";
const EXPECT_MODEL = process.env.EXPECT_MODEL ?? "improve/openai/gpt-image-2.5-sunburst";
const LOCAL = process.env.DEMO_LOCAL ?? "";
const EXPECT_PROMPT = process.env.EXPECT_PROMPT ?? "improve-v4.3";   // demo-14: + список товаров (ADR-0305); .1 — радиатор под окном (demo-20 Г3); .2 — люстра стиля (Г4); .3 — мягкое (demo-24)
const RULES = new URL("../scout/rules/demo-realistic.json", import.meta.url);
const CREDITS_URL = "https://ai-gateway.vercel.sh/v1/credits";

/** Правила ночи из настройки; `--cap-rub N` перекрывает потолок. Нет файла или поля — громкий отказ, а не тихий дефолт. */
export function nightRules(text, argv = []) {
  const r = JSON.parse(text);
  const ci = argv.indexOf("--cap-rub");
  const out = { cap: Number(ci >= 0 ? argv[ci + 1] : r.night_cap_rub), est: Number(r.est_rub_per_job), rate: Number(r.usd_rub), waitS: Number(r.bill_wait_s ?? 90) };
  for (const [k, v] of Object.entries(out)) if (!(Number.isFinite(v) && v >= 0)) throw new Error(`rules/demo-realistic.json: ${k} = ${v}`);
  if (!out.cap || !out.est || !out.rate) throw new Error("rules/demo-realistic.json: потолок, оценка задания и курс обязаны быть больше нуля");
  return out;
}

/** Ключ шлюза картинок — из окружения или tools/scout/.env (как `draft_render.gw_key`); нет — null. Значение не печатается. */
function gwKey() {
  if (process.env.VERCEL_AI_GATEWAY_KEY) return process.env.VERCEL_AI_GATEWAY_KEY.trim();
  try {
    const line = readFileSync(new URL("../scout/.env", import.meta.url), "utf8").split("\n").find((l) => l.startsWith("VERCEL_AI_GATEWAY_KEY="));
    return line ? line.split("=").slice(1).join("=").trim().replace(/^["']|["']$/g, "") : null;
  } catch { return null; }
}

/** Сколько всего списал шлюз, $ (счётчик `total_used`); не узнать — null. */
async function gwUsed() {
  const key = gwKey();
  if (!key) return null;
  try {
    const r = await fetch(CREDITS_URL, { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(10_000) });
    const v = Number((await r.json()).total_used);
    return r.ok && Number.isFinite(v) ? v : null;
  } catch { return null; }
}

/** НОЧНОЙ ЦИКЛ (чистое ядро, deps — заглушки в самопроверке): перед заданием — влезает ли оценка в остаток потолка; после —
 *  факт по приросту счётчика (ждём до `waitS`), не пришёл — оценка. Ошибка или прерванное — стоп, трата учтена.
 *  deps: shoot(t) → {ok, why}; used() → $|null; sleep(ms). → {done, failed, rub, byEst, stop, left, log[]} */
export async function runNight(todo, deps, rules) {
  const res = { done: 0, failed: 0, rub: 0, byEst: 0, stop: "", left: 0, log: [] };
  let last = await deps.used();
  for (let k = 0; k < todo.length; k++) {
    const t = todo[k];
    if (res.rub + rules.est > rules.cap) { res.stop = "cap"; res.left = todo.length - k; break; }
    let r;
    try { r = await deps.shoot(t); } catch (e) { r = { ok: false, why: `прервано, результат неизвестен: ${String(e?.message ?? e).slice(0, 120)}` }; }
    let delta = null;
    if (last !== null) {
      for (let waited = 0; ; waited += 10) {
        const u = await deps.used();
        if (u !== null && u > last + 1e-9) { delta = u - last; last = u; break; }
        if (waited >= rules.waitS) break;
        await deps.sleep(10_000);
      }
    }
    const rub = delta !== null ? delta * rules.rate : rules.est;
    if (delta === null) res.byEst += 1;
    res.rub += rub;
    res.log.push(`  ${t.style}: ${r.ok ? "снято" : "НЕ ВЫШЛО — " + r.why}, ${rub.toFixed(1)} ₽${delta === null ? " (оценка)" : ""}`);
    if (r.ok) res.done += 1;
    else { res.failed += 1; res.stop = "error"; res.why = `${t.style}: ${r.why}`; res.left = todo.length - k - 1; break; }
  }
  return res;
}

/** Строки итога для лога шага: DIGEST — в утреннюю сводку, WARN — в предупреждения дайджеста. */
export function nightLines(n, todoLen, paid, res, cap) {
  if (!todoLen) return ["DIGEST:фото нейросети: все стили с фото своей расстановки — 0 ₽"];
  if (!paid.available) return [`WARN:demo_real: улучшение недоступно (${paid.code ?? "?"}) — без фото своей расстановки ${todoLen}, ничего не снято, 0 ₽`];
  const tail = res.stop === "cap" ? `; потолок — без фото осталось ${res.left}` : res.stop === "error" ? `; остановлено на ошибке, без фото осталось ${res.left}` : "";
  const out = [`DIGEST:фото нейросети: снято ${res.done}, не вышло ${res.failed}, ≈${Math.round(res.rub)} ₽ из ${cap} ₽${res.byEst ? ` (по оценке — ${res.byEst})` : ""}${tail}`];
  if (res.stop === "error") out.push(`WARN:demo_real: ${res.why}`);
  if (res.stop === "cap") out.push(`WARN:demo_real: потолок ${cap} ₽ — без фото своей расстановки осталось ${res.left} (досниму следующей ночью)`);
  return out;
}

async function main() {
  const rules = NIGHT ? nightRules(readFileSync(RULES, "utf8"), process.argv) : null;
  const paid = await (await fetch(`${BASE}/api/draft/paid`)).json().catch(() => ({ available: false, code: "нет ответа" }));
  const browser = await chromium.launch(FRAMES ? { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } : {});
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  if (LOCAL) {
    const file = (n) => readFileSync(join(LOCAL, n));
    await page.route((u) => ["/demo/", "/demo/index.html"].includes(new URL(u).pathname), (r) => r.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: file("index.html") }));
    await page.route((u) => new URL(u).pathname === "/demo/demo-data.json", (r) => r.fulfill({ status: 200, contentType: "application/json", body: file("demo-data.json") }));
    console.log(`страница и данные витрины — из ${LOCAL} (не опубликованы); рендер и реестр — ${BASE}`);
  }
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
      pickVariant(c0); return out; })(${JSON.stringify(NIGHT ? "" : FORCE)})`);
    const before = new Set((await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json()).map((r) => r.id));
    console.log(`фото нейросети: ${FORCE && !NIGHT ? `переснять (--force ${FORCE})` : "без фото своей расстановки"} — ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
    console.log(`улучшение сейчас: ${paid.available ? "доступно" : "НЕДОСТУПНО (" + (paid.code ?? "?") + ")"}`);
    if (NIGHT) {
      const used = await gwUsed();
      console.log(`ночь: потолок ${rules.cap} ₽, оценка задания ${rules.est} ₽ — влезает до ${Math.floor(rules.cap / rules.est)} заданий; счётчик шлюза: ${used === null ? "не читается — трата по оценке" : "читается"}`);
      if (DRY || !todo.length || !paid.available) {
        if (DRY) console.log(`сухой прогон ночи — ничего не снято, 0 ₽ (снял бы ${Math.min(todo.length, Math.floor(rules.cap / rules.est))})`);
        else for (const l of nightLines(0, todo.length, paid, null, rules.cap)) console.log(l);
        return;
      }
      const res = await runNight(todo, { shoot: (t) => shootOne(page, t, before), used: gwUsed, sleep: (ms) => new Promise((ok) => setTimeout(ok, ms)) }, rules);
      for (const l of res.log) console.log(l);
      for (const l of nightLines(0, todo.length, paid, res, rules.cap)) console.log(l);
      done = res.done; failed = res.failed;
      return;
    }
    if (!GO) { console.log("сухой прогон — ничего не снято (для съёмки: --go, затем --go --all)"); return; }
    if (!paid.available) { console.log("STOP: улучшение недоступно — сначала пополнить баланс сервиса картинок"); process.exitCode = 1; return; }
    for (const t of ALL ? todo : todo.slice(0, 1)) {
      const r = await shootOne(page, t, before);
      if (r.ok) { done += 1; console.log(`  ${t.style}: снято за ${r.sec} с — ${r.urls}`); }
      else { failed += 1; console.log(`  ${t.style}: НЕ ВЫШЛО за ${r.sec} с — ${r.why}`); break; }
    }
    if (!ALL && todo.length > 1 && done) console.log("пробное фото снято — посмотреть глазами, затем --go --all");
  } finally {
    await browser.close();
  }
  console.log(`фото нейросети: снято ${done}, не вышло ${failed}`);
  if (failed && !NIGHT) process.exitCode = 1;
}

/** Одно платное задание «realistic» для варианта `t` и проверка по реестру сервера. → {ok, why, sec, urls} */
async function shootOne(page, t, before) {
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
  const ok = !res.error && rec && !why && (rec.shots ?? []).length >= 2;
  return { ok: !!ok, why: res.error ?? (why || "меньше двух кадров"), sec, urls: (rec?.shots ?? []).map((s) => s.url).join(" , ") };
}

async function selftest() {
  const res = [];
  const check = (ok, msg, got) => { res.push(ok); console.log(ok ? `OK   ${msg}` : `FAIL ${msg}: ${JSON.stringify(got)}`); };
  const rules = nightRules(readFileSync(RULES, "utf8"));
  check(rules.cap === 50 && rules.est > 0 && rules.rate > 0, "настройка: потолок 50 ₽ (слово владельца), оценка и курс заданы", rules);
  check(nightRules(readFileSync(RULES, "utf8"), ["--cap-rub", "20"]).cap === 20, "--cap-rub перекрывает потолок", null);
  let threw = false;
  try { nightRules('{"night_cap_rub": 50}'); } catch { threw = true; }
  check(threw, "нет оценки задания или курса в настройке — громкий отказ", threw);
  const R = { cap: 50, est: 10, rate: 100, waitS: 30 };
  const todo = ["лофт", "сканди", "джапанди", "минимализм", "классика", "бохо", "эко", "прованс", "фьюжн"].map((style, i) => ({ i, style }));
  const meter = (per) => { let u = 1.0; return { used: async () => u, bill: () => { u += per; } }; };
  const nap = async () => {};
  // 1) факт по счётчику: 0,06 $ × 100 = 6 ₽ за задание; следующее начинаем, пока 6·k + 10 ≤ 50 → семь заданий, 42 ₽
  let m = meter(0.06), shot = [];
  let r = await runNight(todo, { shoot: async (t) => { shot.push(t.style); m.bill(); return { ok: true }; }, used: m.used, sleep: nap }, R);
  check(r.done === 7 && r.stop === "cap" && r.left === 2 && Math.round(r.rub) === 42 && !r.byEst, "потолок останавливает: по факту 6 ₽ — семь заданий, остальные ждут ночи", r);
  check(nightLines(0, 9, { available: true }, r, 50).some((l) => l.startsWith("DIGEST:фото нейросети: снято 7, не вышло 0, ≈42 ₽ из 50 ₽; потолок — без фото осталось 2")),
    "строка DIGEST с числом, суммой и остатком", nightLines(0, 9, { available: true }, r, 50));
  // 2) счётчика нет — по оценке: 10 ₽ за задание → ровно пять
  r = await runNight(todo, { shoot: async () => ({ ok: true }), used: async () => null, sleep: nap }, R);
  check(r.done === 5 && r.rub === 50 && r.byEst === 5 && r.stop === "cap", "счётчик не читается — по оценке, не больше потолка", r);
  // 3) счётчик не прирос за ожидание — задание по оценке
  m = meter(0);
  r = await runNight(todo.slice(0, 1), { shoot: async () => ({ ok: true }), used: m.used, sleep: nap }, R);
  check(r.rub === 10 && r.byEst === 1, "списание не пришло за ожидание — считаем по оценке", r);
  // 4) прерванное (исключение посреди задания) — потрачено, стоп без повторов
  m = meter(0.06); shot = [];
  r = await runNight(todo, { shoot: async (t) => { shot.push(t.style); if (t.i === 1) throw new Error("Target closed"); m.bill(); return { ok: true }; }, used: m.used, sleep: nap }, R);
  check(r.done === 1 && r.failed === 1 && r.stop === "error" && shot.length === 2 && Math.round(r.rub) === 16 && r.byEst === 1,
    "прерванное считается потраченным (по оценке), после него — стоп, повторов нет", { r, shot });
  check(nightLines(0, 7, { available: true }, r, 50).some((l) => l.startsWith("WARN:demo_real: сканди: прервано")), "сбой — строка WARN:demo_real", nightLines(0, 7, { available: true }, r, 50));
  // 5) ошибка с ответом (нет записи в реестре) — стоп; трата по факту, если шлюз списал
  m = meter(0.06);
  r = await runNight(todo, { shoot: async () => { m.bill(); return { ok: false, why: "в реестре нет новой записи" }; }, used: m.used, sleep: nap }, R);
  check(r.done === 0 && r.failed === 1 && Math.round(r.rub) === 6 && r.left === 8, "ошибка первого — стоп, остальные не тронуты", r);
  // 6) улучшение недоступно, все с фото — 0 ₽
  check(nightLines(0, 3, { available: false, code: "no_credits" }, null, 50)[0].startsWith("WARN:demo_real: улучшение недоступно (no_credits)"), "улучшение недоступно — WARN, 0 ₽", null);
  check(nightLines(0, 0, { available: true }, null, 50)[0] === "DIGEST:фото нейросети: все стили с фото своей расстановки — 0 ₽", "все стили с фото — 0 ₽", null);
  // 7) потолок меньше оценки — ни одного задания
  r = await runNight(todo, { shoot: async () => { throw new Error("не должно звать"); }, used: async () => null, sleep: nap }, { ...R, cap: 5 });
  check(r.done === 0 && r.failed === 0 && r.stop === "cap" && r.rub === 0, "потолок меньше оценки — ничего не начато, 0 ₽", r);
  // 8) шаг ночи: публикация не прошла — demo_real пропущен (bash-ветка refresh_daily.sh)
  const sh = readFileSync(new URL("../scout/refresh_daily.sh", import.meta.url), "utf8");
  const bash = (pub) => {
    // ветка шага из самого refresh_daily.sh; запись в лог ночи — в вывод (сокет node не открыть заново как /dev/stdout)
    const body = sh.slice(sh.indexOf("# ДОСЪЁМКА ФОТО НЕЙРОСЕТИ"), sh.indexOf("# живая проверка демо на проде"));
    return import("node:child_process").then(({ spawnSync }) => spawnSync("bash", ["-c",
      `declare -A RES; RES[flat215_publish]=${pub}; OPENAI_OFF=0; step(){ echo "STEP $1"; }; paid_step(){ step "$@"; }\n${body.replaceAll('>> "$LOG"', "")}\necho "RES=\${RES[demo_real]:-}"`],
    { encoding: "utf8" }).stdout);
  };
  const okRun = await bash("ok"), warnRun = await bash("warn"), failRun = await bash("FAIL"), noRun = await bash("");
  check(/STEP demo_real/.test(okRun) && /STEP demo_real/.test(warnRun) && !/STEP demo_real/.test(failRun) && !/STEP demo_real/.test(noRun)
    && /DIGEST:фото нейросети: пропущено/.test(failRun) && /RES=\n/.test(failRun + "\n"),
    "публикация FAIL (или не было) — шаг demo_real пропущен со строкой DIGEST, без пометки openai.off; ok/warn — шаг идёт", { okRun, failRun, noRun });
  process.exit(res.every(Boolean) ? 0 : 1);
}

if (process.argv.includes("--selftest")) await selftest();
else if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) await main();
