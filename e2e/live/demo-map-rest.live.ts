import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { test, expect, type Browser, type BrowserContextOptions, type Page } from "@playwright/test";

import { demoUrl, LIVE_CHECK_HEADERS } from "./browser";
import { homeStyles, pickStyle } from "./home";

// КАРТА СЦЕНАРИЕВ ДЕМО — ОСТАВШИЕСЯ СТРОКИ (T-20261106-69, план demo-03): 2.30–2.32, 2.39–2.48 `domain/demo-scenario-map.md`.
// Ожидание берём из колонки «ожидание» строки карты, не из факта: проверка краснеет, когда сценарий сломан. Номер строки — в начале
// названия теста (`tools/ops/demo-map-check.mjs`). Денег не тратим и коллекций на проде не пишем: «Улучшить», задания кадров,
// сохранение коллекции и `/api/draft/paid` — подменённые ответы; страница и её код — настоящие, с прода.
//
// МУТАЦИЯ (доказать, что проверка ловит поломку): `LIVE_MUTATE='[["было","стало"],…]'` — подмена строк в HTML демо до загрузки
// (страница та же, что на проде, но со сломанным условием). Пример: `LIVE_MUTATE='[["const PHOTO_EST_S=30;","const PHOTO_EST_S=60;"]]'`
// → 2.43 красный. Не найденная строка — тест падает сразу (мутация не применилась — доказательства нет).
// ЛОКАЛЬНАЯ СБОРКА (правка ещё не на проде): `LIVE_DEMO_HTML=tools/scout/flat215-demo/index.html` — вместо HTML демо с прода
// отдаётся этот файл (API, каталог и картинки — по-прежнему прод); мутация, если задана, применяется уже к нему.

const say = (...a: unknown[]) => console.log("  ·", ...a);
const ROOT = process.cwd();                                      // прогон — из корня репозитория (как у конфига)
const MUT = JSON.parse(process.env.LIVE_MUTATE || "[]") as [string, string][];
const SHOTS = process.env.LIVE_SHOTS_DIR || "";                   // папка снимков прогона (новая, с меткой времени)
const LOCAL_HTML = process.env.LIVE_DEMO_HTML ? readFileSync(process.env.LIVE_DEMO_HTML, "utf8") : "";
const shoot = async (page: Page, name: string) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };

const phone: BrowserContextOptions = { viewport: { width: 375, height: 667 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: "ru-RU" };
const desk: BrowserContextOptions = { viewport: { width: 1440, height: 900 }, locale: "ru-RU" };
const READY = "typeof D !== 'undefined' && !!D && !!FLAT && !!(window.__basket && window.__basket.state())";
const LIVING = "#hmRooms .hm-room[data-room=living] [data-swap]";
const rnd = () => Array.from({ length: 22 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 62)]).join("");

type Pkg = { mode: "pooled" | "split"; limits: { furniture: number; fitout: number } };
type Opts = { pkg?: Pkg; paid?: () => boolean; job?: () => unknown; renders?: { quality: string }[] };

/** Страница демо: метка проверки, события в счётчики не идут, мутация HTML, сохранение коллекции — подменой (на проде не пишем). */
async function demoPage(browser: Browser, ctxOpt: BrowserContextOptions, q = "", o: Opts = {}): Promise<{ page: Page; close: () => Promise<void>; errors: string[] }> {
  const ctx = await browser.newContext({ ...ctxOpt, extraHTTPHeaders: LIVE_CHECK_HEADERS });
  const page = await ctx.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // глобалы страницы объявлены `let/const` (items, VW, LIVE, D…) — в `window` их нет; `__g("items")` читает их по имени
  await page.addInitScript("window.__g = (n) => eval(n)");
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  if (MUT.length || LOCAL_HTML) await page.route((u) => /^\/demo\/?(index\.html)?$/.test(u.pathname), async (r) => {
    if (r.request().resourceType() !== "document") return r.continue();
    const res = await r.fetch();
    let body = LOCAL_HTML || await res.text();
    if (LOCAL_HTML) console.log("  ! ЛОКАЛЬНЫЙ HTML демо:", process.env.LIVE_DEMO_HTML);
    for (const [a, b] of MUT) { if (!body.includes(a)) throw new Error(`мутация не применилась: нет «${a}»`); body = body.split(a).join(b); }
    if (MUT.length) console.log("  ! МУТАЦИЯ:", MUT.map(([a, b]) => `«${a}» → «${b}»`).join("; "));
    await r.fulfill({ response: res, body });
  });
  // сохранение коллекции — подменой: id и секрет как у сервера, чтение по id — «нет» (страница это переживает, см. afterSave)
  await page.route(/\/api\/collections(\/[\w-]+)?(\?.*)?$/, async (r) => {
    const m = r.request().method(), u = new URL(r.request().url());
    if (m === "POST" && u.pathname === "/api/collections") return r.fulfill({ json: { ok: true, id: rnd(), editToken: rnd() } });
    if (m === "PATCH") return r.fulfill({ json: { ok: true } });
    if (m === "GET" && u.pathname !== "/api/collections") return r.fulfill({ status: 404, json: { ok: false } });
    return r.continue();
  });
  if (o.pkg) {
    const pkg = o.pkg;
    await page.route(/\/api\/apartments\//, async (r) => {
      const res = await r.fetch(); const j = await res.json() as { card?: { certificate?: { amount: number }; incentive?: Pkg & { total: number } } };
      const total = pkg.limits.furniture + pkg.limits.fitout;
      if (j.card?.certificate) { j.card.certificate.amount = total; j.card.incentive = { ...pkg, total }; }
      await r.fulfill({ response: res, body: JSON.stringify(j), headers: { ...res.headers(), "content-type": "application/json" } });
    });
  }
  // фото — без денег: «есть ли деньги» отвечаем сами, задание и кадры — подмена (платный путь сервера не вызывается)
  await page.route(/\/api\/draft\/paid/, (r) => r.fulfill({ json: { available: o.paid ? o.paid() : false } }));
  await page.route(/\/api\/render\/frame/, (r) => r.fulfill({ json: { id: "t69-" + rnd() } }));
  await page.route(/\/api\/render(\?.*)?$/, (r) => {
    let b: { quality?: string } = {};
    try { b = JSON.parse(r.request().postData() || "{}") as { quality?: string }; } catch { /* не JSON */ }
    o.renders?.push({ quality: String(b.quality || "") });
    return r.fulfill({ json: { job: "t69-" + Date.now() } });
  });
  await page.route(/\/api\/job\?/, (r) => r.fulfill({ json: o.job ? o.job() : { status: "running" } }));
  await page.goto(demoUrl(`/demo/${q}`), { waitUntil: "load" });
  await page.waitForFunction(READY, null, { timeout: 90_000 });
  return { page, errors, close: () => ctx.close() };
}

/** Окно гостиной в 3D, сцена готова (у варианта может быть реалистичное фото — тогда окно открылось в «Фото»). */
async function openWalk(page: Page) {
  await page.locator(LIVING).click();
  await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
  await page.evaluate("if (VW.mode !== 'walk') vwMode('walk')");
  await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
  await page.waitForTimeout(1200);
}

