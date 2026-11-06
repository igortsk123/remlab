#!/usr/bin/env node
// СНИМКИ ПРИХОЖЕЙ С ЗЕРКАЛОМ (T-20261106-73, план hall-demo-01 этап 2): наборы банка прихожей (`compose_hall`, файл стенда —
// не живой банк) → живая сцена ТЕМ ЖЕ путём, что вариант витрины (`tools/flat3d/hall-snap/entry.ts`: `createDemoScene` → мост →
// сцена → просмотрщик) → кадры режима «Фото» 1440×900 и 375×667. Вариант /demo не выдумывается.
//
// Стратегия ассета роли — из канона `tools/scout/rules/asset-strategies.json` (как поле `strategy` предмета, которое пишет
// сборщик витрины). Мебели без модели стенд даёт метку модели `stand:<роль>`: файла нет, сеть закрыта, и движок рисует
// честную серую коробку — видно, над чем висит зеркало. Два вида на набор: в 1,7 м перед зеркалом и в 3,2 м (дальний).
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

/** Взгляд на зеркало с расстояния `dist` по нормали (и на 40 см вдоль стены — к середине комнаты), внутри комнаты. */
function facePose(room, m, dist) {
  const a = (m.rot * Math.PI) / 180;
  const [nx, ny] = [Math.sin(a), Math.cos(a)];
  const [ux, uy] = [Math.cos(a), -Math.sin(a)];
  const side = (m.x + ux * 40 - room.w / 2) ** 2 + (m.y + uy * 40 - room.d / 2) ** 2
    < (m.x - ux * 40 - room.w / 2) ** 2 + (m.y - uy * 40 - room.d / 2) ** 2 ? 40 : -40;
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const x = clamp(m.x + nx * dist + ux * side, 25, room.w - 25);
  const y = clamp(m.y + ny * dist + uy * side, 25, room.d - 25);
  // поворот фото-позы: rot 0 смотрит на −y, 90 — на +x (`draft_render.cams_from_request`)
  const rot = ((Math.atan2(m.x - x, -(m.y - y)) * 180) / Math.PI + 360) % 360;
  return { x: Math.round(x), y: Math.round(y), rot: Math.round(rot), fov: 70, pose: 2 };
}

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
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const report = [];
let fails = 0;
for (const vp of [{ width: 1440, height: 900, lite: false }, { width: 375, height: 667, lite: true }]) {
  const tab = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  tab.on("pageerror", (e) => { fails += 1; console.error(`ошибка страницы: ${e.message}`); });
  // сеть наружу закрыта: картинки товаров и модели не качаются, кадр воспроизводим
  await tab.route("**/*", (r) => (r.request().url().startsWith(base) ? r.continue() : r.abort()));
  for (const s of sets) {
    const c = hallCase(s);
    const m = c.items.find((it) => it.role.startsWith("зеркало"));
    if (!m) { console.log(`${s.style}: зеркала в наборе нет — пропуск`); continue; }
    const poses = [facePose(c.room, m, 170), facePose(c.room, m, 320)];
    await tab.goto(base);
    await tab.waitForFunction(() => typeof window.hallSnap === "function");
    const got = await tab.evaluate((x) => window.hallSnap(x), { ...c, poses, width: vp.width, height: vp.height, lite: vp.lite });
    got.frames.forEach((url, i) => {
      const file = join(OUT, `${s.style}.v${i + 1}.${vp.width}.jpg`);
      writeFileSync(file, Buffer.from(url.split(",")[1], "base64"));
    });
    report.push({ style: s.style, viewport: `${vp.width}x${vp.height}`, poses, mirror: { x: m.x, y: m.y, rot: m.rot, w: m.w, h: m.h, elev: m.elev },
      clay: got.clay });
    console.log(`${s.style} ${vp.width}: ${got.frames.length} кадра · коробки: ${got.clay.join(", ") || "нет"}`);
  }
  await tab.close();
}
await browser.close();
server.close();
writeFileSync(join(OUT, "cases.json"), JSON.stringify(report, null, 1) + "\n");
console.log(`→ ${OUT}${fails ? ` · ошибок страницы: ${fails}` : ""}`);
process.exit(fails ? 1 : 0);
