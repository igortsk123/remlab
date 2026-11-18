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
// ТРАССА (T-20261118-09/1): отметки времени от старта скрипта — `TRACE node <шаг> <секунды>`; исполнитель собирает их в `timing.trace.node` (ничего не меняет в сцене)
const T_START = Date.now();
const tr = (name) => console.log(`TRACE node ${name} ${((Date.now() - T_START) / 1000).toFixed(2)}`);
const REMOTE_STAT = { n: 0, ms: 0, bytes: 0, local: 0 };       // обращения к remont-lab.online (сеть) и отданные с диска файлы за прогон
const [dataFile, idxS, bundleDir, outDir, ...rest] = process.argv.slice(2);
const extra = Object.fromEntries(rest.map((s) => s.split('=')));
const REMOTE = 'remont-lab.online';
const CACHE = path.join(os.homedir(), 'scout-scenes/mesh3d-cache');
const PUBLIC = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../../public');
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
  if (u !== '/' && u !== '/index.html' && u !== '/entry.js') { REMOTE_STAT.local++; if (process.env.DUMP_URLS) fs.appendFileSync(process.env.DUMP_URLS, `local ${req.url}\n`); }
  const cors = { 'access-control-allow-origin': '*' };
  if (u === '/' || u === '/index.html') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<!doctype html><meta charset=utf-8><script type="module" src="/entry.js"></script>'); return; }
  if (u === '/entry.js') { res.writeHead(200, { 'content-type': 'text/javascript' }); fs.createReadStream(path.join(bundleDir, 'entry.js')).pipe(res); return; }
  // карты материалов (в том числе новые, ещё не выложенные на прод) — из `public/` этой копии репо
  // (и растения `public/flat3d/plants/*.glb`: в main с 17.11, на проде ещё нет)
  const pm = u.match(/^\/flat3d\/(materials|plants)\/([A-Za-z0-9._-]+)$/);
  if (pm && fs.existsSync(path.join(PUBLIC, 'flat3d', pm[1], pm[2]))) { res.writeHead(200, { 'content-type': mime[path.extname(u)] || 'application/octet-stream', ...cors }); fs.createReadStream(path.join(PUBLIC, 'flat3d', pm[1], pm[2])).pipe(res); return; }
  // фото товаров новой витрины, ещё не выложенной на прод (`-art.jpg` новых картин): DEMO_LOCAL_DIR=<папка витрины> — файл оттуда, нет — с сайта
  const lm = process.env.DEMO_LOCAL_DIR && u.match(/^\/demo\/(img\/[A-Za-z0-9._-]+)$/);
  if (lm && fs.existsSync(path.join(process.env.DEMO_LOCAL_DIR, lm[1]))) { res.writeHead(200, { 'content-type': mime[path.extname(u)] || 'application/octet-stream', ...cors }); fs.createReadStream(path.join(process.env.DEMO_LOCAL_DIR, lm[1])).pipe(res); return; }
  const m = u.match(/^\/test\/mesh-pilot10\/([^/]+)\/model\.glb$/);
  if (m && fs.existsSync(path.join(CACHE, m[1] + '.glb'))) { res.writeHead(200, { 'content-type': 'model/gltf-binary', ...cors }); fs.createReadStream(path.join(CACHE, m[1] + '.glb')).pipe(res); return; }
  REMOTE_STAT.local--; REMOTE_STAT.n++;
  if (process.env.DUMP_URLS) fs.appendFileSync(process.env.DUMP_URLS, `remote ${req.url}\n`);        // отладка: какие адреса уходят в сеть (ключи кэша, трасса)
  const tRem = Date.now();
  https.get({ host: REMOTE, path: req.url, headers: { 'user-agent': 'cycles-probe' } }, (r) => {
    r.on('data', (c) => { REMOTE_STAT.bytes += c.length; }); r.on('end', () => { REMOTE_STAT.ms += Date.now() - tRem; });
    if (r.statusCode >= 400) miss.push(`${r.statusCode} ${u}`);
    res.writeHead(r.statusCode, { 'content-type': r.headers['content-type'] || mime[path.extname(u)] || 'application/octet-stream', ...cors });
    r.pipe(res);
  }).on('error', () => { miss.push('ERR ' + u); res.writeHead(502); res.end(); });
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const port = srv.address().port;
tr('server');
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--disable-gpu-sandbox'] });
tr('browser_launch');
const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
tr('new_page');
page.on('console', (m) => console.log('[page]', m.text().slice(0, 300)));
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 600)));
await page.goto(`http://127.0.0.1:${port}/${extra.finish === '0' ? '?finish=0' : ''}`);   // finish=0 — стены и пол плоской краской («до», `finish-textures.ts:finishTexFromUrl`)
tr('page_goto');
await page.waitForFunction(() => typeof window.buildDemoScene === 'function', null, { timeout: 60000 });
tr('bundle_ready');
const t0 = Date.now();
// живая таблица runtime-копий мешей (`/demo/rt-meshes.json`) — ею страница выбирает лёгкую копию; нет — экспорт скажет «лёгких нет»
let runtime = null;
try { runtime = JSON.parse(await new Promise((res, rej) => https.get({ host: REMOTE, path: '/demo/rt-meshes.json', headers: { 'user-agent': 'cycles-probe' } },
  (r) => { let s = ''; r.on('data', (c) => { s += c; }); r.on('end', () => res(s)); }).on('error', rej))).meshes; } catch (e) { console.log('rt-meshes.json не получен:', String(e).slice(0, 100)); }