// ——— 2.30 тап по предмету ———
test("2.30 тап по предмету в 3D: шторка до верха, строка предмета в верхней трети, подсветка держится (VW.sel); тап мимо — выделение снято", async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  const { page, close } = await demoPage(browser, phone, "?live=force");
  await openWalk(page);
  // точки холста в средней полосе (края — поворот), где сверху лежит сам холст (не ценник, не шторка): предмет и пустое место
  const pts = await page.evaluate(() => {
    const W = { LIVE: (window as unknown as { __g: (n: string) => unknown }).__g("LIVE") as { canvas: HTMLCanvasElement; scene: { pick: (x: number, y: number) => number } } };
    const cv = W.LIVE.canvas.getBoundingClientRect(), side = document.getElementById("vside")!.getBoundingClientRect();
    let item: { x: number; y: number; i: number } | null = null, empty: { x: number; y: number } | null = null;
    for (let fy = 0.15; fy < 0.95; fy += 0.04) for (let fx = 0.25; fx <= 0.75; fx += 0.05) {
      const x = Math.round(cv.left + cv.width * fx), y = Math.round(cv.top + cv.height * fy);
      if (y >= side.top - 4 || document.elementFromPoint(x, y) !== W.LIVE.canvas) continue;
      const i = W.LIVE.scene.pick(x, y);
      if (i >= 0 && !item) item = { x, y, i };
      if (i < 0 && !empty) empty = { x, y };
    }
    return { item, empty };
  });
  say("точка предмета:", JSON.stringify(pts.item), "· пустая:", JSON.stringify(pts.empty));
  expect(pts.item, "на сцене нет предмета под тапом").not.toBeNull();
  await page.touchscreen.tap(pts.item!.x, pts.item!.y);
  await expect.poll(() => page.evaluate("VW.sel")).toBe(pts.item!.i);
  await expect.poll(() => page.evaluate("document.getElementById('vside').dataset.pos")).toBe("3");
  await page.waitForTimeout(700);
  const row = await page.evaluate((i) => {
    const W = { items: (window as unknown as { __g: (n: string) => unknown }).__g("items") as { sku?: { sid?: string } }[] };
    const r = document.querySelector("#shotbody .row.hl"), sc = document.getElementById("vscroll")!.getBoundingClientRect();
    if (!r) return null;
    const b = r.getBoundingClientRect();
    return { sid: (r as HTMLElement).dataset.sid ?? null, want: W.items[i]?.sku?.sid ?? null, top: Math.round(b.top - sc.top), third: Math.round(sc.height / 3) };
  }, pts.item!.i);
  say("строка:", JSON.stringify(row));
  await shoot(page, "2.30-tap");
  expect(row, "строка предмета не подсвечена").not.toBeNull();
  if (row!.want) expect(row!.sid).toBe(row!.want);                  // строка — того самого предмета (по артикулу)
  expect(row!.top).toBeGreaterThanOrEqual(0);
  expect(row!.top).toBeLessThanOrEqual(row!.third);
  await page.waitForTimeout(1500);
  expect(await page.evaluate("VW.sel"), "подсветка не держится").toBe(pts.item!.i);
  // тап мимо: шторка поднята — пустая точка выше неё (ищем заново: шторка закрыла низ сцены)
  const empty = await page.evaluate(() => {
    const W = { LIVE: (window as unknown as { __g: (n: string) => unknown }).__g("LIVE") as { canvas: HTMLCanvasElement; scene: { pick: (x: number, y: number) => number } } };
    const cv = W.LIVE.canvas.getBoundingClientRect(), side = document.getElementById("vside")!.getBoundingClientRect();
    for (let fy = 0.05; fy < 0.95; fy += 0.02) for (let fx = 0.25; fx <= 0.75; fx += 0.05) {
      const x = Math.round(cv.left + cv.width * fx), y = Math.round(cv.top + cv.height * fy);
      if (y >= side.top - 4 || document.elementFromPoint(x, y) !== W.LIVE.canvas) continue;
      if (W.LIVE.scene.pick(x, y) < 0) return { x, y };
    }
    return null;
  });
  if (!empty) {
    // шторка закрыла всю сцену — свернуть и тапнуть по пустому месту из первого поиска
    await page.evaluate("vwSheet(0)");
    await page.waitForTimeout(600);
  }
  const e = empty ?? pts.empty;
  expect(e, "нет пустой точки на сцене").not.toBeNull();
  await page.touchscreen.tap(e!.x, e!.y);
  await expect.poll(() => page.evaluate("VW.sel")).toBeNull();
  expect(await page.locator("#shotbody .row.hl").count()).toBe(0);
  await close();
});

// ——— 2.31 наведение после замены ———
// Правило карты: точка съёмки — на расстоянии `frameDistCm` (60–180 см по размеру предмета) от его следа, текущая годится при 0,7–1,4
// от нужного; иначе ближайшая точка колец [нужное, +30, +60]; иначе только поворот. Новый предмет — в середине кадра.
test("2.31 после «Заменить»: 3D, шторка свёрнута, камера на расстоянии по размеру предмета, новый предмет в середине кадра", async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  const { page, close } = await demoPage(browser, phone, "?live=force");
  await openWalk(page);
  await page.locator("#vgrip").click();
  await expect.poll(() => page.evaluate("document.getElementById('vside').dataset.pos")).toBe("3");
  // предмет мебели с лентой замен: первый «Заменить» в списке; номер предмета — `sel` после нажатия
  await page.locator("#shotbody [data-rep]").first().click();
  const k = await page.evaluate("items.indexOf(sel)") as number;
  expect(k).toBeGreaterThanOrEqual(0);
  await page.locator("#sheet .mini:has-text('Заменить')").first().click();
  await expect.poll(() => page.evaluate("LIVE.framed || null"), { timeout: 60_000 }).not.toBeNull();
  await page.waitForFunction("LIVE.state === 'ready'", null, { timeout: 60_000 });
  // камера доехала: поза не меняется 0,8 с
  let pose = "";
  for (let i = 0; i < 20; i++) { await page.waitForTimeout(400); const p = JSON.stringify(await page.evaluate("LIVE.scene.pose()")); if (p === pose) break; pose = p; }
  const m = await page.evaluate((k) => {
    const g = (window as unknown as { __g: (n: string) => unknown }).__g;
    const W = { VW: g("VW") as { mode: string }, LIVE: g("LIVE") as { framed: string; canvas: HTMLCanvasElement; scene: { pose: () => { x: number; y: number }; pins: () => { index: number; x: number; y: number; visible: boolean; box: number[] | null }[] } },
      items: g("items") as { x: number; y: number; w: number; d: number; h?: number; rot?: number; role: string }[] };
    const it = W.items[k]!, p = W.LIVE.scene.pose(), cv = W.LIVE.canvas.getBoundingClientRect();
    // расстояние до следа (прямоугольник w×d с поворотом rot) — как `obstacleDistanceCm`
    const a = -((it.rot || 0) * Math.PI) / 180, dx = p.x - it.x, dy = p.y - it.y;
    const lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a);
    const ex = Math.max(0, Math.abs(lx) - it.w / 2), ey = Math.max(0, Math.abs(ly) - it.d / 2);
    const want = Math.max(60, Math.min(180, Math.max(it.w, it.h || 0) / 2 / Math.tan((72 * Math.PI) / 360) / 0.45 - it.d / 2));
    const pin = W.LIVE.scene.pins().find((q) => q.index === k);
    const cx = pin?.box ? (pin.box[0]! + pin.box[2]!) / 2 : pin?.x ?? -1;
    return { role: it.role, framed: W.LIVE.framed, mode: W.VW.mode, pos: document.getElementById("vside")!.dataset.pos,
      edge: Math.round(Math.hypot(ex, ey)), want: Math.round(want), fx: cv.width ? +(cx / cv.width).toFixed(2) : -1, seen: !!pin?.box };
  }, k);
  say("после замены:", JSON.stringify(m));
  await shoot(page, "2.31-framed");
  expect(m.mode).toBe("walk");
  expect(m.pos).toBe("0");
  expect(["turn", "move", "none"]).toContain(m.framed);
  expect(m.seen, "новый предмет не в кадре").toBe(true);
  expect(m.fx, "новый предмет не в середине кадра").toBeGreaterThanOrEqual(0.3);
  expect(m.fx).toBeLessThanOrEqual(0.7);
  if (m.framed === "turn") { expect(m.edge).toBeGreaterThanOrEqual(m.want * 0.7 - 5); expect(m.edge).toBeLessThanOrEqual(m.want * 1.4 + 5); }
  if (m.framed === "move") { expect(m.edge).toBeGreaterThanOrEqual(m.want - 10); expect(m.edge).toBeLessThanOrEqual(m.want + 75); }
  await close();
});

