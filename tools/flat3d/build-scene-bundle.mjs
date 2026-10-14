#!/usr/bin/env node
// БАНДЛ ДВИЖКА СЦЕНЫ ДЛЯ ДЕМО (план demo-01 п.1). Исходник — `lib/viewer3d/*` (тот же, что у `/flat`), вход —
// `lib/viewer3d/demo-bundle.ts`, выход — `<out>/scene.<версия>.js` (ES-модуль: страница грузит его `import()`; формат
// IIFE не годится — внутри three есть `new URL(…, import.meta.url)` на уровне модуля) и `<out>/scene.json`
// ({file, build, bytes}). ВЕРСИЯ = отпечаток всех входов сборки (файлы из metafile esbuild, версия three и esbuild,
// этот скрипт): одинаковый исходник даёт одинаковую версию, и стык конвейера сверяет её с кодом прода (Codex 14.10).
// Старые версии не удаляются сразу (держим три): открытая страница может догружать прежний файл.
//   node tools/flat3d/build-scene-bundle.mjs --out ~/scout-scenes/flat215-demo/lib      сборка
//   node tools/flat3d/build-scene-bundle.mjs --print-id                                   только версия исходников
import { build as esbuild, version as esbuildVersion } from "esbuild";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const outIdx = args.indexOf("--out");
const OUT = outIdx >= 0 ? resolve(args[outIdx + 1].replace(/^~/, process.env.HOME)) : join(ROOT, "tools/scout/flat215-demo/lib");
const PLACEHOLDER = "__ENGINE_BUILD_PLACEHOLDER__";

const res = await esbuild({
  entryPoints: [join(ROOT, "lib/viewer3d/demo-bundle.ts")],
  bundle: true, format: "esm", minify: true, target: "es2020", write: false, metafile: true,
  alias: { "@": ROOT }, logLevel: "warning",
  define: { __ENGINE_BUILD__: JSON.stringify(PLACEHOLDER), "process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE": "undefined",
    "process.env.NEXT_PUBLIC_FLAT3D_RT_BASE": "undefined" },
});
const h = createHash("sha256");
for (const f of Object.keys(res.metafile.inputs).sort()) h.update(f + "\0").update(readFileSync(join(ROOT, f)));
h.update("three@" + JSON.parse(readFileSync(join(ROOT, "node_modules/three/package.json"), "utf8")).version);
h.update("esbuild@" + esbuildVersion).update(readFileSync(fileURLToPath(import.meta.url)));
const id = h.digest("hex").slice(0, 12);
if (args.includes("--print-id")) { console.log(id); process.exit(0); }

const js = res.outputFiles[0].text.replaceAll(PLACEHOLDER, id);
mkdirSync(OUT, { recursive: true });
const file = `scene.${id}.js`;
writeFileSync(join(OUT, file), js);
writeFileSync(join(OUT, "scene.json"), JSON.stringify({ file, build: id, bytes: js.length, inputs: Object.keys(res.metafile.inputs).length }) + "\n");
const old = readdirSync(OUT).filter((f) => /^scene\.[0-9a-f]{12}\.js$/.test(f) && f !== file)
  .sort((a, b) => statSync(join(OUT, b)).mtimeMs - statSync(join(OUT, a)).mtimeMs);
for (const f of old.slice(2)) unlinkSync(join(OUT, f));
console.log(`движок сцены: ${file} (${Math.round(js.length / 1024)} КБ, входов ${Object.keys(res.metafile.inputs).length}) → ${OUT}`);
