// ПРОГРЕВ КАДРОВ ДЕМО (план b2b-08 п.4). Карточки стилей показывают кадр из серверного реестра (`/test/share/shots.json`),
// а кадр появлялся, только когда кто-то нажимал «снять»: после ночной пересборки витрины стиль мог остаться без кадра
// или с кадром вчерашнего набора. Шаг ночного прогона после публикации: открыть демо на проде и для каждого стиля без
// кадра НОВЕЕ данных витрины снять черновой кадр — функциями самой страницы (`pickVariant`, `makePhoto`), без копии
// логики расстановки. Черновой кадр — рендер на сервере, денег не стоит. Предел — WARM_MAX кадров за прогон.
// ВАРИАНТ БЕЗ КАДРА — ОШИБКА ШАГА (demo-20 Б2, владелец 22.10: «вариантов без фото быть не должно»): главная прячет вариант без
// кадра опубликованного состояния (`index.html:pubShot`), поэтому после прогрева каждый вариант сверяется с реестром ещё раз; кадр
// не снялся или вариантов без кадра осталось больше WARM_MAX — код 1, шаг FAIL в дайджесте `refresh_daily`.
//   node tools/ops/demo-warm.mjs            # прогрев прода
// ТОЧКА СЪЁМКИ — ЧАСТЬ ТОЖДЕСТВА КАДРА (T-20261022-16): номер состояния (`stateIdOf`) ракурс не включает, а главная показывает
// кадр, только если его точка совпадает с нынешней (`index.html:pubShot` → `shotCamOk`). Сверка по одному номеру состояния после
// смены ракурсов (demo-22) считала старые кадры годными, и ночь провал не ловила. Предикат точки — ТОТ ЖЕ код страницы: в прогоне
// он берётся из открытой страницы прода, в селфтесте — из блоков CAMANG/SHOTCAM файла страницы; своей копии формулы здесь нет.
//   DRY=1 node tools/ops/demo-warm.mjs      # только список стилей и итог по реестру, кадры не снимаются
//   node tools/ops/demo-warm.mjs --selftest
// НЕСКОЛЬКО КОМНАТ (onb-12, T-20261105-17): варианты — всех комнат витрины (`room_id`, нет — гостиная), номер состояния — по
// комнате варианта (`pubStateOf` страницы), запись реестра — к варианту по комнате и номеру варианта (`regOf`), предел — по числу комнат.
// КАДР — СВОЙ БРАУЗЕР И СВОЙ СРОК (T-20261107-16): без видеокарты страница после 1–2 кадров вставала (программный WebGL копится в
// одной вкладке), `page.evaluate` не возвращался, и ночь снимала не всё, а то и упиралась в `timeout 1800` обёртки без итога.
// Теперь каждая попытка — новый браузер; срок попытки `WARM_SHOT_SEC` (по умолчанию 180 с, с открытием страницы); не успел или
// кадра нет в реестре — браузер закрывается, ещё одна попытка (`WARM_TRIES`, по умолчанию 2). Общий бюджет `WARM_BUDGET_SEC`
// (1500 с, меньше 1800 обёртки): не хватает на попытку — кадр «не успели», итог печатается всегда. Итог — строкой
// `DIGEST:прогрев кадров: снято X из Y…` в сводку ночи, со временем на кадр. Цикл съёмки — `warmLoop`, проверяется селфтестом.
// СПИСОК КАДРОВ ГЛАВНОЙ (T-20261107-17): реестр полон (120), и ночной черновик того же стиля вытеснял бы фото нейросети, которое
// показывает главная. Прогрев тем же кодом страницы (`rowFits` + `shotCamOk`, как `index.html:pubShot`) выбирает для каждого
// опубликованного варианта последнее годное фото нейросети (нет его — последнюю годную запись) и кладёт их ключи файлом
// `pub-shots.json` рядом с реестром (scp во временный файл + mv, как `refresh_daily.sh:publish_status`) — сразу после разведки и
// после съёмки; сервер кадров при обрезке их не трогает (`draft_guard.registry_trim`). Только главная `/demo/` прода, не DRY, не
// проба, не `WARM_ROOM`; не опубликовалось — ошибка шага. Итог обрезки — строкой `DIGEST:реестр кадров: защищено N, выкинуто M`
// из счётчиков сервера (`shots-trim.json`) минус своя отметка прошлой ночи (`WARM_TRIM_CURSOR`).
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const DRY = !!process.env.DRY;
// ПАПКА ВИТРИНЫ НА САЙТЕ (onb-07, T-20261105-32): по умолчанию главная `/demo/`; проверочная сборка на `/test/<папка>/` прогревается
// тем же путём (`DEMO_PATH=/test/<папка>/`) — кадры идут в общий реестр `/test/share/shots.json` с `room_id` варианта, на главную
// не влияют: у её вариантов другая комната или номер состояния
const PATH = (process.env.DEMO_PATH ?? "/demo/").replace(/\/?$/, "/");
// `WARM_ROOM=bedroom-1` — снимать только эту комнату (проверочная сборка новее данных главной, и без фильтра прогрев переснял бы
// черновики гостиной, у которой фото уже есть); итог «без фото» — тоже по ней
const ONLY = process.env.WARM_ROOM ?? "";
// ПРОБА (`WARM_PROBE=1`, T-20261107-16): те же варианты и тот же путь съёмки, но кадр с `no_registry` — сервер считает его как обычно,
// а в реестр не пишет. Реестр полон (предел 120, `draft_guard.registry_trim`), и лишний черновик вытеснил бы старую запись — так
// замеряем время на кадр без следа на проде. Снимать нечего (все с кадром) — проба берёт все варианты витрины.
const PROBE = !!process.env.WARM_PROBE;
const PROD = "https://remont-lab.online";
const PUB_TARGET = process.env.WARM_PUB_TARGET ?? "root@89.167.127.0:/opt/remlab/test/share/pub-shots.json";
// список кадров главной — только про главную прода (чужой DEMO_BASE — только с явным WARM_PUB_TARGET)
const PUB_ON = PATH === "/demo/" && !DRY && !PROBE && !ONLY && (BASE === PROD || !!process.env.WARM_PUB_TARGET);
const CURSOR = process.env.WARM_TRIM_CURSOR ?? join(homedir(), ".cache", "remlab-warm", "trim-cursor.json");
const PUB_MAX_KEYS = 400;   // тот же предел, что у сервера (`draft_guard.PUB_MAX_KEYS`): больше — сервер файл не примет

