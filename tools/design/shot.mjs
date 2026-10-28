// Самопроверка выгрузки: снимок страницы (файл или URL) в PNG.  node tools/design/shot.mjs <файл|URL> <out.png> [W] [H] [full=1]
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
const [src, out, W = "1440", H = "900", full = "1"] = process.argv.slice(2);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: +W, height: +H } });
const errs = []; p.on("pageerror", (e) => errs.push(String(e))); p.on("requestfailed", (r) => errs.push("FAIL " + r.url().slice(0, 120)));
await p.goto(/^https?:/.test(src) ? src : pathToFileURL(src).href, { waitUntil: "networkidle", timeout: 90000 });
await p.waitForTimeout(800);
if (/^seg/.test(full)) { const H2 = +(full.slice(3) || 2400); const th = await p.evaluate(() => document.documentElement.scrollHeight);
  await p.setViewportSize({ width: +W, height: H2 });
  for (let y = 0, i = 0; y < th && i < 40; y += H2, i++) { await p.evaluate((y) => scrollTo(0, y), y); await p.waitForTimeout(300); await p.screenshot({ path: out.replace(/\.png$/, `-${String(i).padStart(2, "0")}.png`) }); }
} else await p.screenshot({ path: out, fullPage: full === "1" });
console.log(JSON.stringify({ h: await p.evaluate(() => document.documentElement.scrollHeight), errs: errs.slice(0, 10) }));
await b.close();
