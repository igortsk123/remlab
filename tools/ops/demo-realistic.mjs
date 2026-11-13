// РЕАЛИСТИЧНЫЕ ФОТО ВАРИАНТОВ ДЕМО (план demo-09, дополнение 17.10). Фото нейросети на карточках были сняты 13.10 с прежних
// расстановок — страница их больше не показывает (`index.html:shotFits`). Этот шаг снимает новые: для каждого варианта без фото
// ЕГО расстановки — одно задание «realistic» функциями самой страницы (`pickVariant`, `makePhoto(..., {bg})`), обе точки одним
// листом, запись в реестре — с номером состояния. ПЛАТНО: запускать только после пополнения баланса сервиса картинок (владелец).
//   node tools/ops/demo-realistic.mjs              # сухой прогон: кому нужно фото и доступно ли улучшение — ничего не тратит
//   node tools/ops/demo-realistic.mjs --go         # пробная съёмка ОДНОГО варианта, проверка записи в реестре
//   node tools/ops/demo-realistic.mjs --go --all   # остальные — после того как пробное фото посмотрели глазами
//   node tools/ops/demo-realistic.mjs --force сканди [--go]   # переснять и у кого фото уже есть (demo-11: новая модель и промпт)
//   node tools/ops/demo-realistic.mjs --force all --go --all
//   node tools/ops/demo-realistic.mjs --night [--cap-rub 200] [--dry]   # ночной шаг demo_real (demo-29), см. ниже
//   node tools/ops/demo-realistic.mjs --selftest   # ночной учёт и потолок на заглушках — без браузера и денег
//   REAL_STYLES=современный,лофт   только эти стили и в этом порядке (проба на 1–2 парах, T-20261106-88); комната — `REAL_ROOM`
//   --frames   кадры из браузера (живая 3D-сцена, как у покупателя: `vwCaptureViews`), а не серверный эскиз; не снялись — СТОП без оплаты.
//              Ночь и ручная выкладка идут с ним (`demo-real.sh`, T-20261112-114: эскиз не видит картин, штор и тюля из 3D); в `--dry` не действует
//   DEMO_LOCAL=<папка сборки>   страница и данные витрины — из локальной сборки (`FLAT215_DEMO_OUT`), сервер и реестр — прода: фото
//              новых ракурсов снимаются ДО публикации (demo-22: опубликованная страница их сразу показывает — номер состояния тот же).
//              Так идёт и ночь (T-20261107-34). Строки «пустые пары» и «прежнее фото» в этом режиме не печатаются: они про то, что
//              видит покупатель, — их даёт бесплатная проверка `--dry` по опубликованному после прогрева кадров (`refresh_daily.sh`)
// Годна только НОВАЯ запись реестра (не из прежних id) этого стиля и состояния, с обеими точками, позами камер страницы,
// моделью и версией промпта, которых ждём (EXPECT_MODEL, EXPECT_PROMPT); `shots.json` не чистится — старое остаётся историей.
// Ошибка любого варианта останавливает прогон (деньги не тратятся вслепую); счётчик «снято / не вышло» — в конце.
//
// НОЧЬ (план demo-29, владелец 23.10 «а»): `--night` снимает всех без фото своей расстановки, пока трата ночи не дойдёт до потолка
// (`rules/demo-realistic.json:night_cap_rub`, 200 ₽ — владелец 07.11 TG 356; `--cap-rub` — перекрыть; трата выше `night_warn_rub`
// 100 ₽ — WARN в дайджест). Трата — ФАКТ: прирост счётчика шлюза `total_used`
// (GET /v1/credits, бесплатно) после задания; не пришёл за `bill_wait_s` или ключа нет — задание по оценке `est_rub_per_job`.
// Прерванное («результат неизвестен») считается потраченным. Ошибка — стоп без повторов; улучшение недоступно — 0 ₽ и WARN.
// ИСКЛЮЧЕНИЕ — «СЕРВЕР ОБНОВЛЯЛСЯ» (план photo-before-publish-01, T-20261107-34): задание потеряно выкладкой прода (код страницы
// `lost`/`not_found`) — один повтор того же варианта через 5 мин (`LOST_RETRY_MS`), не стоп ночи; трата первой попытки учтена,
// повтор — в пределах потолка; второй отказ подряд — стоп, как обычная ошибка. Число таких отказов — в лог и строку DIGEST.
// ФОТО ДО ПУБЛИКАЦИИ (тот же план): ночь снимает НОВУЮ сборку до выкладки (`DEMO_LOCAL`, `refresh_daily.sh`), публикация идёт
// всегда; варианты, оставшиеся без фото новой расстановки, на странице показывают прежнее фото (`index.html:realisticPublishedShot`)
// — их число и список — строки `DIGEST:`/`WARN:demo_real:` (`staleLines`).
// Итог — строка `DIGEST:` в утреннюю сводку; сбой — `WARN:demo_real:`. Код выхода 0 у обработанных исходов (шаг — warn, не FAIL).
// ВСЕ КОМНАТЫ, СНАЧАЛА ПУСТЫЕ (план room-photos-07 п.2, T-20261106-88): пары «комната × стиль» без единого фото нейросети (ни своей,
// ни прежней расстановки) — первыми, затем те, у кого фото устарело; потолок ночи прежний, остаток — следующей ночью. `--dry` печатает
// список «снял бы» с ценой по оценке. В конце (и в сухом ходе) — строка `DIGEST:пустые пары комната × стиль` (п.5): пара без кадра
// опубликованного состояния или без фото своей расстановки; есть такие — ещё `WARN:demo_real:` со списком.
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { demoUrl } from "./demo-url.cjs";
import { camOkFrom, pairLabel, regOf, withoutShot } from "./demo-warm.mjs";
import { captureViews, launchLive, openLivePage } from "./lib/live-shoot.mjs";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const NIGHT = process.argv.includes("--night"), DRY = process.argv.includes("--dry");
// --frames в сухом ходе не действует: съёмки нет — 3D не грузим (ночная сухая проверка `demo-real.sh --dry` идёт с тем же --frames)
const GO = process.argv.includes("--go") || (NIGHT && !DRY), ALL = process.argv.includes("--all") || NIGHT, FRAMES = process.argv.includes("--frames") && !DRY;
const fi = process.argv.indexOf("--force"), FORCE = fi >= 0 ? (process.argv[fi + 1] || "all") : "";
const EXPECT_MODEL = process.env.EXPECT_MODEL ?? "improve/openai/gpt-image-2.5-sunburst";
const LOCAL = process.env.DEMO_LOCAL ?? "";
// `REAL_ROOM=bedroom-1` — снимать только эту комнату (T-32/3: пробы спальни из проверочной сборки, не трогая гостиную; как WARM_ROOM прогрева)
const ONLY_ROOM = process.env.REAL_ROOM ?? "";
const ONLY_STYLES = (process.env.REAL_STYLES ?? "").split(",").map((x) => x.trim()).filter(Boolean);
const EXPECT_PROMPT = process.env.EXPECT_PROMPT ?? "improve-v4.5";   // demo-14: + список товаров (ADR-0305); .1 — радиатор под окном (demo-20 Г3); .2 — люстра стиля (Г4); .3 — мягкое (demo-24); .4 — шторы по окну, окно по кадру, картины на стену (T-113); .5 — задание по составу набора (П1.50)
const RULES = new URL("../scout/rules/demo-realistic.json", import.meta.url);
const CREDITS_URL = "https://ai-gateway.vercel.sh/v1/credits";