/** Ключ записи реестра — как у сервера (`draft_guard.shot_key`): `id`, у старых без него — комната|стиль|время. */
export function shotKey(r) {
  return String(r.id || `${r.room_id || "living"}|${r.style || ""}|${r.ts || 0}`);
}

/**
 * Ключи записей, которые показывает главная: для каждого варианта среди годных записей (`rowFits`) — фото нейросети, нет их —
 * все годные (как `pubShot`); из них последняя, и последняя с каждой точкой съёмки (`pubShot(v, cam)` выбирает по точке).
 */
export function pubKeys(variants, reg, camOk) {
  if (typeof camOk !== "function") throw new Error("pubKeys: нужен предикат точки съёмки (camOk)");
  const keys = new Set();
  for (const v of variants) {
    if (!v.stateId) continue;
    const fit = reg.filter((r) => rowFits(r, v, camOk));
    const real = fit.filter((r) => r.quality === "realistic"), pool = real.length ? real : fit;
    if (!pool.length) continue;
    keys.add(shotKey(pool[pool.length - 1]));
    const camsOf = (r) => (r.shots ?? []).map((sh) => sh.camera || "C1").filter((c) => camOk({ cams: r.cams, camera: c }, v.cams));
    for (const c of new Set(pool.flatMap(camsOf))) keys.add(shotKey(pool.findLast((r) => camsOf(r).includes(c))));
  }
  return [...keys];
}

/** Положить список рядом с реестром целиком: локальный файл → scp во временный → mv (без `:` в цели — копия + rename). */
export function publishPub(keys, { target = PUB_TARGET, dir, now = Date.now() } = {}) {
  if (keys.length > PUB_MAX_KEYS) throw new Error(`ключей ${keys.length} > ${PUB_MAX_KEYS} — сервер такой список не примет`);
  mkdirSync(dir, { recursive: true });
  const f = join(dir, `pub-shots-${process.pid}.json`);
  writeFileSync(f, JSON.stringify({ ts: now, path: "/demo/", keys }));
  if (target.includes(":")) {
    const host = target.slice(0, target.indexOf(":")), path = target.slice(target.indexOf(":") + 1);
    execFileSync("scp", ["-q", f, `${host}:${path}.tmp`], { timeout: 60_000, stdio: ["ignore", "ignore", "pipe"] });
    execFileSync("ssh", [host, `mv -f '${path}.tmp' '${path}'`], { timeout: 30_000, stdio: ["ignore", "ignore", "pipe"] });
  } else {
    copyFileSync(f, `${target}.tmp`);
    renameSync(`${target}.tmp`, target);
  }
  renameSync(f, join(dir, "pub-shots-last.json"));   // последний отправленный — для разбора; не копится
}

/**
 * Строка сводки по обрезке реестра: итоги сервера (`shots-trim.json`, растут монотонно в своём `epoch`) минус отметка прошлой
 * ночи. Другой `epoch` (файл пересоздан) или итоги меньше отметки — счёт с запуска счётчиков. Возвращает строку и новую отметку.
 */
export function trimDigest(stats, cursor) {
  if (!stats || typeof stats !== "object" || !stats.epoch || !Number.isFinite(stats.dropped_total)) {
    return { line: "DIGEST:реестр кадров: счётчиков обрезки нет (сервер кадров до T-17?)", next: cursor ?? null };
  }
  const same = !!cursor && cursor.epoch === stats.epoch && cursor.dropped_total <= stats.dropped_total;
  const m = stats.dropped_total - (same ? cursor.dropped_total : 0);
  const k = (stats.dropped_realistic_total ?? 0) - (same ? (cursor.dropped_realistic_total ?? 0) : 0);
  const over = stats.overflow_current ?? 0;
  const line = `DIGEST:${over ? "!" : ""}реестр кадров: защищено ${stats.protected_current ?? 0}, выкинуто ${m} (фото нейросети ${k})`
    + (same ? "" : cursor ? "; счётчики сервера начаты заново — счёт с их начала" : "; первый замер — счёт с начала счётчиков")
    + (stats.pub_status && stats.pub_status !== "ok" ? `; список кадров главной у сервера: ${stats.pub_status}` : "")
    + (over ? `; ПЕРЕПОЛНЕНИЕ: обязательных кадров на ${over} больше предела` : "");
  return { line, next: { epoch: stats.epoch, dropped_total: stats.dropped_total, dropped_realistic_total: stats.dropped_realistic_total ?? 0 } };
}

/**
 * Временная папка браузера — на диске (T-20261107-16): Playwright кладёт профиль и кэш Chromium в `os.tmpdir()`, а /tmp на DEV —
 * tmpfs с квотой, забитый до 78 %. Там картинки витрины обрывались `ERR_INSUFFICIENT_RESOURCES`, а вкладка падала («Target
 * crashed»); с TMPDIR на диске — ни одного сбоя. Ночь уже даёт TMPDIR (`refresh_daily.sh`), ручной запуск — нет: берём REMLAB_TMP
 * или ~/remlab-scratch/tmp. Заданный TMPDIR не трогаем. Возвращает папку или '' (CI и чужая машина — системная).
 */
export function browserTmp(env, exists = existsSync, home = homedir()) {
  if (env.TMPDIR) return "";
  const d = env.REMLAB_TMP || (exists(join(home, "remlab-scratch")) ? join(home, "remlab-scratch", "tmp") : "");
  return d;
}

/** Предел кадров за прогон: `WARM_MAX` или 5 стилей на каждую комнату витрины, но не меньше прежних 8 (одна гостиная — как было). */
export function warmMax(env, variants) {
  if (env.WARM_MAX) return Number(env.WARM_MAX);
  return Math.max(8, 5 * new Set(variants.map((v) => v.room || "living")).size);
}

/**
 * Запись реестра — кадр этого варианта? Комната записи (без `room_id` — гостиная, весь реестр до onb-12) та же, что у варианта;
 * дальше — как сопоставляет страница (`index.html:loadShots` → `shotVid`): в гостиной по стилю (номер варианта после ночной
 * пересборки меняется, стиль остаётся), в другой комнате — по номеру варианта, записи без номера — по стилю.
 */
