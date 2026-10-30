import { test, expect, type Page } from "@playwright/test";

// КАРТА СЦЕНАРИЕВ ДЕМО НА ПРОДЕ (план demo-03, `.memory_bank/domain/demo-scenario-map.md`). Номера тестов = номера строк
// карты. Каждая проверка печатает число (время, количество, сумму): «не упало» — не проверка. Платный путь не тратит
// деньги: запрос «Улучшить» шлём, только когда сервер сам говорит, что улучшение сейчас недоступно.

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

const say = (...a: unknown[]) => console.log("  ·", ...a);
async function openDemo(page: Page, q = ""): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const t = Date.now();
  await page.goto(`/demo/${q}`, { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0");
  say("загрузка", Date.now() - t, "мс");
  return errors;
}
// КОНСТРУКТОР — ИЗ ОКНА ВАРИАНТА (demo-19 Б5, владелец 20.10: «свою расстановку делают на основе любой»): окно гостиной → «План» → «Изменить план»
async function openConstructor(page: Page) {
  if (!(await page.locator("#shot.on").count())) await page.locator("#hmRooms [data-swap]").first().click();
  await page.locator('#shot [data-vm="plan"]').click();
  await page.locator("#vCta").click();
  await expect(page.locator("#cons")).toHaveClass(/on/);
}
const num = (t: string) => Number((t.match(/([\d\s ]+)\s*₽/)?.[1] ?? "").replace(/\D/g, ""));

test("1.2–1.5 первый экран: консультация, ипотека, «Подробнее», план квартиры ссылкой, комнаты стиля и заглушки (demo-16)", async ({ page }) => {
  const errors = await openDemo(page);
  for (const id of ["#pcCons", "#pcMort"]) {
    await page.locator(id).click();
    await expect(page.locator("#shot")).toBeVisible();
    say(id, JSON.stringify((await page.locator("#shotbody").innerText()).slice(0, 60)));
    await page.keyboard.press("Escape");
  }
  // условия цены — в «Подробнее» под строкой дома (demo-19 Б1), значка «i» у цены нет
  await page.locator("#flatMoreBtn").click();
  await expect(page.locator("#flatMore")).toBeVisible();
  await expect(page.locator("#flatMore")).toContainText("оплате 100");
  // кнопки «Пройтись по квартире в 3D» в шапке нет (владелец 16.10, demo-02 п.8) — 3D внутри окна варианта
  await expect(page.locator("#pc3d")).toHaveCount(0);
  // план квартиры — ссылкой, не вкладкой (demo-16), и плашкой в конце комнат (demo-20 А7); назад — «← К стилям»
  for (const sel of ["#planLink", "#hmRooms .hm-plan-tile"]) {
    await page.locator(sel).click();
    await expect(page.locator("#screen-plan")).toBeVisible();
    await expect(page.locator("#styleTabs")).toBeHidden();
    await page.locator("#planBack").click();
    await expect(page.locator("#screen-room")).toBeVisible();
  }
  // вкладки — стили; внутри — комнаты в порядке плана, неготовые — одинаковой заглушкой с площадью (demo-16)
  const tabs = await page.locator("#styleTabs [data-style]").allInnerTexts();
  const rooms = await page.locator("#hmRooms [data-room]").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.room));
  const stubs = await page.locator("#hmRooms .hm-stub:not(.hm-plan-tile)").allInnerTexts();
  say("стили:", tabs.join(" | "), "· комнаты:", rooms.join(","));
  expect(tabs.length).toBeGreaterThanOrEqual(4);
  expect(rooms).toEqual(["living", "kitchen", "bedroom-1", "bedroom-2", "bathroom-1", "bathroom-2", "hall"]);
  expect(stubs.length).toBe(rooms.length - 1);   // готова только гостиная (спальня снята с показа — `core/bedroom.md`), плашка плана — не заглушка
  for (const t of stubs) { expect(t).toContain("м²"); expect(t).toContain("появится следующим шагом"); }
  expect(errors).toEqual([]);
});

test("2.1–2.3 окно кадра: фото, список, числа как на карточке комнаты каждого стиля", async ({ page }) => {
  await openDemo(page);
  const n = await page.locator("#styleTabs [data-style]").count();
  for (let i = 0; i < n; i++) {
    await page.locator("#styleTabs [data-style]").nth(i).click();     // вкладка стиля → карточка гостиной этого стиля (demo-16)
    const card = (await page.locator("#hmRooms .hm-room .sum small").innerText()) + " · " + (await page.locator("#hmRooms .hm-room .sum b").innerText());
    await page.locator("#hmRooms .hm-room [data-swap]").click();
    await expect(page.locator("#shot")).toBeVisible();
    // окно варианта (demo-02 v3): число товаров и сумма — атрибуты плашки сертификата `#vsum`
    const cnt = Number(await page.locator("#vsum").getAttribute("data-count"));
    const sum = Number(await page.locator("#vsum").getAttribute("data-sum"));
    say(`вариант ${i}: карточка «${card}» | окно ${cnt} · ${sum}`);
    expect(cnt, "число товаров").toBe(Number(card.match(/^(\d+)/)?.[1]));
    expect(sum, "сумма").toBe(num(card.split("·").pop()!));
    await page.keyboard.press("Escape");
  }
});

