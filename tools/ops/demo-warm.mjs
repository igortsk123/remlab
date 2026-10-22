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
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const MAX = Number(process.env.WARM_MAX ?? 8);
const DRY = !!process.env.DRY;

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

/** Запись реестра — кадр варианта: то же состояние, есть снимки, и хотя бы один снят с нынешней точки варианта. */
export function rowFits(r, v, camOk) {
  return r.stateId === v.stateId && (r.shots ?? []).some((sh) => camOk({ cams: r.cams, camera: sh.camera || "C1" }, v.cams));
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
    .map((v, i) => ({ i, id: v.id, style: v.style, stateId: v.stateId, cams: v.cams }))
    .filter((v) => !shots.some((s) => s.vid === v.id && !s.svc && (s.ts ?? 0) >= dataTs
      && (!s.stateId || !v.stateId || s.stateId === v.stateId) && poseOk(s) && camOk(s, v.cams)));
}

async function main() {
  const head = await fetch(`${BASE}/demo/demo-data.json`, { method: "HEAD" });
  const dataTs = new Date(head.headers.get("last-modified") ?? 0).getTime();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let done = 0, failed = 0, missing = [], camOk = null;
  try {
    // `?live=0` — без живой 3D-сцены: после съёмки страница открывает окно варианта, и сборка сцены программным рендером
    // (у прогрева нет видеокарты) подвешивала следующий кадр (17.10: прогон снял 1 из 5 и встал по сроку)
    await page.goto(`${BASE}/demo/?live=0&lang=ru`, { waitUntil: "domcontentloaded" });
    // данные витрины приходят после разметки: пока `D` пуст, `allVariants()` бросает — ждать надо `D`, иначе прогон падал
    // на первом же ожидании и ночью кадров не снимал вовсе (найдено 17.10: у трёх стилей не было кадра своей расстановки)
    await page.waitForFunction("typeof D !== 'undefined' && !!D && typeof allVariants === 'function' && allVariants().length > 0", null, { timeout: 90_000 });
    await page.waitForTimeout(4000); // реестр кадров приезжает позже данных
    // номер опубликованного состояния — той же функцией страницы (блок STATEID), что ставит его кадрам
    // номер состояния — тем, чем его считает сама страница для кадра (`variantStateOf`, demo-09), а не своей копией формулы
    // ОПУБЛИКОВАННОЕ состояние (данные витрины и своя отделка `v.dev`), а не живое: у открытого варианта живое сбивает общая отделка
    const pub = `allVariants().filter(v => !v.mine && !v.cid).map(v => ({ id: v.id, style: v.style,
      stateId: stateIdOf(v.items || [], (v.decor || []).filter(x => (x.sku || {}).name), D.room, v.dev || {}),
      cams: v.cams || null }))`;
    const variants = await page.evaluate(pub);
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
    console.log(`прогрев кадров: стилей ${variants.length}, нужен свежий кадр ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
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
        const fresh = reg.some((r) => r.style === t.style && r.ts >= dataTs && (r.shots ?? []).length
          && (!t.stateId || rowFits(r, t, camOk)));
        if (fresh) done += 1;
        else { failed += 1; console.log(`  ${t.style}: кадр не появился в реестре`); }
      } catch (e) {
        failed += 1;
        console.log(`  ${t.style}: ${String(e).slice(0, 160)}`);
      }
    }
    // итог — по реестру: у каждого варианта есть кадр опубликованного состояния (снятый когда угодно — главной этого хватает)
    const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
    missing = withoutShot(variants, reg, camOk);
  } finally {
    await browser.close();
  }
  if (!DRY) console.log(`прогрев кадров: снято ${done}, не вышло ${failed}`);
  const list = missing.map((v) => v.style).join(", ");
  console.log(`${missing.length && !DRY ? "ERROR:demo_warm: " : ""}без фото своей расстановки и своих ракурсов — ${missing.length}`
    + (missing.length ? `: ${list} (на главной их нет)` : ""));
  if (DRY) return;
  if (failed) console.log(`ERROR:demo_warm: ${failed} кадр(ов) не снялось`);
  if (missing.length || failed) process.exitCode = 1;
}

/** Варианты без фото своей расстановки и своих ракурсов: в реестре нет записи их состояния со снимком с нынешней точки. */
export function withoutShot(variants, reg, camOk) {
  if (typeof camOk !== "function") throw new Error("withoutShot: нужен предикат точки съёмки (camOk)");
  return variants.filter((v) => v.stateId && !reg.some((r) => rowFits(r, v, camOk)));
}

if (process.argv.includes("--selftest")) {
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
  got = withoutShot(v.slice(0, 2), [{ stateId: "s1-a", shots: [{}] }, { stateId: "s1-b", shots: [] }], any).map((x) => x.id).join(",");
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
  let threw = false;
  try { withoutShot(pv, [], undefined); } catch { threw = true; }
  check(threw, "без предиката точки — громкий отказ, а не тихое старое правило", threw);
  threw = false;
  try { camOkFromHtml("<html></html>"); } catch { threw = true; }
  check(threw, "в странице нет блоков CAMANG/SHOTCAM — громкий отказ", threw);
  process.exit(res.every(Boolean) ? 0 : 1);
} else if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  // только прямой запуск: импорт функций (проба, тест) прогрев прода не запускает
  await main();
}
