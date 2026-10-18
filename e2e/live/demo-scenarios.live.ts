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
const num = (t: string) => Number((t.match(/([\d\s ]+)\s*₽/)?.[1] ?? "").replace(/\D/g, ""));

test("1.2–1.5 шапка и вкладки: консультация, ипотека, «i», 3D, план, «скоро»", async ({ page }) => {
  const errors = await openDemo(page);
  for (const id of ["#pcCons", "#pcMort"]) {
    await page.locator(id).click();
    await expect(page.locator("#shot")).toBeVisible();
    say(id, JSON.stringify((await page.locator("#shotbody").innerText()).slice(0, 60)));
    await page.keyboard.press("Escape");
  }
  await page.locator("#payInfo").click();
  await expect(page.locator("#payInfoTxt")).toBeVisible();
  // кнопки «Пройтись по квартире в 3D» в шапке нет (владелец 16.10, demo-02 п.8) — 3D внутри окна варианта
  await expect(page.locator("#pc3d")).toHaveCount(0);
  await page.locator("#tab-plan").click();
  await expect(page.locator("#screen-plan")).toBeVisible();
  // неготовые комнаты (demo-02 v3): вкладки нажимаются и показывают одинаковую заглушку с площадью из плана
  const soon = await page.locator("[data-soon]").allInnerTexts();
  say("вкладки неготовых комнат:", soon.join(" | "));
  expect(soon.length).toBeGreaterThanOrEqual(5);
  for (let k = 0; k < soon.length; k++) {
    await page.locator("[data-soon]").nth(k).click();
    await expect(page.locator("#screen-soon")).toBeVisible();
    await expect(page.locator("#soonTitle")).toContainText("м²");
    await expect(page.locator("#soonText")).toContainText("Скоро");
  }
  expect(errors).toEqual([]);
});

