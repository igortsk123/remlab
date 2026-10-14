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

test("стили опубликованы, у каждого есть кадр, данные свежие", async ({ page, request }) => {
  const errors = await openDemo(page);
  const styles = await page.evaluate(() => (window as unknown as DemoWindow).allVariants().map((v) => v.style));
  expect(styles.length).toBeGreaterThanOrEqual(4);
  expect(new Set(styles).size).toBe(styles.length);
  const cards = page.locator("[data-swap]");
  await expect(cards).toHaveCount(styles.length);
  const res = await request.get("/demo/demo-data.json");
  const age = (Date.now() - new Date(res.headers()["last-modified"] ?? 0).getTime()) / 86_400_000;
  expect(age, "витрина демо старше 2 суток").toBeLessThan(2);
  // кадры приезжают с сервера позже данных — ждём, потом называем стили без кадра поимённо
  await expect.poll(() => page.evaluate("Array.isArray(shots) && shots.length > 0"), { timeout: 15_000 }).toBe(true);
  const noShot = await page.evaluate("allVariants().filter(v => !shots.some(s => s.vid === v.id && !s.svc)).map(v => v.style)");
  expect(noShot, "стили без кадра").toEqual([]);
  expect(errors).toEqual([]);
});

test("замена предмета меняет сумму; ссылка на вариант открывает его", async ({ page }) => {
  await openDemo(page);
  await page.locator('[data-swap="1"]').click();
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
  const vid = (await page.evaluate("allVariants()[1].id")) as string;
  await page.goto(`/demo/#v=${vid}`, { waitUntil: "networkidle" });
  await expect.poll(() => page.evaluate("(allVariants()[cur] || {}).id")).toBe(vid);
});

test("английский режим: шапка и вкладки без русских надписей", async ({ page }) => {
  await openDemo(page, "?lang=en");
  const head = await page.locator(".tabs, #flatPrice").allInnerTexts();
  expect(head.join(" ")).not.toMatch(/[А-Яа-яЁё]/);
});
