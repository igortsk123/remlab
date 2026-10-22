import { test, expect, type Page } from "@playwright/test";

// Демо для застройщика на ПРОДЕ (план b2b-12): то, что гость заметит за первые две минуты. Данные — живые, поэтому
// проверяем инварианты, а не конкретные товары: стили есть и у каждого есть кадр, замена меняет сумму, ссылка на
// вариант открывает его, английский режим без русских надписей в шапке, ничего не падает в консоль.

type DemoWindow = Window & { allVariants: () => { id: string; style: string }[] };

async function openDemo(page: Page, q = ""): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`/demo/${q}`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => typeof (window as unknown as DemoWindow).allVariants === "function" && (window as unknown as DemoWindow).allVariants().length > 0);
  return errors;
}

test("1.1 стили опубликованы, у каждого есть кадр, данные свежие", async ({ page, request }) => {
  const errors = await openDemo(page);
  const styles = await page.evaluate(() => (window as unknown as DemoWindow).allVariants().map((v) => v.style));
  expect(styles.length).toBeGreaterThanOrEqual(4);
  expect(new Set(styles).size).toBe(styles.length);
  // вкладки главной — стили, по одной на опубликованный вариант (demo-16)
  await expect(page.locator("#styleTabs [data-style]")).toHaveCount(styles.length);
  const res = await request.get("/demo/demo-data.json");
  const age = (Date.now() - new Date(res.headers()["last-modified"] ?? 0).getTime()) / 86_400_000;
  expect(age, "витрина демо старше 2 суток").toBeLessThan(2);
  // кадры приезжают с сервера позже данных — ждём, потом называем стили без кадра поимённо. «Есть кадр» — правило главной
  // (`index.html:pubShot`: кадр опубликованного состояния, снятый с нынешней точки, T-20261022-16): любой кадр варианта
  // засчитывал и кадр прежней расстановки или прежнего ракурса, которого главная не покажет
  await expect.poll(() => page.evaluate("Array.isArray(shots) && shots.length > 0"), { timeout: 15_000 }).toBe(true);
  const noShot = await page.evaluate("allVariants().filter(v => !v.mine && !v.cid && !pubShot(v)).map(v => v.style)");
  expect(noShot, "стили без фото своей расстановки и своих ракурсов").toEqual([]);
  expect(errors).toEqual([]);
});

test("замена предмета меняет сумму; ссылка на вариант открывает его", async ({ page }) => {
  await openDemo(page);
  await page.locator("#styleTabs [data-style]").nth(1).click();
  await page.locator("#hmRooms .hm-room [data-swap]").click();
  // переменные страницы (items, D, sel, tryOn, LAST_SUM, cur) — глобальные `let`, не свойства window: строкой
  const before = await page.evaluate("LAST_SUM");
  const changed = await page.evaluate(`(() => {
    const base = (r) => String(r).replace(/\\s+\\d+$/, "");
    const ok = (i) => i.sku && ((D.feeds || {})[base(i.role)] || []).some((f) => f.sid !== i.sku.sid && f.w && f.d);
    const it = items.find(ok); if (!it) return false;
    const alt = D.feeds[base(it.role)].find((f) => f.sid !== it.sku.sid && f.w && f.d);
    sel = it; tryOn(alt); return true;
  })()`);
  expect(changed).toBe(true);
  await expect.poll(() => page.evaluate("LAST_SUM")).not.toBe(before);
  // ссылка на вариант — в НОВОЙ вкладке: в этой вариант уже выбран нажатием, проверка ничего бы не доказала (verify)
  const vid = (await page.evaluate("allVariants()[allVariants().length - 1].id")) as string;
  const fresh = await page.context().newPage();
  await fresh.goto(`/demo/#v=${vid}`, { waitUntil: "networkidle" });
  await expect.poll(() => fresh.evaluate("(allVariants()[cur] || {}).id")).toBe(vid);
});

test("английский режим: первый экран без русских надписей", async ({ page }) => {
  await openDemo(page, "?lang=en");
  await page.waitForFunction("!!FLAT");
  const head = await page.locator("#hmHd, #flatPrice, #hmCert, #hmHint, #styleTabs, #hmRooms").allInnerTexts();
  expect(head.join(" ")).not.toMatch(/[А-Яа-яЁё]/);
});

test("комната «Спальня 1»: общая заглушка неготовой комнаты в каждом стиле (каталог снят с показа, ADR-0299; demo-16)", async ({ page }) => {
  const errors = await openDemo(page);
  const stub = page.locator('#hmRooms [data-room="bedroom-1"]');
  await expect(stub).toContainText("Спальня 1");
  await expect(stub).toContainText("м²");
  await expect(stub).toContainText("появится следующим шагом");
  await expect(page.locator('[data-br-role="кровать"]')).toHaveCount(0);   // фотокаталога на странице нет
  await page.locator("#styleTabs [data-style]").last().click();
  await expect(stub).toContainText("появится следующим шагом");
  expect(errors).toEqual([]);
});
