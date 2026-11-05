#!/usr/bin/env node
// СНИМКИ НАБОРА КУХНИ (план onb-09 часть А): кадры `buildKitchen` без страницы /flat — для сравнения «до/после» и с фото
// примеров кухонь. Стенд — `tools/flat3d/kitchen-snap/entry.ts` (сборка esbuild), рисует Chromium программным рендером.
// Наборы кадров:
//   legacy   — кухня demo-uk-1 из каталога (`data/flat3d/catalogue-base.json`): 4 уровня корпуса × 4 уровня техники, место 340×60,
//              комната глубиной 180, колонны у дальнего от двери конца — как склеивает `lib/viewer3d/build-scene.ts`;
//   examples — паспорта `data/partners/kitchen-examples/{ru,uk}.json` через `kitchenSpecFromExample` рядом с фото источника.
// Каждый кадр — PNG 1440×900 и 375×667. Выход — НОВАЯ папка (старые снимки не трогаем).
//   node tools/flat3d/kitchen-snap.mjs --set legacy --out <папка> [--kit <путь к kitchen.ts>]
//   node tools/flat3d/kitchen-snap.mjs --set examples --out <папка> --photos <папка с фото _intake/kitchens-2026-11>
import { build as esbuild } from "esbuild";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const SET = arg("--set", "legacy");
const OUT = resolve(arg("--out", join(ROOT, ".claude/tmp-ui/kitchen-snap")));
const PHOTOS = arg("--photos") ? resolve(arg("--photos")) : null;
const KIT = arg("--kit") ? resolve(arg("--kit")) : null; // подмена набора: снимок «до» со старого исходника
if (existsSync(OUT)) {
  console.error(`папка уже есть: ${OUT} — снимки пишем только в новую`);
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

// подмена `@/lib/viewer3d/kits/kitchen` на другой файл (старый исходник из git) — только для кадров «до»
const swapKit = KIT
  ? [{ name: "swap-kit", setup(b) { b.onResolve({ filter: /^@\/lib\/viewer3d\/kits\/kitchen$/ }, () => ({ path: KIT })); } }]
  : [];
const page = await esbuild({
  entryPoints: [join(ROOT, "tools/flat3d/kitchen-snap/entry.ts")],
  bundle: true, format: "esm", target: "es2020", write: false, alias: { "@": ROOT }, logLevel: "warning",
  absWorkingDir: ROOT, plugins: swapKit,
});
const ENTRY = page.outputFiles[0].text;
const HTML = `<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;height:100%;font:14px system-ui;background:#fff}
body{display:flex;flex-direction:column}#row{flex:1;display:flex;min-height:0}
#view{flex:1;min-width:0}#photo{display:none}
body.pair #photo{display:block;flex:1;min-width:0;object-fit:contain;background:#f4f4f4}
@media (max-width:700px){#row{flex-direction:column}}
#cap{padding:6px 10px;color:#333}</style>
<div id="row"><img id="photo" alt=""><div id="view"></div></div><div id="cap"></div>
<script type="module" src="/entry.js"></script>`;

// материалы — как `lib/configurator/data.ts`: файл каталога покрытий с базовым адресом + сплошные цвета каталога
const matsJson = JSON.parse(readFileSync(join(ROOT, "data/flat3d/materials.json"), "utf8"));
const catJson = JSON.parse(readFileSync(join(ROOT, "data/flat3d/catalogue-base.json"), "utf8"));
const withBase = (u) => (!u ? undefined : /^https?:|^\//.test(u) ? u : matsJson.baseUrl + u);
const MATERIALS = [
  ...catJson.materials.map((m) => ({ ...m, baseColorUrl: withBase(m.baseColorUrl) })),
  ...matsJson.materials.map((m) => ({ ...m, baseColorUrl: withBase(m.baseColorUrl), normalUrl: withBase(m.normalUrl),
    roughnessUrl: withBase(m.roughnessUrl), aoUrl: withBase(m.aoUrl) })),
].map((m) => ({ roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [], ...m }));

async function legacyCases() {
  const opt = new Map(catJson.options.map((o) => [o.id, o]));
  const cases = [];
  for (const k of ["kitchen-base", "kitchen-practical", "kitchen-comfort", "kitchen-premium"]) {
    for (const a of ["appliances-base", "appliances-practical", "appliances-comfort", "appliances-premium"]) {
      const ka = opt.get(k).asset;
      const aa = opt.get(a).asset;
      cases.push({
        name: `${k}__${a}`,
        caption: `${k} + ${a}`,
        spec: {
          level: ka.level, features: [...new Set([...ka.features, ...aa.features])], doorMaterialId: ka.materials.door,
          worktopMaterialId: "stone-grey", splashbackMaterialId: "tile-metro", widthCm: 340, depthCm: 60, roomDepthCm: 180, columnsAt: "end",
        },
      });
    }
  }
  return cases;
}

async function exampleCases() {
  // перевод паспорта — тот же код, что в продукте: собираем его для node и зовём
  const res = await esbuild({
    stdin: {
      contents: `import { kitchenSpecFromExample } from "@/lib/viewer3d/kits/kitchen-from-example";
import { kitchenExamplesFile } from "@/contracts/kitchen-example";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
export const out = [ru, uk].flatMap((f) => kitchenExamplesFile.parse(f).examples).map((e) => ({ e, spec: kitchenSpecFromExample(e) }));`,
      resolveDir: ROOT, loader: "ts",
    },
    bundle: true, format: "esm", platform: "node", write: false, alias: { "@": ROOT }, logLevel: "warning", absWorkingDir: ROOT,
    external: ["three"],
  });
  const tmp = join(OUT, "_cases.mjs");
  writeFileSync(tmp, res.outputFiles[0].text);
  const { out } = await import(pathToFileURL(tmp).href);
  return out.map(({ e, spec }) => {
    const file = e.colorFrom.split(" ")[0].split("/").slice(-2).join("/"); // «sima-1322/evropa-1.jpg»
    return {
      name: e.id, spec, photo: PHOTOS ? `/photos/${file}` : undefined,
      caption: `${e.id} · ${e.lengthCm} см · ${spec.shape ?? "straight"} · фасад ${spec.doorMaterialId}${spec.doorUpperMaterialId ? ` / верх ${spec.doorUpperMaterialId}` : ""} · столешница ${spec.worktopMaterialId}`,
    };
  });
}

const TYPES = { ".js": "text/javascript", ".webp": "image/webp", ".jpg": "image/jpeg", ".png": "image/png", ".html": "text/html" };
const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
  let body = null;
  if (url === "/") body = HTML;
  else if (url === "/entry.js") body = ENTRY;
  else {
    const file = url.startsWith("/photos/") && PHOTOS ? join(PHOTOS, url.slice(8)) : join(ROOT, "public", url);
    if (existsSync(file)) body = readFileSync(file);
  }
  if (body === null) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": url === "/" ? "text/html" : TYPES[extname(url)] ?? "application/octet-stream" }).end(body);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

const cases = SET === "examples" ? await exampleCases() : await legacyCases();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
let fails = 0;
for (const vp of [{ width: 1440, height: 900 }, { width: 375, height: 667 }]) {
  const tab = await browser.newPage({ viewport: vp });
  tab.on("pageerror", (e) => { fails += 1; console.error(`ошибка страницы: ${e.message}`); });
  for (const c of cases) {
    await tab.goto(base);
    await tab.waitForFunction(() => typeof window.snap === "function");
    await tab.evaluate((x) => window.snap(x), { ...c, materials: MATERIALS });
    await tab.waitForSelector("body[data-ready]");
    await tab.screenshot({ path: join(OUT, `${c.name}.${vp.width}.png`) });
  }
  await tab.close();
}
await browser.close();
server.close();
writeFileSync(join(OUT, "cases.json"), JSON.stringify(cases.map(({ name, caption, spec }) => ({ name, caption, spec })), null, 1) + "\n");
console.log(`${cases.length} кадров × 2 размера → ${OUT}${fails ? ` · ошибок страницы: ${fails}` : ""}`);
process.exit(fails ? 1 : 0);
