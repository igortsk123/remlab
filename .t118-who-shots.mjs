// T-118 цикл 2: снимки экрана «Кто проверяет?» (375 и 1280). Запуск: node .t118-who-shots.mjs <база> <папка> <секрет>
import { chromium } from "@playwright/test";
import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const [BASE, OUT, SECRET] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });
const cookie = { name: "mesh_review", value: createHmac("sha256", SECRET).update("mesh-review-ok").digest("hex"), url: BASE };
const b = await chromium.launch();
for (const [w, h] of [
  [375, 667],
  [1280, 800],
]) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: w < 500 ? 2 : 1 });
  await ctx.addCookies([cookie]);
  await ctx.addInitScript(() => localStorage.setItem("remlab-cookies", "ok"));
  const pg = await ctx.newPage();
  const errs = [];
  pg.on("pageerror", (e) => errs.push(String(e)));
  await pg.goto(`${BASE}/lab/mesh-check`, { waitUntil: "networkidle", timeout: 180000 });
  const field = pg.getByRole("textbox", { name: "Имя" });
  await field.waitFor({ timeout: 30000 });
  const box = await field.boundingBox();
  const over = await pg.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  await pg.screenshot({ path: join(OUT, `${w}-who.png`) });
  console.log("SHOT", `${w}-who`, "field_left", Math.round(box.x), "field_right", Math.round(w - box.x - box.width), "field_w", Math.round(box.width), "overflow_x", over, "errors", errs.length);
  await ctx.close();
}
await b.close();
