// КАРТИНКИ КАРТОЧЕК КОМНАТ ТУРА — ЗАРАНЕЕ, НА DEV (T-20261112-29, жалоба владельца «сначала план-схема, потом 3D-фото»).
// Раньше снимок 3D карточки снимала только страница покупателя (`index.html:trHomeShot`): не раньше 2,5 с после загрузки, в тишине,
// ~5 с до картинки на телефоне (замер T-29) — всё это время карточка показывала схему плана, и так при каждом заходе. Теперь тот же
// снимок той же функцией снимается ОДИН раз после публикации версии: сама страница тура (закреплённая витрина и данные задания),
// телефонный режим (лёгкие модели, как у карточки на телефоне), точка 1 (`trHsPose`). Ключ расстановки (`trHsKey`) уходит вместе с
// кадром: страница покупателя берёт файл, только если ключ совпал (`index.html:trCardOf`). Загрузку на сервер делает `tools/floorplan/cards.py`.
//
//   node tools/scout/trial_cards.mjs <адрес страницы тура или /demo/> <out.json> [--bundle данные.json] [--only id,id] [--timeout 300]
// `--bundle` — подменить `demo-data.json` страницы (проверка своей сборки на /demo/). Выход — JSON
// {ok, ms, live, cards:[{id, key, w, h, ms, jpg:<base64>} | {id, err}]}; код 0 — снят хоть один кадр или снимать нечего,
// 3 — страница не открылась / 3D не поднялось (тур остаётся как был: страница покупателя снимет сама), 2 — неверный вызов.
import { chromium } from "@playwright/test";
import fs from "node:fs";

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const pos = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--")));
const [URL0, OUT] = pos;
if (!URL0 || !OUT || !/^https?:\/\//.test(URL0)) {
  console.error("usage: trial_cards.mjs <url> <out.json> [--bundle file] [--only ids] [--timeout S]");
  process.exit(2);
}
const BUNDLE = opt("--bundle", "");
const ONLY = (opt("--only", "") || "").split(",").filter(Boolean);
const TIMEOUT_MS = 1000 * +opt("--timeout", "300");
const Q = 0.82;                                   // JPEG 1024×723: 55–80 КБ (замер T-29)
const t0 = Date.now();
const done = (code, res) => { fs.writeFileSync(OUT, JSON.stringify({ ms: Date.now() - t0, ...res })); process.exit(code); };

const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const kill = setTimeout(() => { b.close().catch(() => {}); done(3, { ok: false, error: "timeout" }); }, TIMEOUT_MS);
try {
  // телефон: `isTouchUI` → лёгкие модели, как у карточки на телефоне (главный случай; компьютер берёт тот же кадр)
  const ctx = await b.newContext({ viewport: { width: 375, height: 667 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: "ru-RU" });
  await ctx.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));   // это не посетитель
  // тур до «Подтвердить планировку» агента без ключа закрыт (`lib/trial/buyer-gate.ts`, T-20261112-40): снимальщик проходит Bearer-ом
  // воркера (окружение `cards.py`) — только к адресам этого тура на том же сервере, больше никуда
  const TOKEN = process.env.TRIAL_WORKER_TOKEN || "";
  const tourPath = new URL(URL0).pathname.replace(/\/?$/, "");
  if (TOKEN && /^\/try\/[A-Za-z0-9_-]{22}\/tour$/.test(tourPath)) {
    const origin = new URL(URL0).origin;
    await ctx.route((u) => u.origin === origin && (u.pathname === tourPath || u.pathname.startsWith(tourPath + "/")),
      (r) => r.continue({ headers: { ...r.request().headers(), authorization: `Bearer ${TOKEN}` } }));
  }
  if (BUNDLE) {
    const body = fs.readFileSync(BUNDLE);
    await ctx.route((u) => u.pathname.endsWith("/demo-data.json"), (r) => r.fulfill({ status: 200, contentType: "application/json", body }));
  }
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
  const u = new URL(URL0); u.searchParams.set("live", "force"); u.searchParams.set("quiz", "0");
  await p.goto(u.href, { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&typeof TRIAL==='function'&&TRIAL()&&typeof trHomeShot==='function'", null, { timeout: 90000 });
  const res = await p.evaluate(async ({ only, q }) => {
    const out = [];
    for (const v of allVariants()) {
      if (only.length && !only.includes(String(v.id))) continue;
      if (v.mine || v.cid || !(v.items || []).length || varPending(v) || varRefused(v)) continue;
      const t = performance.now(), key = trHsKey(v);
      let url = "";
      try { url = await trHomeShot(v); } catch (e) { out.push({ id: v.id, err: String(e && e.message || e).slice(0, 200) }); continue; }
      if (!url) { out.push({ id: v.id, err: "empty" }); continue; }
      const bm = await createImageBitmap(await (await fetch(url)).blob()); URL.revokeObjectURL(url);
      const c = document.createElement("canvas"); c.width = bm.width; c.height = bm.height; c.getContext("2d").drawImage(bm, 0, 0);
      const jpg = c.toDataURL("image/jpeg", q).replace(/^data:image\/jpeg;base64,/, "");
      out.push({ id: v.id, key, w: c.width, h: c.height, ms: Math.round(performance.now() - t), jpg });
    }
    return { live: { ok: LIVE.ok }, out };
  }, { only: ONLY, q: Q });
  clearTimeout(kill);
  await b.close();
  const okN = res.out.filter((c) => c.jpg).length;
  done(okN || !res.out.length ? 0 : 3, { ok: okN > 0 || !res.out.length, live: res.live, cards: res.out, page_errors: errs.slice(0, 5) });
} catch (e) {
  clearTimeout(kill);
  await b.close().catch(() => {});
  done(3, { ok: false, error: String(e && e.message || e).slice(0, 300) });
}
