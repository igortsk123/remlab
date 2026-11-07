import { test, expect, type Page } from "@playwright/test";

import { demoUrl } from "./browser";
import { HOME_READY, homeStyles, pickStyle } from "./home";

// Демо для застройщика на ПРОДЕ (план b2b-12): то, что гость заметит за первые две минуты. Данные — живые, поэтому
// проверяем инварианты, а не конкретные товары: стили есть и у каждого есть кадр, замена меняет сумму, ссылка на
// вариант открывает его, английский режим без русских надписей в шапке, ничего не падает в консоль.

type DemoWindow = Window & { allVariants: () => { id: string; style: string }[] };

async function openDemo(page: Page, q = ""): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(demoUrl(`/demo/${q}`), { waitUntil: "networkidle" });
  await page.waitForFunction(() => typeof (window as unknown as DemoWindow).allVariants === "function" && (window as unknown as DemoWindow).allVariants().length > 0);
  return errors;
}

test("1.1 стили опубликованы, у каждого есть кадр, данные свежие", async ({ page, request }) => {
  const errors = await openDemo(page);
  // стили — по вариантам ГОСТИНОЙ: с показом спален (T-20261107-04/5) `allVariants()` держит и варианты спален тех же стилей
  // (было «16 ≠ 6»), уникален стиль только внутри комнаты (`roomIdOf` страницы)
  const styles = (await page.evaluate("allVariants().filter((v) => roomIdOf(v) === 'living').map((v) => v.style)")) as string[];
  expect(styles.length).toBeGreaterThanOrEqual(4);
  expect(new Set(styles).size).toBe(styles.length);
  // вместо вкладок стилей — строка выбранного интерьера «Вариант N» (home-mix-01 шаг 5)
  await expect(page.locator("#hmMixName")).toHaveText(/^Вариант(ы)?\s\d/);
  const res = await request.get("/demo/demo-data.json");
  const age = (Date.now() - new Date(res.headers()["last-modified"] ?? 0).getTime()) / 86_400_000;
  expect(age, "витрина демо старше 2 суток").toBeLessThan(2);
  // кадры приезжают с сервера позже данных — ждём, потом называем стили без кадра поимённо. «Есть кадр» — правило главной
  // (`index.html:pubShot`: кадр опубликованного состояния, снятый с нынешней точки, T-20261022-16): любой кадр варианта
  // засчитывал и кадр прежней расстановки или прежнего ракурса, которого главная не покажет
  await expect.poll(() => page.evaluate("Array.isArray(shots) && shots.length > 0"), { timeout: 15_000 }).toBe(true);
  // по всем комнатам: спальня без кадра — тоже дефект показа; имя — номер варианта (стиль у комнат повторяется)
  const noShot = await page.evaluate("allVariants().filter(v => !v.mine && !v.cid && !pubShot(v)).map(v => v.id)");
  expect(noShot, "стили без фото своей расстановки и своих ракурсов").toEqual([]);
  expect(errors).toEqual([]);
});

test("замена предмета меняет сумму; ссылка на вариант открывает его", async ({ page }) => {
  await openDemo(page);
  await pickStyle(page, (await homeStyles(page))[1]!.id);
  await page.locator("#hmRooms .hm-room[data-room=living] [data-swap]").click();
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
  await fresh.goto(demoUrl(`/demo/#v=${vid}`), { waitUntil: "networkidle" });
  await expect.poll(() => fresh.evaluate("(allVariants()[cur] || {}).id")).toBe(vid);
});

test("английский режим: первый экран без русских надписей", async ({ page }) => {
  await openDemo(page, "?lang=en");
  await page.waitForFunction("!!FLAT");
  const head = await page.locator("#hmHd, #flatPrice, #hmView, #hmCert, #hmMix, #hmHint, #hmRooms").allInnerTexts();
  expect(head.join(" ")).not.toMatch(/[А-Яа-яЁё]/);
});

// СПАЛЬНИ ПОКАЗЫВАЕМ (T-20261107-04/5; было — заглушка «появится следующим шагом», demo-16): в каждом стиле у «Спальни 1» —
// карточка с фото нейросети (`drawHome`: только `realistic`-кадр, иначе «Откройте — покажем в 3D»), заглушек спален нет. Кадры
// приезжают позже данных — ждём. Фотокаталог спальни (ADR-0299) по-прежнему снят с показа
test("комната «Спальня 1»: карточка с фото нейросети в каждом стиле, заглушек спален нет", async ({ page }) => {
  const errors = await openDemo(page);
  await page.waitForFunction(HOME_READY);
  const card = page.locator('#hmRooms article.hm-room[data-room="bedroom-1"]');
  const bad: string[] = [];
  for (const s of await homeStyles(page)) {
    await pickStyle(page, s.id);
    const ok = await expect
      .poll(async () => (await card.count()) === 1 && !!(await card.locator(".hm-ph img").getAttribute("src").catch(() => null)), { timeout: 20_000 })
      .toBe(true)
      .then(() => true, () => false);
    const stubs = await page.locator('#hmRooms .hm-stub[data-room^="bedroom"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-room")));
    if (!ok || stubs.length) bad.push(`${s.title}: ${ok ? "" : "нет карточки «Спальня 1» с фото нейросети"}${stubs.length ? ` заглушки ${stubs.join(",")}` : ""}`);
  }
  await expect(card).toContainText("Спальня 1");
  await expect(card).toContainText("м²");
  await expect(page.locator('[data-br-role="кровать"]')).toHaveCount(0);   // фотокаталога на странице нет
  expect(bad, "стили без карточки спальни с фото").toEqual([]);
  expect(errors).toEqual([]);
});