test("2.4 режимы в одном окне: «Фото» — только при реалистичном снимке этой расстановки, иначе 3D; ракурсы — подписями (demo-09, demo-15)", async ({ page }) => {
  await openDemo(page, "?live=force");
  await page.locator("button[data-swap]").first().click();
  const hasPhoto = await page.locator('[data-vm="photo"]').isVisible();
  const start = await page.evaluate("VW.mode") as string;
  say("реалистичный снимок этой расстановки:", hasPhoto, "· окно открылось в", start);
  expect(start).toBe(hasPhoto ? "photo" : "walk");
  if (start !== "walk") await page.locator('[data-vm="walk"]').click();
  // ракурсы — подписями «Со стороны окна/двери» или «Ракурс 1/2» (demo-15 п.3); стрелок и точек нет
  await expect(page.locator("#vPrev, #vNext, #vDots, #shotPrev, #shotNext")).toHaveCount(0);
  say("ракурсы:", (await page.locator("#vCams [data-cam]").allInnerTexts()).join(" | "));
  await page.locator('#vCams [data-cam="1"]').click();
  await expect(page.locator('#vCams [data-cam="1"]')).toHaveClass(/on/);
  for (const m of ["plan", ...(hasPhoto ? ["photo"] : []), "walk"]) {
    const t = Date.now();
    await page.locator(`[data-vm="${m}"]`).click();
    await expect(page.locator(`[data-vm="${m}"]`)).toHaveClass(/on/);
    say(`режим ${m}: ${Date.now() - t} мс`);
  }
  await expect(page.locator("#shot .livecv")).toBeVisible();   // закончили в 3D — видна живая сцена (картинка «Фото» под ней спрятана)
});

test("2.24 без реалистичного фото — 3D с ценниками и «Сделать реалистичнее»; без 3D — заглушка, не эскиз (demo-09)", async ({ page }) => {
  await openDemo(page, "?live=force");
  await page.evaluate("shots = shots.filter((x) => x.quality !== 'realistic'); openLiveWindow()");
  await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
  expect(await page.evaluate("VW.mode")).toBe("walk");
  await expect(page.locator('[data-vm="photo"]')).toBeHidden();
  await expect(page.locator("#vCta")).toHaveText(/реалистичнее/);
  await expect.poll(() => page.locator("#vpins .vpin:not([hidden])").count(), { timeout: 15_000 }).toBeGreaterThanOrEqual(3);
  say("ценников в 3D:", await page.locator("#vpins .vpin:not([hidden])").count());
  await page.goto("/demo/?live=0", { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0 && !!FLAT");
  await page.evaluate("shots = shots.filter((x) => x.quality !== 'realistic'); openLiveWindow()");
  await expect(page.locator("#vStub")).toBeVisible();
  await expect(page.locator("#vCta")).toBeVisible();
  await expect(page.locator("#shot .restale")).toBeHidden();
});

// 2.25–2.26 (demo-09): «Сделать реалистичнее» — фоновое задание; ответ сервера подменён (платный путь не вызывается)
// 2.26 после demo-20 Г5: менять расстановку, пока рисуется её фото, нельзя (`vwEditLock`) — правка не применяется, подсказка; фото — само
test("2.25–2.26 фото готово для этой расстановки → «Фото» само; правка во время съёмки не применяется — подсказка, фото той же расстановки", async ({ page }) => {
  let ready = false;
  await page.route(/\/api\/render/, (r) => r.fulfill({ json: { job: "fake-" + Date.now() } }));
  await page.route(/\/api\/job\?/, (r) => r.fulfill({ json: ready
    ? { shots: [{ camera: "C1", url: "/demo/img/og.jpg" }, { camera: "C2", url: "/demo/img/og.jpg" }], backend: "fake" }
    : { status: "running", eta: 30 } }));
  await openDemo(page, "?live=force");
  await page.evaluate("shots = shots.filter((x) => x.quality !== 'realistic'); openLiveWindow()");
  await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
  await page.locator("#vCta").click();
  // сразу «Фото» с ходом работы во весь кадр (demo-20 Б3, владелец 22.10 TG 791/795)
  await expect(page.locator("#shot .vphwait b")).toHaveText(/^Улучшаю… \d+ %$/);
  expect(await page.evaluate("VW.mode")).toBe("photo");
  ready = true;
  await expect.poll(() => page.evaluate("VW.mode"), { timeout: 20_000 }).toBe("photo");
  // «Фото» включено сразу с ходом работы (demo-20 Б3) — ждём КОНЕЦ задания: пока «Улучшаю…», правки заперты (demo-20 Г5, `vwEditLock`)
  await expect(page.locator("#shot .vphwait")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.locator('[data-vm="photo"]')).toBeVisible();
  await expect(page.locator("#vCta")).toBeHidden();
  ready = false;
  await page.evaluate("(() => { const g = devGroups().find((x) => x.kind === 'flooring'); devSet(g.id, g.variants[1].id); })()");
  await expect.poll(() => page.evaluate("VW.mode")).toBe("walk");               // изменение → 3D
  await page.locator("#vCta").click();
  const floor = "(() => { const g = devGroups().find((x) => x.kind === 'flooring'); return devPick(g).id; })()";
  const before = await page.evaluate(floor);
  await page.evaluate("(() => { const g = devGroups().find((x) => x.kind === 'flooring'); devSet(g.id, g.variants[2].id); })()");
  await expect(page.locator("#toast")).toContainText("Менять можно, когда улучшение закончится");
  expect(await page.evaluate(floor)).toBe(before);                              // правка не применилась
  ready = true;
  await expect(page.locator("#shot .vphwait")).toHaveCount(0, { timeout: 20_000 });
  expect(await page.evaluate("VW.mode")).toBe("photo");
  await expect(page.locator('[data-vm="photo"]')).toBeVisible();
});

// 2.27 (demo-09, дополнение 17.10): фото нейросети 13.10 сняты с прежних расстановок — карточка показывает кадр ТОЛЬКО своей расстановки
test("2.27 карточка: кадр своей расстановки или «Откройте — покажем в 3D», не старое фото", async ({ page }) => {
  await openDemo(page);
  await page.waitForFunction("shots.length > 0");
  // карточка комнаты каждого стиля (demo-16): вкладка → гостиная этого стиля
  const cards: { style: string; shown: string; fits: boolean }[] = [];
  for (const id of await page.locator("#styleTabs [data-style]").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.style))) {
    await page.locator(`#styleTabs [data-style="${id}"]`).click();
    cards.push(...(await page.evaluate(`[allVariants()[cur]].map((v) => { const el = document.querySelector('#hmRooms .hm-room'), im = el && el.querySelector('img');
    const s = im ? shots.find((x) => thumbOf(x) === im.getAttribute('src') || x.url === im.dataset.url) : null;
    return { style: v.style, shown: s ? s.quality + ':' + (s.stateId ? 'state' : 'items') : (el && el.querySelector('.nopv') ? 'заглушка' : '?'), fits: !s || shotFits(s, v) }; })`) as { style: string; shown: string; fits: boolean }[]));
  }
  say(cards.map((c) => `${c.style}: ${c.shown}`).join(" | "));
  for (const c of cards) expect(c.fits, `${c.style}: на карточке кадр чужой расстановки`).toBe(true);
  expect(cards.every((c) => c.shown !== "?")).toBe(true);
});