// ——— 2.32 окно на компьютере ———
test("2.32 компьютер: окно без полос, сцена во всю высоту области, «Сделать реалистичнее» стоит под плашкой «Остаток» и не уезжает", async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  const { page, close } = await demoPage(browser, desk, "?live=force");
  await openWalk(page);
  const geo = () => page.evaluate(() => {
    const R = (s: string) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return { l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom), h: Math.round(b.height), w: Math.round(b.width) }; };
    const cta = document.getElementById("vCta")!;
    return { wrap: R("#shot .shotwrap"), cv: R("#shot .livecv"), sum: R("#vsum"), cta: R("#vCta"), scroll: R("#vscroll"), ctaInScroll: !!cta.closest("#vscroll"),
      ctaVisible: !!cta.offsetParent && !cta.hidden, ctaText: cta.innerText.trim(), sh: document.getElementById("vscroll")!.scrollHeight };
  });
  const a = await geo();
  say("компьютер:", JSON.stringify(a));
  await shoot(page, "2.32-desk");
  expect(a.cv && a.wrap).toBeTruthy();
  // без полос: холст сцены занимает всю область кадра (по высоте и ширине)
  expect(Math.abs(a.cv!.t - a.wrap!.t)).toBeLessThanOrEqual(1);
  expect(Math.abs(a.cv!.h - a.wrap!.h)).toBeLessThanOrEqual(1);
  expect(Math.abs(a.cv!.w - a.wrap!.w)).toBeLessThanOrEqual(1);
  // кнопка — вне прокрутки списка, под плашкой сертификата
  expect(a.ctaVisible).toBe(true);
  expect(a.ctaText).toMatch(/реалистичнее/);
  expect(a.ctaInScroll).toBe(false);
  expect(a.cta!.t).toBeGreaterThanOrEqual(a.sum!.b - 1);
  expect(a.cta!.t - a.sum!.b).toBeLessThanOrEqual(40);
  expect(a.cta!.b).toBeLessThanOrEqual(a.scroll!.t + 1);
  await page.evaluate("document.getElementById('vscroll').scrollTop = 1e6");
  await page.waitForTimeout(400);
  const b = await geo();
  say("после прокрутки списка:", JSON.stringify(b.cta), "высота списка", b.sh);
  expect(b.cta).toEqual(a.cta);
  await close();
});

// ——— 2.39 чтение избранного пачками ———
// 60 избранных, которых на сервере нет: три пачки (25+25+10). Первая — 429 с Retry-After 1, потом настоящий сервер; вторая — 503 один раз;
// третья — 503 всегда (после 4 попыток — «не прочитана»). «Недоступна» — только та, о которой сервер сам ответил, что её нет.
test("2.39 избранное читается пачками по 25 с повтором после 429/5xx; «недоступна» — только если коллекции нет на сервере; отказ включения называет причину", async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  const { page, close } = await demoPage(browser, desk);
  const apt = await page.evaluate("(window.__basket.state() || {}).apartmentId") as string;
  const ids = Array.from({ length: 60 }, () => rnd());
  await page.evaluate(([apt, ids]) => {
    const fav = (id: string, k: number) => ({ favoriteId: id, roomId: "living", roomKind: "living", styleId: "t69", stateId: "t69-" + k, sourceVariantId: "t69",
      displayName: "Проверка #" + (k + 1), autoName: false, createdAt: Date.now() - k, quote: { status: "pending", currency: "RUB", at: 0, lines: [] } });
    localStorage.setItem("remlab-basket:v2:" + apt, JSON.stringify({ v: 2, apartmentId: apt, favorites: (ids as string[]).map(fav), includedByRoom: {} }));
  }, [apt, ids] as const);
  const batches = new Map<string, number>(), log: { at: number; key: string; n: number; status: number }[] = [];
  let single = 0;
  const t0 = Date.now();
  await page.unroute(/\/api\/collections(\/[\w-]+)?(\?.*)?$/);
  await page.route(/\/api\/collections/, async (r) => {
    const u = new URL(r.request().url());
    if (u.pathname !== "/api/collections") { single++; return r.fulfill({ status: 404, json: { ok: false } }); }
    const got = (u.searchParams.get("ids") || "").split(",").filter(Boolean);
    const key = got[0] ?? "", k = ids.indexOf(key), part = k < 25 ? 0 : k < 50 ? 1 : 2, n = (batches.get(key) ?? 0) + 1;
    batches.set(key, n);
    const status = part === 0 && n === 1 ? 429 : part === 1 && n === 1 ? 503 : part === 2 ? 503 : 200;
    log.push({ at: Date.now() - t0, key: String(part), n: got.length, status });
    if (status === 429) return r.fulfill({ status, headers: { "retry-after": "1" }, json: { ok: false } });
    if (status !== 200) return r.fulfill({ status, json: { ok: false } });
    return r.continue();                                            // настоящий сервер: таких коллекций у него нет
  });
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(READY, null, { timeout: 90_000 });
  // третья пачка: 1+2+4 с повторов — итог через ~7 с
  await expect.poll(() => log.filter((x) => x.key === "2").length, { timeout: 30_000 }).toBe(4);
  await page.waitForTimeout(1500);
  const st = await page.evaluate((ids) => {
    const b = (window as unknown as { __basket: { state: () => { favorites: { favoriteId: string; quote: { status: string } }[] } } }).__basket.state();
    const by = Object.fromEntries(b.favorites.map((f) => [f.favoriteId, f.quote.status]));
    return { gone: ids.slice(0, 50).filter((i) => by[i] === "unavailable").length, failedMarked: ids.slice(50).filter((i) => by[i] === "unavailable").length, n: b.favorites.length };
  }, ids);
  const gaps = (p: string) => log.filter((x) => x.key === p).map((x) => x.at).map((t, i, a) => (i ? t - a[i - 1]! : 0)).slice(1);
  say("запросы:", JSON.stringify(log));
  say("паузы повторов, мс: 429 →", gaps("0").join(","), "· 503 один раз →", gaps("1").join(","), "· 503 всегда →", gaps("2").join(","));
  say("состояние:", JSON.stringify(st), "· чтений по одной:", single);
  expect(Math.max(...log.map((x) => x.n)), "пачка больше 25").toBeLessThanOrEqual(25);
  expect(new Set(log.map((x) => x.key)).size).toBe(3);
  expect(single, "читали по одной — пачки не работают").toBe(0);
  expect(gaps("0")[0]).toBeGreaterThanOrEqual(950);                // Retry-After 1 (и не меньше 1 с)
  expect(gaps("1")[0]).toBeGreaterThanOrEqual(950);
  const g2 = gaps("2");
  expect(g2[0]).toBeGreaterThanOrEqual(950); expect(g2[1]).toBeGreaterThanOrEqual(1900); expect(g2[2]).toBeGreaterThanOrEqual(3800);
  expect(st.gone, "коллекций нет на сервере — «недоступна»").toBe(50);
  expect(st.failedMarked, "сбой сети не должен делать «недоступна»").toBe(0);
  // отказ включения называет причину
  await page.evaluate((id) => (window as unknown as { __fav: { include: (id: string) => void } }).__fav.include(id), ids[0]!);
  await expect(page.locator("#toast")).toContainText("больше недоступна");
  say("отказ включения:", await page.locator("#toast").innerText());
  await close();
});