export function regOf(r, v) {
  const room = r.room_id || "living";
  if (room !== (v.room || "living")) return false;
  return room === "living" || !r.variant_id ? r.style === v.style : r.variant_id === v.id;
}

/** Предикат точки кадра из исходника страницы: `camAng`, `CAM_ID_TOL` и `shotCamOk(кадр, точки варианта)` → функция. */
export function camOkFrom(src) {
  const f = new Function(`${src}\n;return typeof shotCamOk === "function" ? shotCamOk : null;`)();
  if (!f) throw new Error("demo_warm: в странице нет shotCamOk — сверять точку съёмки нечем");
  return f;
}

/** Тот же предикат из файла страницы — блоки CAMANG и SHOTCAM (селфтест; падает громко, если блоков нет). */
export function camOkFromHtml(html) {
  const cut = (n) => {
    const a = html.indexOf(`// ${n} START`), b = html.indexOf(`// ${n} END`);
    if (a < 0 || b < a) throw new Error(`demo_warm: в странице нет блока ${n}`);
    return html.slice(a, b);
  };
  return camOkFrom(`${cut("CAMANG")}\n${cut("SHOTCAM")}`);
}

/** Запись реестра — кадр варианта: та же комната и вариант, то же состояние, есть снимки, хотя бы один — с нынешней точки варианта. */
export function rowFits(r, v, camOk) {
  return regOf(r, v) && r.stateId === v.stateId && (r.shots ?? []).some((sh) => camOk({ cams: r.cams, camera: sh.camera || "C1" }, v.cams));
}

/**
 * Каким стилям нужен свежий кадр. С demo-02 (разбор Codex 14.10) кадр годится, если снят С ТОГО ЖЕ СОСТОЯНИЯ, что
 * опубликовано (`stateId` страницы), и после публикации данных (новая версия движка/моделей — тоже повод переснять).
 * Старые кадры без номера состояния — по прежнему правилу «новее данных». Чистая функция (селфтест).
 */
export function needWarm(variants, shots, dataTs, poseVer, camOk) {
  if (typeof camOk !== "function") throw new Error("needWarm: нужен предикат точки съёмки (camOk)");
  // поза камеры (demo-02, 14.10): эскиз прежней позы — тоже «нет кадра»; фото нейросети годится при любой позе
  const poseOk = (s) => !poseVer || s.quality === "realistic" || (Number(s.pose) || 1) === poseVer;
  return variants
    .map((v, i) => ({ i: v.i ?? i, id: v.id, room: v.room || "living", style: v.style, stateId: v.stateId, cams: v.cams }))
    .filter((v) => !shots.some((s) => s.vid === v.id && !s.svc && (s.ts ?? 0) >= dataTs
      && (!s.stateId || !v.stateId || s.stateId === v.stateId) && poseOk(s) && camOk(s, v.cams)));
}

/** Обещание или его срок: `{ value }` / `{ error }` / `{ timeout: true }` — цикл съёмки не ждёт зависшую страницу. */
export function withDeadline(p, ms) {
  let tm;
  const late = new Promise((ok) => { tm = setTimeout(() => ok({ timeout: true }), ms); });
  return Promise.race([Promise.resolve(p).then((value) => ({ value }), (e) => ({ error: String(e) })), late])
    .finally(() => clearTimeout(tm));
}

/**
 * ЦИКЛ СЪЁМКИ (T-20261107-16): по кадру за раз, каждая попытка — `shoot(t)` (новый браузер), после неё всегда `reset()` (браузер
 * закрыт). Попытка в сроке `shotMs`; кадр засчитан, только если он есть в реестре (`fresh(t)`) — и после «не успел» тоже: сервер мог
 * досчитать. Не хватает бюджета на попытку — кадр «не успели». Возвращает снятые, не снятые (с причиной), не успевшие и время на кадр.
 */
export async function warmLoop(todo, { shoot, reset, fresh, shotMs, budgetMs, tries = 2, now = Date.now, log = console.log, label = pairLabel }) {
  const t0 = now(), out = { done: [], failed: [], skipped: [], times: [] };
  for (const t of todo) {
    let ok = false, why = "", over = false;
    for (let k = 1; k <= tries && !ok; k += 1) {
      if (now() - t0 + shotMs > budgetMs) { over = true; break; }
      const s0 = now();
      const r = await withDeadline(shoot(t), shotMs);
      await reset();
      const sec = Math.round((now() - s0) / 1000);
      if (await fresh(t, r)) {
        ok = true; out.times.push(sec);
        log(`  ${label(t)}: кадр снят за ${sec} с${k > 1 ? ` (попытка ${k})` : ""}`);
      } else {
        why = r.timeout ? `не успел за ${Math.round(shotMs / 1000)} с` : r.error ? r.error.slice(0, 160) : "кадр не появился в реестре";
        log(`  ${label(t)}: попытка ${k} — ${why}${k < tries ? ", новый браузер, ещё раз" : ""}`);
      }
    }
    if (ok) out.done.push(t);
    else if (over && !why) out.skipped.push(t);
    else out.failed.push({ ...t, why: why || "не успели по общему сроку" });
  }
  return out;
}

/** Строка в сводку ночи: снято / не снято / не успели, время на кадр (медиана и максимум), без фото на главной. */
export function digestLine({ todo = [], done = [], failed = [], skipped = [], times = [], missing = [], variants = [] }) {
  const lab = (l) => l.map(pairLabel).join(", ");
  if (!todo.length) {
    return `DIGEST:прогрев кадров: свежий кадр не нужен — у ${variants.length - missing.length} из ${variants.length} вариантов кадр есть`
      + (missing.length ? `; без фото ${missing.length}: ${lab(missing)}` : "");
  }
  const st = [...times].sort((a, b) => a - b), med = st.length ? st[Math.floor((st.length - 1) / 2)] : 0;
  return `DIGEST:прогрев кадров: снято ${done.length} из ${todo.length}`
    + (failed.length ? `, не снято ${failed.length}: ${lab(failed)}` : "")
    + (skipped.length ? `, не успели ${skipped.length}: ${lab(skipped)}` : "")
    + (st.length ? `; кадр ~${med} с (до ${st[st.length - 1]} с)` : "")
    + (missing.length ? `; без фото на главной ${missing.length}` : "");
}