test("2.1–2.3 окно кадра: фото, список, числа как на карточке", async ({ page }) => {
  await openDemo(page);
  await page.locator("#tab-room").click();
  const n = await page.locator("button[data-swap]").count();
  for (let i = 0; i < n; i++) {
    const card = await page.locator(".lay .pr").nth(i).innerText();
    await page.locator("button[data-swap]").nth(i).click();
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
  await page.locator("#tab-room").click();
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
test("2.25–2.26 фото готово для этой расстановки → «Фото» само; расстановку меняли во время съёмки → 3D и подсказка", async ({ page }) => {
  let ready = false;
  await page.route(/\/api\/render/, (r) => r.fulfill({ json: { job: "fake-" + Date.now() } }));
  await page.route(/\/api\/job\?/, (r) => r.fulfill({ json: ready
    ? { shots: [{ camera: "C1", url: "/demo/img/og.jpg" }, { camera: "C2", url: "/demo/img/og.jpg" }], backend: "fake" }
    : { status: "running", eta: 30 } }));
  await openDemo(page, "?live=force");
  await page.evaluate("shots = shots.filter((x) => x.quality !== 'realistic'); openLiveWindow()");
  await page.waitForFunction("LIVE.scene && LIVE.state === 'ready'", null, { timeout: 120_000 });
  await page.locator("#vCta").click();
  await expect(page.locator("#vCta")).toContainText("Рисуем фото");
  expect(await page.evaluate("VW.mode")).toBe("walk");
  ready = true;
  await expect.poll(() => page.evaluate("VW.mode"), { timeout: 20_000 }).toBe("photo");
  await expect(page.locator('[data-vm="photo"]')).toBeVisible();
  await expect(page.locator("#vCta")).toBeHidden();
  ready = false;
  await page.evaluate("(() => { const g = devGroups().find((x) => x.kind === 'flooring'); devSet(g.id, g.variants[1].id); })()");
  await expect.poll(() => page.evaluate("VW.mode")).toBe("walk");               // изменение → 3D
  await page.locator("#vCta").click();
  await page.evaluate("(() => { const g = devGroups().find((x) => x.kind === 'flooring'); devSet(g.id, g.variants[2].id); })()");
  ready = true;
  await expect(page.locator("#shot .vready")).toBeVisible({ timeout: 20_000 });  // «Фото готово для прежней расстановки»
  expect(await page.evaluate("VW.mode")).toBe("walk");
  await expect(page.locator('[data-vm="photo"]')).toBeHidden();
});

// 2.27 (demo-09, дополнение 17.10): фото нейросети 13.10 сняты с прежних расстановок — карточка показывает кадр ТОЛЬКО своей расстановки
test("2.27 карточка: кадр своей расстановки или «Откройте — покажем в 3D», не старое фото", async ({ page }) => {
  await openDemo(page);
  await page.waitForFunction("shots.length > 0");
  await page.locator("#tab-room").click();
  const cards = await page.evaluate(`allVariants().map((v, i) => { const el = document.querySelectorAll('#coll .lay')[i], im = el && el.querySelector('img.pv');
    const s = im ? shots.find((x) => x.url === im.dataset.url) : null;
    return { style: v.style, shown: s ? s.quality + ':' + (s.stateId ? 'state' : 'items') : (el && el.querySelector('.nopv') ? 'заглушка' : '?'), fits: !s || shotFits(s, v) }; })`) as { style: string; shown: string; fits: boolean }[];
  say(cards.map((c) => `${c.style}: ${c.shown}`).join(" | "));
  for (const c of cards) expect(c.fits, `${c.style}: на карточке кадр чужой расстановки`).toBe(true);
  expect(cards.every((c) => c.shown !== "?")).toBe(true);
});

test("2.5–2.6 замена из окна: лента, выбор, сумма пересчитана, окно в 3D с «Сделать реалистичнее»", async ({ page }) => {
  await openDemo(page);
  await page.locator("#tab-room").click();
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
  await page.locator("#tab-room").click();
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
  await page.locator("#tab-room").click();
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
  await page.locator("text=Добавить новую расстановку").first().click();
  await expect(page.locator("#consHint")).toBeVisible();
  say("подсказка:", (await page.locator("#consHint").innerText()).slice(0, 50));
});

test("2.14–2.15 «поделиться» иконкой с подтверждением и избранное сердечком с именем коллекции (demo-15)", async ({ page }) => {
  await openDemo(page);
  await page.locator("#tab-room").click();
  await expect(page.locator("#coll button[data-link], #feedShare, #collSave")).toHaveCount(0);   // текстовой «Ссылки» и «Избранное» внизу нет
  await page.evaluate("navigator.share = undefined");                                            // без системного меню — копирование + тост
  await page.locator("#coll button[data-share]").first().click();
  await expect(page.locator("#toast")).toContainText(/скопирована/);
  say("буфер:", await page.evaluate("navigator.clipboard.readText()"));
  await page.locator("#coll button[data-favorite]").first().click();
  await expect(page.locator("#favName")).toHaveValue(/ #\d+$/);                                 // «<Стиль> #N»
  say("имя по умолчанию:", await page.locator("#favName").inputValue());
  await page.locator("#favNo").click();                                                         // ночью в базу не пишем
  await expect(page.locator("#favPop")).toHaveCount(0);
});

test("1.6 английский: конструктор и ожидание без русских подписей", async ({ page }) => {
  await openDemo(page, "?lang=en");
  await page.locator("#tab-room").click();
  await page.locator("text=Add a new layout").first().click();
  const t = await page.locator("#consWhat, #consSum, #consHint").allInnerTexts();
  say(t.join(" | ").slice(0, 160));
  expect(t.join(" ")).not.toMatch(/[А-Яа-яЁё]/);
});

test("2.18 телефон: без горизонтальной прокрутки, план во всю ширину", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "ru-RU" });
  const page = await ctx.newPage();
  await openDemo(page);
  const sw = await page.evaluate("[document.documentElement.scrollWidth, innerWidth]") as number[];
  say("ширина страницы / экрана:", sw.join(" / "));
  expect(sw[0]!).toBeLessThanOrEqual(sw[1]! + 1);
  await page.locator("#tab-room").click();
  await page.locator("text=Добавить новую расстановку").first().click();
  const w = await page.evaluate("stage.getBoundingClientRect().width / innerWidth") as number;
  say("план занимает ширины экрана:", Math.round(w * 100), "%");
  expect(w).toBeGreaterThan(0.9);
  await ctx.close();
});

// 2.29 (demo-11, ADR-0302): чем нарисует «Сделать реалистичнее» — без оплаты, пробным запросом (`dry_run` задания не создаёт никогда)
test("2.29 реалистичное фото: модель sunburst medium и промпт improve-v4 (ADR-0305) у рисующего процесса (пробный запрос, без трат)", async ({ request }) => {
  const r = await request.post("/api/render", { data: { async: 1, quality: "realistic", dry_run: 1, style: "сканди", room: { w: 439, d: 325 }, items: [{ role: "диван", x: 1, y: 1 }] } });
  const j = await r.json() as { dry_run?: boolean; code?: string; render?: { realistic_model?: string; image_quality?: string; prompt_version?: string }; render_from?: string; prompt?: { version?: string; photo_look?: boolean; shape_rule?: boolean } };
  say("ответ", r.status(), JSON.stringify(j).slice(0, 220));
  if (!j.dry_run) { say("улучшение сейчас недоступно (", j.code, ") — модель не проверить, честный отказ"); expect([402, 503]).toContain(r.status()); return; }
  expect(j.render_from).toBe("proxy");
  expect(j.render?.realistic_model).toBe("openai/gpt-image-2.5-sunburst");
  expect(j.render?.image_quality).toBe("medium");
  expect(j.render?.prompt_version).toBe("improve-v4");
  expect(j.prompt).toMatchObject({ version: "improve-v4", photo_look: true, shape_rule: true });
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
