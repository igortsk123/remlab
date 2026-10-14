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
  await expect(page.locator("#pc3d")).toHaveAttribute("href", /\/flat/);
  await page.locator("#tab-plan").click();
  await expect(page.locator("#screen-plan")).toBeVisible();
  const soon = await page.locator(".tab.soon").allInnerTexts();
  say("вкладки «скоро»:", soon.join(" | "));
  expect(soon.every((t) => /скоро/.test(t) || !/Спальня 2/.test(t))).toBe(true);
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
    const head = (await page.locator("#vsum b").innerText()).replace(/\s+/g, " ");   // окно варианта (demo-02): сумма в шапке колонки
    say(`вариант ${i}: карточка «${card}» | окно «${head}»`);
    expect(Number(head.match(/^(\d+)/)?.[1]), "число товаров").toBe(Number(card.match(/^(\d+)/)?.[1]));
    expect(num(head), "сумма").toBe(num(card.split("·").pop()!));
    await page.keyboard.press("Escape");
  }
});

test("2.4 ракурсы 1/2 и 3D переключаются в одном окне (demo-02)", async ({ page }) => {
  await openDemo(page, "?live=force");
  await page.locator("#tab-room").click();
  await page.locator("button[data-swap]").first().click();
  for (const m of ["c2", "walk", "c1"]) {
    const t = Date.now();
    await page.locator(`[data-vm="${m}"]`).click();
    await expect(page.locator(`[data-vm="${m}"]`)).toHaveClass(/on/);
    say(`режим ${m}: ${Date.now() - t} мс`);
  }
  await expect(page.locator("#shot .livecv, #shot .shotwrap img.vmain").first()).toBeVisible();
});

test("2.5–2.6 замена из окна: лента, выбор, сумма пересчитана, зовём снять фото", async ({ page }) => {
  await openDemo(page);
  await page.locator("#tab-room").click();
  await page.locator("button[data-swap]").first().click();
  const before = num(await page.locator("#vsum b").innerText());
  await page.locator("#shotbody [data-rep]").first().click();
  await expect(page.locator("#sheet")).toBeVisible();
  const cards = page.locator("#sheet .mini:has-text('Заменить')");
  await expect(cards.first()).toBeVisible();
  say("замен в ленте:", await cards.count());
  expect(await cards.count()).toBeGreaterThanOrEqual(3);
  await cards.first().click();
  await expect.poll(async () => num(await page.locator("#vsum b").innerText())).not.toBe(before);
  say("сумма:", before, "→", num(await page.locator("#vsum b").innerText()));
  await expect(page.locator("#shReshoot")).toBeVisible();
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
  await page.locator('[data-vm="plan"]').click();        // «План» в окне варианта (demo-02) — конструктор
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
  await page.keyboard.press("Escape");
  await page.locator("text=Добавить новую расстановку").first().click();
  await expect(page.locator("#consHint")).toBeVisible();
  say("подсказка:", (await page.locator("#consHint").innerText()).slice(0, 50));
});

test("2.14–2.15 ссылка с подтверждением, избранное и «отправить себе»", async ({ page }) => {
  await openDemo(page);
  await page.locator("#tab-room").click();
  await page.locator("button[data-link]").first().click();
  await expect(page.locator("#toast")).toContainText(/скопирована/);
  say("буфер:", await page.evaluate("navigator.clipboard.readText()"));
  await page.locator("button.heart").first().click();
  await page.locator("#feedShare").click();
  await expect(page.locator("text=Получить в Telegram").first()).toBeVisible();
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
