#!/usr/bin/env node
// СНИМКИ ПРИХОЖЕЙ С ЗЕРКАЛОМ (T-20261106-73, план hall-demo-01 этап 2): наборы банка прихожей (`compose_hall`, файл стенда —
// не живой банк) → живая сцена ТЕМ ЖЕ путём, что вариант витрины (`tools/flat3d/hall-snap/entry.ts`: `createDemoScene` → мост →
// сцена → просмотрщик) → кадры режима «Фото» 1440×900 и 375×667. Вариант /demo не выдумывается.
//
// Стратегия ассета роли — из канона `tools/scout/rules/asset-strategies.json` (как поле `strategy` предмета, которое пишет
// сборщик витрины). Мебели без модели стенд даёт метку модели `stand:<роль>`: файла нет, сеть закрыта, и движок рисует
// честную серую коробку — видно, над чем висит зеркало. Два вида на набор — подбор по правилу `tools/scout/rules/hall-views.json`
// (вид 1 — зеркало целиком и ближнее хранение, вид 2 — главное хранение целиком; `hall-snap/views.ts`): одни точки для 1440 и 375,
// «целиком» проверяется по кадру компьютера. Точки и отчёт подбора — в `cases.json` (по ним снимает и сервер, `test_wall_plane.py`).
// Выход — НОВАЯ папка (старые снимки не трогаем).
//   node tools/flat3d/hall-snap.mjs --bank <bank-hall.json> --out <новая папка> [--only сканди,лофт]
import { build as esbuild } from "esbuild";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BANK = arg("--bank") ? resolve(arg("--bank")) : null;
const OUT = arg("--out") ? resolve(arg("--out")) : null;
const ONLY = arg("--only") ? new Set(arg("--only").split(",")) : null;
if (!BANK || !OUT) {
  console.error("нужны --bank <bank-hall.json> и --out <новая папка>");
  process.exit(2);
}
if (existsSync(OUT)) {
  console.error(`папка уже есть: ${OUT} — снимки пишем только в новую`);
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

const canon = JSON.parse(readFileSync(join(ROOT, "tools/scout/rules/asset-strategies.json"), "utf8")).roles;
const strategyOf = (role) => canon[String(role).replace(/\s+\d+$/, "").trim()] ?? canon._default ?? "hunyuan3d";

/** Набор банка → комната и предметы в форме варианта витрины (x, y — центр следа; `z` банка — это `y` плана). */
function hallCase(set) {
  const r = set.layout._room;
  const room = { w: r.w, d: r.d, title: "Прихожая", height_cm: 270, openings: r.openings };
  const items = Object.entries(set.layout).filter(([k]) => !k.startsWith("_")).map(([role, p]) => {
    const it = set.items?.[role] ?? {};
    const strategy = strategyOf(role);
    return { role, x: p.x, y: p.z, rot: p.rot, w: p.w, d: p.d, h: p.h, elev: p.elev ?? 0, strategy,
      sku: { name: it.name ?? role, price: it.price, sid: it.sid ?? p.sid, img: it.img,
        ...(strategy === "hunyuan3d" ? { msid: `stand:${role}` } : {}) } };
  });
  return { room, items };
}

const html = readFileSync(join(ROOT, "tools/scout/flat215-demo/index.html"), "utf8");
const CAMFIT = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const RULE = JSON.parse(readFileSync(join(ROOT, "tools/scout/rules/hall-views.json"), "utf8"));
const ASPECT = 1440 / 900;

const page = await esbuild({
  entryPoints: [join(ROOT, "tools/flat3d/hall-snap/entry.ts")],
  bundle: true, format: "esm", target: "es2020", write: false, alias: { "@": ROOT }, logLevel: "warning", absWorkingDir: ROOT,
  define: { __ENGINE_BUILD__: JSON.stringify("hall-snap"), "process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE": "undefined",
    "process.env.NEXT_PUBLIC_FLAT3D_RT_BASE": "undefined" },
});
const ENTRY = page.outputFiles[0].text;
const HTML = `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#fff}</style>
<canvas id="view"></canvas><script type="module" src="/entry.js"></script>`;
const TYPES = { ".js": "text/javascript", ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".wasm": "application/wasm" };
// карты пола, стен и вид за окном — из `public/` (в worktree их может не быть — тогда из основной копии)
const PUBLIC = [join(ROOT, "public"), resolve(ROOT, "../../../public")];
const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
  let body = null;
  if (url === "/") body = HTML;
  else if (url === "/entry.js") body = ENTRY;
  else for (const dir of PUBLIC) if (!body && existsSync(join(dir, url)) && !url.endsWith("/")) body = readFileSync(join(dir, url));
  if (body === null) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": url === "/" ? "text/html" : TYPES[extname(url)] ?? "application/octet-stream" }).end(body);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

const bank = JSON.parse(readFileSync(BANK, "utf8"));
const sets = (Array.isArray(bank) ? bank : bank.sets).filter((s) => !ONLY || ONLY.has(s.style));
const report = [];
let fails = 0;
let retries = 0;
const SET_MS = 240_000;

/** Один набор — в СВОЁМ браузере. Чёрный кадр 1440 (прогоны 10:23, 11:44, 14:39, 15:13) — браузеру не хватило общей памяти
 *  (`CommandBufferHelper::AllocateRingBuffer() failed`, `ERR_INSUFFICIENT_RESOURCES`): Playwright по умолчанию запускает его с
 *  `--disable-dev-shm-usage`, и общая память идёт в /tmp, а на DEV /tmp — tmpfs 788 МБ с квотой, забитый чужими файлами (урок 495).
 *  Поэтому флаг снят — общая память в /dev/shm; после сбоя WebGL в этом браузере не встаёт, отсюда свежий браузер на попытку и
 *  предел времени. Ответ страницы несёт `lost` (контекст WebGL отобран) и `dark` (кадр чёрный целиком) — сбой виден в отчёте,
 *  а не сохраняется молча как снимок. */
async function shoot(c, vp) {
  const browser = await chromium.launch({ ignoreDefaultArgs: ["--disable-dev-shm-usage"],
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const errs = [];
  let timer;
  try {
    const tab = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    tab.on("pageerror", (e) => errs.push(`ошибка страницы: ${e.message}`));
    tab.on("crash", () => errs.push("вкладка упала"));
    // ошибки консоли — в журнал; 404 пропускаем: у мебели стенда модели нет нарочно (`stand:<роль>`)
    tab.on("console", (m) => { if (m.type() === "error" && !/status of 404/.test(m.text())) console.error(`  [браузер] ${m.text()}`); });
    // сеть наружу закрыта: картинки товаров и модели не качаются, кадр воспроизводим
    await tab.route("**/*", (r) => (r.request().url().startsWith(base) ? r.continue() : r.abort()));
    await tab.goto(base);
    await tab.waitForFunction(() => typeof window.hallSnap === "function");
    const run = tab.evaluate((x) => window.hallSnap(x), { ...c, pick: { camfit: CAMFIT, rule: RULE, aspect: ASPECT },
      width: vp.width, height: vp.height, lite: vp.lite });
    const late = new Promise((_, no) => { timer = setTimeout(() => no(new Error(`нет ответа за ${SET_MS / 1000} с`)), SET_MS); });
    const got = await Promise.race([run, late]);
    const why = [...errs, ...(got.lost ? ["контекст WebGL потерян"] : []),
      ...got.dark.flatMap((d, i) => (d ? [`вид ${i + 1} — чёрный кадр`] : []))];
    return { got, why };
  } catch (e) {
    return { got: null, why: [...errs, `страница: ${String(e.message ?? e).split("\n")[0]}`] };
  } finally {
    clearTimeout(timer);
    await browser.close().catch(() => {});
  }
}

for (const vp of [{ width: 1440, height: 900, lite: false }, { width: 375, height: 667, lite: true }]) {
  for (const s of sets) {
    const c = hallCase(s);
    const m = c.items.find((it) => it.role.startsWith("зеркало"));
    if (!m) { console.log(`${s.style}: зеркала в наборе нет — пропуск`); continue; }
    let { got, why } = await shoot(c, vp);
    if (why.length) {
      // один повтор в новой вкладке: сбой браузера, а не набора, — второй раз обычно проходит; оба раза — в отчёт
      console.error(`${s.style} ${vp.width}: повтор — ${why.join("; ")}`);
      retries += 1;
      ({ got, why } = await shoot(c, vp));
    }
    if (why.length || !got) {
      fails += 1;
      console.error(`${s.style} ${vp.width}: НЕ СНЯТ — ${why.join("; ")}`);
      report.push({ style: s.style, viewport: `${vp.width}x${vp.height}`, error: why });
      continue;
    }
    const bad = got.views.filter((v) => !v.ok);
    if (bad.length) { fails += bad.length; bad.forEach((v) => console.error(`${s.style}: вид ${v.id} не годен — ${v.why.join("; ")}`)); }
    got.frames.forEach((url, i) => {
      const file = join(OUT, `${s.style}.v${i + 1}.${vp.width}.jpg`);
      writeFileSync(file, Buffer.from(url.split(",")[1], "base64"));
    });
    report.push({ style: s.style, viewport: `${vp.width}x${vp.height}`, poses: got.views.map((v) => v.pose), views: got.views,
      mirror: { x: m.x, y: m.y, rot: m.rot, w: m.w, h: m.h, elev: m.elev }, clay: got.clay });
    console.log(`${s.style} ${vp.width}: ${got.views.map((v) => `${v.id} ${JSON.stringify(v.pose)} ${v.ok ? "годен" : "НЕ ГОДЕН"}`).join(" · ")} · коробки: ${got.clay.join(", ") || "нет"}`);
  }
}
server.close();
writeFileSync(join(OUT, "cases.json"), JSON.stringify(report, null, 1) + "\n");
console.log(`→ ${OUT} · повторов: ${retries}${fails ? ` · ошибок: ${fails}` : ""}`);
process.exit(fails ? 1 : 0);