// номер опубликованного состояния — той же функцией страницы (блок STATEID), что ставит его кадрам
// номер состояния — тем, чем его считает сама страница для кадра (`variantStateOf`, demo-09), а не своей копией формулы
// ОПУБЛИКОВАННОЕ состояние (данные витрины и своя отделка `v.dev`), а не живое: у открытого варианта живое сбивает общая отделка
// комната варианта (onb-12): номер — `pubStateOf` страницы (геометрия `roomOf(v)`); страница до onb-07 его не знает — прежняя
// формула с `D.room`. Вариант, чьей комнаты нет в данных (`roomGeoOf` → null), главная не показывает — и снимать его не в чем.
// `i` — номер в `allVariants()`: по нему страница открывает вариант (`pickVariant`), фильтр номера не сдвигает
const PUB = `allVariants().map((v, i) => ({ v, i })).filter(({ v }) => !v.mine && !v.cid
    && (typeof roomGeoOf !== 'function' || !!roomGeoOf(v))).map(({ v, i }) => ({ i, id: v.id,
  room: typeof roomIdOf === 'function' ? roomIdOf(v) : 'living', style: v.style,
  stateId: typeof pubStateOf === 'function' ? pubStateOf(v)
    : stateIdOf(v.items || [], (v.decor || []).filter(x => (x.sku || {}).name), D.room, v.dev || {}),
  cams: v.cams || null }))`;

