import { test, expect, type Page } from "@playwright/test";

import { alternatives, feedForStyle, type FeedItem } from "../../lib/configurator/demo-feeds";

// КВАРТИРА В 3D (/flat) — СТРОКИ 2.19–2.22 КАРТЫ СЦЕНАРИЕВ (долг плана demo-03, T-20261018-11). Как и 1д (`flat-walk.live.ts`),
// мерим числами по сцене, а не по снимку: у движка спрашиваем позу камеры (`debugWalk`), что видно (`projectSlot`) и где стоят
// предметы (`placed` движка — поле без доступа снаружи в типах, но живое в браузере: проверке нужны ТВ и ваза, которых нет в
// данных витрины, их ставит сцена). Ничего не сохраняем, кроме одной анонимной коллекции в 2.22 (как 2.13, без ПДн).

type Walk = { x: number; y: number; heading: number; inRoom: boolean; nearestCm: number | null; loading?: boolean };
type Spot = { kind?: string; slotId: string; roomId?: string; placement: { x: number; y: number; rot: number; wCm: number; dCm: number; hCm: number; elevCm?: number } };
type Opening = { kind: string; wall: "north" | "south" | "east" | "west"; offsetCm: number; widthCm: number };
type Room = { id: string; kind?: string; x: number; y: number; w: number; d: number; openings: Opening[] };
type Viewer = {
  debugState(): { placed: number };
  debugWalk(): Walk;
  projectSlot(id: string): { visible: boolean } | null;
  placed: Map<string, { spec: Spot }>;
  apartment: { rooms: Room[] };
  catalogue: { materials: { id: string; surfaces?: string[]; baseColorUrl?: string }[] };
};
type Item = { role?: string; x?: number; y?: number; w?: number; d?: number; sku?: { msid?: string; sid?: string; name?: string } };
type Variant = { id: string; style?: string; items: Item[] };
type DemoData = { variants: Variant[]; feeds?: Record<string, FeedItem[]>; variant_aliases?: Record<string, string> };

const CORE = ["диван", "столик", "тв-тумба", "стол обеденный"];
const FLAT = "flat215";

// без видеокарты (DEV, ночной шаг) — программный рендер ANGLE и свежая вкладка на каждый вариант, как в 1д
test.use({ launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } });

async function demoData(request: import("@playwright/test").APIRequestContext): Promise<DemoData> {
  return (await (await request.get(process.env.LIVE_DEMO_DATA ?? "/demo/demo-data.json")).json()) as DemoData;
}
const variants = async (request: import("@playwright/test").APIRequestContext): Promise<Variant[]> => (await demoData(request)).variants;

/** Сцена догружена: предметов столько, сколько у варианта (ковёр — фото на полу, не модель), и движок не грузит модели. */
async function sceneReady(page: Page, v: Variant): Promise<boolean> {
  const want = v.items.filter((it) => it.sku?.msid && !String(it.role).startsWith("ковёр")).length;
  let last = -1;
  for (let i = 0; i < 90; i += 1) {
    const n = (await page.evaluate("window.__flatViewer ? window.__flatViewer.debugState().placed : -1")) as number;
    if (n >= want && n === last) break;
    last = n;
    await page.waitForTimeout(1000);
  }
  for (let i = 0; i < 60; i += 1) {
    const busy = await page.evaluate("window.__flatViewer ? window.__flatViewer.debugWalk().loading : true");
    if (!busy) break;
    await page.waitForTimeout(1000);
  }
  await page.waitForTimeout(1500);   // старт выбирается заново после загрузки (под заставкой)
  return (await page.evaluate("!!window.__flatViewer")) as boolean;
}

/** Свежая вкладка на вариант; сцена не поднялась (без видеокарты вкладка падает — «Target crashed») — одна повторная попытка. */
async function openVariant(browser: import("@playwright/test").Browser, v: Variant, report: string[]): Promise<Page | null> {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const page = await browser.newPage();
    let crashed = false;
    page.on("crash", () => { crashed = true; });
    try {
      await page.goto(`/flat?demo=${v.id}&flat=${FLAT}`, { waitUntil: "load", timeout: 120_000 });
      if (!crashed && (await sceneReady(page, v))) return page;
    } catch {
      /* упавшая вкладка роняет evaluate — это та же «не поднялась» */
    }
    report.push(`  ! ${v.id}: сцена не поднялась (попытка ${attempt}${crashed ? ", вкладка упала" : ""})`);
    await page.close().catch(() => undefined);
  }
  return null;
}