/** Правила ночи из настройки; `--cap-rub N` перекрывает потолок. Нет файла или поля — громкий отказ, а не тихий дефолт. */
export function nightRules(text, argv = []) {
  const r = JSON.parse(text);
  const ci = argv.indexOf("--cap-rub");
  const out = { cap: Number(ci >= 0 ? argv[ci + 1] : r.night_cap_rub), warn: Number(r.night_warn_rub), est: Number(r.est_rub_per_job), rate: Number(r.usd_rub),
    waitS: Number(r.bill_wait_s ?? 90) };
  for (const [k, v] of Object.entries(out)) if (!(Number.isFinite(v) && v >= 0)) throw new Error(`rules/demo-realistic.json: ${k} = ${v}`);
  if (!out.cap || !out.est || !out.rate) throw new Error("rules/demo-realistic.json: потолок, оценка задания и курс обязаны быть больше нуля");
  return out;
}

/** Есть ли у пары хоть одно фото нейросети в реестре (любой расстановки): нет — пара «пустая», снимаем первой. */
export function hasAnyReal(reg, t) {
  return reg.some((r) => regOf(r, t) && r.quality === "realistic" && (r.shots ?? []).length > 0);
}

/** Очередь съёмки: `styles` (REAL_STYLES) — только они и в их порядке; иначе пары без единого фото первыми, порядок витрины внутри. */
export function orderTodo(todo, reg, styles = []) {
  if (styles.length) return styles.flatMap((st) => todo.filter((t) => t.style === st));
  const bare = todo.filter((t) => !hasAnyReal(reg, t));
  return [...bare, ...todo.filter((t) => !bare.includes(t))];
}

/** Пара для списка: «комната/стиль», а если фото своей точки нет у одного вида из двух (T-20261108-73/3) — и какого. */
export function todoLabel(t) {
  return `${pairLabel(t)}${Array.isArray(t.miss) && t.miss.length === 1 ? ` (вид ${t.miss[0]})` : ""}`;
}

/** Сухой ход: строка на пару «комната/стиль — пусто|устарело — ≈N ₽», в пределах потолка помечена «снял бы». */
export function dryLines(todo, reg, rules) {
  const fit = Math.floor(rules.cap / rules.est);
  return todo.map((t, k) => `  ${k < fit ? "снял бы" : "ждёт   "} ${todoLabel(t)} — ${hasAnyReal(reg, t) ? "фото устарело" : "фото нет совсем"} — ≈${rules.est} ₽`)
    .concat([`  итого за ночь ≈${Math.min(todo.length, fit) * rules.est} ₽ по оценке (потолок ${rules.cap} ₽), ждут следующей ночи ${Math.max(0, todo.length - fit)}`]);
}

/**
 * ПУСТЫЕ ПАРЫ (план room-photos-07 п.5): у каждого варианта каждой комнаты витрины должны быть кадр опубликованного состояния и фото
 * нейросети своей расстановки. `all` — все пары витрины, `noFrame` / `noPhoto` — id пар без кадра / без фото (после съёмки ночи).
 */
export function emptyLines(all, noFrame, noPhoto) {
  const key = (v) => `${v.room || "living"}|${v.id}`;
  const nf = new Set(noFrame.map(key)), np = new Set(noPhoto.map(key));
  const bad = all.filter((v) => nf.has(key(v)) || np.has(key(v)))
    .map((v) => `${pairLabel(v)} (${nf.has(key(v)) && np.has(key(v)) ? "нет кадра и фото" : nf.has(key(v)) ? "нет кадра" : "нет фото"})`);
  const head = `DIGEST:пустые пары комната × стиль: ${bad.length} из ${all.length}`;
  return bad.length ? [`${head} — ${bad.join(", ")}`, `WARN:demo_real: пустые пары комната × стиль — ${bad.length}: ${bad.join(", ")}`] : [head];
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

/** Пауза перед повтором задания, потерянного выкладкой прода («сервер обновлялся»): выкладка с проверкой — 2–4 мин. */
export const LOST_RETRY_MS = 300_000;

/** Отказ «сервер обновлялся»: код страницы (`makePhoto` → `opt.fail(текст, код)`) или — у страницы без кода — её текст. */
export function isLost(r) {
  return !r.ok && (["lost", "not_found"].includes(r.code)
    || /сервер обновлялся|обновлении сервера|server update|сервер кадров недоступен/i.test(r.why ?? ""));
}

/** НОЧНОЙ ЦИКЛ (чистое ядро, deps — заглушки в самопроверке): перед заданием — влезает ли оценка в остаток потолка; после —
 *  факт по приросту счётчика (ждём до `waitS`), не пришёл — оценка. Ошибка или прерванное — стоп, трата учтена.
 *  «Сервер обновлялся» (`isLost`) — один повтор того же варианта через `LOST_RETRY_MS`, отказ — в `lost`; второй подряд — стоп.
 *  deps: shoot(t) → {ok, why, code?}; used() → $|null; sleep(ms). → {done, failed, lost, rub, byEst, stop, left, log[]} */
export async function runNight(todo, deps, rules) {
  const res = { done: 0, failed: 0, lost: 0, rub: 0, byEst: 0, stop: "", left: 0, log: [], ok: [] };
  let last = await deps.used(), again = false;
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
    const retry = !r.ok && !again && isLost(r);
    res.log.push(`  ${pairLabel(t)}: ${r.ok ? "снято" : "НЕ ВЫШЛО — " + r.why}, ${rub.toFixed(1)} ₽${delta === null ? " (оценка)" : ""}`
      + (retry ? ` — сервер обновлялся, повтор через ${LOST_RETRY_MS / 60_000} мин` : ""));
    if (r.ok) { res.done += 1; res.ok.push(t); again = false; }
    else if (retry) { res.lost += 1; again = true; await deps.sleep(LOST_RETRY_MS); k -= 1; }
    else { res.failed += 1; res.stop = "error"; res.why = `${pairLabel(t)}: ${r.why}${again ? " (после повтора)" : ""}`; res.left = todo.length - k - 1; break; }
  }
  if (res.lost) res.log.push(`  отказов «сервер обновлялся» за ночь: ${res.lost} (каждый — один повтор через ${LOST_RETRY_MS / 60_000} мин)`);
  return res;
}