/** Открыть витрину и дождаться данных. */
async function openDemo(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  // `?live=0` — без живой 3D-сцены: после съёмки страница открывает окно варианта, и сборка сцены программным рендером
  // (у прогрева нет видеокарты) подвешивала следующий кадр (17.10: прогон снял 1 из 5 и встал по сроку)
  // `quiz=0` — без опроса-знакомства (onb-03): окно опроса поверх витрины не нужно кадру и не держит страницу
  await page.goto(`${BASE}${PATH}?live=0&quiz=0&lang=ru`, { waitUntil: "domcontentloaded" });
  // данные витрины приходят после разметки: пока `D` пуст, `allVariants()` бросает — ждать надо `D`, иначе прогон падал
  // на первом же ожидании и ночью кадров не снимал вовсе (найдено 17.10: у трёх стилей не было кадра своей расстановки)
  await page.waitForFunction("typeof D !== 'undefined' && !!D && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
  return page;
}

async function main() {
  const head = await fetch(`${BASE}${PATH}demo-data.json`, { method: "HEAD" });
  const dataTs = new Date(head.headers.get("last-modified") ?? 0).getTime();
  const SHOT_MS = Number(process.env.WARM_SHOT_SEC ?? 180) * 1000, BUDGET_MS = Number(process.env.WARM_BUDGET_SEC ?? 1500) * 1000;
  const TRIES = Number(process.env.WARM_TRIES ?? 2);
  let missing = [], camOk = null, variants = [], todo = [];
  let res = { done: [], failed: [], skipped: [], times: [] };
  const bt = browserTmp(process.env);
  if (bt) { mkdirSync(bt, { recursive: true }); process.env.TMPDIR = bt; }
  console.log(`временная папка браузера: ${process.env.TMPDIR || "системная"}${PROBE ? "; ПРОБА — кадры в реестр не пишутся" : ""}`);
  // разведка — своим браузером: список вариантов, реестр, предикат точки; съёмка — каждый кадр в новом (T-20261107-16).
  // Вкладка без видеокарты изредка падает и здесь («Target crashed») — до 3 попыток, каждая в новом браузере
  let browser = null;
  for (let k = 1; ; k += 1) {
    browser = await chromium.launch();
    const r = await withDeadline(scout(browser), 150_000);
    await closeQuick(browser);
    browser = null;
    if (r.value) break;
    const why = r.timeout ? "разведка не успела за 150 с" : r.error.split("\n")[0].slice(0, 160);
    if (k >= 3) throw new Error(`demo_warm: витрина не открылась за 3 попытки — ${why}`);
    console.log(`  разведка, попытка ${k} — ${why}; новый браузер, ещё раз`);
  }
  async function scout(b) {
    const page = await openDemo(b);
    await page.waitForTimeout(4000); // реестр кадров приезжает позже данных
    variants = (await page.evaluate(PUB)).filter((v) => !ONLY || v.room === ONLY);
    const MAX = warmMax(process.env, variants);
    const shots = await page.evaluate("(Array.isArray(shots) ? shots : []).map(s => ({ vid: s.vid, svc: !!s.svc, ts: s.ts, stateId: s.stateId || '', quality: s.quality || '', pose: ((s.cams || [])[0] || {}).pose || 1, cams: s.cams || null, camera: s.camera || 'C1' }))");
    const poseVer = await page.evaluate("typeof POSE_VER === 'number' ? POSE_VER : 0");
    // предикат точки — код самой страницы прода (`pubShot` → `shotCamOk`), а не копия. Страница без него (выкладка до demo-22)
    // сама точку не сверяет — сверяем, как она, только по состоянию, и говорим об этом в журнале
    const camSrc = await page.evaluate("typeof shotCamOk === 'function' && typeof camAng === 'function' ? 'const camAng=' + camAng.toString() + ';const CAM_ID_TOL=' + JSON.stringify(CAM_ID_TOL) + ';' + shotCamOk.toString() : ''");
    if (camSrc) camOk = camOkFrom(camSrc);
    else {
      camOk = () => true;
      console.log("WARN:demo_warm: страница прода без сверки точки съёмки (shotCamOk) — сверяю, как она: только по состоянию");
    }
    todo = needWarm(variants, shots, dataTs, poseVer, camOk).slice(0, MAX);
    if (PROBE && !todo.length) todo = variants.slice(0, MAX);
    const rooms = new Set(variants.map((v) => v.room)).size;
    console.log(`прогрев кадров: стилей ${variants.length}${rooms > 1 ? ` в ${rooms} комнатах` : ""}, нужен свежий кадр ${todo.length}${todo.length ? ": " + todo.map(pairLabel).join(", ") : ""}`);
    return true;
  }
  const registry = async () => (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
  let pubFail = 0;
  const pubStep = async (when, reg) => {
    if (!PUB_ON) return;
    try {
      const keys = pubKeys(variants, reg ?? await registry(), camOk);
      publishPub(keys, { dir: dirname(CURSOR) });
      console.log(`список кадров главной (${when}): ${keys.length} → ${PUB_TARGET}`);
    } catch (e) {
      pubFail += 1;
      console.log(`ERROR:demo_warm: список кадров главной не опубликован (${when}) — ${String(e.message || e).split("\n")[0].slice(0, 200)}`);
    }
  };
  // сразу после разведки: витрина уже новая, а реестр защищал бы кадры вчерашней
  await pubStep("после разведки");
  // проба (DRY) ничего не снимает, но итог по нынешнему реестру считает — что ночь сочла бы провалом
  if (!DRY && todo.length) {
    console.log(`съёмка: каждый кадр в новом браузере, срок ${SHOT_MS / 1000} с, попыток ${TRIES}, бюджет ${BUDGET_MS / 1000} с`);
    res = await warmLoop(todo, {
      shotMs: SHOT_MS, budgetMs: BUDGET_MS, tries: TRIES,
      shoot: async (t) => {
        browser = await chromium.launch();
        const page = await openDemo(browser);
        // номер варианта ищем заново в этой странице (по номеру и комнате), а не верим прежнему
        const i = await page.evaluate(`(${PUB}).find(v => v.id === ${JSON.stringify(t.id)} && v.room === ${JSON.stringify(t.room)})?.i ?? -1`);
        if (i < 0) throw new Error("вариант пропал из витрины");
        // ФОНОВЫЙ РЕЖИМ СТРАНИЦЫ (`opt.bg`, как у demo-realistic): без экрана ожидания и окна кадра после съёмки, отказ сервера —
        // текстом в ответ (в обычном режиме он уходил в окно на странице, и прогрев видел только «кадр не появился в реестре»)
        const r = await page.evaluate(([n, probe]) => {
          // кадр — опубликованного состояния: отделка варианта, а не общая (`DEVOPT`) — иначе номер состояния кадра не совпал бы
          DEVOPT = devCanon(allVariants()[n].dev || {});
          pickVariant(n);
          return new Promise((ok) => makePhoto("draft", "", "", { bg: true, extra: probe ? { no_registry: 1 } : {}, progress: () => {},
            fail: (m) => ok({ error: String(m) }), done: (n0) => ok({ n: shots.length - n0 }) }));
        }, [i, PROBE]);
        if (r.error) throw new Error(r.error);
        if (!r.n) throw new Error("сервер вернул кадр без снимков");
        return r;
      },
      reset: async () => { if (browser) await closeQuick(browser); browser = null; },
      // кадр — в реестре сервера (draft_service._registry_add); проверяем по реестру, а не по странице. Проба (`WARM_PROBE`) в реестр
      // не пишет — там зачёт по ответу страницы
      fresh: async (t, r) => {
        if (PROBE) return !!(r && r.value);
        try {
          return (await registry()).some((r) => regOf(r, t) && r.ts >= dataTs && (r.shots ?? []).length && (!t.stateId || rowFits(r, t, camOk)));
        } catch { return false; }
      },
    });
  }
  // итог — по реестру: у каждого варианта есть кадр опубликованного состояния (снятый когда угодно — главной этого хватает)
  const regEnd = await registry();
  missing = withoutShot(variants, regEnd, camOk);
  await pubStep("после съёмки", regEnd);
  const failedV = [...res.failed, ...res.skipped], nFail = failedV.length;
  if (!DRY) console.log(`прогрев кадров: снято ${res.done.length}, не вышло ${nFail}`);
  console.log(`по парам комната × стиль (${variants.length}):`);
  for (const l of pairLines(variants, { done: res.done, failed: failedV, missing })) console.log(l);
  const list = missing.map(pairLabel).join(", ");
  console.log(`${missing.length && !DRY ? "ERROR:demo_warm: " : ""}без фото своей расстановки и своих ракурсов — ${missing.length}`
    + (missing.length ? `: ${list} (на главной их нет)` : ""));
  if (DRY) return;
  console.log(digestLine({ todo, ...res, missing, variants }));
  if (nFail) console.log(`ERROR:demo_warm: ${nFail} кадр(ов) не снялось`);
  if (PUB_ON) await trimStep();
  if (missing.length || nFail || pubFail) process.exitCode = 1;
}

/** Строка сводки по обрезке реестра и новая отметка ночи (пишется целиком: временный файл + rename). Сбой чтения — не ошибка шага. */
async function trimStep() {
  let stats = null, cursor = null;
  try {
    const r = await fetch(`${BASE}/test/share/shots-trim.json?v=${Date.now()}`);
    stats = r.ok ? await r.json() : null;
  } catch (e) {
    console.log(`DIGEST:реестр кадров: счётчики не прочитаны — ${String(e.message || e).slice(0, 120)}`);
    return;
  }
  try { cursor = JSON.parse(readFileSync(CURSOR, "utf8")); } catch { cursor = null; }
  const { line, next } = trimDigest(stats, cursor);
  console.log(line);
  if (!next || next === cursor) return;
  try {
    mkdirSync(dirname(CURSOR), { recursive: true });
    writeFileSync(`${CURSOR}.tmp`, JSON.stringify(next));
    renameSync(`${CURSOR}.tmp`, CURSOR);
  } catch (e) {
    console.log(`WARN:demo_warm: отметка счётчиков не записана — ${String(e.message || e).slice(0, 120)}`);
  }
}

/** Закрыть браузер, не повиснув на нём: зависшая вкладка может держать и закрытие — ждём 15 с и идём дальше. */
async function closeQuick(b) {
  await withDeadline(b.close(), 15_000);
}

/** Подпись пары: гостиная — стиль (как было), другая комната — «комната/стиль». */
export const pairLabel = (v) => (!v.room || v.room === "living" ? v.style : `${v.room}/${v.style}`);

/**
 * СТРОКА НА ПАРУ «КОМНАТА × СТИЛЬ» (план room-photos-07 п.1, T-20261106-88): в отчёте прогрева видно каждую комнату витрины, а не
 * только общее число. Порядок — комнаты в порядке витрины, внутри — стили. Исход: снят / не вышел / кадр был / без кадра (нет в главной).
 */
export function pairLines(variants, { done = [], failed = [], missing = [] } = {}) {
  const has = (list, v) => list.some((x) => x.id === v.id && (x.room || "living") === (v.room || "living"));
  const rooms = [...new Set(variants.map((v) => v.room || "living"))];
  return rooms.flatMap((room) => variants.filter((v) => (v.room || "living") === room).map((v) => `  ${pairLabel(v)}: ${
    has(failed, v) ? "кадр не снялся" : has(done, v) ? "кадр снят" : has(missing, v) ? "БЕЗ КАДРА (на главной нет)" : "кадр есть"}`));
}

/** Варианты без фото своей расстановки и своих ракурсов: в реестре нет записи их состояния со снимком с нынешней точки. */
export function withoutShot(variants, reg, camOk) {
  if (typeof camOk !== "function") throw new Error("withoutShot: нужен предикат точки съёмки (camOk)");
  return variants.filter((v) => v.stateId && !reg.some((r) => rowFits(r, v, camOk)));
}

// только прямой запуск: импорт функций (проба, тест, `demo-realistic.mjs`) ни прогрев прода, ни эту самопроверку не запускает
const DIRECT = import.meta.url === pathToFileURL(process.argv[1] ?? "").href;
if (DIRECT && process.argv.includes("--selftest")) {
  // предикат точки — из файла страницы (блоки CAMANG/SHOTCAM), то есть тот же код, что решает показ на главной
  const camOk = camOkFromHtml(readFileSync(new URL("../scout/flat215-demo/index.html", import.meta.url), "utf8"));
  const any = () => true;
  const res = [];
  const check = (ok, msg, got) => { res.push(ok); console.log(ok ? `OK   ${msg}` : `FAIL ${msg}: ${got}`); };
  const v = [{ id: "a", style: "лофт", stateId: "s1-a" }, { id: "b", style: "сканди", stateId: "s1-b" },
    { id: "c", style: "джапанди", stateId: "s1-c" }, { id: "d", style: "минимализм", stateId: "s1-d" }, { id: "e", style: "старый", stateId: "s1-e" }];
  const s = [{ vid: "a", svc: false, ts: 200, stateId: "s1-a" }, { vid: "b", svc: false, ts: 50, stateId: "s1-b" },
    { vid: "c", svc: true, ts: 300, stateId: "s1-c" }, { vid: "d", svc: false, ts: 300, stateId: "s1-x" }, { vid: "e", svc: false, ts: 300 }];
  let got = needWarm(v, s, 100, 0, any).map((x) => x.id).join(",");
  check(got === "b,c,d", "свежий кадр того же состояния — не трогаем; старый, служебный и чужое состояние — снимаем; без номера — по времени", got);
  const s2 = [{ vid: "a", svc: false, ts: 200, stateId: "s1-a", pose: 1 }, { vid: "e", svc: false, ts: 300, quality: "realistic", pose: 1 }];
  got = needWarm([v[0], v[4]], s2, 100, 2, any).map((x) => x.id).join(",");
  check(got === "a", "эскиз прежней позы камеры — снимаем заново; фото нейросети — оставляем", got);
  got = withoutShot(v.slice(0, 2), [{ style: "лофт", stateId: "s1-a", shots: [{}] }, { style: "сканди", stateId: "s1-b", shots: [] }], any).map((x) => x.id).join(",");
  check(got === "b", "итог по реестру: вариант без кадра своего состояния — в ошибку", got);
  // ТОЧКА СЪЁМКИ (T-20261022-16): состояние то же, точка другая — «без фото»; сдвиг в пределах допуска страницы — годится
  const C = (x, y, rot, fov = 72) => [{ name: "C1", x, y, rot, fov }, { name: "C2", x: 400, y: 300, rot: 200, fov: 72 }];
  const pv = [{ id: "p", style: "сканди", stateId: "s2-p", cams: C(10, 10, 45) }];
  const regAt = (cams, camera = "C1") => [{ style: "сканди", stateId: "s2-p", ts: 300, cams, shots: [{ url: "u", camera }] }];
  got = withoutShot(pv, regAt(C(120, 10, 45)), camOk).map((x) => x.id).join(",");
  check(got === "p", "итог: то же состояние, кадр с другой точки — «без фото своих ракурсов»", got);
  got = withoutShot(pv, regAt(C(10, 10, 90)), camOk).map((x) => x.id).join(",");
  check(got === "p", "итог: та же точка, другой поворот — «без фото»", got);
  got = withoutShot(pv, regAt(C(11, 9, 46)), camOk).map((x) => x.id).join(",");
  check(got === "", "итог: сдвиг в пределах допуска страницы (±2 см и °) — кадр годен", got);
  got = withoutShot(pv, regAt(null), camOk).map((x) => x.id).join(",");
  check(got === "", "итог: старый кадр без записи точки — по-старому, годен (как у страницы)", got);
  got = withoutShot(pv, [...regAt(C(120, 10, 45)), ...regAt(C(10, 10, 45))], camOk).map((x) => x.id).join(",");
  check(got === "", "итог: среди старых есть кадр с нынешней точки — годен", got);
  got = withoutShot(pv, regAt(C(120, 10, 45)), any).map((x) => x.id).join(",");
  check(got === "", "контроль: без сверки точки (старое правило) тот же кадр сочли бы годным — дыра, которую закрываем", got);
  const ps = (cams) => [{ vid: "p", svc: false, ts: 300, stateId: "s2-p", pose: 1, camera: "C1", cams }];
  got = needWarm(pv, ps(C(120, 10, 45)), 100, 0, camOk).map((x) => x.id).join(",");
  check(got === "p", "прогрев: то же состояние, другая точка — нужен свежий кадр", got);
  got = needWarm(pv, ps(C(10, 10, 45)), 100, 0, camOk).map((x) => x.id).join(",");
  check(got === "", "прогрев: та же точка — не трогаем", got);
  // НЕСКОЛЬКО КОМНАТ (onb-12): запись → вариант по комнате и номеру варианта; без комнаты — гостиная, как весь нынешний реестр
  const lv = { id: "set3", room: "living", style: "сканди" }, bv = { id: "bed1", room: "bedroom", style: "сканди" };
  check(regOf({ style: "сканди" }, lv) && regOf({ room_id: "living", variant_id: "set9", style: "сканди" }, lv),
    "гостиная: старая запись без комнаты и запись с чужим номером варианта (пересборка) — по стилю, как у страницы", null);
  check(!regOf({ style: "сканди" }, bv) && !regOf({ room_id: "living", style: "сканди" }, bv), "запись гостиной не идёт в зачёт спальне того же стиля", null);
  check(regOf({ room_id: "bedroom", variant_id: "bed1", style: "лофт" }, bv) && !regOf({ room_id: "bedroom", variant_id: "bed2", style: "сканди" }, bv),
    "спальня: по номеру варианта, а не по стилю", null);
  check(regOf({ room_id: "bedroom", style: "сканди" }, bv), "спальня: запись без номера варианта — по стилю в своей комнате", null);
  got = withoutShot([{ ...lv, stateId: "s9" }, { ...bv, stateId: "s9" }], [{ style: "сканди", stateId: "s9", shots: [{}] }], any).map((x) => x.id).join(",");
  check(got === "bed1", "итог: кадр гостиной с тем же номером состояния спальню не закрывает", got);
  got = needWarm([{ id: "bed1", i: 7, room: "bedroom", style: "сканди", stateId: "s9" }], [], 100, 0, any).map((x) => `${x.i}:${x.room}`).join(",");
  check(got === "7:bedroom", "прогрев: номер варианта страницы и комната сохраняются", got);
  // СТРОКА НА ПАРУ (room-photos-07 п.1): каждая комната витрины и каждый её стиль — своей строкой, исход по паре
  const pv2 = [{ id: "set3", style: "сканди" }, { id: "bed1", room: "bedroom-1", style: "сканди" }, { id: "set4", room: "living", style: "лофт" },
    { id: "bed2", room: "bedroom-1", style: "лофт" }, { id: "hal1", room: "hall", style: "сканди" }];
  got = pairLines(pv2, { done: [{ id: "bed1", room: "bedroom-1" }], failed: [{ id: "hal1", room: "hall" }], missing: [{ id: "bed2", room: "bedroom-1" }, { id: "hal1", room: "hall" }] });
  check(got.join("|") === "  сканди: кадр есть|  лофт: кадр есть|  bedroom-1/сканди: кадр снят|  bedroom-1/лофт: БЕЗ КАДРА (на главной нет)|  hall/сканди: кадр не снялся",
    "пары: все комнаты витрины по порядку, внутри — стили; исход каждой пары (сбой съёмки важнее «без кадра»)", got);
  check(pairLines(pv2, { done: [{ id: "bed1", room: "living" }] })[2] === "  bedroom-1/сканди: кадр есть", "пара — по комнате и номеру, чужая комната не засчитывается", null);
  const two = [lv, bv], one = [lv, { id: "set4", style: "лофт" }];
  check(warmMax({}, one) === 8 && warmMax({}, two) === 10 && warmMax({ WARM_MAX: "3" }, two) === 3,
    "предел: одна гостиная — прежние 8, две комнаты — 10, WARM_MAX перекрывает", [warmMax({}, one), warmMax({}, two)]);
  let threw = false;
  try { withoutShot(pv, [], undefined); } catch { threw = true; }
  check(threw, "без предиката точки — громкий отказ, а не тихое старое правило", threw);
  threw = false;
  try { camOkFromHtml("<html></html>"); } catch { threw = true; }
  check(threw, "в странице нет блоков CAMANG/SHOTCAM — громкий отказ", threw);
  // ЦИКЛ СЪЁМКИ (T-20261107-16): второй кадр виснет (обещание не возвращается) — срок, браузер закрыт, новая попытка; кадр,
  // который сервер досчитал после срока, засчитан; бюджет кончился — «не успели»; время на кадр — в строке сводки
  const L = [], tl = [{ id: "a", style: "сканди" }, { id: "b", room: "bedroom-1", style: "лофт" }, { id: "c", style: "лофт" },
    { id: "d", style: "джапанди" }, { id: "e", style: "минимализм" }];
  let clock = 0, resets = 0, launched = 0;
  const att = {}, inReg = new Set();
  const plan = { a: ["ok"], b: ["hang", "ok"], c: ["hang-late"], d: ["err", "err"], e: ["ok"] };
  const shoot = (t) => {
    launched += 1;
    const k = att[t.id] = (att[t.id] ?? 0) + 1, what = plan[t.id][k - 1];
    if (what === "ok") { clock += 20_000; inReg.add(t.id); return Promise.resolve(); }
    if (what === "err") { clock += 5_000; return Promise.reject(new Error("сервер кадров недоступен")); }
    clock += 60_000; if (what === "hang-late") inReg.add(t.id);   // сервер досчитал, страница так и не вернулась
    return new Promise(() => {});
  };
  const loop = await warmLoop(tl, { shoot, reset: async () => { resets += 1; }, fresh: async (t) => inReg.has(t.id),
    shotMs: 30, budgetMs: 170_000, tries: 2, now: () => clock, log: (s) => L.push(s) });
  const ids = (l) => l.map((x) => x.id).join(",");
  check(ids(loop.done) === "a,b,c" && ids(loop.failed) === "d" && ids(loop.skipped) === "e",
    "цикл: зависание — срок и новая попытка; досчитанный после срока — снят; два сбоя — не снят; бюджет кончился — не успели",
    JSON.stringify({ done: ids(loop.done), failed: ids(loop.failed), skipped: ids(loop.skipped) }));
  check(resets === launched && launched === 6, "каждая попытка — свой браузер, и после каждой он закрыт (6 попыток — 6 закрытий)", [launched, resets]);
  check(L.some((s) => s.includes("bedroom-1/лофт: попытка 1 — не успел за 0 с, новый браузер")) && L.some((s) => s.includes("bedroom-1/лофт: кадр снят за 20 с (попытка 2)")),
    "журнал: зависшая попытка и повтор в новом браузере видны строкой", L.join(" | "));
  check(loop.failed[0].why === "Error: сервер кадров недоступен", "причина несданного кадра — текст ошибки", loop.failed[0].why);
  got = digestLine({ todo: tl, ...loop, missing: [{ id: "e", style: "минимализм" }], variants: tl });
  check(got === "DIGEST:прогрев кадров: снято 3 из 5, не снято 1: джапанди, не успели 1: минимализм; кадр ~20 с (до 60 с); без фото на главной 1",
    "строка сводки: снято / не снято / не успели, время на кадр, без фото на главной", got);
  got = digestLine({ todo: [], variants: tl, missing: [] });
  check(got === "DIGEST:прогрев кадров: свежий кадр не нужен — у 5 из 5 вариантов кадр есть", "строка сводки, когда снимать нечего", got);
  check(browserTmp({ TMPDIR: "/x" }) === "" && browserTmp({ REMLAB_TMP: "/r" }) === "/r"
    && browserTmp({}, () => true, "/h") === "/h/remlab-scratch/tmp" && browserTmp({}, () => false, "/h") === "",
  "папка браузера: заданный TMPDIR — его; иначе REMLAB_TMP, иначе ~/remlab-scratch/tmp; нет его — системная", null);
  // СПИСОК КАДРОВ ГЛАВНОЙ (T-20261107-17): ключ — как у сервера (те же примеры, что в tests/test_registry_protect.py)
  check(shotKey({ room_id: "bedroom-1", style: "лофт", ts: 12345 }) === "bedroom-1|лофт|12345" && shotKey({ style: "x", ts: 7 }) === "living|x|7"
    && shotKey({ id: "abc", style: "x" }) === "abc", "ключ записи — как у сервера (draft_guard.shot_key)", null);
  const R = (id, extra = {}) => ({ id, style: "сканди", stateId: "s2-p", ts: 300, cams: C(10, 10, 45), shots: [{ url: "u", camera: "C1" }], ...extra });
  const regP = [R("r1", { quality: "realistic" }), R("d1"), R("r2", { quality: "realistic", cams: C(120, 10, 45) }),
    R("r3", { quality: "realistic", style: "лофт" }), R("r4", { quality: "realistic", room_id: "bedroom-1", variant_id: "p" }),
    R("r5", { quality: "realistic", stateId: "s1-old" })];
  got = pubKeys(pv, regP, camOk).join(",");
  check(got === "r1", "список: фото нейросети варианта; свежий черновик, чужая точка, чужой стиль, чужая комната, старое состояние — нет", got);
  got = pubKeys(pv, [R("d1"), R("d2"), R("r2", { quality: "realistic", cams: C(120, 10, 45) })], camOk).join(",");
  check(got === "d2", "список: фото нейросети нет — последняя годная запись (вариант не пропадёт с главной)", got);
  got = pubKeys(pv, [R("r1", { quality: "realistic", shots: [{ url: "a", camera: "C1" }, { url: "b", camera: "C2" }] }),
    R("r6", { quality: "realistic", shots: [{ url: "c", camera: "C2" }] })], camOk).sort().join(",");
  check(got === "r1,r6", "список: последняя запись и последняя с каждой точкой (главная выбирает кадр по точке)", got);
  check(pubKeys([{ ...pv[0], stateId: "" }], regP, camOk).length === 0, "список: вариант без номера состояния — ничего", null);
  const { mkdtempSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const td = mkdtempSync(join(tmpdir(), "warm-pub-"));
  publishPub(["r1", "d2"], { target: join(td, "pub-shots.json"), dir: join(td, "w"), now: 5 });
  const pj = JSON.parse(readFileSync(join(td, "pub-shots.json"), "utf8"));
  check(pj.keys.join(",") === "r1,d2" && pj.path === "/demo/" && pj.ts === 5 && !existsSync(join(td, "pub-shots.json.tmp")),
    "публикация списка: целый файл на месте, временного не осталось", JSON.stringify(pj));
  threw = false;
  try { publishPub(Array.from({ length: 401 }, (_, i) => `k${i}`), { target: join(td, "x.json"), dir: join(td, "w") }); } catch { threw = true; }
  check(threw && !existsSync(join(td, "x.json")), "публикация списка: больше 400 ключей — отказ, сервер такой не примет", threw);
  rmSync(td, { recursive: true, force: true });
  const S = (o = {}) => ({ epoch: "e1", dropped_total: 30, dropped_realistic_total: 4, protected_current: 15, overflow_current: 0, pub_status: "ok", ...o });
  let td2 = trimDigest(null, null);
  check(td2.line === "DIGEST:реестр кадров: счётчиков обрезки нет (сервер кадров до T-17?)", "сводка обрезки: у сервера счётчиков нет — так и пишем", td2.line);
  td2 = trimDigest(S(), null);
  check(td2.line === "DIGEST:реестр кадров: защищено 15, выкинуто 30 (фото нейросети 4); первый замер — счёт с начала счётчиков"
    && td2.next.dropped_total === 30, "сводка обрезки: первый замер — итоги сервера", td2.line);
  td2 = trimDigest(S({ dropped_total: 42, dropped_realistic_total: 5 }), td2.next);
  check(td2.line === "DIGEST:реестр кадров: защищено 15, выкинуто 12 (фото нейросети 1)", "сводка обрезки: за ночь — разница с прошлой отметкой", td2.line);
  check(trimDigest(S({ dropped_total: 42, dropped_realistic_total: 5 }), td2.next).line.includes("выкинуто 0 (фото нейросети 0)"),
    "сводка обрезки: повтор ночи — второй раз не считается", null);
  td2 = trimDigest(S({ epoch: "e2", dropped_total: 3, dropped_realistic_total: 0, pub_status: "stale", overflow_current: 2 }), td2.next);
  check(td2.line === "DIGEST:!реестр кадров: защищено 15, выкинуто 3 (фото нейросети 0); счётчики сервера начаты заново — счёт с их начала; список кадров главной у сервера: stale; ПЕРЕПОЛНЕНИЕ: обязательных кадров на 2 больше предела",
    "сводка обрезки: счётчики пересозданы, список устарел, переполнение — закреплённой строкой", td2.line);
  const dl = await withDeadline(new Promise(() => {}), 10);
  check(dl.timeout === true, "срок: вечное обещание отпускает", JSON.stringify(dl));
  process.exit(res.every(Boolean) ? 0 : 1);
} else if (DIRECT) {
  await main();
  // зависший процесс браузера не держит node: итог и строка сводки уже напечатаны
  process.exit(process.exitCode ?? 0);
}
