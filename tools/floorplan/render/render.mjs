#!/usr/bin/env node
// Рендер серого 3D стенда планировок (T-20261109-02): model-*.json → кадры сверху / под углом / изнутри (PNG).
//   node tools/floorplan/render/render.mjs --out <новая папка> --views top,oblique[,interior] model-A-0.json [...]
// three — из node_modules проекта, Chromium — из @playwright/test (swiftshader, как tools/flat3d/hall-snap.mjs).
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const OUT = arg("--out") ? resolve(arg("--out")) : null;
const VIEWS = arg("--views", "top,oblique").split(",");
const MODELS = args.filter((a, i) => a.endsWith(".json") && !["--out", "--views"].includes(args[i - 1]));
if (!OUT || !MODELS.length) {
  console.error("нужны --out <папка> и model-*.json");
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

const THREE_DIR = join(ROOT, "node_modules/three/build");
const HTML = `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#fff}</style>
<script type="module" src="/scene.js"></script>`;
const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
  let body = null;
  if (url === "/") body = HTML;
  else if (url === "/scene.js") body = readFileSync(join(HERE, "scene.js"));
  else if (url.startsWith("/three/") && existsSync(join(THREE_DIR, basename(url)))) body = readFileSync(join(THREE_DIR, basename(url)));
  if (body === null) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": url === "/" ? "text/html" : extname(url) === ".js" ? "text/javascript" : "application/octet-stream" }).end(body);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ ignoreDefaultArgs: ["--disable-dev-shm-usage"],
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const tab = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  tab.on("pageerror", (e) => console.error("page:", e.message));
  await tab.goto(base);
  await tab.waitForFunction(() => window.ready === true, null, { timeout: 60000 });
  for (const mp of MODELS) {
    const model = JSON.parse(readFileSync(mp, "utf8"));
    for (const v of VIEWS) {
      const t0 = Date.now();
      const url = await tab.evaluate(([m, view]) => window.renderView(m, view), [model, v]);
      const name = `3d-${model.plan}-${basename(mp).replace(/^model-[A-Z]-/, "").replace(".json", "")}-${v}.png`;
      writeFileSync(join(OUT, name), Buffer.from(url.split(",")[1], "base64"));
      console.log(name, `${Date.now() - t0} мс`);
    }
  }
} finally {
  await browser.close().catch(() => {});
  server.close();
}