/** Строки итога для лога шага: DIGEST — в утреннюю сводку, WARN — в предупреждения дайджеста. `warn` — порог траты ночи для WARN
 *  (`rules/demo-realistic.json:night_warn_rub`, 100 ₽): выше него — строка WARN, даже если потолок не достигнут. */
export function nightLines(n, todoLen, paid, res, cap, warn = Infinity) {
  if (!todoLen) return ["DIGEST:фото нейросети: все стили с фото своей расстановки — 0 ₽"];
  if (!paid.available) return [`WARN:demo_real: улучшение недоступно (${paid.code ?? "?"}) — без фото своей расстановки ${todoLen}, ничего не снято, 0 ₽`];
  const tail = res.stop === "cap" ? `; потолок — без фото осталось ${res.left}` : res.stop === "error" ? `; остановлено на ошибке, без фото осталось ${res.left}` : "";
  const out = [`DIGEST:фото нейросети: снято ${res.done}, не вышло ${res.failed}, ≈${Math.round(res.rub)} ₽ из ${cap} ₽${res.byEst ? ` (по оценке — ${res.byEst})` : ""}`
    + `${res.lost ? `, отказов «сервер обновлялся» ${res.lost} (повтор через 5 мин)` : ""}${tail}`];
  if (res.stop === "error") out.push(`WARN:demo_real: ${res.why}`);
  if (res.stop === "cap") out.push(`WARN:demo_real: потолок ${cap} ₽ — без фото своей расстановки осталось ${res.left} (досниму следующей ночью)`);
  if (res.rub > warn) out.push(`WARN:demo_real: трата ночи ≈${Math.round(res.rub)} ₽ — выше порога ${warn} ₽ (потолок ${cap} ₽)`);
  return out;
}

/**
 * ПРЕЖНЕЕ ФОТО (план photo-before-publish-01, владелец 07.11 TG 378): сборка выкладывается всегда, а вариант, оставшийся без фото
 * новой расстановки, страница показывает с последним фото нейросети того же варианта из прежних расстановок
 * (`index.html:realisticPublishedShot`); нет и его — вариант на главной не виден. `todo` — пары без фото своей расстановки до съёмки,
 * `shot` — снятые этой ночью. → строка DIGEST и, если прежнее фото кто-то показывает, WARN со списком.
 */
export function staleLines(todo, shot, reg) {
  const key = (v) => `${v.room || "living"}|${v.id}`, got = new Set(shot.map(key));
  const left = todo.filter((t) => !got.has(key(t)));
  const prev = left.filter((t) => hasAnyReal(reg, t));
  const head = `DIGEST:фото новой расстановки нет у ${left.length}: показывают прежнее фото ${prev.length}, без фото (на главной не видны) ${left.length - prev.length}`;
  return prev.length ? [head, `WARN:demo_real: прежнее фото показывают ${prev.length}: ${prev.map(pairLabel).join(", ")}`] : [head];
}