/** Предметы гостиной в сцене: место, вид, след — для расстояний «до экрана» и «ваза на столике». */
async function spots(page: Page): Promise<Spot[]> {
  return (await page.evaluate(() => {
    const vw = (window as unknown as { __flatViewer: Viewer }).__flatViewer;
    return [...vw.placed.values()].map((p) => ({ kind: p.spec.kind, slotId: p.spec.slotId, roomId: p.spec.roomId, placement: p.spec.placement }));
  })) as Spot[];
}

/** Расстояние от точки до прямоугольника следа (как `tvDist` движка): 0 — внутри. */
function toRect(p: Spot["placement"], x: number, y: number): number {
  const a = (-p.rot * Math.PI) / 180;
  const dx = x - p.x;
  const dy = y - p.y;
  const lx = dx * Math.cos(a) - dy * Math.sin(a);
  const ly = dx * Math.sin(a) + dy * Math.cos(a);
  return Math.hypot(Math.max(Math.abs(lx) - p.wCm / 2, 0), Math.max(Math.abs(ly) - p.dCm / 2, 0));
}

// 2.19: правило старта движка (`viewer.ts`, решение d8 16.10): ≥ 80 см до мебели и ≥ 1,5 м до экрана ТВ; ни одна точка не прошла —
// старт от двери (в 60 см от проёма внутрь, взгляд между диваном и обеденной группой). В обоих случаях видно ≥ 3 предмета ядра
test("2.19 «бродилка»: старт ≥ 80 см от мебели и ≥ 1,5 м от экрана (иначе — от двери), видно ≥ 3 предмета ядра", async ({ browser, request }) => {
  test.setTimeout(15 * 60_000);
  const report: string[] = [];
  const bad: string[] = [];
  for (const v of await variants(request)) {
    const page = await openVariant(browser, v, report);
    if (!page) {
      bad.push(`${v.id}: сцена не поднялась дважды (вкладка падает без видеокарты?)`);
      continue;
    }
    const start = (await page.evaluate("window.__flatViewer.debugWalk()")) as Walk;
    const all = await spots(page);
    const tv = all.find((s) => s.kind === "tv" && s.roomId === "living");
    const tvCm = tv ? Math.round(toRect(tv.placement, start.x, start.y)) : null;
    const living = (await page.evaluate(() =>
      (window as unknown as { __flatViewer: Viewer }).__flatViewer.apartment.rooms.find((r) => r.id === "living") ?? null)) as Room | null;
    // точка в 60 см от двери внутрь (как выбирает движок) — старт «от двери», если до неё ≤ 40 см (поправка на «где можно стоять»)
    const door = living?.openings.find((o) => o.kind === "door");
    const doorSpot = living && door ? (() => {
      const mid = door.offsetCm + door.widthCm / 2;
      return door.wall === "south" ? { x: living.x + mid, y: living.y + 60 } : door.wall === "north" ? { x: living.x + mid, y: living.y + living.d - 60 }
        : door.wall === "west" ? { x: living.x + 60, y: living.y + mid } : { x: living.x + living.w - 60, y: living.y + mid };
    })() : null;
    const atDoor = !!doorSpot && Math.hypot(start.x - doorSpot.x, start.y - doorSpot.y) <= 40;
    const strict = (start.nearestCm ?? 999) >= 80 && (tvCm ?? 999) >= 150;
    const core = CORE.filter((r) => v.items.some((i) => i.role === r)).map((r) => `${r}#0`);
    const seen = (await page.evaluate((ids) => {
      const vw = (window as unknown as { __flatViewer: Viewer }).__flatViewer;
      return ids.filter((id) => vw.projectSlot(id)?.visible);
    }, core)) as string[];
    report.push(`${v.id} ${v.style ?? ""}: старт (${start.x}, ${start.y})${strict ? "" : atDoor ? " — запасной, от двери" : ""}, до мебели ${start.nearestCm} см, до экрана ${tvCm ?? "—"} см, видно ядра ${seen.length}/${core.length}`);
    if (!start.inRoom) bad.push(`${v.id}: старт вне комнаты ${JSON.stringify(start)}`);
    // правило не выполнено — допустим только запасной старт от двери (там движок держит ≥ 20 см и смотрит на диван и обеденную группу)
    if (!strict && !atDoor) bad.push(`${v.id}: до мебели ${start.nearestCm} см (норма ≥ 80), до экрана ${tvCm} см (норма ≥ 150), и это не старт от двери`);
    if (!strict && atDoor && (start.nearestCm ?? 999) < 20) bad.push(`${v.id}: старт от двери вплотную к мебели — ${start.nearestCm} см`);
    if (seen.length < Math.min(3, core.length)) bad.push(`${v.id}: видно ядра ${seen.length}/${core.length} (${seen.join(", ")})`);
    await page.close();
  }
  console.log(report.join("\n"));
  expect(bad, "старт «бродилки» нарушает правило 2.19").toEqual([]);
});

