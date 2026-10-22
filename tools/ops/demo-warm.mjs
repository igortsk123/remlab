// ПРОГРЕВ КАДРОВ ДЕМО (план b2b-08 п.4). Карточки стилей показывают кадр из серверного реестра (`/test/share/shots.json`),
// а кадр появлялся, только когда кто-то нажимал «снять»: после ночной пересборки витрины стиль мог остаться без кадра
// или с кадром вчерашнего набора. Шаг ночного прогона после публикации: открыть демо на проде и для каждого стиля без
// кадра НОВЕЕ данных витрины снять черновой кадр — функциями самой страницы (`pickVariant`, `makePhoto`), без копии
// логики расстановки. Черновой кадр — рендер на сервере, денег не стоит. Предел — WARM_MAX кадров за прогон.
// ВАРИАНТ БЕЗ КАДРА — ОШИБКА ШАГА (demo-20 Б2, владелец 22.10: «вариантов без фото быть не должно»): главная прячет вариант без
// кадра опубликованного состояния (`index.html:pubShot`), поэтому после прогрева каждый вариант сверяется с реестром ещё раз; кадр
// не снялся или вариантов без кадра осталось больше WARM_MAX — код 1, шаг FAIL в дайджесте `refresh_daily`.
//   node tools/ops/demo-warm.mjs            # прогрев прода
//   DRY=1 node tools/ops/demo-warm.mjs      # только список стилей, кадры не снимаются
import { chromium } from "@playwright/test";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const MAX = Number(process.env.WARM_MAX ?? 8);

/**
 * Каким стилям нужен свежий кадр. С demo-02 (разбор Codex 14.10) кадр годится, если снят С ТОГО ЖЕ СОСТОЯНИЯ, что
 * опубликовано (`stateId` страницы), и после публикации данных (новая версия движка/моделей — тоже повод переснять).
 * Старые кадры без номера состояния — по прежнему правилу «новее данных». Чистая функция (селфтест).
 */
export function needWarm(variants, shots, dataTs, poseVer = 0) {
  // поза камеры (demo-02, 14.10): эскиз прежней позы — тоже «нет кадра»; фото нейросети годится при любой позе
  const poseOk = (s) => !poseVer || s.quality === "realistic" || (Number(s.pose) || 1) === poseVer;
  return variants
    .map((v, i) => ({ i, id: v.id, style: v.style, stateId: v.stateId }))
    .filter((v) => !shots.some((s) => s.vid === v.id && !s.svc && (s.ts ?? 0) >= dataTs
      && (!s.stateId || !v.stateId || s.stateId === v.stateId) && poseOk(s)));
}

async function main() {
  const head = await fetch(`${BASE}/demo/demo-data.json`, { method: "HEAD" });
  const dataTs = new Date(head.headers.get("last-modified") ?? 0).getTime();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let done = 0, failed = 0, missing = [];
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
      stateId: stateIdOf(v.items || [], (v.decor || []).filter(x => (x.sku || {}).name), D.room, v.dev || {}) }))`;
    const variants = await page.evaluate(pub);
    const shots = await page.evaluate("(Array.isArray(shots) ? shots : []).map(s => ({ vid: s.vid, svc: !!s.svc, ts: s.ts, stateId: s.stateId || '', quality: s.quality || '', pose: ((s.cams || [])[0] || {}).pose || 1 }))");
    const poseVer = await page.evaluate("typeof POSE_VER === 'number' ? POSE_VER : 0");
    const todo = needWarm(variants, shots, dataTs, poseVer).slice(0, MAX);
    console.log(`прогрев кадров: стилей ${variants.length}, нужен свежий кадр ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
    if (process.env.DRY) return;
    for (const t of todo) {
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
          && (!t.stateId || r.stateId === t.stateId));
        if (fresh) done += 1;
        else { failed += 1; console.log(`  ${t.style}: кадр не появился в реестре`); }
      } catch (e) {
        failed += 1;
        console.log(`  ${t.style}: ${String(e).slice(0, 160)}`);
      }
    }
    // итог — по реестру: у каждого варианта есть кадр опубликованного состояния (снятый когда угодно — главной этого хватает)
    const reg = await (await fetch(`${BASE}/test/share/shots.json?v=${Date.now()}`)).json();
    missing = withoutShot(variants, reg);
  } finally {
    await browser.close();
  }
  console.log(`прогрев кадров: снято ${done}, не вышло ${failed}`);
  if (missing.length) console.log(`ERROR:demo_warm: без кадра опубликованного состояния — ${missing.map((v) => v.style).join(", ")}: на главной их нет`);
  else if (failed) console.log(`ERROR:demo_warm: ${failed} кадр(ов) не снялось`);
  if (missing.length || failed) process.exitCode = 1;
}

/** Варианты, у которых в реестре нет ни одного кадра их состояния (запись реестра — `stateId` и непустой `shots`). */
export function withoutShot(variants, reg) {
  return variants.filter((v) => v.stateId && !reg.some((r) => r.stateId === v.stateId && (r.shots ?? []).length));
}

if (process.argv.includes("--selftest")) {
  const v = [{ id: "a", style: "лофт", stateId: "s1-a" }, { id: "b", style: "сканди", stateId: "s1-b" },
    { id: "c", style: "джапанди", stateId: "s1-c" }, { id: "d", style: "минимализм", stateId: "s1-d" }, { id: "e", style: "старый", stateId: "s1-e" }];
  const s = [{ vid: "a", svc: false, ts: 200, stateId: "s1-a" }, { vid: "b", svc: false, ts: 50, stateId: "s1-b" },
    { vid: "c", svc: true, ts: 300, stateId: "s1-c" }, { vid: "d", svc: false, ts: 300, stateId: "s1-x" }, { vid: "e", svc: false, ts: 300 }];
  const got = needWarm(v, s, 100).map((x) => x.id).join(",");
  const ok = got === "b,c,d";
  console.log(ok ? "OK   свежий кадр того же состояния — не трогаем; старый, служебный и чужое состояние — снимаем; без номера — по времени" : `FAIL ${got}`);
  const s2 = [{ vid: "a", svc: false, ts: 200, stateId: "s1-a", pose: 1 }, { vid: "e", svc: false, ts: 300, quality: "realistic", pose: 1 }];
  const got2 = needWarm([v[0], v[4]], s2, 100, 2).map((x) => x.id).join(",");
  const ok2 = got2 === "a";
  console.log(ok2 ? "OK   эскиз прежней позы камеры — снимаем заново; фото нейросети — оставляем" : `FAIL поза: ${got2}`);
  const miss = withoutShot(v.slice(0, 2), [{ stateId: "s1-a", shots: [{}] }, { stateId: "s1-b", shots: [] }]).map((x) => x.id).join(",");
  const ok3 = miss === "b";
  console.log(ok3 ? "OK   итог по реестру: вариант без кадра своего состояния — в ошибку" : `FAIL итог: ${miss}`);
  process.exit(ok && ok2 && ok3 ? 0 : 1);
} else {
  await main();
}
