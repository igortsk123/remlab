// T-118: снимки НАСТОЯЩЕЙ страницы /lab/mesh-check (dev-сервер своей копии на временной БД t118-pg, без 3D) + живая проверка
// «закрыл вкладку посреди ввода — текст на сервере». Запуск: node .t118-page-shots.mjs <база http://127.0.0.1:PORT> <папка> <секрет>
import { chromium } from "@playwright/test";
import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const [BASE, OUT, SECRET] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });
const cookie = { name: "mesh_review", value: createHmac("sha256", SECRET).update("mesh-review-ok").digest("hex"), url: BASE };
const b = await chromium.launch();

async function open(w, h, qs, who = "Аня") {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: w < 500 ? 2 : 1 });
  await ctx.addCookies([cookie]);
  if (who) await ctx.addInitScript((n) => localStorage.setItem("mesh-check-reviewer", n), who);
  await ctx.addInitScript(() => localStorage.setItem("remlab-cookies", "ok")); // плашку cookie живой человек закрывает один раз
  const pg = await ctx.newPage();
  const errs = [];
  pg.on("pageerror", (e) => errs.push(String(e)));
  await go(pg, `${BASE}/lab/mesh-check${qs}`, !!who);
  return { ctx, pg, errs };
}

// переход + ожидание: страница проснулась (заголовок) и первые 4 картинки догрузились (раньше снимок ловил пустые рамки)
async function go(pg, url, board = true) {
  await pg.goto(url, { waitUntil: "networkidle", timeout: 180000 });
  if (!board) return;
  await pg.getByRole("heading", { name: "Проверка мешей" }).waitFor({ timeout: 30000 }).catch(() => console.log("WARN нет заголовка", url));
  const ok = await pg
    .waitForFunction(() => [...document.images].filter((i) => i.offsetParent).slice(0, 4).every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 60000 })
    .then(() => true)
    .catch(() => false);
  if (!ok) console.log("WARN картинки не догрузились", url);
}

async function shot(pg, errs, name, full = false) {
  const over = await pg.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  await pg.screenshot({ path: join(OUT, `${name}.png`), fullPage: full });
  console.log("SHOT", name, "overflow_x", over, "errors", errs.length, errs.slice(0, 2).join(" | "));
}

// вход: «кто проверяет»
{
  const { ctx, pg, errs } = await open(375, 667, "", "");
  await shot(pg, errs, "375-who");
  await ctx.close();
}
// телефон: диваны сверху, нажатия, комментарий, полная страница
{
  const { ctx, pg, errs } = await open(375, 667, "?s=divan");
  await shot(pg, errs, "375-divan-top");
  const cards = pg.locator("section[data-sku]");
  // повторное нажатие снимает отметку: жмём, только если ещё не нажато (иначе повторный прогон снимок «нажато» стирает)
  const press = async (card, name) => {
    const btn = card.getByRole("button", { name });
    if ((await btn.getAttribute("aria-pressed")) !== "true") await btn.click();
  };
  await press(cards.nth(0), /Ок/);
  await pg.waitForTimeout(800);
  await cards.nth(1).getByRole("textbox").fill("ножки пропали, цвет темнее фото");
  await pg.waitForTimeout(1500);
  await press(cards.nth(1), /Брак/);
  await pg.waitForTimeout(1200);
  await cards.nth(0).scrollIntoViewIfNeeded();
  await shot(pg, errs, "375-divan-pressed");
  await shot(pg, errs, "375-divan-full", true);
  await cards.nth(1).locator("button").nth(0).click(); // фото → увеличение
  await pg.waitForTimeout(800);
  await shot(pg, errs, "375-zoom-photo");
  await pg.getByRole("dialog").getByRole("button", { name: "модель", exact: true }).click();
  await pg.waitForTimeout(500);
  await shot(pg, errs, "375-zoom-model");
  await ctx.close();
}
// закрыл вкладку посреди ввода (до истечения 1 с) — текст должен оказаться на сервере
{
  const { ctx, pg } = await open(375, 667, "?s=kreslo");
  const note = "закрыл вкладку сразу " + Date.now();
  await pg.locator("section[data-sku]").nth(0).getByRole("textbox").fill(note);
  await pg.close({ runBeforeUnload: true });
  await new Promise((r) => setTimeout(r, 1500));
  const pg2 = await ctx.newPage();
  // черновик браузера не в счёт: проверяем именно сервер (имя проверяющего оставляем, иначе откроется вход)
  await ctx.addInitScript(() => Object.keys(localStorage).filter((k) => k.startsWith("mesh-check-note:")).forEach((k) => localStorage.removeItem(k)));
  // маяк под нагрузкой доходит за 4+ с (прогон 00:41: запись в БД есть, а перезагрузка через 1,5 с её опередила) — ждём до 20 с
  let got = "";
  for (let t = 0; t < 5 && got !== note; t++) {
    await go(pg2, `${BASE}/lab/mesh-check?s=kreslo`);
    got = await pg2.locator("section[data-sku]").nth(0).getByRole("textbox").inputValue();
    if (got !== note) await new Promise((r) => setTimeout(r, 4000));
  }
  console.log("BEACON", got === note ? "ok" : `ПОТЕРЯ: «${got}»`);
  await ctx.close();
}
// компьютер
{
  const { ctx, pg, errs } = await open(1280, 800, "?s=divan");
  await shot(pg, errs, "1280-divan");
  await pg.locator("section[data-sku]").nth(1).locator("button").nth(1).click(); // модель → увеличение
  await pg.waitForTimeout(800);
  await shot(pg, errs, "1280-zoom");
  await pg.keyboard.press("Escape");
  await go(pg, `${BASE}/lab/mesh-check?s=divan&f=bad`);
  await shot(pg, errs, "1280-filter-bad");
  await go(pg, `${BASE}/lab/mesh-check?s=kashpo`);
  await shot(pg, errs, "1280-kashpo", true);
  await ctx.close();
}
await b.close();