tr('rt_meshes_fetch');
const lite = extra.lite === '1';       // телефон: LITE_QUALITY, лёгкие карты
const sceneArgs = { room, items: v.items, decor, base: `http://127.0.0.1:${port}/demo/`, runtime, lite, cams: v.cams || [], style: v.style };
const info = await page.evaluate((a) => window.buildDemoScene(a), sceneArgs);
tr('build_scene');
for (const m of (info.trace || [])) console.log(`TRACE page ${m.name} ${m.s}`);
delete info.trace;                 // отметки времени — только в журнал: в scene_info.json (едет в пакет задания) их быть не должно (файл не должен меняться от прогона к прогону)
console.log('сцена собрана за', ((Date.now() - t0) / 1000).toFixed(1), 'с; узлов', info.nodes.length, 'мест', info.slots.length);
fs.writeFileSync(path.join(outDir, 'scene_info.json'), JSON.stringify({ variant: v.id, room, decorIn: decor.map((d) => ({ role: d.role, strategy: d.strategy, place: d.place })), ...info }, null, 1));
if (extra.livecam) {
  // livecam=<ракурс>:<ширина>x<высота>:<верх>,<низ> — камера «3D» как на странице (`liveCamera` входа): полоса холста — доли высоты, свободная от кнопок и шторки
  const [ci, sz, bd] = extra.livecam.split(':'); const [lw, lh] = sz.split('x').map(Number); const [bt, bb] = bd.split(',').map(Number);
  const lc = await page.evaluate((x) => window.liveCamera(x.ci, x.w, x.h, { top: x.bt, bottom: x.bb }), { ci: Number(ci), w: lw, h: lh, bt, bb });
  fs.writeFileSync(path.join(outDir, 'live_cam.json'), JSON.stringify(lc, null, 1));
  console.log('камера живой 3D:', JSON.stringify(lc.pos.map((v) => +v.toFixed(3))), 'взгляд', JSON.stringify(lc.dir.map((v) => +v.toFixed(3))), 'vfov', lc.vfov.toFixed(1));
}
fs.writeFileSync(path.join(outDir, 'scene-export.json'), JSON.stringify(await page.evaluate(() => window.__export), null, 1));
fs.writeFileSync(path.join(outDir, 'shell_info.json'), JSON.stringify(await page.evaluate(() => window.shellInfo()), null, 1));
tr('infos_written');
if (extra.export) {
  const keys = extra.export === 'all' ? null : extra.export.split(',');
  // ключ `rod` — карниз: узлы `fixtures:` выше 2 м (плинтус и порожки той же группы не берём)
  // ткань, чья форма не рисуется геометрией (`data/flat3d/textile.json` → `render.<форма>: false`; плед — ярлык, ADR-0425, владелец TG 1476
  // «оранжевую фигню убери»), в рендер не идёт: её узел в сцене — прозрачное место ярлыка, в GLB он стал бы цветной доской. По флагу, не по названию
  const TX = JSON.parse(fs.readFileSync(path.resolve(PUBLIC, '../data/flat3d/textile.json'), 'utf-8')).render || {};
  const noGeom = new Set(info.slots.filter((s) => s.kit === 'textile' && (s.features || []).some((f) => TX[f] === false)).map((s) => s.slotId));
  // радиатор под окном (slot `radiator`, T-20261117-11) идёт в выгрузку ВСЕГДА, кроме явного `-radiator` в списке: иначе фото-рендер и живая 3D расходятся
  // шторы окон по умолчанию (`curtains: true` движка: группа `curtains`, не слот декора) идут в выгрузку ВСЕГДА, кроме явного `-curtains`: на странице они есть
  // у каждого окна, а ключи `textile,…` ловят только шторы-СЛОТЫ декора (T-20261117-16/2, владелец: «в спальне нет штор»)
  const noCur = keys && keys.includes('-curtains');
  const noRad = keys && keys.includes('-radiator');
  // оболочка комнаты строится Blender'ом сама (плиты пола/стен/потолка из export_scene): её плоскость потолка (`ceiling:<комната>` без `Mesh<`, y = высота
  // потолка) в выгрузку не идёт — иначе накладывается на плиту и даёт серые «треугольники» z-fighting (T-20261117-19/2 п.1, все комнаты).
  // Люстра/плафон (`ceiling:люстра#…`, `Mesh<ceiling:…:lamp`) — не оболочка, их ключ `ceiling` берёт как раньше
  const isShellCeiling = (n) => /^ceiling:[^<:]+<room:/.test(n.chain);
  // шторы оболочки — правилом выше (`noCur`, T-20261117-16/3); правило T-19/2 `isShellCurtain` при слиянии поглощено им
  const pick = info.nodes.filter((n) => n.visible && n.type === 'Mesh' && !noGeom.has(n.slot) && !isShellCeiling(n) && ((n.slot === 'radiator' && !noRad) || (n.chain.includes('curtains') && !noCur) || !keys || keys.some((k) => k === 'rod'
    ? n.chain.includes('fixtures:') && n.min[1] > 2.0 && n.max[1] < 2.69 : k === 'plant' ? n.plant : (n.slot + '|' + n.chain).includes(k)))).map((n) => n.uuid);
  console.log('выгружаю узлов', pick.length);
  tr('pick');
  const b64 = await page.evaluate((u) => window.exportNodes(u), pick);
  tr('export_nodes_glb');
  fs.writeFileSync(path.join(outDir, 'demo_nodes.glb'), Buffer.from(b64, 'base64'));
  fs.writeFileSync(path.join(outDir, 'demo_nodes_uuids.json'), JSON.stringify(info.nodes.filter((n) => pick.includes(n.uuid))));
  fs.writeFileSync(path.join(outDir, 'dump_keys.json'), JSON.stringify({ export: extra.export }));
  tr('glb_written');    // какими ключами брали узлы: сторож кадров (frame_qa.dump_keys) отличает явный минус (`-curtains`) от потери
}
// байты, которые /demo качает при первом показе: карты оболочки (`sceneAssetUrls().shell`); файлы materials — с диска этой копии репо
if (extra.assets) {
  const urls = await page.evaluate((a) => window.assetUrls(a), { room, items: v.items, decor, base: sceneArgs.base, lite });
  const mats = urls.shell.filter((u) => /\/flat3d\/materials\//.test(u)).map((u) => new URL(u, 'http://x/').pathname);
  const rows = mats.map((p) => ({ url: p, bytes: fs.existsSync(path.join(PUBLIC, p)) ? fs.statSync(path.join(PUBLIC, p)).size : null }));
  fs.writeFileSync(path.join(outDir, 'assets.json'), JSON.stringify({ lite, count: rows.length, bytes: rows.reduce((s, r) => s + (r.bytes || 0), 0), rows,
    meshes: urls.meshes.length }, null, 1));
  console.log('карты оболочки:', rows.length, 'файлов,', rows.reduce((s, r) => s + (r.bytes || 0), 0), 'байт');
}
// снимки по ракурсам квартиры: shots=<ширина>x<высота> (375x667 — телефон)
if (extra.shots) {
  const [sw, sh] = extra.shots.split('x').map(Number);
  const n = (v.cams || []).length;
  const times = [];
  for (let i = 0; i < Math.min(n, +(extra.maxcams || 3)); i++) {
    const r = await page.evaluate(([i_, w, h]) => window.shot(i_, w, h), [i, sw, sh]);
    fs.writeFileSync(path.join(outDir, `shot-${extra.finish === '0' ? 'before' : 'after'}-${i}.jpg`), Buffer.from(r.b64, 'base64'));
    times.push(r.ms);
  }
  fs.writeFileSync(path.join(outDir, `shot-times-${extra.finish === '0' ? 'before' : 'after'}.json`), JSON.stringify({ lite, w: sw, h: sh, ms: times }));
  console.log('снимки', times.length, 'за', times.join(', '), 'мс');
}
if (miss.length) { fs.writeFileSync(path.join(outDir, 'miss.txt'), miss.join('\n')); console.log('не нашлось:', miss.length); }
tr('before_close');
await browser.close();
srv.close();
tr('close');
console.log(`TRACE node remote_n ${REMOTE_STAT.n}\nTRACE node remote_ms ${(REMOTE_STAT.ms / 1000).toFixed(2)}\nTRACE node remote_mb ${(REMOTE_STAT.bytes / 1048576).toFixed(2)}\nTRACE node local_n ${REMOTE_STAT.local}`);
