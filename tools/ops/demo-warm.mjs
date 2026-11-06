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
import { readFileSync } from "node:fs";
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

async function main() {
  const head = await fetch(`${BASE}${PATH}demo-data.json`, { method: "HEAD" });
  const dataTs = new Date(head.headers.get("last-modified") ?? 0).getTime();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let done = 0, failed = 0, missing = [], camOk = null, variants = [];
  const doneV = [], failedV = [];
  try {
    // `?live=0` — без живой 3D-сцены: после съёмки страница открывает окно варианта, и сборка сцены программным рендером
    // (у прогрева нет видеокарты) подвешивала следующий кадр (17.10: прогон снял 1 из 5 и встал по сроку)
    // `quiz=0` — без опроса-знакомства (onb-03): окно опроса поверх витрины не нужно кадру и не держит страницу
    await page.goto(`${BASE}${PATH}?live=0&quiz=0&lang=ru`, { waitUntil: "domcontentloaded" });
    // данные витрины приходят после разметки: пока `D` пуст, `allVariants()` бросает — ждать надо `D`, иначе прогон падал
    // на первом же ожидании и ночью кадров не снимал вовсе (найдено 17.10: у трёх стилей не было кадра своей расстановки)
    await page.waitForFunction("typeof D !== 'undefined' && !!D && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
    await page.waitForTimeout(4000); // реестр кадров приезжает позже данных
    // номер опубликованного состояния — той же функцией страницы (блок STATEID), что ставит его кадрам
    // номер состояния — тем, чем его считает сама страница для кадра (`variantStateOf`, demo-09), а не своей копией формулы
    // ОПУБЛИКОВАННОЕ состояние (данные витрины и своя отделка `v.dev`), а не живое: у открытого варианта живое сбивает общая отделка
    // комната варианта (onb-12): номер — `pubStateOf` страницы (геометрия `roomOf(v)`); страница до onb-07 его не знает — прежняя
    // формула с `D.room`. Вариант, чьей комнаты нет в данных (`roomGeoOf` → null), главная не показывает — и снимать его не в чем.
    // `i` — номер в `allVariants()`: по нему страница открывает вариант (`pickVariant`), фильтр номера не сдвигает
    const pub = `allVariants().map((v, i) => ({ v, i })).filter(({ v }) => !v.mine && !v.cid
        && (typeof roomGeoOf !== 'function' || !!roomGeoOf(v))).map(({ v, i }) => ({ i, id: v.id,
      room: typeof roomIdOf === 'function' ? roomIdOf(v) : 'living', style: v.style,
      stateId: typeof pubStateOf === 'function' ? pubStateOf(v)
        : stateIdOf(v.items || [], (v.decor || []).filter(x => (x.sku || {}).name), D.room, v.dev || {}),
      cams: v.cams || null }))`;
    variants = (await page.evaluate(pub)).filter((v) => !ONLY || v.room === ONLY);
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
    const todo = needWarm(variants, shots, dataTs, poseVer, camOk).slice(0, MAX);
    const label = pairLabel;
    const rooms = new Set(variants.map((v) => v.room)).size;
    console.log(`прогрев кадров: стилей ${variants.length}${rooms > 1 ? ` в ${rooms} комнатах` : ""}, нужен свежий кадр ${todo.length}${todo.length ? ": " + todo.map(label).join(", ") : ""}`);
    // проба (DRY) ничего не снимает, но итог по нынешнему реестру считает — что ночь сочла бы провалом
    for (const t of DRY ? [] : todo) {
      try {
        await page.evaluate(async (i) => {
          // кадр — опубликованного состояния: отделка варианта, а не общая (`DEVOPT`) — иначе номер состояния кадра не совпал бы
          // eslint-disable-next-line no-undef -- функции страницы демо
          DEVOPT = devCanon(allVariants()[i].dev || {});
          // eslint-disable-next-line no-undef
          pickVariant(i);
          // eslint-disable-next-line no-undef
          await makePhoto("draft");
        }, t.i);
        // ответ пришёл — кадр в реестре сервера (draft_service._registry_add); проверяем по реестру, а не по странице
        const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
        const fresh = reg.some((r) => regOf(r, t) && r.ts >= dataTs && (r.shots ?? []).length
          && (!t.stateId || rowFits(r, t, camOk)));
        if (fresh) { done += 1; doneV.push(t); }
        else { failed += 1; failedV.push(t); console.log(`  ${label(t)}: кадр не появился в реестре`); }
      } catch (e) {
        failed += 1; failedV.push(t);
        console.log(`  ${label(t)}: ${String(e).slice(0, 160)}`);
      }
    }
    // итог — по реестру: у каждого варианта есть кадр опубликованного состояния (снятый когда угодно — главной этого хватает)
    const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
    missing = withoutShot(variants, reg, camOk);
  } finally {
    await browser.close();
  }
  if (!DRY) console.log(`прогрев кадров: снято ${done}, не вышло ${failed}`);
  console.log(`по парам комната × стиль (${variants.length}):`);
  for (const l of pairLines(variants, { done: doneV, failed: failedV, missing })) console.log(l);
  const list = missing.map((v) => (v.room && v.room !== "living" ? `${v.room}/${v.style}` : v.style)).join(", ");
  console.log(`${missing.length && !DRY ? "ERROR:demo_warm: " : ""}без фото своей расстановки и своих ракурсов — ${missing.length}`
    + (missing.length ? `: ${list} (на главной их нет)` : ""));
  if (DRY) return;
  if (failed) console.log(`ERROR:demo_warm: ${failed} кадр(ов) не снялось`);
  if (missing.length || failed) process.exitCode = 1;
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
  process.exit(res.every(Boolean) ? 0 : 1);
} else if (DIRECT) {
  await main();
}
