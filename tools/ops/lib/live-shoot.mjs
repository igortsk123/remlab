// СЪЁМКА КАДРОВ ЖИВОЙ 3D-СЦЕНЫ В БЕЗГОЛОВОМ БРАУЗЕРЕ — ОДИН МОДУЛЬ ДЛЯ ВИТРИНЫ И ТУРА (T-20261112-115, план tour-auto-photos-01 Ф3).
// Тот же путь, что кнопка «Сделать фото» у покупателя: страница сама строит 3D комнаты варианта и снимает два ракурса
// (`index.html:vwCaptureViews`), сервер получает кадры, а не рисует свой эскиз (на эскизе нет картин, штор и тюля из 3D — T-114).
// Пользователи: ночная досъёмка витрины `tools/ops/demo-realistic.mjs` (`shootOne`, `--frames`) и автофото тура
// `tools/ops/tour-auto-photos.mjs`. Без видеокарты 3D рисует процессор (SwiftShader): 6–7 ядер на страницу — запуск только под
// `tools/ops/heavy-slot.sh --cores 6 --min-gb 3`, одна страница и одна комната за раз.

/** Аргументы Chromium: программный WebGL (SwiftShader) — на DEV нет видеокарты. */
export const SOFT_GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];

/** Браузер для съёмки: `gl` — с программным 3D (кадры), иначе обычный (страница без 3D). */
export function launchLive(chromium, gl = true) {
  return chromium.launch(gl ? { args: SOFT_GL_ARGS } : {});
}

/**
 * Служебный Bearer воркера — только к адресам ЭТОГО тура на том же сервере (как `tools/scout/trial_cards.mjs`): тур без ключа агента
 * закрыт до подтверждения (`lib/trial/buyer-gate.ts`). Ключ берётся из окружения вызывающего и нигде не печатается.
 * → true, если маршрут поставлен (адрес — тур `/try/<id22>/tour`, ключ есть).
 */
export async function routeTourBearer(ctx, url, token) {
  const u = new URL(url), tourPath = u.pathname.replace(/\/?$/, "");
  if (!token || !/^\/try\/[A-Za-z0-9_-]{22}\/tour$/.test(tourPath)) return false;
  await ctx.route((x) => x.origin === u.origin && (x.pathname === tourPath || x.pathname.startsWith(tourPath + "/")),
    (r) => r.continue({ headers: { ...r.request().headers(), authorization: `Bearer ${token}` } }));
  return true;
}

/** Готовность данных страницы (витрина и тур): данные, квартира и список вариантов. */
export const PAGE_READY = "typeof D !== 'undefined' && !!D && !!FLAT && typeof allVariants === 'function' && allVariants().length > 0";

/** Открыть страницу и дождаться данных; `settleMs` — реестр кадров приезжает позже данных (витрина). */
export async function openLivePage(page, url, { gl = true, settleMs = 0, ready = PAGE_READY } = {}) {
  await page.goto(url, { waitUntil: gl ? "load" : "domcontentloaded", timeout: 120_000 });
  await page.waitForFunction(ready, null, { timeout: 90_000 });
  if (settleMs) await page.waitForTimeout(settleMs);
}

/**
 * ФУНКЦИЯ СТРАНИЦЫ (идёт в `page.evaluate`, поэтому самодостаточна; в самопроверках — на заглушках `globalThis`).
 * Вариант `i` → окно варианта в «3D» → ждём готовую сцену ИМЕННО его комнаты (`liveHere`, T-20261112-108/2: сцена прошлой комнаты —
 * как её нет) → `vwCaptureViews` (он сам ставит мебель этой расстановки и сверяет комнату). `poses` — пара точек съёмки
 * [{name,x,y,rot,fov}] вместо пары страницы; `noUpload` — не грузить кадры на сервер (сухой ход); `b64` — вернуть кадры JPEG
 * base64. Снятое кладётся в `globalThis.__liveCap` (кадры-Blob через evaluate не передать): заказ фото следующим вызовом берёт его.
 * Имена страницы — голые (`cams`, `LIVE`, `VW` — её `let`/`const` верхнего уровня, не свойства `window`); в самопроверке они —
 * свойства `globalThis`.
 * → {ok, error?, size, ms, room, roomId, variant, stateId, readyMs, poses, views?, jpgs?}
 */
export async function pageCapture(o) {
  globalThis.__liveCap = null;
  pickVariant(o.i);
  openLiveWindow(); if (VW.mode !== "walk") vwMode("walk");
  const here = () => (typeof liveHere === "function" ? liveHere() : LIVE.scene);
  const t0 = performance.now();
  for (let k = 0; k < (o.waitTicks ?? 600) && !(here() && LIVE.state === "ready"); k++) await new Promise((ok) => setTimeout(ok, 300));
  const ready = Math.round(performance.now() - t0);
  if (o.poses) cams = o.poses.map((c) => ({ ...c }));
  const cap = await vwCaptureViews({ noUpload: !!o.noUpload });
  const v = allVariants()[o.i] || {};
  const info = { variant: String(v.id || ""), roomId: typeof roomIdOf === "function" ? roomIdOf(v) : "living",
    stateId: typeof curStateId === "function" ? curStateId() : "", readyMs: ready };
  if (!cap) return { ok: false, error: "кадры из браузера не сняты", ...info, live: [LIVE.ok, LIVE.state, LIVE.why || ""].join("/") };
  globalThis.__liveCap = cap;
  const poses = typeof camPoseOf === "function" ? (cams || loadCams()).slice(0, 2).map(camPoseOf) : [];
  const out = { ok: true, ...info, size: cap.size, ms: cap.ms, room: cap.room || "", poses, views: cap.views || null };
  if (o.b64) {
    out.jpgs = [];
    for (const b of cap.blobs || []) {
      const a = new Uint8Array(await b.arrayBuffer());
      let s = "";
      for (let k = 0; k < a.length; k += 0x8000) s += String.fromCharCode.apply(null, a.subarray(k, k + 0x8000));
      out.jpgs.push(btoa(s));
    }
  }
  return out;
}

/** Снять кадры варианта `i` на странице `page` (см. `pageCapture`). */
export function captureViews(page, i, opt = {}) {
  return page.evaluate(pageCapture, { i, ...opt });
}
