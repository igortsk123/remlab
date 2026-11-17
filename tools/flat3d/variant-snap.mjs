#!/usr/bin/env node
// СНИМКИ ВАРИАНТА ВИТРИНЫ ЖИВОЙ СЦЕНОЙ + ЗАМЕР (T-20261117-07, растения кашпо и ваз): вариант из `demo-data.json` → `createDemoScene`
// (`variant-snap/entry.ts`) → кадры экранной камеры в позах ракурсов варианта и обрезки вокруг кашпо/вазы. Модели и картинки —
// с прода через прокси с кэшем на диске (сеть одна и та же в обоих режимах — замер сравним); `/flat3d/plants/*` и карты пола/стен —
// из `public/` worktree. Режимы: `--plants 0|1|both` (по умолчанию both: кадры «без» и «с» растениями, замер байт и времени).
//   node tools/flat3d/variant-snap.mjs --data ~/scout-scenes/flat215-demo/demo-data.json --variants set1,set4 --out <НОВАЯ папка>
//        [--plants both] [--sizes 1440x900,375x667] [--focus кашпо,ваза] [--gaps подушка,pillow] [--cache <папка кэша>]
//   node tools/flat3d/variant-snap.mjs --sheet calathea,fern,... --out <НОВАЯ папка>      лист-превью растений из `public/flat3d/plants/`
import { build as esbuild } from "esbuild";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { chromium } from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const PROD = "https://remont-lab.online";
const home = (p) => resolve(p.replace(/^~/, homedir()));
const OUT = arg("--out") ? home(arg("--out")) : null;
const SHEET = (arg("--sheet") ?? "").split(",").filter(Boolean);
let VARIANTS = (arg("--variants") ?? "").split(",").filter(Boolean);   // «all» — все варианты файла данных
const MODES = arg("--plants", "both") === "both" ? [0, 1] : [Number(arg("--plants"))];
const SIZES = arg("--sizes", "1440x900,375x667").split(",").map((s) => s.split("x").map(Number));
const FOCUS = arg("--focus", "кашпо,ваза").split(",").filter(Boolean);
const GAPS = (arg("--gaps") ?? "").split(",").filter(Boolean);   // роли/формы, у которых мерить зазор до опоры (`supportGaps`): подушка,pillow,throw,лампа…
const CACHE = home(arg("--cache") ?? join(homedir(), "remlab-logs", "snap-cache"));
if (!OUT || (!SHEET.length && (!arg("--data") || !VARIANTS.length))) {
  console.error("нужны --out <новая папка> и либо --sheet id,id, либо --data <demo-data.json> --variants a,b");
  process.exit(2);
}
if (existsSync(OUT)) { console.error(`папка уже есть: ${OUT} — снимки пишем только в новую`); process.exit(2); }
mkdirSync(OUT, { recursive: true });
mkdirSync(CACHE, { recursive: true });

const page = await esbuild({
  entryPoints: [join(ROOT, "tools/flat3d/variant-snap/entry.ts")], bundle: true, format: "esm", target: "es2020", write: false,
  alias: { "@": ROOT }, logLevel: "warning", absWorkingDir: ROOT,
  define: { __ENGINE_BUILD__: JSON.stringify("variant-snap"), "process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE": "undefined", "process.env.NEXT_PUBLIC_FLAT3D_RT_BASE": "undefined" },
});
const ENTRY = page.outputFiles[0].text;
const HTML = `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#fff}</style><canvas id="view"></canvas><script type="module" src="/entry.js"></script>`;
const TYPES = { ".js": "text/javascript", ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".glb": "model/gltf-binary", ".wasm": "application/wasm", ".json": "application/json" };
const PUBLIC = [join(ROOT, "public"), resolve(ROOT, "../../../public")];
const LOCAL = /^\/(flat3d)\//;   // свои файлы worktree (растения, карты, панорама); остальное — с прода