test("2.5–2.6 замена из окна: лента, выбор, сумма пересчитана, окно в 3D с «Сделать реалистичнее»", async ({ page }) => {
  await openDemo(page);
  await page.locator("button[data-swap]").first().click();
  const sumNow = async () => Number(await page.locator("#vsum").getAttribute("data-sum"));
  const before = await sumNow();
  await page.locator("#shotbody [data-rep]").first().click();
  await expect(page.locator("#sheet")).toBeVisible();
  const cards = page.locator("#sheet .mini:has-text('Заменить')");
  await expect(cards.first()).toBeVisible();
  say("замен в ленте:", await cards.count());
  expect(await cards.count()).toBeGreaterThanOrEqual(3);
  await cards.first().click();
  await expect.poll(sumNow).not.toBe(before);
  say("сумма:", before, "→", await sumNow());
  // любое изменение → 3D (demo-09 п.4); черновика из окна нет
  await expect.poll(() => page.evaluate("VW.mode")).toBe("walk");
  await expect(page.locator("#vCta")).toHaveText(/реалистичнее/);
});

test("2.6 живая сцена: замена видна сразу, без запроса кадра к серверу (demo-01)", async ({ page }) => {
  // `?live=force`: в проверочном браузере нет видеокарты (программный рендер), обычный покупатель с ним получил бы эскиз
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && /\/api\/render/.test(r.url())) posts.push(r.url()); });
  await openDemo(page, "?live=force");
  await page.locator("button[data-swap]").first().click();
  await page.locator("#shotbody [data-rep]").first().click();
  const t = Date.now();
  await page.locator("#sheet .mini:has-text('Заменить')").first().click();
  await expect(page.locator("#shot .livecv")).toBeVisible({ timeout: 45_000 });
  say("живая сцена в окне через", Date.now() - t, "мс; движок:", await page.evaluate("JSON.stringify(LIVE.probe)"));
  expect(posts, "правка не должна звать серверный кадр").toEqual([]);
});

test("2.10–2.11, 2.17 конструктор: подсказка, перетаскивание, кнопка кадра", async ({ page }) => {
  await openDemo(page);
  await page.locator("button[data-swap]").first().click();
  // «План» в окне варианта (demo-02 v3) — план для просмотра; редактор — по «Изменить план»
  await page.locator('[data-vm="plan"]').click();
  await expect(page.locator("#vPlan svg")).toBeVisible();
  await page.locator("#vCta").click();
  await expect(page.locator("#cons")).toBeVisible();
  await expect(page.locator("#consHint")).toBeVisible();
  const before = await page.evaluate("items.map(i => [i.x, i.y])") as number[][];
  // журнальный столик — посреди комнаты: в углах лежат значки камер, и нажатие там выбирает камеру, а не предмет
  const pos = await page.evaluate(`(() => { const r = stage.getBoundingClientRect();
    const it = items.find(i => /^столик/.test(i.role)) || items.find(i => !/^ковёр/.test(i.role));
    return { x: r.left + PAD + it.x * S, y: r.top + PAD + it.y * S }; })()`) as { x: number; y: number };
  await page.mouse.move(pos.x, pos.y);
  await page.mouse.down();
  for (let k = 1; k <= 10; k++) await page.mouse.move(pos.x + 4 * k, pos.y + 3 * k);
  await page.mouse.up();
  const after = await page.evaluate("items.map(i => [i.x, i.y])") as number[][];
  const moved = after.findIndex((p, k) => Math.hypot(p[0]! - before[k]![0]!, p[1]! - before[k]![1]!) > 5);
  say("сдвинут предмет №", moved, "на", moved >= 0 ? Math.round(Math.hypot(after[moved]![0]! - before[moved]![0]!, after[moved]![1]! - before[moved]![1]!)) : 0, "см");
  expect(moved).toBeGreaterThanOrEqual(0);
  await expect(page.locator("#consShot")).toBeVisible();
  await page.locator("#consDone").click();
  await expect(page.locator("#shot")).toBeVisible();      // «Готово» возвращает в окно кадра, откуда пришли
  await expect(page.locator('[data-vm="walk"]')).toHaveClass(/on/);   // …в 3D: расстановку меняли (demo-09 п.4)
  await page.keyboard.press("Escape");
  await openConstructor(page);   // карточки «Добавить новую расстановку» нет (demo-19 Б5) — вход из окна варианта
  await expect(page.locator("#consHint")).toBeVisible();
  say("подсказка:", (await page.locator("#consHint").innerText()).slice(0, 50));
});