// ——— 2.40 страница под слоем стоит ———
test("2.40 под любым полноэкранным слоем страница стоит (body fixed), после закрытия — то же место (375×667, 390×844, 1440×900)", async ({ browser }) => {
  test.setTimeout(6 * 60_000);
  const bad: string[] = [];
  for (const vp of [phone, { ...phone, viewport: { width: 390, height: 844 } }, desk]) {
    const label = `${vp.viewport!.width}×${vp.viewport!.height}`;
    const { page, close } = await demoPage(browser, vp, "?live=force");
    const isDesk = !vp.isMobile;
    // закрыть, как человек: на телефоне — «×» (первый может только свернуть шторку), на компьютере — Esc
    const shutShot = async () => {
      for (let i = 0; i < 3 && (await page.locator("#shot.on").count()); i++) {
        if (isDesk) await page.keyboard.press("Escape"); else await page.locator("#shotx").click();
        await page.waitForTimeout(400);
      }
      await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/);
    };
    const layers: [string, () => Promise<void>, () => Promise<void>][] = [
      ["окно варианта #shot", async () => { await page.locator(LIVING).click(); await expect(page.locator("#shot")).toHaveClass(/\bon\b/); }, shutShot],
      ["лента замен #sheet в окне", async () => {
        await page.locator(LIVING).click(); await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
        await page.evaluate("if (VW.mode === 'photo') vwMode('walk'); if (window.vwSheet) vwSheet(3)"); await page.waitForTimeout(500);
        await page.locator("#shotbody [data-rep]").first().click(); await expect(page.locator("#sheet")).toHaveClass(/\bopen\b/);
      }, async () => {
        const st = async () => await page.evaluate("({ shot: document.getElementById('shot').classList.contains('on'), sheet: document.getElementById('sheet').classList.contains('open'), pos: document.body.style.position })") as { shot: boolean; sheet: boolean; pos: string };
        await shoot(page, `2.40-sheet-0-open-${label}`);
        if (isDesk) {
          // компьютер: Esc закрывает ВЕРХНИЙ слой, по одному за нажатие — сперва ленту замен (окно под ней остаётся), потом окно
          await page.keyboard.press("Escape"); await page.waitForTimeout(400);
          const a = await st(); await shoot(page, `2.40-sheet-1-esc-${label}`);
          if (!a.shot && a.sheet) bad.push(`${label} лента замен: Esc закрыл окно, а лента замен осталась открытой поверх главной (страница заперта)`);
          else if (a.sheet) bad.push(`${label} лента замен: первый Esc ленту не закрыл`);
          else if (!a.shot) bad.push(`${label} лента замен: первый Esc закрыл и ленту, и окно под ней — ждали по одному слою`);
          await page.keyboard.press("Escape"); await page.waitForTimeout(400);
          const b = await st(); await shoot(page, `2.40-sheet-2-esc-${label}`);
          if (b.shot) bad.push(`${label} лента замен: второй Esc окно варианта не закрыл`);
          if (!b.shot && !b.sheet && b.pos === "fixed") bad.push(`${label} лента замен: все слои закрыты, а body всё ещё fixed`);
        } else {
          // телефон: как раньше — «×» ленты, потом «×» окна
          if (await page.locator("#sheet.open").count()) { await page.locator("#sh-close").click(); await page.waitForTimeout(400); }
          const a = await st(); await shoot(page, `2.40-sheet-1-x-${label}`);
          if (a.sheet) bad.push(`${label} лента замен: «×» ленту не закрыл`);
          if (!a.shot) bad.push(`${label} лента замен: «×» ленты закрыл и окно варианта`);
        }
        if (await page.locator("#sheet.open").count()) { await page.locator("#sh-close").click(); await page.waitForTimeout(400); }
        await shutShot();
        await shoot(page, `2.40-sheet-3-closed-${label}`);
      }],
      ["конструктор #cons", async () => {
        await page.locator(LIVING).click(); await page.locator('#shot [data-vm="plan"]').click(); await page.locator("#vCta").click();
        await expect(page.locator("#cons")).toHaveClass(/\bon\b/);
      }, async () => {
        if (isDesk) await page.keyboard.press("Escape"); else await page.locator("#consDone").click();
        await page.waitForTimeout(400);
        // не закрылся — запись в список и «Готово», чтобы прогон дошёл до конца и показал все находки разом
        if (await page.locator("#cons.on").count()) {
          bad.push(`${label} конструктор: ${isDesk ? "Esc" : "«Готово»"} его не закрыл`);
          await page.locator("#consDone").click(); await page.waitForTimeout(400);
        }
        await expect(page.locator("#cons")).not.toHaveClass(/\bon\b/);
        await shutShot();
      }],
      ["окошко имени #favPop", async () => {
        await page.locator(LIVING).click(); await page.waitForSelector("#vFav:visible"); await page.locator("#vFav").click();
        await expect(page.locator("#favPop")).toBeVisible();
      }, async () => {
        await page.locator("#favNo").click(); await expect(page.locator("#favPop")).toHaveCount(0);
        await shutShot();
      }],
    ];
    for (const [name, open, shut] of layers) {
      await page.evaluate("scrollTo(0, 250)");
      await page.waitForTimeout(300);
      // сколько реально прокрутилось (на 1440×900 главная короче — максимум ~67 px): от этого места и ждём сдвиг body
      const y0 = await page.evaluate("Math.round(scrollY)") as number;
      if (y0 < 20) bad.push(`${label} ${name}: главная не прокручивается (scrollY ${y0}) — нечем проверить`);
      const top0 = await page.evaluate("Math.round(document.getElementById('hmRooms').getBoundingClientRect().top)") as number;
      await open();
      await page.waitForTimeout(400);
      const s1 = await page.evaluate("({pos: document.body.style.position || getComputedStyle(document.body).position, top: document.body.style.top, rooms: Math.round(document.getElementById('hmRooms').getBoundingClientRect().top)})") as { pos: string; top: string; rooms: number };
      await page.mouse.wheel(0, 600);                                 // жест по слою не листает главную
      await page.waitForTimeout(400);
      const rooms2 = await page.evaluate("Math.round(document.getElementById('hmRooms').getBoundingClientRect().top)") as number;
      await shut();
      await page.waitForTimeout(400);
      const after = await page.evaluate("({y: Math.round(scrollY), rooms: Math.round(document.getElementById('hmRooms').getBoundingClientRect().top)})") as { y: number; rooms: number };
      say(`${label} ${name}: body ${s1.pos} top ${s1.top}; комнаты ${top0} → ${s1.rooms} → после жеста ${rooms2} → после закрытия ${after.rooms}, scrollY ${after.y}`);
      if (s1.pos !== "fixed") bad.push(`${label} ${name}: body не fixed (${s1.pos})`);
      if (s1.top !== `-${y0}px`) bad.push(`${label} ${name}: сдвиг body ${s1.top}, ждали -${y0}px`);
      if (Math.abs(rooms2 - top0) > 1) bad.push(`${label} ${name}: страница под слоем сдвинулась ${top0} → ${rooms2}`);
      if (Math.abs(after.y - y0) > 1 || Math.abs(after.rooms - top0) > 1) bad.push(`${label} ${name}: после закрытия scrollY ${after.y} (было ${y0}), комнаты ${top0} → ${after.rooms}`);
    }
    await close();
  }
  expect(bad, bad.join("\n")).toEqual([]);
});

