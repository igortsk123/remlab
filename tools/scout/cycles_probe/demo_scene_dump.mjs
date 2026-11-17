// ПРОБА T-20261117-02/2: поднять сцену /demo (бандл `demo_scene_entry.ts`) в headless Chromium (программный WebGL) для варианта витрины
// и выгрузить её описание (места, узлы) и — по желанию — GLB выбранных узлов. 0 ₽.
//   node demo_scene_dump.mjs <demo-data.json> <индекс варианта> <папка бандла> <выход-папка> [export=<подстрока-слота,...>|all]
// Меши — из локального кэша `~/scout-scenes/mesh3d-cache/<sid>.glb` (полные), остальное (картинки, материалы, окружение) — с remont-lab.online.
import { createRequire } from 'module';
import http from 'http';
import https from 'https';
import fs from 'fs';
import os from 'os';
import path from 'path';

const require = createRequire('/home/pakar/igor/remlab/package.json');
const { chromium } = require('/home/pakar/igor/remlab/node_modules/.pnpm/playwright@1.51.1/node_modules/playwright');
const [dataFile, idxS, bundleDir, outDir, ...rest] = process.argv.slice(2);
const extra = Object.fromEntries(rest.map((s) => s.split('=')));
const REMOTE = 'remont-lab.online';
const CACHE = path.join(os.homedir(), 'scout-scenes/mesh3d-cache');
fs.mkdirSync(outDir, { recursive: true });

const D = JSON.parse(fs.readFileSync(dataFile, 'utf-8'));
const v = D.variants[+idxS];
const room = (D.rooms_geo && D.rooms_geo[v.room_id || 'living']) || D.room;
const SOFT = (D.rules && D.rules.soft_roles) || ['плед', 'подушка', 'покрывало', 'полка', 'шторы'];
const isSoft = (role) => SOFT.includes(String(role || '').replace(/\s+\d+$/, ''));
const isCloth3d = (x) => { const p = x && x.place, l = x && x.look, k = (x && x.sku) || {};
  return !!x && !x.list_only && x.strategy === 'textile_abstract' && !!k.name && !!p && ['curtain', 'throw', 'pillow'].includes(p.kind) && !!l
    && /^#[0-9a-fA-F]{6}$/.test(l.hex || '') && l.of === String(k.sid || k.name || '') && [p.x, p.y, p.elev_cm].every(Number.isFinite)
    && (p.kind !== 'curtain' || Number.isInteger(p.opening)); };
const in3dDecor = (x) => !!x && !x.list_only && (!isSoft(x.role) || isCloth3d(x));      // тот же признак, что `liveDecor` страницы
const decor = (v.decor || []).filter(in3dDecor);

const mime = { '.html': 'text/html', '.js': 'text/javascript', '.glb': 'model/gltf-binary', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp' };
const miss = [];
const srv = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]);
  const cors = { 'access-control-allow-origin': '*' };
  if (u === '/' || u === '/index.html') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<!doctype html><meta charset=utf-8><script type="module" src="/entry.js"></script>'); return; }
  if (u === '/entry.js') { res.writeHead(200, { 'content-type': 'text/javascript' }); fs.createReadStream(path.join(bundleDir, 'entry.js')).pipe(res); return; }
  const m = u.match(/^\/test\/mesh-pilot10\/([^/]+)\/model\.glb$/);
  if (m && fs.existsSync(path.join(CACHE, m[1] + '.glb'))) { res.writeHead(200, { 'content-type': 'model/gltf-binary', ...cors }); fs.createReadStream(path.join(CACHE, m[1] + '.glb')).pipe(res); return; }
  https.get({ host: REMOTE, path: req.url, headers: { 'user-agent': 'cycles-probe' } }, (r) => {
    if (r.statusCode >= 400) miss.push(`${r.statusCode} ${u}`);
    res.writeHead(r.statusCode, { 'content-type': r.headers['content-type'] || mime[path.extname(u)] || 'application/octet-stream', ...cors });
    r.pipe(res);
  }).on('error', () => { miss.push('ERR ' + u); res.writeHead(502); res.end(); });
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const port = srv.address().port;
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--disable-gpu-sandbox'] });
const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
page.on('console', (m) => console.log('[page]', m.text().slice(0, 300)));
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 600)));
await page.goto(`http://127.0.0.1:${port}/`);
await page.waitForFunction(() => typeof window.buildDemoScene === 'function', null, { timeout: 60000 });
const t0 = Date.now();
const info = await page.evaluate((a) => window.buildDemoScene(a), { room, items: v.items, decor, base: `http://127.0.0.1:${port}/demo/` });
console.log('сцена собрана за', ((Date.now() - t0) / 1000).toFixed(1), 'с; узлов', info.nodes.length, 'мест', info.slots.length);
fs.writeFileSync(path.join(outDir, 'scene_info.json'), JSON.stringify({ variant: v.id, room, decorIn: decor.map((d) => ({ role: d.role, strategy: d.strategy, place: d.place })), ...info }, null, 1));
fs.writeFileSync(path.join(outDir, 'shell_info.json'), JSON.stringify(await page.evaluate(() => window.shellInfo()), null, 1));
if (extra.export) {
  const keys = extra.export === 'all' ? null : extra.export.split(',');
  // ключ `rod` — карниз: узлы `fixtures:` выше 2 м (плинтус и порожки той же группы не берём)
  const pick = info.nodes.filter((n) => n.visible && n.type === 'Mesh' && (!keys || keys.some((k) => k === 'rod'
    ? n.chain.includes('fixtures:') && n.min[1] > 2.0 && n.max[1] < 2.69 : (n.slot + '|' + n.chain).includes(k)))).map((n) => n.uuid);
  console.log('выгружаю узлов', pick.length);
  const b64 = await page.evaluate((u) => window.exportNodes(u), pick);
  fs.writeFileSync(path.join(outDir, 'demo_nodes.glb'), Buffer.from(b64, 'base64'));
  fs.writeFileSync(path.join(outDir, 'demo_nodes_uuids.json'), JSON.stringify(info.nodes.filter((n) => pick.includes(n.uuid))));
}
if (miss.length) { fs.writeFileSync(path.join(outDir, 'miss.txt'), miss.join('\n')); console.log('не нашлось:', miss.length); }
await browser.close();
srv.close();
