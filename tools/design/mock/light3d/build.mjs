#!/usr/bin/env node
// Сборка движка демо для прототипа света (T-20261111-22): те же настройки esbuild, что `tools/flat3d/build-scene-bundle.mjs`,
// вход — `entry.ts` (движок + классы three для вставки). В выход вшиты две точки входа для вставки:
//   1) сразу после `this.addLights()` в конструкторе сцены — `globalThis.__light3d(this)` (вставка меняет свет до первого кадра);
//   2) проверка «программный рендер» — `globalThis.__L3D_FULL` её выключает, чтобы снимок «компьютер» шёл полным профилем (с тенями),
//      как у человека с видеокартой (на машине без GPU движок иначе сам уходит в облегчённый).
// Прод-бандл не меняется: файл кладётся в --out, страница получает его подменой запроса в Playwright (`shoot.cjs`).
//   node tools/design/mock/light3d/build.mjs --out <папка>
import { build as esbuild } from "esbuild";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const args = process.argv.slice(2);
const OUT = resolve(args[args.indexOf("--out") + 1] ?? join(ROOT, ".t22-out"));

const res = await esbuild({
  entryPoints: [join(ROOT, "tools/design/mock/light3d/entry.ts")],
  bundle: true, format: "esm", minify: true, target: "es2020", write: false,
  alias: { "@": ROOT }, logLevel: "warning", absWorkingDir: ROOT,
  define: { __ENGINE_BUILD__: JSON.stringify("l3d-proto"), "process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE": "undefined",
    "process.env.NEXT_PUBLIC_FLAT3D_RT_BASE": "undefined" },
});
let js = res.outputFiles[0].text;
const swap = (from, to) => {
  const n = js.split(from).length - 1;
  if (n !== 1) throw new Error(`точка вставки «${from}» найдена ${n} раз(а), нужна 1`);
  js = js.replace(from, to);
};
swap("this.addLights(),", "this.addLights(),globalThis.__light3d&&globalThis.__light3d(this),");
swap("return/swiftshader|llvmpipe|software|microsoft basic/i.test(", "return!globalThis.__L3D_FULL&&/swiftshader|llvmpipe|software|microsoft basic/i.test(");
mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "scene-l3d.js"), js);
console.log(JSON.stringify({ file: join(OUT, "scene-l3d.js"), bytes: js.length }));