// ——— 2.41–2.42 шкала сертификата и сообщения ———
const scale = (page: Page, root: string) => page.evaluate((root) => {
  const c = document.querySelector(root + " .cs");
  if (!c) return null;
  const w = (s: string) => { const e = c.querySelector(s) as HTMLElement | null; return e ? +(parseFloat(e.style.width) || 0).toFixed(2) : -1; };
  const L = c.querySelector(".cs-l")!.getBoundingClientRect(), R = c.querySelector(".cs-r")!.getBoundingClientRect();
  return { left: (c.querySelector(".cs-l") as HTMLElement).innerText.trim(), chosen: Number((c.querySelector(".cs-l b[data-k=inc]") as HTMLElement).dataset.to),
    right: (c.querySelector(".cs-r") as HTMLElement).innerText.trim(), leftIsLeft: L.right <= R.left, s: w(".sg i.s"), pv: w(".sg i.pv"),
    info: !!c.querySelector("button.vpl-i"), meters: c.querySelectorAll("[role=meter]").length };
}, root);
const MONEY = /[\d\s  ]+₽/;
const rub = (t: string) => Number((t.match(/([\d\s  ]+)₽/)?.[1] ?? "").replace(/\D/g, ""));
test("2.41–2.42 одна шкала сертификата (главная, окно, избранное) и сообщения: вид .msg, «включено, остаток N», доплата с подтверждением", async ({ browser }) => {
  test.setTimeout(6 * 60_000);
  const { page, close } = await demoPage(browser, phone, "?live=force");
  // главная — липкий низ (home-figma-02): «Выбрано N» = сумма вариантов всех комнат главной (ведущий 07.11), справа — сумма сертификата
  // без слова «сертификат», «i» на месте
  const h0 = await scale(page, "#hmCert");
  expect(h0).not.toBeNull();
  const total = rub(h0!.right);
  const home = Math.round(await page.evaluate("homeChosen()") as number);
  say("главная до выбора:", JSON.stringify(h0), "· сертификат", total, "· комнаты главной", home);
  expect(h0!.left).toMatch(/^Выбрано/);
  expect(home).toBeGreaterThan(0);
  expect(h0!.chosen).toBe(home);
  expect(rub(h0!.right), "справа — сумма сертификата").toBeGreaterThan(0);
  expect(h0!.right).not.toMatch(/сертификат/);
  expect(h0!.leftIsLeft).toBe(true);
  expect(h0!.s).toBeGreaterThan(0);
  expect(h0!.info).toBe(true);
  // окно: та же шкала; светлая часть — что добавит эта расстановка
  await page.locator(LIVING).click();
  await page.waitForSelector("#vFav:visible");
  const sum = Number(await page.locator("#vsum").getAttribute("data-sum"));
  const w0 = await scale(page, "#vsum");
  say("окно до выбора:", JSON.stringify(w0), "сумма расстановки", sum);
  expect(w0!.left).toMatch(/^Выбрано/);
  expect(rub(w0!.right)).toBe(rub(h0!.right));
  expect(w0!.pv, "светлая часть «добавит эта расстановка» пустая").toBeGreaterThan(0);
  // «i» — остаток и как включить (ничего не выбрано — остаток = весь сертификат: «Вам доступно N»)
  await page.locator("#vsum button.vpl-i").click();
  const bub = (await page.locator("#vsum .vpl-bub").innerText()).replace(/\s+/g, " ");
  say("пузырь «i» окна:", bub.slice(0, 200));
  expect(bub).toMatch(/доступн/);
  expect(rub(bub.split(".")[0]!), "в «i» — не остаток").toBe(total);
  expect(bub).toMatch(/включить/);
  await page.locator("#vsum button.vpl-i").click();
  // сохранили — первая гостиная включилась сама: сообщение «… включено в сертификат, остаток N»
  await page.locator("#vFav").click();
  await page.locator("#favOk").click();
  await expect(page.locator("#toast")).toContainText(/включено в сертификат, остаток/, { timeout: 30_000 });
  const t1 = await page.locator("#toast").innerText();
  say("сообщение после сохранения:", t1);
  expect(t1).toMatch(/«[^»]+» — (в избранном, )?включено в сертификат, остаток [\d\s  ]+₽/);
  // вид сообщения — один: полупрозрачный фон, ширина min(92vw, 560px)
  const look = await page.evaluate("(() => { const e = document.getElementById('toast'), c = getComputedStyle(e); return { cls: e.className, bg: c.backgroundColor, w: Math.round(e.getBoundingClientRect().width), vw: innerWidth }; })()") as { cls: string; bg: string; w: number; vw: number };
  say("вид сообщения:", JSON.stringify(look));
  await shoot(page, "2.42-toast-phone");
  expect(look.cls).toMatch(/\bmsg\b/);
  const alpha = Number(look.bg.match(/rgba?\(([^)]+)\)/)?.[1]?.split(",")[3] ?? 1);
  expect(alpha, "фон сообщения непрозрачный").toBeLessThan(1);
  expect(look.w).toBe(Math.round(Math.min(look.vw * 0.92, 560)));
  // шкала главной после сохранения — по-прежнему выбор комнат главной (корзина её не меняет); полоса = выбрано; «i» — остаток
  await page.keyboard.press("Escape");
  const h1 = await scale(page, "#hmCert");
  const home1 = Math.round(await page.evaluate("homeChosen()") as number);
  say("главная после выбора:", JSON.stringify(h1));
  expect(h1!.chosen).toBe(home1);
  expect(h1!.s).toBeCloseTo(Math.min(100, (home1 / Math.max(total, home1)) * 100), 0);
  await page.locator("#hmCert button.vpl-i").click();
  const hb = (await page.locator("#hmCert .vpl-bub").innerText()).replace(/\s+/g, " ");
  say("пузырь «i» главной:", hb.slice(0, 200));
  if (home1 <= total) {
    expect(hb).toMatch(/Осталось/);
    expect(rub(hb.split("Осталось")[1]!), "остаток в «i»").toBe(total - home1);
  } else expect(hb).toMatch(/Доплата/);
  await page.locator("#hmCert button.vpl-i").click();
  // липкий низ — только на главной; на экране избранного его нет
  await page.evaluate("window.__basket.open('living')");
  await expect(page.locator("#screen-fav")).toBeVisible();
  await expect(page.locator("#hmBot")).toBeHidden();
  // своё имя: «Гостиная «<имя>» — включено…» (не включать → включить снова)
  const id = await page.evaluate("Object.values(window.__basket.state().includedByRoom)[0]") as string;
  await page.evaluate(([id]) => { const F = (window as unknown as { __fav: { rename: (i: string, n: string) => Promise<void>; exclude: (i: string) => void } }).__fav; return F.rename(id!, "Проверка").then(() => F.exclude(id!)); }, [id]);
  await page.waitForTimeout(400);
  await page.evaluate(([id]) => (window as unknown as { __fav: { include: (i: string) => void } }).__fav.include(id!), [id]);
  await expect(page.locator("#toast")).toContainText(/включено в сертификат/);
  const t2 = await page.locator("#toast").innerText();
  say("своё имя:", t2);
  expect(t2).toMatch(/^Гостиная «Проверка» — включено в сертификат, остаток [\d\s  ]+₽$/);
  await close();
  // компьютер: ширина сообщения 560
  const d = await demoPage(browser, desk);
  await d.page.evaluate("toast('Проверка вида сообщения')");
  const dw = await d.page.evaluate("Math.round(document.getElementById('toast').getBoundingClientRect().width)") as number;
  say("компьютер: ширина сообщения", dw);
  expect(dw).toBe(560);
  await d.close();
  // доплата: мебель 100 000 — «Доплата N — подтвердить?»; после «Подтвердить» — «… включено в сертификат, доплата N»
  const o = await demoPage(browser, phone, "?live=force", { pkg: { mode: "pooled", limits: { furniture: 100_000, fitout: 0 } } });
  await o.page.locator(LIVING).click();
  await o.page.waitForSelector("#vFav:visible");
  await o.page.locator("#vFav").click();
  await o.page.locator("#favOk").click();
  await expect(o.page.locator("#favPop")).toContainText(/Доплата [\d\s  ]+₽ — подтвердить\?/, { timeout: 30_000 });
  const ask = rub(await o.page.locator("#favPop b").first().innerText());
  await o.page.locator("#favPop button.primary").click();
  await expect(o.page.locator("#toast")).toContainText(/включено в сертификат, доплата/);
  const t3 = (await o.page.locator("#toast").innerText()).replace(/\s*Перейти\s*→\s*$/, "");   // «Перейти →» — кнопка в сообщении, не текст
  say("доплата:", ask, "→", t3);
  await shoot(o.page, "2.42-topup");
  expect(t3).toMatch(/«[^»]+» — включено в сертификат, доплата [\d\s  ]+₽$/);
  expect(rub(t3)).toBe(ask);
  await o.close();
  expect(MONEY.test(t1)).toBe(true);
});