test("2.14–2.15 «поделиться» иконкой с подтверждением и избранное сердечком с именем коллекции (demo-15)", async ({ page }) => {
  await openDemo(page);
  await expect(page.locator("#coll button[data-link], #feedShare, #collSave")).toHaveCount(0);   // текстовой «Ссылки» и «Избранное» внизу нет
  await page.evaluate("navigator.share = undefined");                                            // без системного меню — копирование + тост
  await page.locator("#hmRooms button[data-share]").first().click();                             // карточка комнаты стиля (demo-16)
  await expect(page.locator("#toast")).toContainText(/скопирована/);
  say("буфер:", await page.evaluate("navigator.clipboard.readText()"));
  await page.locator("#hmRooms button[data-favorite]").first().click();
  await expect(page.locator("#favName")).toHaveValue(/ #\d+$/);                                 // «<Стиль> #N»
  say("имя по умолчанию:", await page.locator("#favName").inputValue());
  await page.locator("#favNo").click();                                                         // ночью в базу не пишем
  await expect(page.locator("#favPop")).toHaveCount(0);
});

test("1.6 английский: конструктор и ожидание без русских подписей", async ({ page }) => {
  await openDemo(page, "?lang=en");
  await openConstructor(page);
  const t = await page.locator("#consWhat, #consSum, #consHint").allInnerTexts();
  say(t.join(" | ").slice(0, 160));
  expect(t.join(" ")).not.toMatch(/[А-Яа-яЁё]/);
});

// 1.7 БРИТАНСКАЯ МАСКА (demo-31, владелец 30.10): у английского двойника — английские названия, цена товара × 1.5, ни магазина, ни
// ссылки «в магазин»; русское демо — как было. Смотрим окно гостиной (список под кадром) и ленту замены
const SHOPS = /divan\.ru|tvoydom\.ru|mnogomebeli\.com|ormatek\.com|divanboss\.ru|gdeslon/i;
async function windowTexts(page: Page): Promise<{ list: string; sheet: string; hrefs: string[] }> {
  await page.locator("#hmRooms .hm-room [data-swap]").first().click();
  await expect(page.locator("#shot")).toBeVisible();
  const list = await page.locator("#shotbody").innerText();
  await page.locator("#shotbody [data-rep]").first().click();
  await expect(page.locator("#sheet")).toBeVisible();
  await expect(page.locator("#sheet .nm").first()).toBeVisible();
  const sheet = await page.locator("#sheet").innerText();
  const hrefs = await page.locator("#shotbody a[href], #sheet a[href]").evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).href));
  return { list, sheet, hrefs };
}
test("1.7 английский: британская маска — английские названия, цена × 1.5, без магазинов; русский — магазины на месте (demo-31)", async ({ page }) => {
  const errors = await openDemo(page, "?lang=en");
  await page.waitForFunction("typeof FLAT !== 'undefined' && !!FLAT");
  const fx = await page.evaluate("({ id: FLAT.id, mask: FLAT.demoMask, base: FLAT.fx && FLAT.fx.rate, shown: fxRate() })") as
    { id: string; mask: { priceMarkup: number } | null; base: number; shown: number };
  say("квартира", fx.id, "маска", JSON.stringify(fx.mask), "курс", fx.base, "→", fx.shown);
  expect(fx.mask?.priceMarkup).toBe(1.5);
  expect(fx.shown).toBeCloseTo(fx.base * 1.5, 10);
  const en = await windowTexts(page);
  const names = await page.locator("#shotbody .row .t b, #sheet .nm").allInnerTexts();
  say("названия:", names.slice(0, 4).join(" | "), "… всего", names.length, "· ссылок", en.hrefs.length);
  expect(names.length).toBeGreaterThan(3);
  for (const n of names) expect(n).not.toMatch(/[А-Яа-яЁё]/);
  expect(en.list + en.sheet).not.toMatch(SHOPS);
  expect(en.list + en.sheet).not.toMatch(/to shop|view in shop|в магазин/i);
  expect(en.hrefs.filter((h) => SHOPS.test(h))).toEqual([]);
  expect(errors).toEqual([]);
});
test("1.7 русский: магазины и «В магазин» на месте, курса и маски нет (demo-31)", async ({ page }) => {
  await openDemo(page);
  await page.waitForFunction("typeof FLAT !== 'undefined' && !!FLAT");
  expect(await page.evaluate("FLAT.demoMask")).toBeNull();
  const ru = await windowTexts(page);
  say("ссылок в магазин:", ru.hrefs.filter((h) => SHOPS.test(h)).length);
  expect(ru.list + ru.sheet).toMatch(SHOPS);
  expect(ru.sheet).toMatch(/В магазин/);
  expect(ru.hrefs.some((h) => SHOPS.test(h))).toBe(true);
});

test("2.18 телефон: без горизонтальной прокрутки, план во всю ширину", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "ru-RU" });
  const page = await ctx.newPage();
  await openDemo(page);
  const sw = await page.evaluate("[document.documentElement.scrollWidth, innerWidth]") as number[];
  say("ширина страницы / экрана:", sw.join(" / "));
  expect(sw[0]!).toBeLessThanOrEqual(sw[1]! + 1);
  await openConstructor(page);   // карточки «Добавить новую расстановку» нет (demo-19 Б5) — вход из окна варианта
  const w = await page.evaluate("stage.getBoundingClientRect().width / innerWidth") as number;
  say("план занимает ширины экрана:", Math.round(w * 100), "%");
  expect(w).toBeGreaterThan(0.9);
  await ctx.close();
});

// 2.29 (demo-11, ADR-0302): чем нарисует «Сделать реалистичнее» — без оплаты, пробным запросом (`dry_run` задания не создаёт никогда)
test("2.29 реалистичное фото: модель sunburst medium и промпт improve-v4.3 (ADR-0305, радиатор под окном — demo-20 Г3, люстра стиля — Г4, мягкое третьим листом — demo-24) у рисующего процесса (пробный запрос, без трат)", async ({ request }) => {
  // подушка в списке варианта (demo-24): в запрос она уходит третьим листом и местом словами — видно в пробном ответе (`soft`)
  const r = await request.post("/api/render", { data: { async: 1, quality: "realistic", dry_run: 1, style: "сканди", room: { w: 439, d: 325 }, items: [{ role: "диван", x: 1, y: 1 }],
    decor: [{ role: "подушка", sku: { name: "Подушка 45×45", w: 45, d: 45, h: 11 } }] } });
  const j = await r.json() as { dry_run?: boolean; code?: string; render?: { realistic_model?: string; image_quality?: string; prompt_version?: string }; render_from?: string;
    prompt?: { version?: string; photo_look?: boolean; shape_rule?: boolean; soft_block?: boolean }; soft?: { item?: string; place?: string }[] };
  say("ответ", r.status(), JSON.stringify(j).slice(0, 220));
  if (!j.dry_run) { say("улучшение сейчас недоступно (", j.code, ") — модель не проверить, честный отказ"); expect([402, 503]).toContain(r.status()); return; }
  expect(j.render_from).toBe("proxy");
  expect(j.render?.realistic_model).toBe("openai/gpt-image-2.5-sunburst");
  expect(j.render?.image_quality).toBe("medium");
  expect(j.render?.prompt_version).toBe("improve-v4.3");
  expect(j.prompt).toMatchObject({ version: "improve-v4.3", photo_look: true, shape_rule: true, soft_block: true });
  expect(j.soft?.[0]).toMatchObject({ item: "cushion" });
});