async function main() {
  const rules = NIGHT ? nightRules(readFileSync(RULES, "utf8"), process.argv) : null;
  const paid = await (await fetch(`${BASE}/api/draft/paid`)).json().catch(() => ({ available: false, code: "нет ответа" }));
  const browser = await launchLive(chromium, FRAMES);
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
    // реестр кадров приезжает позже данных — 4 с после готовности
    await openLivePage(page, demoUrl(`${BASE}/demo/?live=${FRAMES ? "force" : "0"}&lang=ru`), { gl: FRAMES, settleMs: 4000 });
    // кому нужно фото: у варианта нет реалистичного снимка его нынешней расстановки (то же правило, что у вкладки «Фото»)
    // все комнаты витрины (onb-12): номер состояния `curStateId` считает страница по комнате открытого варианта (`curRoom`);
    // вариант, чьей комнаты нет в данных (`roomGeoOf` → null), главная не показывает — его не снимаем
    // все пары витрины: `want` — нужно фото; `pub`/`vcams` — опубликованное состояние и точки варианта (проверка кадра, как у прогрева)
    const all = await page.evaluate(`((force, only) => { const c0 = cur, out = [];
      allVariants().forEach((v, i) => { if (typeof roomGeoOf === 'function' && !roomGeoOf(v)) return; if (v.mine || v.cid) return; pickVariant(i);
        // --force <стиль> — только он; --force all — все; без --force — у кого хоть у одного вида нет фото своей расстановки и своей
        // точки (vwRealMissing, T-20261108-73/3: фото не своей точки — тот же повод; прежде — только «нет ни у одного вида»)
        const miss = typeof vwRealMissing === 'function' ? vwRealMissing(vwRealShots(), cams || loadCams()) : (vwRealShots().length ? [] : ['все']);
        const want = force ? (force === "all" || force === v.style) : miss.length > 0;
        const room = typeof roomIdOf === 'function' ? roomIdOf(v) : 'living';
        if (!only || room === only) out.push({ i, id: v.id, room, style: v.style, stateId: curStateId(), want, miss,
          pub: typeof pubStateOf === 'function' ? pubStateOf(v) : curStateId(), vcams: v.cams || null,
          cams: (cams || loadCams()).map((c) => [c.name, Math.round(c.x), Math.round(c.y), Math.round(c.rot || 0)].join(":")).join("|") }); });
      pickVariant(c0); return out; })(${JSON.stringify(NIGHT ? "" : FORCE)}, ${JSON.stringify(ONLY_ROOM)})`);
    const reg0 = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
    const before = new Set(reg0.map((r) => r.id));
    const todo = orderTodo(all.filter((t) => t.want), reg0, ONLY_STYLES);
    // кадр опубликованного состояния — предикатом точки самой страницы (как `demo-warm.mjs`); нет его на странице — только по состоянию
    const camSrc = await page.evaluate("typeof shotCamOk === 'function' && typeof camAng === 'function' ? 'const camAng=' + camAng.toString() + ';const CAM_ID_TOL=' + JSON.stringify(CAM_ID_TOL) + (typeof POSE_VER === 'number' ? ';const POSE_VER=' + POSE_VER : '') + ';' + shotCamOk.toString() : ''");
    const camOk = camSrc ? camOkFrom(camSrc) : () => true;
    const noFrame = withoutShot(all.map((t) => ({ ...t, stateId: t.pub, cams: t.vcams })), reg0, camOk);
    const empty = (shot = []) => emptyLines(all, noFrame, all.filter((t) => t.want && !shot.some((x) => x.id === t.id && x.room === t.room)));
    console.log(`фото нейросети: ${FORCE && !NIGHT ? `переснять (--force ${FORCE})` : "без фото своей расстановки"} — ${todo.length}${todo.length ? ": " + todo.map(todoLabel).join(", ") : ""}`
      + `${ONLY_STYLES.length ? ` (только ${ONLY_STYLES.join(", ")})` : ""}`);
    console.log(`улучшение сейчас: ${paid.available ? "доступно" : "НЕДОСТУПНО (" + (paid.code ?? "?") + ")"}`);
    if (NIGHT) {
      const used = await gwUsed();
      console.log(`ночь: потолок ${rules.cap} ₽, оценка задания ${rules.est} ₽ — влезает до ${Math.floor(rules.cap / rules.est)} заданий; счётчик шлюза: ${used === null ? "не читается — трата по оценке" : "читается"}`);
      if (DRY || !todo.length || !paid.available) {
        if (DRY) {
          console.log(`сухой прогон ночи — ничего не снято, 0 ₽ (снял бы ${Math.min(todo.length, Math.floor(rules.cap / rules.est))}):`);
          for (const l of dryLines(todo, reg0, rules)) console.log(l);
        } else for (const l of nightLines(0, todo.length, paid, null, rules.cap, rules.warn)) console.log(l);
        if (!LOCAL) for (const l of [...empty(), ...(todo.length ? staleLines(todo, [], reg0) : [])]) console.log(l);
        return;
      }
      const res = await runNight(todo, { shoot: (t) => shootOne(page, t, before), used: gwUsed, sleep: (ms) => new Promise((ok) => setTimeout(ok, ms)) }, rules);
      for (const l of res.log) console.log(l);
      for (const l of nightLines(0, todo.length, paid, res, rules.cap, rules.warn)) console.log(l);
      if (!LOCAL) for (const l of [...empty(res.ok), ...staleLines(todo, res.ok, reg0)]) console.log(l);
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

/** Одно платное задание «realistic» для варианта `t` и проверка по реестру сервера. → {ok, why, sec, urls}
 *  `frames` — кадры из браузера (по умолчанию флаг `--frames`; самопроверка передаёт явно) */
async function shootOne(page, t, before, frames = FRAMES) {
  const t0 = Date.now();
  // кадры — общим модулем с автофото тура (`lib/live-shoot.mjs:pageCapture`: сцена ЭТОЙ комнаты, кадры загружены на сервер);
  // не снялись — платный вызов не делаем
  const cap = frames ? await captureViews(page, t.i) : null;
  const res = frames && !cap?.ok ? { error: "кадры из браузера не сняты — платный вызов не делаю" } : await page.evaluate(async ([i, frames]) => {
    pickVariant(i);
    const c = frames ? globalThis.__liveCap : null;
    const extra = c ? { views: c.views, clay: c.clay, sheet: c.sheet } : {};
    // код отказа (`lost`/`not_found` — «сервер обновлялся») страница отдаёт вторым аргументом (T-20261107-34) — для повтора ночью
    return await new Promise((ok) => makePhoto("realistic", "", "", { bg: true, extra, progress: () => {}, fail: (m, code) => ok({ error: String(m), code: code || "" }),
      done: (n0) => ok({ n: shots.length - n0, frames: (shots[n0] || {}).timing?.frames }) }));
  }, [t.i, frames]);
  if (frames && !res.error && res.frames !== "browser") res.error = `снято не из кадров браузера (${res.frames ?? "?"})`;
  // проверка по реестру сервера, а не по странице: запись этого варианта (комната и номер — `regOf`, как у прогрева и страницы)
  // с номером его состояния и обеими точками
  const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
  const sig = (r) => (r.cams ?? []).map((c) => [c.name, Math.round(c.x), Math.round(c.y), Math.round(c.rot || 0)].join(":")).join("|");
  const rec = reg.find((r) => !before.has(r.id) && regOf(r, t) && r.quality === "realistic" && r.stateId === t.stateId);
  const why = !rec ? "в реестре нет новой записи с номером состояния"
    : rec.model !== EXPECT_MODEL ? `модель ${rec.model}, ждали ${EXPECT_MODEL}`
    : rec.prompt_version !== EXPECT_PROMPT ? `промпт ${rec.prompt_version ?? "—"}, ждали ${EXPECT_PROMPT}`
    : sig(rec) !== t.cams ? `позы камер ${sig(rec)} ≠ страницы ${t.cams}` : "";
  const sec = Math.round((Date.now() - t0) / 1000);
  const ok = !res.error && rec && !why && (rec.shots ?? []).length >= 2;
  return { ok: !!ok, why: res.error ?? (why || "меньше двух кадров"), code: res.code ?? "", sec, urls: (rec?.shots ?? []).map((s) => s.url).join(" , ") };
}

async function selftest() {
  const res = [];
  const check = (ok, msg, got) => { res.push(ok); console.log(ok ? `OK   ${msg}` : `FAIL ${msg}: ${JSON.stringify(got)}`); };
  const rules = nightRules(readFileSync(RULES, "utf8"));
  check(rules.cap === 200 && rules.warn === 100 && rules.est > 0 && rules.rate > 0,
    "настройка: потолок 200 ₽ (владелец 07.11 TG 356), WARN выше 100 ₽, оценка и курс заданы", rules);
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
  // 7а) «СЕРВЕР ОБНОВЛЯЛСЯ» (T-20261107-34): один повтор того же варианта через 5 мин, ночь идёт дальше; второй отказ подряд — стоп
  const lostR = { ok: false, why: "Улучшение прервалось: сервер обновлялся. Результат неизвестен", code: "lost" };
  let naps = []; const napLog = async (ms) => { naps.push(ms); };
  let tries = {}; shot = [];
  r = await runNight(todo.slice(0, 3), { shoot: async (t) => { tries[t.style] = (tries[t.style] ?? 0) + 1; shot.push(t.style);
    return t.i === 1 && tries[t.style] === 1 ? lostR : { ok: true }; }, used: async () => null, sleep: napLog }, { ...R, cap: 200 });
  check(r.done === 3 && r.failed === 0 && r.lost === 1 && !r.stop && shot.join(",") === "лофт,сканди,сканди,джапанди" && naps.includes(LOST_RETRY_MS)
    && r.rub === 40 && r.log.some((l) => l.includes("сервер обновлялся, повтор через 5 мин")) && r.log.at(-1).includes("отказов «сервер обновлялся» за ночь: 1"),
    "сервер обновлялся — повтор того же варианта через 5 мин, трата обеих попыток учтена, ночь идёт дальше, счётчик отказов в логе", { r, shot, naps });
  check(nightLines(0, 3, { available: true }, r, 200)[0].includes("отказов «сервер обновлялся» 1"), "строка DIGEST — с числом отказов «сервер обновлялся»", null);
  naps = []; shot = [];
  r = await runNight(todo.slice(0, 3), { shoot: async (t) => { shot.push(t.style); return t.i === 1 ? lostR : { ok: true }; }, used: async () => null, sleep: napLog }, { ...R, cap: 200 });
  check(r.done === 1 && r.failed === 1 && r.lost === 1 && r.stop === "error" && shot.join(",") === "лофт,сканди,сканди" && r.left === 1 && /после повтора/.test(r.why),
    "второй отказ «сервер обновлялся» подряд — стоп ночи (повтор один)", { r, shot });
  r = await runNight(todo.slice(0, 2), { shoot: async (t) => (t.i === 0 ? { ok: false, why: "Задание прервалось при обновлении сервера — нажмите «Повторить»." } : { ok: true }),
    used: async () => null, sleep: nap }, { ...R, cap: 200 });
  check(r.lost === 1 && r.failed === 1 && r.stop === "error", "страница без кода — отказ узнаётся по тексту «при обновлении сервера»", r);
  r = await runNight(todo.slice(0, 2), { shoot: async () => ({ ok: false, why: "в реестре нет новой записи" }), used: async () => null, sleep: nap }, { ...R, cap: 200 });
  check(r.lost === 0 && r.failed === 1 && r.stop === "error", "иная ошибка — стоп без повтора, как прежде", r);
  shot = [];
  r = await runNight(todo.slice(0, 3), { shoot: async (t) => { shot.push(t.style); return lostR; }, used: async () => null, sleep: nap }, { ...R, cap: 15 });
  check(r.lost === 1 && r.stop === "cap" && shot.length === 1 && r.rub === 10, "повтор — в пределах потолка: не влезает — стоп по потолку, без повторной оплаты", { r, shot });
  // 7в) WARN по трате ночи выше night_warn_rub (100 ₽), потолок 200
  const big = { done: 12, failed: 0, lost: 0, rub: 120, byEst: 12, stop: "", left: 0 }, small = { ...big, done: 9, rub: 90 };
  check(nightLines(0, 12, { available: true }, big, 200, 100).includes("WARN:demo_real: трата ночи ≈120 ₽ — выше порога 100 ₽ (потолок 200 ₽)")
    && !nightLines(0, 9, { available: true }, small, 200, 100).some((l) => l.includes("трата ночи")),
    "трата ночи выше 100 ₽ — WARN в дайджест; 90 ₽ — без него", nightLines(0, 12, { available: true }, big, 200, 100));
  // 7б) ВСЕ КОМНАТЫ, СНАЧАЛА ПУСТЫЕ (room-photos-07 п.2): пары без единого фото — первыми; REAL_STYLES — только они, их порядок
  const P = [{ id: "s1", room: "living", style: "сканди" }, { id: "s2", room: "living", style: "современный" }, { id: "b1", room: "bedroom-1", style: "сканди" },
    { id: "b2", room: "bedroom-1", style: "лофт" }];
  const regP = [{ room_id: "living", style: "сканди", quality: "realistic", shots: [{}] }, { room_id: "bedroom-1", variant_id: "b2", quality: "draft", shots: [{}] }];
  let ord = orderTodo(P, regP).map((t) => t.id).join(",");
  check(ord === "s2,b1,b2,s1", "очередь: пары без единого фото нейросети первыми (черновик не в счёт), устаревшее — после", ord);
  ord = orderTodo(P, regP, ["лофт", "современный"]).map((t) => t.id).join(",");
  check(ord === "b2,s2", "REAL_STYLES: только эти стили и в их порядке", ord);
  const dl = dryLines(orderTodo(P, regP), regP, { cap: 20, est: 10 });
  check(dl[0] === "  снял бы современный — фото нет совсем — ≈10 ₽" && dl[1] === "  снял бы bedroom-1/сканди — фото нет совсем — ≈10 ₽"
    && dl[2].startsWith("  ждёт    bedroom-1/лофт") && dl[3].startsWith("  ждёт    сканди — фото устарело")
    && dl[4] === "  итого за ночь ≈20 ₽ по оценке (потолок 20 ₽), ждут следующей ночи 2", "--dry: список «комната/стиль» с ценой и пометкой «снял бы» в пределах потолка", dl);
  const dm = dryLines([{ ...P[0], miss: ["C2"] }, { ...P[1], miss: ["C1", "C2"] }], regP, { cap: 20, est: 10 });
  check(dm[0].includes(" (вид C2) — ") && !dm[1].includes("(вид"), "--dry: фото своей точки нет у одного вида из двух — в строке пары назван вид (T-73/3)", dm);
  let el = emptyLines(P, [P[2]], [P[1], P[2]]);
  check(el[0] === "DIGEST:пустые пары комната × стиль: 2 из 4 — современный (нет фото), bedroom-1/сканди (нет кадра и фото)"
    && el[1].startsWith("WARN:demo_real: пустые пары комната × стиль — 2:"), "пустые пары: строка дайджеста и WARN со списком", el);
  el = emptyLines(P, [], []);
  check(el.length === 1 && el[0] === "DIGEST:пустые пары комната × стиль: 0 из 4", "пустых пар нет — одна строка DIGEST, без WARN", el);
  check(emptyLines(P, [{ id: "b1", room: "living" }], [])[0].endsWith("0 из 4"), "пара — по комнате и номеру: чужая комната не засчитывается", null);
  // ПРЕЖНЕЕ ФОТО (T-20261107-34): s1 (гостиная, сканди) — есть фото прежней расстановки; s2, b1 — нет никакого; b1 снят этой ночью
  let sl = staleLines(P.slice(0, 3), [P[2]], regP);
  check(sl[0] === "DIGEST:фото новой расстановки нет у 2: показывают прежнее фото 1, без фото (на главной не видны) 1"
    && sl[1] === "WARN:demo_real: прежнее фото показывают 1: сканди", "не досняли — строка, сколько вариантов показывают прежнее фото, и WARN со списком", sl);
  sl = staleLines(P.slice(1, 3), [], regP);
  check(sl.length === 1 && sl[0].endsWith("показывают прежнее фото 0, без фото (на главной не видны) 2"), "прежнего фото нет ни у кого — без WARN о прежнем", sl);
  m = meter(0.06);
  r = await runNight(P, { shoot: async () => { m.bill(); return { ok: true }; }, used: m.used, sleep: nap }, R);
  check(r.ok.map((t) => t.id).join(",") === "s1,s2,b1,b2" && r.log[2].startsWith("  bedroom-1/сканди: снято"), "ночь: снятые пары — в итог (для пустых пар), подпись «комната/стиль»", r.log);
  // 8) ВИТРИНА НОЧЬЮ (photo-before-publish-01, T-20261107-34): сборка → ворота → платная досъёмка на ЛОКАЛЬНОЙ сборке → публикация
  // ВСЕГДА (фото её не держит, TG 378) → прогрев → бесплатная проверка по опубликованному каждую ночь. Ветка — из самого refresh_daily.sh
  const sh = readFileSync(new URL("../scout/refresh_daily.sh", import.meta.url), "utf8");
  const bash = ({ off = 0, fail = "", undef = "" } = {}) => {
    // запись в лог ночи — в вывод (сокет node не открыть заново как /dev/stdout). `paid_step` — настоящий из refresh_daily.sh (он и
    // решает про openai.off), `step` — заглушка: печатает команду, шаг `fail` роняет
    const a = sh.indexOf('if [ -n "$rooms_undef" ]; then'), b = sh.indexOf("# скорость фото нейросети за сутки");
    if (a < 0 || b < a) throw new Error("в refresh_daily.sh нет блока витрины (rooms_undef … скорость фото)");
    const paidDef = (/^paid_step\(\) .*$/m.exec(sh) || [""])[0];
    if (!paidDef) throw new Error("в refresh_daily.sh нет paid_step()");
    return import("node:child_process").then(({ spawnSync }) => spawnSync("bash", ["-c",
      `set -u; declare -A RES; rooms_undef=${JSON.stringify(undef)}; OPENAI_OFF=${off}; PY=py; HOME=/h; unset FLAT215_DEMO_OUT
step(){ echo "STEP $*"; if [ "$1" = ${JSON.stringify(fail)} ]; then RES[$1]=FAIL; return 1; fi; RES[$1]=ok; }
${paidDef.replaceAll('>> "$LOG"', "")}\n${sh.slice(a, b).replaceAll('>> "$LOG"', "")}\necho "RES=\${RES[demo_real]:-}"`],
    { encoding: "utf8" }).stdout);
  };
  const order = (out) => [...out.matchAll(/^STEP (\S+)/gm)].map((m) => m[1]).join(" ");
  const okRun = await bash(), rtRun = await bash({ fail: "demo_rt" }), offRun = await bash({ off: 1 }), realFail = await bash({ fail: "demo_real" }),
    undefRun = await bash({ undef: "bedroom " });
  check(order(okRun) === "flat215_demo page_check trial_images demo_rt demo_real flat215_publish tour_reissue scene_artifacts demo_warm demo_real_check"
    && /STEP demo_real env DEMO_LOCAL=\/h\/scout-scenes\/flat215-demo bash \.\.\/ops\/demo-real\.sh\n/.test(okRun)
    && /STEP flat215_publish env PUB_PHOTOS_DONE=1 PUB_REISSUE=0 bash publish_demo\.sh\n/.test(okRun)
    && /STEP tour_reissue env TOUR_REISSUE_NIGHT=1 bash \.\.\/ops\/tour-reissue\.sh --bg --why ночь\n/.test(okRun)
    && /STEP demo_real_check bash \.\.\/ops\/demo-real\.sh --dry\n/.test(okRun),
    "ночь: досъёмка фото на НОВОЙ сборке (DEMO_LOCAL) до публикации, публикация с отметкой «фото сняты» без своего хука туров, перевыпуск туров фоном сразу после (T-92), сухая проверка — после прогрева", okRun);
  check(order(realFail) === order(okRun), "досъёмка упала — публикация всё равно идёт (держим только фото, не сборку)", realFail);
  check(order(rtRun) === "flat215_demo page_check trial_images demo_rt scene_artifacts demo_warm demo_real_check" && /DIGEST:фото нейросети: пропущено — демо не опубликовано \(ворота demo_rt\)/.test(rtRun),
    "ворота demo_rt не прошли — ни досъёмки, ни публикации, ни перевыпуска туров, строка DIGEST; сухая проверка идёт", rtRun);
  check(order(offRun) === "flat215_demo page_check trial_images demo_rt flat215_publish tour_reissue scene_artifacts demo_warm demo_real_check" && /openai\.off: платный шаг «demo_real» пропущен/.test(offRun)
    && /RES=skipped/.test(offRun) && /DIGEST:фото нейросети: пропущено — платные шаги выключены \(openai\.off\)/.test(offRun),
    "openai.off — платная досъёмка пропущена со строкой DIGEST, публикация, перевыпуск туров и одна сухая проверка идут", offRun);
  check(order(undefRun) === "scene_artifacts demo_warm demo_real_check" && /RES=\n/.test(undefRun + "\n"),
    "состояние банка комнат не определено — ни сборки, ни досъёмки, ни публикации, ни перевыпуска туров; сухая проверка по опубликованному идёт", undefRun);
  const wrap = readFileSync(new URL("./demo-real.sh", import.meta.url), "utf8");
  check(/demo-realistic\.mjs --night --frames "\$@"/.test(wrap),
    "demo-real.sh: ночь и ручная выкладка — с кадрами из браузера (--frames, T-20261112-114), аргументы (--dry) — дальше в скрипт", null);
  // 8а) КАДРЫ НЕ СНЯЛИСЬ — СТОП БЕЗ ОПЛАТЫ (T-20261112-114): `vwCaptureViews` вернул null (3D нет, кадр не загрузился) — платный
  // `makePhoto` не зовётся, задание — ошибка, ночь встаёт. Функции страницы — заглушки в этом процессе, реестр сервера — пустой
  const g = globalThis, fetch0 = g.fetch;
  let paidCalls = 0, paidExtra = null;
  const pageStub = (cap) => Object.assign(g, { pickVariant: () => {}, openLiveWindow: () => {}, VW: { mode: "walk" }, vwMode: () => {},
    LIVE: { scene: {}, state: "ready" }, vwCaptureViews: async () => cap, shots: [{ timing: { frames: "browser" } }],
    allVariants: () => [{ id: "v0" }], cams: null,
    makePhoto: (q, a, b, opt) => { paidCalls += 1; paidExtra = opt.extra; opt.done(0); } });
  const fakePage = { evaluate: (fn, arg) => fn(arg) };
  g.fetch = async () => ({ json: async () => [] });
  try {
    pageStub(null);
    const sf = await shootOne(fakePage, { i: 0, style: "лофт", cams: "" }, new Set(), true);
    check(!sf.ok && paidCalls === 0 && sf.why === "кадры из браузера не сняты — платный вызов не делаю",
      "--frames: кадры не снялись — платный вызов не делается, задание — ошибка", { sf, paidCalls });
    r = await runNight(todo.slice(0, 3), { shoot: (t) => shootOne(fakePage, t, new Set(), true), used: async () => null, sleep: nap }, { ...R, cap: 200 });
    check(paidCalls === 0 && r.done === 0 && r.failed === 1 && r.stop === "error" && r.left === 2,
      "--frames: ночь встаёт на первом варианте без кадров, платных вызовов 0, остальные не тронуты", { r, paidCalls });
    pageStub({ views: [{ camera: "C1", id: "a" }, { camera: "C2", id: "b" }], clay: "c", sheet: "landscape" });
    await shootOne(fakePage, { i: 0, style: "лофт", cams: "" }, new Set(), true);
    check(paidCalls === 1 && paidExtra?.views?.length === 2, "--frames: кадры снялись — задание уходит с ними (views C1, C2)", { paidCalls, paidExtra });
  } finally { g.fetch = fetch0; }
  // 9) очередь тяжёлых прогонов (T-20261107-03): вне слота — перезапуск себя под heavy-slot с теми же аргументами; в слоте — нет
  const sNight = underSlot({}, ["--night", "--cap-rub", "10"], "/n", "/s.mjs"), sGo = underSlot({}, ["--go"], "/n", "/s.mjs");
  check(sNight && sNight[0].endsWith("/heavy-slot.sh") && sNight[1].join(" ") === "demo-real-night --min-gb 2 --cores 2 --timeout 7200 -- /n /s.mjs --night --cap-rub 10"
    && sGo && sGo[1].join(" ") === "demo-real --min-gb 2 --cores 2 --timeout 3600 -- /n /s.mjs --go"
    && underSlot({ HEAVY_SLOT_HELD: "123" }, ["--go"], "/n", "/s.mjs") === null && underSlot({ REAL_NO_SLOT: "1" }, [], "/n", "/s.mjs") === null
    && underSlot({ REAL_SLOT_GB: "3" }, [], "/n", "/s.mjs")[1][2] === "3",
    "вне очереди — себя под heavy-slot (ночь ждёт 2 ч, ручной — час), аргументы те же; в слоте (HEAVY_SLOT_HELD) и REAL_NO_SLOT=1 — без", { sNight, sGo });
  const sFr = underSlot({}, ["--night", "--frames"], "/n", "/s.mjs"), sFrDry = underSlot({}, ["--night", "--frames", "--dry"], "/n", "/s.mjs");
  const sGoFr = underSlot({}, ["--go", "--frames"], "/n", "/s.mjs");
  check(sFr[1].join(" ") === "demo-real-night --min-gb 3 --cores 6 --prio 1 --timeout 7200 -- /n /s.mjs --night --frames"
    && sFrDry[1].join(" ") === "demo-real-night --min-gb 2 --cores 2 --timeout 7200 -- /n /s.mjs --night --frames --dry"
    && sGoFr[1].join(" ") === "demo-real --min-gb 3 --cores 6 --timeout 3600 -- /n /s.mjs --go --frames",
    "очередь честно: ночь с кадрами — 6 ядер, 3 ГБ, приоритет 1; сухой ход — 2 ядра, 2 ГБ, без приоритета; ручной --go с кадрами — без приоритета (T-114/2)",
    { sFr, sFrDry, sGoFr });
  const outer = Number((/timeout (\d+) node tools\/ops\/demo-realistic\.mjs --night/.exec(wrap) || [])[1] || 0);
  check(outer >= NIGHT_WAIT_S + 3600, "demo-real.sh: внешний timeout ≥ ожидание очереди ночью + час съёмки (иначе он оборвал бы ожидание)", { outer });
  const miss3 = slotMissedLine("фото нейросети: без фото своей расстановки — 3: bedroom-2/лофт …\nDIGEST:…"), missQ = slotMissedLine("");
  check(miss3 === "WARN:demo_real: очередь тяжёлых прогонов DEV занята дольше 120 мин — фото нейросети этой ночью не сняты, вариантов без фото: 3"
    && missQ.endsWith("вариантов без фото: ? (сухой проход не ответил)"),
    "ночь не дождалась очереди — WARN с числом вариантов без фото из сухого прохода; нет ответа — «?»", { miss3, missQ });
  // T-20261107-20: строки пустых пар в такую ночь — из сухого прохода; не ответил — «не посчитаны», сводка о парах не молчит
  const dryOk = `фото нейросети: без фото своей расстановки — 1: лофт\n${emptyLines(P, [], [P[1]]).join("\n")}\n`;
  const se0 = slotEmptyLines(dryOk), se1 = slotEmptyLines(""), se2 = slotEmptyLines(undefined);
  check(se0.length === 0 && dryOk.includes("DIGEST:пустые пары комната × стиль: 1 из 4") && se1.length === 1
    && se1[0].startsWith("DIGEST:!пустые пары комната × стиль: не посчитаны") && se2.length === 1,
    "очередь занята: строки «пустые пары» сухого прохода идут в журнал как есть; нет их — одна строка «не посчитаны»", { se0, se1 });
  process.exit(res.every(Boolean) ? 0 : 1);
}

/** ТЯЖЁЛОЕ — ПОД ОБЩЕЙ ОЧЕРЕДЬЮ DEV (T-20261107-03). Съёмка держит браузер и нагружает DEV-рендер (draft_service ~2,5 ГБ); 07.11
 * в 05:02 она шла вне очереди рядом с прогоном, превысившим свой порог, earlyoom снял DEV-рендер, а задание ушло на запасной рендер
 * прода. Теперь и ночной шаг (`demo-real.sh`), и ручной запуск сами встают в `tools/ops/heavy-slot.sh`: вне слота → [команда, аргументы]
 * перезапуска себя с теми же аргументами; уже в слоте (HEAVY_SLOT_HELD — его ставит держатель) или REAL_NO_SLOT=1 → null.
 * Порог памяти — REAL_SLOT_GB (2 ГБ; дальше heavy-slot уточняет по замерам). Ожидание — ночью 2 ч (владелец: голых обложек не бывает,
 * перенос на сутки = голая обложка у сменивших состояние; за ночь очередь освобождается), вручную час; внешний `timeout` в
 * `demo-real.sh` — больше ожидания и съёмки (NIGHT_WAIT_S + 3600). */
export const NIGHT_WAIT_S = 7200;
// ЯДРА И ПАМЯТЬ — ЧЕСТНО (T-20261112-114): с кадрами (`--frames`, не сухой ход) браузер рисует 3D процессором — 6 ядер, 3 ГБ (правило
// очереди для Playwright с 3D); без 3D (сухой ход, серверный эскиз) — 2 ядра, 2 ГБ: прежде очередь выводила 6 ядер по признаку
// «подключает playwright», и сухая проверка на 7 с ждала свободных 6 ядер до часа (12.11: 3522 с)
// ПРИОРИТЕТ НОЧИ С КАДРАМИ (T-20261112-114/2, директор): заявку на 6 ядер вечером обгоняют мелкие задачи (проба 12.11 стояла 40+ мин при
// 14,5 из 15 занятых) — за 2 ч ожидания ночь осталась бы без фото. `--prio 1` (класс загрузки тура): в очереди — впереди обычных,
// бюджет ядер не ждёт, может взять резерв пробы; память и «Обустроить» (класс 2) — как прежде. Сухой ход и ручной `--go` — без приоритета
export function underSlot(env, argv, node, self) {
  if (env.HEAVY_SLOT_HELD || env.REAL_NO_SLOT === "1") return null;
  const night = argv.includes("--night"), frames = argv.includes("--frames") && !argv.includes("--dry");
  return [fileURLToPath(new URL("./heavy-slot.sh", import.meta.url)),
    [night ? "demo-real-night" : "demo-real", "--min-gb", env.REAL_SLOT_GB ?? (frames ? "3" : "2"), "--cores", frames ? "6" : "2",
      ...(night && frames ? ["--prio", "1"] : []),
      "--timeout", env.REAL_SLOT_WAIT_S ?? String(night ? NIGHT_WAIT_S : 3600), "--", node, self, ...argv]];
}

/** Ночь не дождалась очереди: строка WARN с числом вариантов без фото своей расстановки — из вывода сухого прохода (`--dry`). */
export function slotMissedLine(dryOut) {
  const m = /без фото своей расстановки — (\d+)/.exec(dryOut);
  return `WARN:demo_real: очередь тяжёлых прогонов DEV занята дольше ${NIGHT_WAIT_S / 60} мин — фото нейросети этой ночью не сняты, вариантов без фото: ${m ? m[1] : "? (сухой проход не ответил)"}`;
}

/**
 * Строки пустых пар в ночь, не дождавшуюся очереди (T-20261107-20): сухой проход сам печатает `emptyLines` — их и отдаём (вывод уже
 * в журнале), а не ответил он или упал раньше счёта — одна строка «не посчитаны», чтобы утренняя сводка не молчала о парах.
 */
export function slotEmptyLines(dryOut) {
  return /^DIGEST:пустые пары комната × стиль:/m.test(dryOut ?? "") ? []
    : ["DIGEST:!пустые пары комната × стиль: не посчитаны — сухой проход не ответил (очередь тяжёлых прогонов занята, фото не сняты)"];
}

if (process.argv.includes("--selftest")) await selftest();
else if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const slot = underSlot(process.env, process.argv.slice(2), process.execPath, process.argv[1]);
  if (!slot) await main();
  else {
    const { spawnSync } = await import("node:child_process");
    const r = spawnSync("bash", [slot[0], ...slot[1]], { stdio: "inherit" });
    if (r.status === 124 && NIGHT) {
      // ночь не дождалась очереди за 2 ч (обработанный исход: шаг warn, не FAIL). Вариант, сменивший состояние, до следующей ночи
      // остаётся без фото своей расстановки — утром должно быть видно, сколько таких: бесплатный сухой проход (браузер, без съёмки)
      const d = spawnSync(process.execPath, [process.argv[1], ...process.argv.slice(2).filter((a) => a !== "--dry"), "--dry"],
        { encoding: "utf8", env: { ...process.env, REAL_NO_SLOT: "1" }, timeout: 600_000 });
      process.stdout.write(d.stdout ?? "");
      console.log(slotMissedLine(d.stdout ?? ""));
      for (const l of slotEmptyLines(d.stdout)) console.log(l);
      process.exit(0);
    }
    process.exit(r.status ?? 1);
  }
}