// 2.20: мост окна в 3D (ADR-0281): ковёр — место с фото товара и ценой, ваза — на столике (`resolve.placeTabletop`; не влезла —
// на обеденном столе, правило `decorLayout`), ТВ — над тумбой (`build-scene.sceneExtras`), у предметов ядра лента «Варианты» ≥ 5 (или
// вся лента стиля, если товара в ней меньше: нехватка — каталог, а не мост; печатается строкой «!»)
test("2.20 ковёр с фото и ценой, ваза на столике, ТВ над тумбой, «Варианты» ≥ 5 у предметов ядра", async ({ browser, request }) => {
  test.setTimeout(15 * 60_000);
  const report: string[] = [];
  const bad: string[] = [];
  const data = await demoData(request);
  for (const v of data.variants) {
    const page = await openVariant(browser, v, report);
    if (!page) {
      bad.push(`${v.id}: сцена не поднялась дважды (вкладка падает без видеокарты?)`);
      continue;
    }
    const all = (await spots(page)).filter((s) => s.roomId === "living");
    const at = (role: string) => all.find((s) => s.slotId === `${role}#0`)?.placement;
    // ТВ над тумбой: центр экрана в следе тумбы, низ экрана не ниже её верха
    const tv = all.find((s) => s.kind === "tv")?.placement;
    const stand = at("тв-тумба");
    if (!tv || !stand) bad.push(`${v.id}: нет ${tv ? "" : "ТВ "}${stand ? "" : "тумбы"} в сцене`);
    else {
      const top = (stand.elevCm ?? 0) + stand.hCm;
      if (toRect(stand, tv.x, tv.y) > 1 || (tv.elevCm ?? 0) < top - 1) bad.push(`${v.id}: ТВ не над тумбой — ТВ ${JSON.stringify(tv)}, тумба ${JSON.stringify(stand)}`);
      report.push(`${v.id} ${v.style ?? ""}: ТВ над тумбой, низ экрана ${tv.elevCm} см, верх тумбы ${Math.round(top)} см`);
    }
    // ваза: в следе опоры, дно на её верхе
    const vase = all.find((s) => s.slotId.startsWith("decor:ваза"))?.placement;
    if (!vase) bad.push(`${v.id}: вазы нет в сцене`);
    else {
      const sup = ["столик", "стол обеденный"].map((r) => ({ r, p: at(r) })).find(({ p }) => p && toRect(p, vase.x, vase.y) < 1);
      const top = sup?.p ? (sup.p.elevCm ?? 0) + sup.p.hCm : null;
      if (!sup || top === null || Math.abs((vase.elevCm ?? 0) - top) > 2) bad.push(`${v.id}: ваза не на опоре — ${JSON.stringify(vase)}`);
      else report.push(`  ваза на «${sup.r}» на высоте ${vase.elevCm} см`);
      if (sup && sup.r !== "столик") report.push(`  ! ${v.id}: ваза не на столике, а на «${sup.r}» (столик не вместил — правило decorLayout)`);
    }
    // полоса выбора: ковёр — фото и цена в строке выбранного; ядро — ≥ 5 плиток
    const bar = page.getByRole("region", { name: "Панель выбора" });
    await expect(bar).toBeVisible();
    const strip = bar.locator("ul li");
    for (const slot of ["ковёр#0", ...CORE.map((r) => `${r}#0`)]) {
      const btn = bar.locator(`button[data-slot="${slot}"]`);
      if (!(await btn.count())) {
        if (v.items.some((i) => `${i.role}#0` === slot)) bad.push(`${v.id}: нет кнопки «${slot}» в полосе`);
        continue;
      }
      await btn.click();
      await expect(btn).toHaveAttribute("aria-pressed", "true");
      const n = await strip.count();
      const line = await bar.locator("p.truncate").first().innerText();
      if (slot.startsWith("ковёр")) {
        // фото ковра — фото товара на самом ковре в сцене (материал `rug:…`, `fromDemo.ts`), цена — на плитке выбранного
        const photo = (await page.evaluate(() => {
          const vw = (window as unknown as { __flatViewer: Viewer }).__flatViewer;
          return vw.catalogue.materials.find((m) => m.id.startsWith("rug:") && m.surfaces?.includes("rug"))?.baseColorUrl ?? null;
        })) as string | null;
        const ok = photo ? (await page.request.get(photo)).ok() : false;
        const tile = await strip.locator("button[aria-pressed=true]").innerText();
        report.push(`  ковёр: «${line.slice(0, 60)}», фото в сцене ${photo ? (ok ? "открывается" : "НЕ ОТКРЫВАЕТСЯ") : "НЕТ"}, плитка «${tile.replace(/\s+/g, " ")}», вариантов ${n}`);
        if (!photo || !ok) bad.push(`${v.id}: ковёр без фото товара в сцене (${photo ?? "нет ссылки"})`);
        if (!/\d[\d\s ]*\s?₽/.test(tile)) bad.push(`${v.id}: у ковра нет цены — «${tile}»`);
      } else {
        // сколько может дать лента витрины (то же правило, что у моста `fromDemo` и окна): товар места + ближайшие из ленты стиля
        const it = v.items.find((i) => `${i.role}#0` === slot)!;
        const role = slot.slice(0, -2);
        const can = 1 + alternatives(feedForStyle(data.feeds?.[role] ?? [], v.style), { w: it.w ?? 0, d: it.d ?? 0 },
          new Set([it.sku?.sid ?? "", it.sku?.name ?? ""])).length;
        const need = Math.min(5, can);
        report.push(`  ${slot}: вариантов ${n}${can < 5 ? ` — ! в ленте стиля всего ${can} (норма карты ≥ 5: мало товара в каталоге)` : ""}`);
        if (n < need) bad.push(`${v.id}: у «${slot}» вариантов ${n}, лента стиля даёт ${can}`);
      }
    }
    await page.close();
  }
  console.log(report.join("\n"));
  expect(bad, "ковёр/ваза/ТВ/ленты не по правилу 2.20").toEqual([]);
});