test("2.9 «Улучшить» без денег — честный ответ за ≤ 3 с (без трат)", async ({ request }) => {
  const paid = await (await request.get("/api/draft/paid")).json() as { available: boolean; code: string | null };
  say("улучшение доступно:", paid.available, paid.code ?? "");
  // `dry_run` — сервер проверяет деньги и НИКОГДА не создаёт задание; при деньгах проверять тут нечего
  test.skip(paid.available, "деньги на улучшение есть — честный отказ проверить нельзя");
  const t = Date.now();
  const r = await request.post("/api/render", { data: { room: { w: 400, d: 300 }, items: [{ role: "диван", x: 100, y: 50, rot: 0, w: 200, d: 90 }],
    quality: "realistic", async: 1, no_registry: 1, dry_run: 1 }, headers: { origin: "https://remont-lab.online" } });
  const j = await r.json() as { code?: string; error?: string; job?: string };
  say("ответ", r.status(), j.code, Date.now() - t, "мс");
  expect(j.job, "платное задание не должно создаваться").toBeUndefined();
  expect(["no_credits", "unavailable"]).toContain(j.code);
  expect(Date.now() - t).toBeLessThan(3000);
});

// ——— demo-16: главная «стиль → комнаты», корзина сертификата, липкая шапка, возврат «назад» (строки карты 2.33–2.36) ———
const phone = { viewport: { width: 375, height: 667 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: "ru-RU" };
const basketReady = "typeof D !== 'undefined' && !!D && !!FLAT && !!(window.__basket && window.__basket.state())";
type Pkg = { mode: "pooled" | "split"; limits: { furniture: number; fitout: number } };
async function phonePage(browser: import("@playwright/test").Browser, q = "", pkg?: Pkg) {
  const ctx = await browser.newContext({ ...phone, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await ctx.newPage();
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  // пакет застройщика (demo-23: режим и лимиты двух бюджетов) — подменой ответа карточки, страница не трогается
  if (pkg) await page.route(/\/api\/apartments\//, async (r) => {
    const res = await r.fetch(); const j = await res.json() as { card?: { certificate?: { amount: number }; incentive?: Pkg & { total: number } } };
    const total = pkg.limits.furniture + pkg.limits.fitout;
    if (j.card?.certificate) { j.card.certificate.amount = total; j.card.incentive = { ...pkg, total }; }
    await r.fulfill({ response: res, body: JSON.stringify(j), headers: { ...res.headers(), "content-type": "application/json" } });
  });
  await page.goto(`/demo/${q}`, { waitUntil: "load" });
  await page.waitForFunction(basketReady, null, { timeout: 90_000 });
  return { ctx, page };
}
const basketState = (page: Page) => page.evaluate(() => {
  const w = window as unknown as { __basket: { state: () => { favorites: { favoriteId: string; displayName: string }[]; includedByRoom: Record<string, string> } } };
  const b = w.__basket.state();
  return { n: b.favorites.length, inc: b.includedByRoom, names: b.favorites.map((f) => f.displayName), cert: Number((document.getElementById("hmCert") as HTMLElement).dataset.included) };
});
const saveHeart = async (page: Page) => {
  await page.locator("#vFav").click();
  const name = await page.locator("#favName").inputValue();
  await page.locator("#favOk").click();
  await page.waitForFunction("!document.querySelector('#favPop #favName')", null, { timeout: 30_000 });
  await page.waitForTimeout(1200);
  return name;
};

test("2.33 первый экран телефона: вкладки стилей и ≥ 120 px фото первой комнаты до сгиба (375×667 и 390×844)", async ({ browser }) => {
  for (const vp of [{ width: 375, height: 667 }, { width: 390, height: 844 }]) {
    const ctx = await browser.newContext({ ...phone, viewport: vp });
    const page = await ctx.newPage();
    await page.goto("/demo/", { waitUntil: "load" });
    await page.waitForFunction("document.querySelectorAll('#styleTabs [data-style]').length > 0 && !!FLAT");
    const m = await page.evaluate(() => { const ph = document.querySelector("#hmRooms .hm-room .hm-ph")!.getBoundingClientRect(), tb = document.getElementById("styleTabs")!.getBoundingClientRect();
      return { tabsVisible: tb.top >= 0 && tb.bottom <= innerHeight, visiblePhotoHeight: Math.round(Math.max(0, Math.min(ph.bottom, innerHeight) - Math.max(ph.top, tb.bottom))) }; });
    say(`${vp.width}×${vp.height}:`, JSON.stringify(m));
    expect(m.tabsVisible).toBe(true);
    expect(m.visiblePhotoHeight).toBeGreaterThanOrEqual(120);
    await ctx.close();
  }
});

// 2.34 (demo-23 T-19/2): в липком состоянии полоса пакета — компакт (строка «Выбрано … лимит» + трек, легенда скрыта) — ≤ 140 px
// в обеих схемах: РФ (один бюджет) и UK (два раздельных бюджета)
test("2.34 липкая шапка после прокрутки ≤ 140 px (РФ и UK раздельно), вкладка стиля из любого места — комнаты стиля под шапкой", async ({ browser }) => {
  for (const q of ["", "?lang=en"]) {
    const ctx = await browser.newContext(phone);
    const page = await ctx.newPage();
    await page.goto(`/demo/${q}`, { waitUntil: "load" });
    await page.waitForFunction("document.querySelectorAll('#styleTabs [data-style]').length > 1 && !!FLAT");
    await page.evaluate("scrollTo(0, document.documentElement.scrollHeight)");
    await page.waitForTimeout(500);
    const st = await page.evaluate(`({ sticky: Math.round(Math.max(document.getElementById('hmHd').getBoundingClientRect().bottom, document.getElementById('styleTabs').getBoundingClientRect().bottom)),
      mode: document.getElementById('hmCert').dataset.mode, stuck: document.getElementById('hmCert').classList.contains('stuck'),
      legend: [...document.querySelectorAll('#hmCert .cs-lg, #hmCert .cs-ov')].some((e) => !!e.offsetParent) })`) as { sticky: number; mode: string; stuck: boolean; legend: boolean };
    say(`${q || "РФ"} липкая часть:`, JSON.stringify(st));
    expect(st.mode).toBe(q ? "split" : "pooled");
    expect(st.stuck).toBe(true);
    expect(st.legend).toBe(false);
    expect(st.sticky).toBeLessThanOrEqual(140);
    const id = await page.locator("#styleTabs [data-style]").nth(1).getAttribute("data-style");
    await page.locator(`#styleTabs [data-style="${id}"]`).click();
    await page.waitForTimeout(900);
    const r = await page.evaluate("({top: Math.round(document.getElementById('hmRooms').getBoundingClientRect().top), style: new URLSearchParams(location.search).get('style'), card: document.querySelector('#hmRooms .hm-room').dataset.style})") as { top: number; style: string; card: string };
    say("после вкладки:", JSON.stringify(r));
    expect(r.style).toBe(id);
    expect(r.card).toBe(id);
    expect(r.top).toBeGreaterThanOrEqual(st.sticky - 1);
    await ctx.close();
  }
});

// 2.35 корзина (владелец 18.10): две коллекции и по одной на каждую схему пакета при подменённом лимите — без ПДн, без номера менеджера.
// Перерасход (demo-23, ADR-0308) — не отказ, а доплата: полоса окна «выйдет за лимит на N», включение — только по «Доплата N — подтвердить?»
test("2.35 корзина: 0 на старте; первая гостиная включается сама; вторая — «вместо …?»; «Не включать»; перерасход — «выйдет за лимит», доплата с подтверждением (общий и раздельный пакет)", async ({ browser }) => {
  test.setTimeout(8 * 60_000);
  const { ctx, page } = await phonePage(browser, "?live=force");
  expect((await basketState(page)).cert).toBe(0);
  await page.locator("#hmRooms .hm-room [data-swap]").click();
  await page.waitForSelector("#vFav:visible");
  expect(await saveHeart(page)).toMatch(/ #\d+$/);
  const s1 = await basketState(page);
  say("после первого:", JSON.stringify(s1));
  expect(Object.keys(s1.inc).length).toBe(1);
  expect(s1.cert).toBeGreaterThan(0);
  await page.keyboard.press("Escape");
  await page.locator("#styleTabs [data-style]").nth(1).click();
  await page.locator("#hmRooms .hm-room [data-swap]").click();
  await page.waitForSelector("#vFav:visible");
  await page.locator("#vFav").click();
  await page.locator("#favOk").click();
  await expect(page.locator("#favPop")).toContainText(/вместо «.+ #1»/, { timeout: 30_000 });
  await page.locator("#favPop button.primary").click();
  const s2 = await basketState(page);
  expect(s2.n).toBe(2);
  expect(s2.cert).not.toBe(s1.cert);
  // «Не включать в сертификат» — из «⋯» избранного: шкала 0, вариант остаётся
  await page.keyboard.press("Escape");
  await page.evaluate("window.__basket.open('living')");
  const inc = Object.values(s2.inc)[0]!;
  await page.locator(`#favGrid [data-fmore="${inc}"]`).click();
  await page.locator("#favExcl").click();
  const s3 = await basketState(page);
  say("после «не включать»:", JSON.stringify(s3));
  expect(s3.cert).toBe(0);
  expect(s3.n).toBe(2);
  await ctx.close();
  // перерасход: мебель 100 000 — общий пакет (РФ) и раздельный (+ улучшения 50 000); гостиная дороже лимита мебели
  for (const pkg of [{ mode: "pooled", limits: { furniture: 100_000, fitout: 0 } }, { mode: "split", limits: { furniture: 100_000, fitout: 50_000 } }] as Pkg[]) {
    const o = await phonePage(browser, "?live=force", pkg);
    expect(await o.page.locator("#hmCert [role=group] [role=meter]").count()).toBe(pkg.mode === "split" ? 2 : 1);
    await o.page.locator("#hmRooms .hm-room [data-swap]").click();
    await o.page.waitForSelector("#vFav:visible");
    await expect(o.page.locator("#vsum .cs-ov")).toContainText(/выйдет за лимит на [\d\s  ]+₽/, { timeout: 30_000 });
    await o.page.locator("#vFav").click();
    await o.page.locator("#favOk").click();
    await expect(o.page.locator("#favPop")).toContainText(/Доплата [\d\s  ]+₽ — подтвердить\?/, { timeout: 30_000 });
    await expect(o.page.locator("#favPop")).toContainText("Изменить расстановку");
    await o.page.mouse.click(3, 3);                                  // закрыть мимо — без подтверждения ничего не меняется
    const s4 = await basketState(o.page);
    say(pkg.mode, "без подтверждения:", JSON.stringify(s4));
    expect(s4.n).toBe(1);
    expect(s4.inc).toEqual({});
    // из избранного: «Включить» → тот же вопрос → «Подтвердить» — включено, на полосе доплата
    await o.page.keyboard.press("Escape");
    await o.page.evaluate("window.__basket.open('living')");
    await o.page.locator("#favGrid [data-finc]").first().click();
    await expect(o.page.locator("#favPop")).toContainText(/Доплата [\d\s  ]+₽ — подтвердить\?/);
    await o.page.locator("#favPop button.primary").click();
    const s5 = await basketState(o.page);
    expect(Object.keys(s5.inc).length).toBe(1);
    await expect(o.page.locator("#hmCert .cs-ov")).toContainText(/доплата [\d\s  ]+₽/);
    await o.ctx.close();
  }
});

test("2.36 возврат «назад»: «Перейти →» из окна — экран избранного; «назад» — то же окно, ракурс и шторка; «вперёд» — избранное", async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  const { ctx, page } = await phonePage(browser, "?live=force");
  await page.locator("#hmRooms .hm-room [data-swap]").click();
  await page.waitForSelector("#vFav:visible");
  await saveHeart(page);
  await page.evaluate("vwCamGo(1); vwSheet(1)");
  await page.waitForTimeout(700);
  const before = await page.evaluate("({vid: allVariants()[cur].id, photo: VW.photo, sheet: document.getElementById('vside').dataset.pos})");
  await page.evaluate("histGoFavs('living')");
  await expect(page.locator("#screen-fav")).toBeVisible();
  await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/);
  await page.goBack();
  await expect(page.locator("#shot")).toHaveClass(/\bon\b/, { timeout: 20_000 });
  await page.waitForTimeout(1500);
  const back = await page.evaluate("({vid: allVariants()[cur].id, photo: VW.photo, sheet: document.getElementById('vside').dataset.pos})");
  say("до:", JSON.stringify(before), "после «назад»:", JSON.stringify(back));
  expect(back).toEqual(before);
  await page.goForward();
  await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/, { timeout: 20_000 });
  await expect(page.locator("#screen-fav")).toBeVisible();
  await ctx.close();
});

// 2.38 (demo-17, владелец 18.10): избранное — отдельный экран с «← Назад» туда, откуда добавили; поле имени — курсор в конце сразу
test("2.38 избранное — экран: ♡ → курсор в конце имени; «Перейти →» — экран с «← Назад»; «← Назад» — то же окно; «Открыть» → «назад» — экран", async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  const { ctx, page } = await phonePage(browser, "?live=force");
  await page.locator("#hmRooms .hm-room [data-swap]").click();
  await page.waitForSelector("#vFav:visible");
  await page.locator("#vFav").click();
  // фокус в том же тапе (иначе iPhone не откроет клавиатуру), каретка в конце, без выделения
  const caret = await page.evaluate("(() => { const i = document.getElementById('favName'); return { focus: document.activeElement === i, start: i.selectionStart, end: i.selectionEnd, len: i.value.length }; })()") as { focus: boolean; start: number; end: number; len: number };
  say("поле имени:", JSON.stringify(caret));
  expect(caret.focus).toBe(true);
  expect(caret.len).toBeGreaterThan(0);
  expect([caret.start, caret.end]).toEqual([caret.len, caret.len]);
  await page.locator("#favOk").click();
  await page.waitForFunction("!document.querySelector('#favPop #favName')", null, { timeout: 30_000 });
  await page.waitForTimeout(1200);
  await page.evaluate("vwCamGo(1); vwSheet(1)");
  await page.waitForTimeout(700);
  const view = "({vid: allVariants()[cur].id, photo: VW.photo, sheet: document.getElementById('vside').dataset.pos})";
  const before = await page.evaluate(view);
  await page.evaluate("histGoFavs('living')");   // как «Перейти →» тоста
  await expect(page.locator("#screen-fav")).toBeVisible();
  await expect(page.locator("#favBack")).toBeVisible();
  await expect(page.locator("#favSec")).toHaveCount(0);   // раскрывающейся секции на главной больше нет
  await expect(page.locator("#favTitle")).toHaveText(/Избранное · 1/);
  expect(await page.evaluate("location.hash")).toBe("#fav");
  await page.locator("#favBack").click();
  await expect(page.locator("#shot")).toHaveClass(/\bon\b/, { timeout: 20_000 });
  await page.waitForTimeout(1500);
  const back = await page.evaluate(view);
  say("до:", JSON.stringify(before), "после «← Назад»:", JSON.stringify(back));
  expect(back).toEqual(before);
  // «Открыть» с карточки — окно; «назад» браузера — снова экран избранного
  await page.evaluate("histGoFavs('living')");
  await expect(page.locator("#screen-fav")).toBeVisible();
  await page.locator("#favGrid .favcard .acts [data-fopen]").click();
  await expect(page.locator("#shot")).toHaveClass(/\bon\b/, { timeout: 20_000 });
  await page.goBack();
  await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/, { timeout: 20_000 });
  await expect(page.locator("#screen-fav")).toBeVisible();
  await ctx.close();
});