// ——— 2.43 ожидание фото ———
test("2.43 «Сделать реалистичнее»: полоса и «осталось N с» от 30 вниз; после нуля «ещё немного…», полоса до 99 %; без «2–4 минуты»", async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  const renders: { quality: string }[] = [];
  const { page, close } = await demoPage(browser, desk, "?live=force", { renders });
  await page.evaluate("shots = shots.filter((x) => x.quality !== 'realistic'); openLiveWindow()");
  await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
  await expect(page.locator("#vCta")).toHaveText(/реалистичнее/);
  const t0 = Date.now();
  await page.locator("#vCta").click();
  const read = () => page.evaluate(() => {
    const cta = document.getElementById("vCta")!, ov = document.querySelector("#shot .vphwait");
    const pct = (e: Element | null) => (e ? parseFloat((e as HTMLElement).style.width) || 0 : -1);
    return { mode: ((window as unknown as { __g: (n: string) => unknown }).__g("VW") as { mode: string }).mode, btn: cta.querySelector(".vcta-t")?.textContent ?? "", btnBar: pct(cta.querySelector(".vcta-bar")),
      ov: ov?.querySelector("small")?.textContent ?? null, ovBar: pct(ov?.querySelector("s") ?? null), ovHead: ov?.querySelector("b")?.textContent ?? null, all: document.getElementById("shot")!.innerText };
  });
  await expect.poll(async () => (await read()).btn, { timeout: 20_000, intervals: [100] }).toMatch(/осталось \d+ с/);
  const a = await read(), sa = (Date.now() - t0) / 1000, ta = Date.now();
  await page.waitForTimeout(3000);
  const b = await read(), sb = (Date.now() - t0) / 1000;
  const left = (t: string | null) => Number(t?.match(/осталось (\d+) с/)?.[1] ?? NaN);
  say(`через ${sa.toFixed(1)} с:`, JSON.stringify({ ...a, all: undefined }));
  say(`через ${sb.toFixed(1)} с:`, JSON.stringify({ ...b, all: undefined }));
  await shoot(page, "2.43-wait");
  expect(renders.map((r) => r.quality)).toContain("realistic");     // задание ушло (подмена — денег нет)
  expect(a.btn).toMatch(/^Улучшаю · осталось \d+ с$/);
  // первый отсчёт — сразу после старта задания: 30 (съёмка кадров до него не считается — задание стартует после)
  expect(left(a.btn)).toBeLessThanOrEqual(30);
  expect(left(a.btn)).toBeGreaterThanOrEqual(28);
  expect(left(b.btn)).toBeLessThan(left(a.btn));                    // отсчёт идёт вниз
  expect(b.btnBar).toBeGreaterThan(a.btnBar);
  if (a.mode === "photo") { expect(a.ov).toMatch(/^осталось \d+ с$/); expect(a.ovBar).toBeGreaterThan(0); }
  // ноль — через ~N с после первого отсчёта N; ждём его + 3 с
  await page.waitForTimeout(Math.max(0, (left(a.btn) + 3) * 1000 - (Date.now() - ta)));
  const c = await read();
  say("после 30 с:", JSON.stringify({ ...c, all: undefined }));
  await shoot(page, "2.43-after30");
  expect(c.btn).toMatch(/ещё немного…/);
  expect(c.btnBar).toBeGreaterThanOrEqual(95);
  expect(c.btnBar).toBeLessThanOrEqual(99);
  if (c.mode === "photo") expect(c.ov).toBe("ещё немного…");
  expect(c.all).not.toMatch(/2[–-]4 минут/);
  await page.waitForTimeout(30_000);
  const d = await read();
  say("через минуту:", d.btnBar);
  expect(d.btnBar).toBeLessThanOrEqual(99);
  await close();
});