const server = createServer(async (req, res) => {
  const url = decodeURIComponent(req.url ?? "/");
  const path = url.split("?")[0];
  if (path === "/" || path === "/demo/") { res.writeHead(200, { "content-type": "text/html" }).end(HTML); return; }
  if (path === "/entry.js") { res.writeHead(200, { "content-type": "text/javascript" }).end(ENTRY); return; }
  const type = TYPES[extname(path)] ?? "application/octet-stream";
  if (LOCAL.test(path)) for (const dir of PUBLIC) if (existsSync(join(dir, path))) { res.writeHead(200, { "content-type": type }).end(readFileSync(join(dir, path))); return; }
  // прод: кэш на диске по адресу (с параметрами)
  const f = join(CACHE, createHash("sha1").update(url).digest("hex") + extname(path));
  try {
    let body;
    if (existsSync(f)) body = readFileSync(f);
    else {
      const r = await fetch(PROD + url);
      if (!r.ok) { res.writeHead(r.status).end(); return; }
      body = Buffer.from(await r.arrayBuffer());
      writeFileSync(f, body);
    }
    res.writeHead(200, { "content-type": type }).end(body);
  } catch { res.writeHead(502).end(); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
// страница стоит на /demo/, как живая: относительные адреса витрины (`img/…` — фото картин и ковра) считаются от неё (было `/` → 404 → чёрные картины, T-20261117-09)
const base = `http://127.0.0.1:${server.address().port}/demo/`;
const launch = () => chromium.launch({ ignoreDefaultArgs: ["--disable-dev-shm-usage"], args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const save = (name, url) => writeFileSync(join(OUT, name), Buffer.from(url.split(",")[1], "base64"));

if (SHEET.length) {
  const browser = await launch();
  const [CW, CH] = String(arg("--cell", "360x440")).split("x").map(Number);
  const tab = await browser.newPage({ viewport: { width: CW + 40, height: CH + 60 } });
  tab.on("pageerror", (e) => console.error(`ошибка страницы: ${e.message}`));
  await tab.goto(base);
  await tab.waitForFunction(() => typeof window.plantSheet === "function");
  const url = await tab.evaluate(([u, w, h]) => window.plantSheet(u, w, h), [SHEET.map((id) => `/flat3d/plants/${id}.glb`), CW, CH]);
  save(`sheet.${SHEET.join("+").slice(0, 80)}.jpg`, url);
  await browser.close();
  server.close();
  console.log(`→ ${OUT}`);
  process.exit(0);
}

const demo = JSON.parse(readFileSync(home(arg("--data")), "utf8"));
if (VARIANTS[0] === "all") VARIANTS = demo.variants.map((x) => x.id);
const rt = (await (await fetch(`${PROD}/demo/rt-meshes.json`)).json()).meshes;
// пол и стены — отделка по умолчанию из карточки квартиры, как `index.html:devFloor/devWall` (первая группа пола/стен гостиной, вариант по умолчанию)
const finish = await (async () => {
  try {
    const j = await (await fetch(`${PROD}/api/apartments/${encodeURIComponent(demo.apartment_id ?? "flat215")}?lang=ru&demo=1`)).json();
    const pick = (slot) => {
      const g = (j.card?.options ?? []).find((x) => (x.slotIds ?? []).includes(slot) && (!x.roomKind || x.roomKind === "living"));
      return g ? (g.variants.find((x) => x.id === g.defaultVariantId) ?? g.variants[0]) : null;
    };
    const f = pick("floor"), w = pick("wall");
    return {
      floor: f?.material ?? undefined,
      wall: w?.material ? { material: w.material, ...(w.accent?.material ? { accent: { material: w.accent.material, anchor: w.accent.anchor } } : {}) } : undefined,
    };
  } catch { return {}; }
})();
const report = [];
for (const vid of VARIANTS) {
  const v = demo.variants.find((x) => x.id === vid);
  if (!v) { console.error(`нет варианта ${vid}`); continue; }
  const room = { ...(demo.room ?? {}), ...((demo.rooms_geo ?? {})[v.room_id] ?? {}) };
  // позы ракурсов варианта + «смотрящие» на предметы ролей из --focus, у которых есть место в данных (кашпо; ваза стоит на опоре без своих
  // координат — её видно в ракурсах): 150 см от предмета в сторону центра комнаты, взгляд на него; сдвиг объектива --shift поднимает
  // низкий предмет в кадр (знак проверяется снимком)
  const SHIFT = Number(arg("--shift", "0")), DIST = Number(arg("--dist", "150"));
  const looks = SHIFT === 0 ? [] : [...(v.items ?? []), ...(v.decor ?? [])]
    .filter((it) => FOCUS.some((r) => String(it.role).startsWith(r)) && it.x != null && Number.isFinite(+it.x)).map((it) => {
      const dx = room.w / 2 - +it.x, dy = room.d / 2 - +it.y, n = Math.hypot(dx, dy) || 1;
      const px = +it.x + (dx / n) * DIST, py = +it.y + (dy / n) * DIST;
      return { x: px, y: py, rot: (Math.atan2(+it.x - px, -(+it.y - py)) * 180) / Math.PI, fov: 80, pose: 3, pshift: SHIFT };
    });
  const poses = [...(v.cams ?? []), ...looks];
  for (const [w, h] of SIZES) {
    for (const plants of MODES) {
      const browser = await launch();
      const tab = await browser.newPage({ viewport: { width: w, height: h } });
      let bytes = 0, files = 0;
      const errs = [];
      tab.on("pageerror", (e) => errs.push(String(e.message)));
      tab.on("response", async (r) => { try { const b = await r.body(); bytes += b.length; files += 1; } catch { /* редирект */ } });
      await tab.goto(base);
      await tab.waitForFunction(() => typeof window.variantSnap === "function");
      const got = await tab.evaluate((c) => window.variantSnap(c), { room, items: v.items ?? [], decor: v.decor ?? [], rt, floor: finish.floor, wall: finish.wall, lite: w < 600, plants: !!plants,
        style: v.style_id, poses, focus: FOCUS, gapRoles: GAPS, width: w, height: h });
      await browser.close();
      got.frames.forEach((url, i) => save(`${vid}.cam${i + 1}.${w}x${h}.plants${plants}.jpg`, url));
      got.crops.forEach((c, i) => save(`${vid}.crop-${c.role}.cam${c.pose + 1}.${w}x${h}.plants${plants}.jpg`, c.url));
      report.push({ variant: vid, size: `${w}x${h}`, plants, readyMs: got.readyMs, plantsMs: got.plantsMs, bytes, files, lost: got.lost, errs, plantLog: got.plantLog, gaps: got.gaps });
      for (const g of got.gaps) console.log(`  ${vid} зазор ${String(g.gapCm ?? "—").padStart(6)} см  ${g.role.padEnd(8)} «${g.title}» низ ${g.bottomCm} (план ${g.plannedBottomCm}), опора ${g.supportCm ?? "—"} ${g.support ?? ""}, высота ${g.heightCm}`);
      for (const e of got.plantLog) console.log(`  ${vid} ${e.why.padEnd(8)} ${e.role.padEnd(6)} «${e.title}» ${e.mount} горло ${e.throatCm?.toFixed(1) ?? "-"} см, геом ${e.geoWhy ?? "ок"}, кромка ${e.rimSpread?.toFixed(2) ?? "-"}, шея ${e.neckRatio?.toFixed(2) ?? "-"}${e.word ? " · слово «" + e.word + "»" : ""}${e.plant ? " → " + e.plant : ""}`);
      console.log(`${vid} ${w}x${h} plants=${plants}: ready ${got.readyMs} мс, растения ${got.plantsMs} мс, ${(bytes / 1024).toFixed(0)} КБ в ${files} файлах, обрезок ${got.crops.length}${got.lost ? " · КОНТЕКСТ ПОТЕРЯН" : ""}${errs.length ? " · ошибки: " + errs.join("; ") : ""}`);
    }
  }
}
server.close();
writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 1) + "\n");
console.log(`→ ${OUT}`);