// ——— demo-02 шторка v5.2: свёрнутая = плашка + чип + кнопка; по умолчанию при открытии и после замены (строка карты 2.37) ———
const collapsed = (page: Page) => page.evaluate(() => {
  const sd = document.getElementById("vside") as HTMLElement, c = (document.getElementById("vCta") as HTMLElement).getBoundingClientRect();
  return { pos: sd.dataset.pos, h: Math.round(innerHeight - sd.getBoundingClientRect().top), ctaTop: Math.round(c.top), ctaBottom: Math.round(c.bottom), H: innerHeight };
});
test("2.37 свёрнутая шторка = плашка + чип + кнопка; по умолчанию при открытии и после замены (375×667 и 390×844)", async ({ browser }) => {
  test.setTimeout(4 * 60_000);
  for (const vp of [{ width: 375, height: 667 }, { width: 390, height: 844 }]) {
    const ctx = await browser.newContext({ ...phone, viewport: vp });
    const page = await ctx.newPage();
    await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
    await page.goto("/demo/?live=force", { waitUntil: "load" });
    await page.waitForFunction(basketReady, null, { timeout: 90_000 });
    await page.locator("#hmRooms .hm-room [data-swap]").click();
    await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
    // у варианта может быть реалистичное фото — тогда окно в «Фото», где кнопки нет (снимок уже есть); меряем в 3D
    await page.evaluate("if (VW.mode === 'photo') vwMode('walk')");
    await page.waitForTimeout(900);
    const open = await collapsed(page);
    say(`${vp.width}×${vp.height}`, "открыл окно:", JSON.stringify(open));
    expect(open.pos).toBe("0");
    expect(open.ctaTop).toBeGreaterThanOrEqual(0);
    expect(open.ctaBottom).toBeLessThanOrEqual(open.H);
    if (vp.height === 667) expect(open.h).toBeLessThanOrEqual(190);
    await expect(page.locator("#vCta")).toHaveText(/реалистичнее/);
    // замена как человек: чип → полная, «Заменить» у первой строки, первая карточка ленты
    await page.locator("#vgrip").click();
    await expect.poll(() => page.evaluate("document.getElementById('vside').dataset.pos")).toBe("3");
    await page.waitForTimeout(500);
    const sumNow = async () => Number(await page.locator("#vsum").getAttribute("data-sum"));
    const before = await sumNow();
    await page.locator("#shotbody [data-rep]").first().click();
    await page.locator("#sheet .mini:has-text('Заменить')").first().click();
    await expect.poll(sumNow).not.toBe(before);
    await page.waitForTimeout(900);
    const after = await collapsed(page);
    say("после замены:", JSON.stringify(after), "сумма", before, "→", await sumNow());
    expect(after.pos).toBe("0");
    expect(after.ctaTop).toBeGreaterThanOrEqual(0);
    expect(after.ctaBottom).toBeLessThanOrEqual(after.H);
    await ctx.close();
  }
});

