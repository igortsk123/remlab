// ПЕРВАЯ КАРТОЧКА ГЛАВНОЙ ПО ВРЕМЕНИ (T-20261112-29): что показывает карточка комнаты «Интерьер» в 0 / 0,5 / 1 / 2 / 4 / 8 с от
// начала загрузки — фото (файл или снимок браузера), схема плана, заглушка; снимки телефона 375×667 на каждой отметке; `--warm` —
// второй заход с тёплым кэшем. Проверка «стало» до выкладки — подменой на лету:
//   --html файл.html   страница вместо ответа сервера (для тура в неё вставляется «песочница» тура из живого ответа + карта снимков)
//   --bundle файл.json данные вместо `demo-data.json`
//   --cards out.json   кадры `tools/scout/trial_cards.mjs`: карта «ключ → cards/<sha16>.jpg» в страницу, файлы отдаются отсюда
//   node tools/ops/card-timeline.mjs <OUT> <url> [метка] [--warm] [--html f] [--bundle f] [--cards f]   (тур — с `?live=force`)
import { chromium } from "@playwright/test";
import crypto from "node:crypto";
import fs from "node:fs";

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : ""; };
const [OUT, URL0, TAG = "card"] = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && ["--html", "--bundle", "--cards"].includes(args[i - 1])));
const WARM = args.includes("--warm"), HTML = opt("--html"), BUNDLE = opt("--bundle"), CARDS = opt("--cards");
fs.mkdirSync(OUT, { recursive: true });
const MARKS = [0, 500, 1000, 2000, 4000, 8000];

const cardFiles = new Map(), cardMap = {};
if (CARDS) for (const c of JSON.parse(fs.readFileSync(CARDS, "utf8")).cards || []) {
  if (!c.jpg) continue;
  const buf = Buffer.from(c.jpg, "base64"), f = crypto.createHash("sha256").update(buf).digest("hex").slice(0, 16) + ".jpg";
  cardFiles.set(f, buf); cardMap[c.key] = "cards/" + f;
}

const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const ctx = await b.newContext({ viewport: { width: 375, height: 667 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "ru-RU" });
await ctx.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
if (BUNDLE) await ctx.route((u) => u.pathname.endsWith("/demo-data.json"), (r) => r.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(BUNDLE) }));
if (CARDS) await ctx.route(/\/cards\/[a-f0-9]{16}\.jpg/, (r) => {
  const f = new URL(r.request().url()).pathname.split("/").pop(), buf = cardFiles.get(f);
  return buf ? r.fulfill({ status: 200, contentType: "image/jpeg", body: buf }) : r.fulfill({ status: 404, body: "" });
});
if (HTML) await ctx.route((u) => u.href.split("?")[0] === URL0.split("?")[0] || u.href.split("?")[0] === URL0.split("?")[0] + "/", async (r) => {
  if (r.request().resourceType() !== "document") return r.continue();
  let html = fs.readFileSync(HTML, "utf8");
  const live = await r.fetch();
  const txt = await live.text();
  // песочница тура — первый скрипт живого ответа сразу после <head> (`lib/trial/tour-page.ts:injectTour`); у /demo её нет
  const m = /^[\s\S]*?<head[^>]*>(<script>\(function\(\)\{\nwindow\.__TOUR_VER[\s\S]*?<\/script>)/i.exec(txt);
  let boot = m ? m[1] : "";
  if (boot) boot = boot.replace(/window\.__TOUR_CARDS=[^;]*;/, "").replace("window.__TOUR_VER", `window.__TOUR_CARDS=${JSON.stringify(cardMap)};\nwindow.__TOUR_VER`);
  const at = html.search(/<head[^>]*>/i), hl = html.match(/<head[^>]*>/i)[0].length;
  html = html.slice(0, at + hl) + boot + html.slice(at + hl);
  return r.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: html });
});

const state = (p) => p.evaluate(() => {
  const a = document.querySelector("#hmRooms article.hm-room.on") || document.querySelector("#hmRooms article.hm-room");
  if (!a) return { kind: "none" };
  const ph = a.querySelector(".hm-ph"), img = ph && ph.querySelector("img");
  const src = img ? (img.currentSrc || img.src) : "";
  const kind = img ? (src.startsWith("blob:") ? "img-blob(снимок браузера)" : /\/cards\//.test(src) ? "img-card(готовый файл)" : "img-file") :
    ph && ph.querySelector(".tr-plan") ? "plan" : ph && ph.querySelector(".hm-ld") ? "skeleton" : ph && ph.querySelector(".nopv") ? "nopv" : "other";
  return { kind, room: a.dataset.room, src: src.slice(0, 120), loaded: img ? img.complete && img.naturalWidth > 0 : null };
});
async function pass(name) {
  const p = await ctx.newPage();
  const log = [], reqs = [], t0 = Date.now();
  p.on("request", (r) => { const u = r.url(); if (/\.(jpe?g|webp|png|glb)(\?|$)|demo-data\.json/.test(u)) reqs.push([Date.now() - t0, r.resourceType(), u.slice(0, 140)]); });
  await p.goto(URL0, { waitUntil: "commit", timeout: 120000 });
  let last = "", mi = 0, firstImg = null, planSeen = false;
  while (Date.now() - t0 < 9000) {
    const dt = Date.now() - t0;
    let s; try { s = await state(p); } catch (e) { s = { kind: "nav" }; }
    const k = JSON.stringify(s);
    if (k !== last) { log.push([dt, s]); last = k; }
    if (s.kind === "plan") planSeen = true;
    if (firstImg == null && /^img/.test(s.kind) && s.loaded) firstImg = dt;
    if (mi < MARKS.length && dt >= MARKS[mi]) { await p.screenshot({ path: `${OUT}/${TAG}-${name}-${String(MARKS[mi]).padStart(4, "0")}.png` }).catch(() => {}); mi++; }
    await p.waitForTimeout(80);
  }
  console.log(`\n== ${TAG} ${name}: картинка на карточке с ${firstImg == null ? "— (нет за 9 с)" : firstImg + " мс"}; схема показывалась: ${planSeen ? "да" : "нет"}`);
  for (const [t, s] of log) console.log(String(t).padStart(5), JSON.stringify(s));
  console.log("запросы (первые 12):"); for (const r of reqs.slice(0, 12)) console.log(" ", r.join(" "));
  await p.close();
}
await pass("cold");
if (WARM) await pass("warm");
await b.close();