// ——— 2.44 «во весь экран» ———
const FAKE_SHOTS = ["/demo/img/og.jpg", "/demo/img/og.jpg?v=2"];
async function realWindow(page: Page) {
  // настоящие реалистичные снимки этой расстановки, если есть; нет — два снимка подменой задания (как 2.25), денег не тратим
  await page.locator(LIVING).click();
  await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
  if (((await page.evaluate("vwRealShots().length")) as number) >= 2) return "настоящие";
  return "подмена";
}
test("2.44 «во весь экран»: свайп вбок — соседний ракурс, вниз — закрыть; подписи как в окне; стрелки только с мышью; ←/→/Esc", async ({ browser }) => {
  test.setTimeout(5 * 60_000);
  for (const [label, vp] of [["компьютер", desk], ["телефон", phone]] as const) {
    let ready = false;
    const { page, close } = await demoPage(browser, vp, "?live=force", { job: () => ready
      ? { shots: [{ camera: "C1", url: FAKE_SHOTS[0] }, { camera: "C2", url: FAKE_SHOTS[1] }], backend: "fake" } : { status: "running" } });
    const src = await realWindow(page);
    if (src === "подмена") {
      await page.evaluate("if (VW.mode !== 'walk') vwMode('walk')");
      await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
      await page.locator("#vCta").click();
      ready = true;
      await expect.poll(() => page.evaluate("vwRealShots().length"), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
      await page.evaluate("if (VW.mode !== 'photo') vwMode('photo')");
    }
    await expect.poll(() => page.evaluate("VW.mode")).toBe("photo");
    const camLabels = (await page.locator("#vCams [data-cam]").allInnerTexts()).map((t) => t.trim());
    const photo0 = await page.evaluate("VW.photo") as number;
    if (label === "компьютер") await page.locator("#vzBtn").click();
    else await page.locator("#shot .shotwrap img.vmain").tap();
    await expect(page.locator("#vzoom")).toHaveClass(/\bon\b/);
    const st = () => page.evaluate(() => {
      const z = document.getElementById("vzoom")!;
      return { on: z.classList.contains("on"), at: Number(z.dataset.at), src: (z.querySelector("img") as HTMLImageElement | null)?.getAttribute("src") ?? "",
        arrows: [...z.querySelectorAll(".vzarr")].filter((e) => getComputedStyle(e).display !== "none" && !(e as HTMLElement).hidden).length,
        labels: [...z.querySelectorAll(".vzcams [data-zi]")].map((e) => (e as HTMLElement).innerText.trim()) };
    });
    const s0 = await st();
    say(`${label} (${src} снимки): открыл`, JSON.stringify(s0), "· подписи окна", camLabels.join(" | "));
    await shoot(page, `2.44-${label}`);
    expect(s0.labels).toEqual(camLabels);
    expect(s0.at).toBe(photo0);
    if (label === "компьютер") {
      expect(s0.arrows, "стрелки с мышью").toBe(2);
      // смена ракурса — с анимацией 200 мс (`vwZoom` → `go`)
      await page.keyboard.press("ArrowRight"); await page.waitForTimeout(500);
      const s1 = await st();
      say("→:", JSON.stringify(s1));
      expect(s1.at).toBe((photo0 + 1) % camLabels.length);
      expect(s1.src).not.toBe(s0.src);
      await page.keyboard.press("ArrowLeft"); await page.waitForTimeout(500);
      expect((await st()).at).toBe(photo0);
      await page.keyboard.press("ArrowRight"); await page.waitForTimeout(500);
      await page.keyboard.press("Escape");
      await expect(page.locator("#vzoom")).not.toHaveClass(/\bon\b/);
      expect(await page.evaluate("VW.photo"), "выбранный ракурс вернулся в окно").toBe((photo0 + 1) % camLabels.length);
    } else {
      expect(s0.arrows, "на телефоне стрелок нет").toBe(0);
      const vw = vp.viewport!.width, vh = vp.viewport!.height;
      const drag = async (x0: number, y0: number, x1: number, y1: number) => {
        await page.mouse.move(x0, y0); await page.mouse.down();
        for (let i = 1; i <= 6; i++) { await page.mouse.move(x0 + ((x1 - x0) * i) / 6, y0 + ((y1 - y0) * i) / 6); await page.waitForTimeout(25); }
        await page.mouse.up();
      };
      await drag(vw * 0.8, vh * 0.5, vw * 0.2, vh * 0.52);            // свайп влево — следующий ракурс
      await page.waitForTimeout(600);
      const s1 = await st();
      say("свайп влево:", JSON.stringify(s1));
      expect(s1.at).toBe((photo0 + 1) % camLabels.length);
      await drag(vw * 0.5, vh * 0.3, vw * 0.52, vh * 0.75);           // вниз — закрыть
      await expect(page.locator("#vzoom")).not.toHaveClass(/\bon\b/);
    }
    await close();
  }
});

// ——— 2.45 замена пары ———
test("2.45 замена одного из одинаковых (стулья ×2, кресла ×2) меняет все такие же, с размерами; «Заменено: стулья ×2 · ±N ₽» — разница по списку покупок", async ({ browser }) => {
  test.setTimeout(5 * 60_000);
  const { page, close } = await demoPage(browser, desk, "?live=force");
  // стиль, где у гостиной есть пара одинаковых (одна роль, один товар)
  const S = await homeStyles(page);
  let found: { base: string; idx: number[] } | null = null;
  for (let i = 0; i < S.length && !found; i++) {
    await pickStyle(page, S[i]!.id);   // квартира в этом стиле (home-mix-01 шаг 5: вкладок стилей больше нет)
    await page.locator(LIVING).click();
    await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
    found = await page.evaluate(() => {
      const g = (window as unknown as { __g: (n: string) => unknown }).__g;
      const W = { items: g("items") as { role: string; dec?: number; sku?: { name?: string } }[], baseRole: g("baseRole") as (r: string) => string };
      const grp = new Map<string, number[]>();
      W.items.forEach((it, k) => { if (it.dec !== undefined || !it.sku?.name) return; const key = W.baseRole(it.role) + "|" + it.sku.name; grp.set(key, [...(grp.get(key) ?? []), k]); });
      for (const [key, idx] of grp) if (idx.length > 1 && /^(стул|кресло)\|/.test(key)) return { base: key.split("|")[0]!, idx };
      return null;
    });
    if (!found) await page.keyboard.press("Escape");
  }
  say("пара:", JSON.stringify(found));
  expect(found, "ни в одном стиле нет пары одинаковых стульев/кресел").not.toBeNull();
  const k0 = found!.idx[0]!;
  const sum0 = Number(await page.locator("#vsum").getAttribute("data-sum"));
  // «Заменить» у строки этого товара → первая карточка ленты
  await page.evaluate((k) => { (window as unknown as { vwSheet?: (n: number) => void }).vwSheet?.(3); return k; }, k0);
  const row = await page.evaluate((k) => {
    const g = (window as unknown as { __g: (n: string) => unknown }).__g;
    const W = { items: g("items") as { sku?: { sid?: string; name?: string } }[], vwRowOf: g("vwRowOf") as (it: unknown) => Element | null };
    const r = W.vwRowOf(W.items[k]); const b = r?.querySelector("[data-rep]") as HTMLElement | null; return b?.dataset.rep ?? null;
  }, k0);
  expect(row, "у строки пары нет «Заменить»").not.toBeNull();
  await page.locator(`#shotbody [data-rep="${row}"]`).click();
  await expect(page.locator("#sheet .mini:has-text('Заменить')").first()).toBeVisible();
  await page.locator("#sheet .mini:has-text('Заменить')").first().click();
  await expect(page.locator("#toast")).toContainText("Заменено:", { timeout: 30_000 });
  const toastText = await page.locator("#toast").innerText();
  const sum1 = Number(await page.locator("#vsum").getAttribute("data-sum"));
  const after = await page.evaluate((idx) => {
    const W = { items: (window as unknown as { __g: (n: string) => unknown }).__g("items") as { w: number; d: number; h?: number; sku?: { name?: string } }[] };
    return idx.map((k) => { const it = W.items[k]!; return { name: it.sku?.name, w: it.w, d: it.d, h: it.h }; });
  }, found!.idx);
  say("сообщение:", toastText, "· сумма", sum0, "→", sum1, "· после:", JSON.stringify(after));
  await shoot(page, "2.45-pair");
  const plural: Record<string, string> = { "стул": "стулья", "кресло": "кресла" };
  expect(toastText).toMatch(new RegExp(`^Заменено: ${plural[found!.base]} ×${found!.idx.length}( · [+−][\\d\\s  ]+₽)?$`));
  expect(new Set(after.map((a) => a.name)).size, "заменился не каждый из пары").toBe(1);
  expect(new Set(after.map((a) => `${a.w}×${a.d}×${a.h}`)).size, "размеры пары разошлись").toBe(1);
  const d = sum1 - sum0;
  if (d) {
    expect(toastText).toContain(d > 0 ? "+" : "−");
    expect(rub(toastText), "разница в сообщении ≠ разнице суммы списка").toBe(Math.abs(d));
  }
  await close();
});

// ——— 2.46 автофото избранного ———
const AKEY = "remlab-autophoto-v1";
// Строка карты — про расстановку БЕЗ фото. У готовых вариантов прода фото уже есть (`vwRealShots`): тогда `save()` берёт его
// картинкой (`snap.shot`) и ни миниатюры, ни черновика, ни автофото не нужно — это верно. Поэтому сперва меняем предмет
// («Заменить» → первая карточка ленты), пока у состояния не станет фото, и ждём, пока 3D пересоберётся.
async function freshState(page: Page) {
  for (let i = 0; i < 4; i++) {
    await page.evaluate("if (window.vwSheet) vwSheet(3)"); await page.waitForTimeout(400);
    await page.locator("#shotbody [data-rep]").nth(i).click();
    await expect(page.locator("#sheet .mini:has-text('Заменить')").first()).toBeVisible();
    await page.locator("#sheet .mini:has-text('Заменить')").first().click();
    await expect(page.locator("#toast")).toContainText("Заменено", { timeout: 30_000 });
    if (await page.locator("#sheet.open").count()) { await page.locator("#sh-close").click(); await page.waitForTimeout(300); }
    await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
    await page.waitForTimeout(1200);
    if (await page.evaluate("vwRealShots().length === 0")) return;
  }
  throw new Error("за 4 замены не нашлась расстановка без фото");
}
async function saveFav(page: Page) {
  await page.locator("#vFav").click(); await page.locator("#favOk").click();
  await page.waitForFunction("!document.querySelector('#favPop #favName')", null, { timeout: 30_000 });
}
test("2.46 сохранили без фото → автофото: плашка с отсчётом на карточке, одно на состояние, ≤ 10 в сутки, готовое — картинкой; без денег — тихо 3D-снимок", async ({ browser }) => {
  test.setTimeout(5 * 60_000);
  // (а) денег нет: улучшения нет, сообщения об отказе нет, остаётся 3D-снимок (бесплатный черновик)
  {
    const renders: { quality: string }[] = [];
    const { page, close } = await demoPage(browser, phone, "?live=force", { paid: () => false, renders });
    await openWalk(page);
    await freshState(page);
    await saveFav(page);
    const toast = await page.locator("#toast").innerText().catch(() => "");
    // 3D-снимок: миниатюра из сцены (`grabThumb` → `remlab-fav-thumbs`), затем бесплатный черновик коллекции (`snapLater`)
    await expect.poll(() => renders.filter((r) => r.quality === "draft").length, { timeout: 60_000 }).toBeGreaterThanOrEqual(1);
    const s = await page.evaluate((k) => {
      const b = (window as unknown as { __basket: { state: () => { favorites: { favoriteId: string }[] } } }).__basket.state(), id = b.favorites[0]?.favoriteId ?? "";
      const th = JSON.parse(localStorage.getItem("remlab-fav-thumbs") || "{}") as Record<string, string>;
      return { job: !!((window as unknown as { __g: (n: string) => unknown }).__g("VJ") as { job: unknown }).job, ap: localStorage.getItem(k), thumb: (th[id] || "").slice(0, 23) };
    }, AKEY);
    say("без денег:", JSON.stringify(s), "задания:", JSON.stringify(renders), "сообщение:", toast);
    expect(s.job).toBe(false);
    expect(s.ap, "заказ автофото без денег").toBeNull();
    expect(renders.filter((r) => r.quality === "realistic")).toEqual([]);
    expect(s.thumb, "нет миниатюры 3D").toMatch(/^data:image\/jpeg/);
    expect(toast).not.toMatch(/ошиб|не получилось|недоступн|улучш/i);
    await close();
  }
  // (б) лимит суток: 10 уже заказано — новое не заказываем
  {
    const renders: { quality: string }[] = [];
    const { page, close } = await demoPage(browser, phone, "?live=force", { paid: () => true, renders });
    await page.evaluate((k) => { const d = new Date(); localStorage.setItem(k, JSON.stringify({ d: d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(), n: 10, s: {} })); }, AKEY);
    await openWalk(page);
    await freshState(page);
    await saveFav(page);
    // лимит — только на автофото: черновик 3D-снимка уходит, как без денег
    await expect.poll(() => renders.filter((r) => r.quality === "draft").length, { timeout: 60_000 }).toBeGreaterThanOrEqual(1);
    say("лимит 10 в сутки исчерпан — задания:", JSON.stringify(renders));
    expect(renders.filter((r) => r.quality === "realistic"), "11-е автофото за сутки").toEqual([]);
    await close();
  }
  // (в) деньги есть: плашка с отсчётом на карточке, отметка состояния; готовое — картинкой во всех избранных этого состояния
  {
    let ready = false;
    const renders: { quality: string }[] = [];
    const frame = "/test/share/frames/t69-autophoto.jpg";
    const { page, close } = await demoPage(browser, phone, "?live=force", { paid: () => true, renders,
      job: () => ready ? { shots: [{ camera: "C1", url: frame }, { camera: "C2", url: frame.replace(".jpg", "-2.jpg") }], backend: "fake" } : { status: "running" } });
    await openWalk(page);
    await freshState(page);
    const state = await page.evaluate("curStateId()") as string;
    await saveFav(page);
    await expect.poll(() => renders.filter((r) => r.quality === "realistic").length, { timeout: 60_000 }).toBe(1);
    const ap = JSON.parse((await page.evaluate((k) => localStorage.getItem(k), AKEY)) || "{}") as { n: number; s: Record<string, unknown> };
    say("заказано:", JSON.stringify(ap), "состояние", state);
    expect(Object.keys(ap.s)).toContain(state);
    // то же состояние сохранили ещё раз — нового заказа нет (одно фото на stateId)
    await page.waitForTimeout(1500);
    await saveFav(page);
    await page.waitForTimeout(4000);
    const nFav = await page.evaluate(`(window.__basket.state().favorites || []).filter((f) => f.stateId === ${JSON.stringify(state)}).length`) as number;
    say("сохранили то же состояние ещё раз: избранных этого состояния", nFav, "· заданий realistic", renders.filter((r) => r.quality === "realistic").length);
    expect(renders.filter((r) => r.quality === "realistic").length, "второй заказ того же состояния").toBe(1);
    await page.keyboard.press("Escape");
    await page.evaluate("window.__basket.open('living')");
    await expect(page.locator("#favGrid .pwait").first()).toBeVisible({ timeout: 15_000 });
    const pw = await page.locator("#favGrid .pwait").first().innerText();
    say("плашка на карточке:", pw);
    await shoot(page, "2.46-pwait");
    expect(pw).toMatch(/Улучшаю · осталось \d+ с/);
    await page.evaluate("window.__basket.close()");
    ready = true;                                                    // задание готово — ждём картинку в избранном
    await expect.poll(() => page.evaluate("(window.__basket.state().favorites || []).map((f) => f.shot || '').join(',')"), { timeout: 30_000 }).toContain(frame);
    const favs = await page.evaluate("window.__basket.state().favorites.map((f) => ({ st: f.stateId, shot: f.shot || '' }))") as { st: string; shot: string }[];
    say("избранные после готового фото:", JSON.stringify(favs));
    expect(favs.filter((f) => f.st === state).every((f) => f.shot === frame)).toBe(true);
    expect(renders.filter((r) => r.quality === "realistic").length, "одно фото на состояние").toBe(1);
    await close();
  }
});

// ——— 2.47 уголок с банкеткой ———
const SWAP_RULES = JSON.parse(readFileSync(join(ROOT, "tools/scout/rules/demo-swap.json"), "utf8")) as { nook_min_benches: number };
test("2.47 «уголок» с банкеткой — только если в ленте стиля ≥ nook_min_benches банкеток; иначе обычная столовая со стульями и банкетки в списке нет", async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  const { page, close } = await demoPage(browser, desk);
  const rows = await page.evaluate(() => {
    const g = (window as unknown as { __g: (n: string) => unknown }).__g;
    const W = { D: g("D") as { feeds?: Record<string, { styles?: string[]; style?: string }[]> }, allVariants: g("allVariants") as () => { id: string; style: string; items?: { role: string; sku?: { name?: string } }[] }[],
      plainStyle: g("plainStyle") as (s: string) => string, baseRole: g("baseRole") as (r: string) => string };
    const feed = W.D.feeds?.["банкетка"] ?? [];
    return W.allVariants().filter((v) => (v.items ?? []).length).map((v) => {
      const st = W.plainStyle(v.style), its = v.items ?? [];
      const n = feed.filter((p) => (p.styles ? p.styles.includes(st) : !p.style || p.style === st)).length;
      const role = (r: string) => its.filter((i) => W.baseRole(i.role) === r).length;
      return { id: v.id, style: st, benchFeed: n, bench: role("банкетка"), chairs: role("стул"), table: role("стол обеденный") };
    });
  });
  for (const r of rows) say(JSON.stringify(r));
  say("порог из правил:", SWAP_RULES.nook_min_benches);
  expect(rows.length).toBeGreaterThan(0);
  const bad = rows.filter((r) => (r.bench > 0 && r.benchFeed < SWAP_RULES.nook_min_benches) || (r.bench === 0 && r.table > 0 && r.chairs < 2));
  expect(bad, "банкетка без ленты или столовая без стульев").toEqual([]);
  // список покупок окна: банкетки нет там, где её нет в расстановке (стиль без ленты банкеток)
  for (const s of await homeStyles(page)) {
    await pickStyle(page, s.id);
    await page.locator(LIVING).click();
    await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
    const w = await page.evaluate(() => {
      const g = (window as unknown as { __g: (n: string) => unknown }).__g;
      const W = { items: g("items") as { role: string }[], baseRole: g("baseRole") as (r: string) => string, allVariants: g("allVariants") as () => { style: string }[], cur: g("cur") as number, plainStyle: g("plainStyle") as (s: string) => string };
      return { style: W.plainStyle(W.allVariants()[W.cur]!.style), bench: W.items.filter((x) => W.baseRole(x.role) === "банкетка").length, list: /банкетк/i.test(document.getElementById("shotbody")!.innerText) };
    });
    const r = rows.find((x) => x.style === w.style);
    say(`окно ${w.style}: банкеток в расстановке ${w.bench}, в списке ${w.list ? "есть" : "нет"}, в ленте ${r?.benchFeed}`);
    if (r && r.benchFeed < SWAP_RULES.nook_min_benches) { expect(w.bench).toBe(0); expect(w.list).toBe(false); }
    await page.keyboard.press("Escape");
    await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/);
    await page.waitForTimeout(500);
  }
  await close();
});

