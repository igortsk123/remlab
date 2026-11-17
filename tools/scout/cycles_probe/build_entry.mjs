// Сборка выгрузчика сцены /demo (`demo_scene_entry.ts`) в один файл для headless-страницы: node build_entry.mjs <выход-папка>
// Те же алиасы и подмены `NEXT_PUBLIC_*`, что у боевой сборки движка (`tools/flat3d/build-scene-bundle.mjs`); исходники — из ЭТОЙ копии репо.
import { createRequire } from 'module';
import path from 'path';
import fs from 'fs';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../..');
const require = createRequire(path.join(ROOT, 'package.json'));
const { build } = require('esbuild');
const out = process.argv[2];
fs.mkdirSync(out, { recursive: true });
await build({
  entryPoints: [path.join(ROOT, 'tools/scout/cycles_probe/demo_scene_entry.ts')],
  outfile: path.join(out, 'entry.js'),
  bundle: true, format: 'esm', target: 'es2020', minify: false, absWorkingDir: ROOT, alias: { '@': ROOT }, logLevel: 'warning',
  define: { 'process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE': 'undefined', 'process.env.NEXT_PUBLIC_FLAT3D_RT_BASE': 'undefined' },
});
console.log('собрано', path.join(out, 'entry.js'), fs.statSync(path.join(out, 'entry.js')).size, 'байт');
