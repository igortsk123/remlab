// ПРОГРЕВ КАДРОВ ДЕМО (план b2b-08 п.4). Карточки стилей показывают кадр из серверного реестра (`/test/share/shots.json`),
// а кадр появлялся, только когда кто-то нажимал «снять»: после ночной пересборки витрины стиль мог остаться без кадра
// или с кадром вчерашнего набора. Шаг ночного прогона после публикации: открыть демо на проде и для каждого стиля без
// кадра НОВЕЕ данных витрины снять черновой кадр — функциями самой страницы (`pickVariant`, `makePhoto`), без копии
// логики расстановки. Черновой кадр — рендер на сервере, денег не стоит. Предел — WARM_MAX кадров за прогон.
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
  let done = 0, failed = 0;
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
    const variants = await page.evaluate(`allVariants().map(v => ({ id: v.id, style: v.style,
      stateId: typeof variantStateOf === "function" ? variantStateOf(v) : "" }))`);
    const shots = await page.evaluate("(Array.isArray(shots) ? shots : []).map(s => ({ vid: s.vid, svc: !!s.svc, ts: s.ts, stateId: s.stateId || '', quality: s.quality || '', pose: ((s.cams || [])[0] || {}).pose || 1 }))");
    const poseVer = await page.evaluate("typeof POSE_VER === 'number' ? POSE_VER : 0");
    const todo = needWarm(variants, shots, dataTs, poseVer).slice(0, MAX);
    console.log(`прогрев кадров: стилей ${variants.length}, нужен свежий кадр ${todo.length}${todo.length ? ": " + todo.map((t) => t.style).join(", ") : ""}`);
    if (process.env.DRY) return;
    for (const t of todo) {
      try {
        await page.evaluate(async (i) => {
          // eslint-disable-next-line no-undef -- функции страницы демо
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
  } finally {
    await browser.close();
  }
  console.log(`прогрев кадров: снято ${done}, не вышло ${failed}`);
  if (failed) console.log(`WARN:demo_warm: ${failed} стил. без свежего кадра — карточки покажут старый кадр или пустоту`);
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
  process.exit(ok && ok2 ? 0 : 1);
} else {
  await main();
}