// ——— demo-05 п.1(е): ценники-пины в пределах кадра (ночной отчёт `scene_artifacts.py` пины не видит — нужен браузер) ———
// Видимый пин — целиком внутри области сцены (слой `#vpins` ∩ холст ∩ экран) и не заходит на шторку `#vside`, в т.ч. на её шапку
// (пилюля + плашка + чип + кнопка — всё выше `#vscroll`). Правило страницы то же (`vwPinsTick`: «только целиком в кадре, не под
// кнопками и шторкой») — тест ловит его поломку. Каждый стиль, телефон 375×667 и компьютер; меряем, когда пины перестали двигаться.
type Box = { left: number; top: number; right: number; bottom: number };
const pinsInFrame = (page: Page) => page.evaluate(() => {
  const r = (e: Element | null): Box | null => {
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0 ? { left: b.left, top: b.top, right: b.right, bottom: b.bottom } : null;
  };
  const cut = (a: Box, b: Box): Box => ({ left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) });
  const hit = (a: Box, b: Box) => a.left < b.right - 0.5 && a.right > b.left + 0.5 && a.top < b.bottom - 0.5 && a.bottom > b.top + 0.5;
  const R = (b: Box | null) => b && `${Math.round(b.left)},${Math.round(b.top)}–${Math.round(b.right)},${Math.round(b.bottom)}`;
  const scr: Box = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
  const layer = r(document.getElementById("vpins")), cv = r(document.querySelector("#shot .livecv"));
  const scene = layer && cv ? cut(cut(layer, cv), scr) : null;
  const sd = r(document.getElementById("vside")), sc = r(document.getElementById("vscroll"));
  const sheet = sd ? cut(sd, scr) : null;
  const head = sd && sc ? cut({ ...sd, bottom: Math.max(sd.top, sc.top) }, scr) : null;
  const pins = [...document.querySelectorAll("#vpins .vpin:not([hidden])")].map((n) => ({ t: (n as HTMLElement).innerText, b: r(n) }))
    .filter((p): p is { t: string; b: Box } => !!p.b);
  const bad: string[] = [];
  for (const p of pins) {
    const at = `«${p.t}» ${R(p.b)}`;
    if (!scene || p.b.left < scene.left - 0.5 || p.b.right > scene.right + 0.5 || p.b.top < scene.top - 0.5 || p.b.bottom > scene.bottom + 0.5) bad.push(`${at} за краем сцены`);
    if (head && head.bottom > head.top && hit(p.b, head)) bad.push(`${at} на шапке шторки`);
    else if (sheet && sheet.bottom > sheet.top && hit(p.b, sheet)) bad.push(`${at} на шторке`);
  }
  return { n: pins.length, bad, key: pins.map((p) => R(p.b)).join(" "), scene: R(scene), head: R(head) };
});
async function pinsEveryStyle(page: Page, label: string): Promise<string[]> {
  await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await page.goto("/demo/?live=force", { waitUntil: "load" });
  await page.waitForFunction("document.querySelectorAll('#styleTabs [data-style]').length > 0 && !!FLAT", null, { timeout: 90_000 });
  const n = await page.locator("#styleTabs [data-style]").count();
  const bad: string[] = [];
  for (let i = 0; i < n; i++) {
    const style = (await page.locator("#styleTabs [data-style]").nth(i).innerText()).trim();
    await page.locator("#styleTabs [data-style]").nth(i).click();
    await page.locator("#hmRooms .hm-room [data-swap]").click();
    await expect(page.locator("#shot")).toHaveClass(/\bon\b/);
    await page.evaluate("if (VW.mode !== 'walk') vwMode('walk')");   // у варианта может быть реалистичное фото — пины только в 3D
    await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
    await expect.poll(() => page.locator("#vpins .vpin:not([hidden])").count(), { timeout: 20_000 }).toBeGreaterThanOrEqual(3);
    // пины стоят (шторка доехала, камера на месте): два замера подряд через 400 мс совпали
    let m = await pinsInFrame(page);
    for (let k = 0; k < 15; k++) {
      await page.waitForTimeout(400);
      const prev = m.key;
      m = await pinsInFrame(page);
      if (m.key === prev) break;
    }
    say(`${label} ${style}: пинов ${m.n}, сцена ${m.scene}, шапка шторки ${m.head ?? "—"}, вне кадра ${m.bad.length}`);
    bad.push(...m.bad.map((b) => `${label} ${style}: ${b}`));
    await page.keyboard.press("Escape");
    await expect(page.locator("#shot")).not.toHaveClass(/\bon\b/);
  }
  return bad;
}
test("п.1(е) пины цен в пределах кадра: внутри сцены и не на шторке — каждый стиль, телефон 375×667 и компьютер (demo-05)", async ({ browser, page }) => {
  test.setTimeout(8 * 60_000);
  const bad = await pinsEveryStyle(page, "компьютер");
  const ctx = await browser.newContext(phone);
  bad.push(...await pinsEveryStyle(await ctx.newPage(), "телефон 375×667"));
  await ctx.close();
  expect(bad, bad.join("\n")).toEqual([]);
});