// 2.21: устаревший номер варианта (ночная пересборка витрины) открывает текущий того же стиля с пометкой, а не 404
// (`resolveFlat.replaced`, `app/flat/page.tsx`). Псевдоним set18 → джапанди лежит в `variant_aliases` данных витрины.
// ⚠ каждое открытие +1 к счётчику `stale_link` отчёта застройщика за день (так устроен счётчик) — один заход за прогон
test("2.21 старая ссылка ?demo=set18 — 200, текущий вариант того же стиля с пометкой «обновилась»", async ({ page, request }) => {
  const data = await demoData(request);
  const style = data.variant_aliases?.set18;
  expect(style, "set18 есть в псевдонимах витрины").toBeTruthy();
  expect(data.variants.some((v) => v.id === "set18"), "set18 не опубликован — ссылка действительно устаревшая").toBe(false);
  const res = await page.goto(`/flat?demo=set18&flat=${FLAT}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
  expect(res?.status()).toBe(200);
  const note = page.locator("p.note", { hasText: "обновилась" });
  await expect(note).toBeVisible();
  await expect(note).toContainText(`в том же стиле (${style})`);
  console.log(`  set18 → «${(await note.innerText()).trim()}»`);
});

// 2.22: покупатель по ссылке из окна демо (`?demo=`) и по коллекции (`?coll=`) видит строку застройщика (ЖК · квартира ·
// сертификат) вместо шапки remont-lab (`app/flat/page.tsx`, demo-05 п.7). Ссылка менеджера (`?s=`) не проверяется: живого номера
// отправки в проверках нет, а заводить отправку с менеджером ночью нельзя (ПДн) — см. отчёт T-20261018-11
test("2.22 ссылка из окна и коллекция: строка застройщика вместо шапки remont-lab", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  // как без входа покупателя: шапка сайта и заголовок квартиры — для сравнения
  await page.goto(`/flat?flat=${FLAT}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".site-header")).toBeVisible();
  await expect(page.locator("main h1").first()).not.toContainText("сертификат до");

  const buyerHeader = async (url: string): Promise<string> => {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 120_000 });
    await expect(page.locator(".site-header")).toBeHidden();
    const h1 = page.locator("main h1").first();
    await expect(h1).toContainText("сертификат до");
    await expect(page.getByText("сервис remont-lab")).toBeVisible();
    return (await h1.innerText()).replace(/\s+/g, " ").trim();
  };
  console.log(`  ?demo=: «${await buyerHeader(`/flat?demo=set1&flat=${FLAT}`)}»`);

  // коллекция: ♡ в окне варианта → номер из корзины избранного (как 2.13: одна анонимная коллекция за прогон, без ПДн)
  await page.goto("/demo/", { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0");
  await page.locator("button[data-swap]").first().click();
  await page.locator("#vFav").click();
  await page.locator("#favOk").click();
  await expect(page.locator("#vFav.on")).toBeVisible();
  const cid = (await page.evaluate("((window.__fav && window.__fav.list()) || [])[0]?.collectionId || ''")) as string;
  expect(cid).toMatch(/^[A-Za-z0-9_-]{22}$/);
  console.log(`  ?coll=: «${await buyerHeader(`/flat?coll=${cid}`)}»`);
});