// ——— 2.48 обеденный стол ———
test("2.48 слот «стол обеденный» — только обеденные: высота 65–90 см, глубина ≥ 50 см, рядом со «стол» не кофейный/рабочий/барный/консоль; без размеров — не отсев", async ({ browser }) => {
  test.setTimeout(3 * 60_000);
  const { page, close } = await demoPage(browser, desk);
  const t = await page.evaluate(() => {
    const g = (window as unknown as { __g: (n: string) => unknown }).__g;
    const W = { D: g("D") as { feeds?: Record<string, { name?: string; w?: number; d?: number; h?: number }[]> }, allVariants: g("allVariants") as () => { id: string; items?: { role: string; w?: number; d?: number; h?: number; sku?: { name?: string } }[] }[], baseRole: g("baseRole") as (r: string) => string };
    const placed = W.allVariants().flatMap((v) => (v.items ?? []).filter((i) => W.baseRole(i.role) === "стол обеденный").map((i) => ({ src: "вариант " + v.id, name: i.sku?.name ?? "", d: i.d ?? null, h: i.h ?? null })));
    const feed = (W.D.feeds?.["стол обеденный"] ?? []).map((p) => ({ src: "лента", name: p.name ?? "", d: p.d ?? null, h: p.h ?? null }));
    return [...placed, ...feed];
  });
  say("обеденных столов:", t.length, "(в расстановках", t.filter((x) => x.src !== "лента").length, ")");
  expect(t.length).toBeGreaterThan(0);
  // числа — из ожидания карты (здесь, независимо); слово рядом со «стол» — правило сборки (`unfit.py` → `category_map.dining_name_bad`)
  const bad = t.filter((x) => (x.h != null && x.h > 0 && (x.h < 65 || x.h > 90)) || (x.d != null && x.d > 0 && x.d < 50));
  const py = execFileSync("python3", ["-c", [
    "import sys, json; sys.path.insert(0, 'tools/scout')",
    "from unfit import unfit",
    "rows = json.load(sys.stdin)",
    "print(json.dumps({'bad': [r['src'] + ': ' + r['name'] for r in rows if unfit('стол обеденный', r['name'], None, r['h'], None, d=r['d'])],",
    "  'nodims': unfit('стол обеденный', 'Стол обеденный Проверка', None, None, None, d=None)}))"].join("\n")],
  { input: JSON.stringify(t), cwd: ROOT }).toString();
  const rule = JSON.parse(py) as { bad: string[]; nodims: boolean };
  for (const x of bad) say("не обеденный:", JSON.stringify(x));
  say("правило сборки отсеяло бы:", rule.bad.length, rule.bad.slice(0, 5).join(" | "), "· без размеров отсев:", rule.nodims);
  expect(bad, "в слоте обеденного стола не обеденный").toEqual([]);
  expect(rule.bad, "правило unfit отсеяло бы стол из демо").toEqual([]);
  expect(rule.nodims, "без размеров — не отсев").toBe(false);
  await close();
});
