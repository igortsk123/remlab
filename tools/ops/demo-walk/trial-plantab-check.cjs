// T-20261110-04: вкладка «План квартиры» в ТУРЕ ПРОБЫ (`/try/<id>/tour/`) против /demo — подписи в стенах, двери, низ страницы на
// телефоне, одна строка про масштаб, окно спальни, порядок комнат на главной.
// БЕСПЛАТНО: данные тура — файл (`trial_bundle.py` по входам задания), обвязка — настоящая (`lib/trial/tour-page.ts:injectTour`),
// движок/меши — прод `/demo/`, все `/api/*` — 403.
//   PAGE=<index.html> node tools/ops/demo-walk/trial-plantab-check.cjs <WxH> <новая папка> <tour.json> [метка] [ru|en]
// Снимки: главная, план (окно и вся страница), низ плана после прокрутки (окно), окно спальни. Замеры — JSON в stdout и в папку.
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const esbuild = require(pick('esbuild'));
const PAGE = process.env.PAGE || path.join(ROOT, 'tools/scout/flat215-demo/index.html');
const ORIGIN = 'https://remont-lab.online';
const ID = 'T04plantabT04plantab00';
const TOUR = `/try/${ID}/tour/`;
const [W, H] = (process.argv[2] || '1280x800').split('x').map(Number);
const OUT = process.argv[3]; fs.mkdirSync(OUT, { recursive: true });
const DEMO = process.argv[4] === '--demo';      // для сравнения: живой /demo (данные прод) с той же страницей PAGE
const DATA = DEMO ? null : JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const TAG = process.argv[5] || 'new';
const LANG = process.argv[6] || 'ru';
const PHONE = W <= 700;
const EN = LANG === 'en';

function loadInject() {
  const out = esbuild.buildSync({ entryPoints: [path.join(ROOT, 'lib/trial/tour-page.ts')], bundle: true, platform: 'node', format: 'cjs',
    write: false, tsconfig: path.join(ROOT, 'tsconfig.json'), logLevel: 'error' });
  const m = { exports: {} };
  new Function('module', 'exports', 'require', out.outputFiles[0].text)(m, m.exports, require);
  return m.exports;
}
const TP = loadInject();

async function openDemo(b) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE,
    locale: EN ? 'en-GB' : 'ru-RU' });
  const p = await ctx.newPage();
  p.log = [];
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  await p.route(/\/demo\/(index\.html)?(\?.*)?$/, r => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: fs.readFileSync(PAGE, 'utf8') }));
  await p.route(/\/api\//, r => r.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false,"code":"probe"}' }));
  await p.goto(ORIGIN + `/demo/?quiz=0&live=force&lang=${LANG}`, { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForTimeout(2500);
  return p;
}

async function open(b) {
  if (DEMO) return openDemo(b);
  const d = JSON.parse(JSON.stringify(DATA));
  d.trial = Object.assign({}, d.trial, { job_id: ID });
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE,
    locale: EN ? 'en-GB' : 'ru-RU' });
  const p = await ctx.newPage();
  p.log = [];
  p.on('console', m => { if (m.type() === 'error') p.log.push('error: ' + m.text().slice(0, 300)); });
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  const html = TP.injectTour(fs.readFileSync(PAGE, 'utf8'), ID, 0);
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith(TOUR), async r => {
    const rel = new URL(r.request().url()).pathname.slice(TOUR.length);
    if (rel === '' || rel === 'index.html') return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    if (rel === 'demo-data.json') return r.fulfill({ status: 200, contentType: 'application/json', headers: { etag: '"v1"' }, body: JSON.stringify(d) });
    if (rel === 'version.json') return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: 0, bundle: 1, rebuild: null, rebuildError: null }) });
    const f = await r.fetch({ url: ORIGIN + '/demo/' + rel + new URL(r.request().url()).search });
    return r.fulfill({ response: f });
  });
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith('/api/'), r => r.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false}' }));
  await p.goto(ORIGIN + TOUR + `?quiz=0&live=force&lang=${LANG}`, { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!D.trial&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForTimeout(2500);
  return p;
}

// замеры плана: подпись за стеной комнаты, наезд подписей разных комнат, двери, строки под планом, низ страницы
const planProbe = () => {
  const svg = document.querySelector('#flatRooms svg'); if (!svg) return { svg: false };
  const groups = [...svg.querySelectorAll(':scope > g')];
  const rooms = [], boxes = [];
  groups.forEach((g, gi) => {
    const shape = g.querySelector('polygon,rect'); if (!shape) return;
    const rb = shape.getBBox();
    const texts = [...g.querySelectorAll('text')];
    const lines = texts.map(t => { const b = t.getBBox(); boxes.push({ gi, b, t: t.textContent });
      const over = Math.max(rb.x - b.x, b.x + b.width - (rb.x + rb.width), rb.y - b.y, b.y + b.height - (rb.y + rb.height));
      return { t: t.textContent, over: +over.toFixed(3) }; });
    rooms.push({ name: lines[0] && lines[0].t, w: +rb.width.toFixed(2), d: +rb.height.toFixed(2), lines });
  });
  const hit = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], c = boxes[j]; if (a.gi === c.gi) continue;
    const ox = Math.min(a.b.x + a.b.width, c.b.x + c.b.width) - Math.max(a.b.x, c.b.x), oy = Math.min(a.b.y + a.b.height, c.b.y + c.b.height) - Math.max(a.b.y, c.b.y);
    if (ox > 0.01 && oy > 0.01) hit.push(a.t + ' × ' + c.t);
  }
  const hints = [...document.querySelectorAll('#flatRooms .hint')].filter(e => e.offsetHeight > 0).map(e => e.textContent.trim());
  const hh = document.getElementById('trHead'), head = hh && hh.offsetHeight > 0 ? hh.innerText : '';   // видимое — не textContent
  return { svg: true, rooms: rooms.filter(r => r.lines.some(l => l.over > 0.02)).map(r => ({ name: r.name, w: r.w, d: r.d, lines: r.lines })),
    nRooms: rooms.length, overlaps: hit, doors: svg.querySelectorAll('[data-door="door"]').length, gaps: svg.querySelectorAll('[data-door="gap"]').length,
    windows: svg.querySelectorAll('[data-door="window"]').length,
    fonts: rooms.map(r => r.name + ' ' + r.lines.length),
    hints, head: head.trim() };
};
// видимые в окне элементы «шторки подбора» (`#sheet`) после прокрутки вниз
const sheetProbe = () => {
  const s = document.getElementById('sheet'); if (!s) return { sheet: false };
  const r = s.getBoundingClientRect(), cs = getComputedStyle(s);
  return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight, display: cs.display, visibility: cs.visibility,
    visible: cs.display !== 'none' && cs.visibility !== 'hidden' && r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0 && r.height > 0 };
};

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const res = { W, H, tag: TAG, lang: LANG };
  const p = await open(b);
  res.homeOrder = await p.evaluate(() => homeRooms().map(r => r.title));
  await p.screenshot({ path: `${OUT}/home-${W}-${TAG}.png` });
  await p.evaluate(() => showTab('plan')); await p.waitForTimeout(1500);
  res.plan = await p.evaluate(planProbe);
  await p.screenshot({ path: `${OUT}/plan-${W}-${TAG}.png` });
  await p.screenshot({ path: `${OUT}/plan-${W}-${TAG}-full.png`, fullPage: true });
  await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); await p.waitForTimeout(800);
  res.sheet = await p.evaluate(sheetProbe);
  await p.screenshot({ path: `${OUT}/plan-${W}-${TAG}-bottom.png` });
  // окно спальни: первый вариант спальни с мебелью
  await p.evaluate(() => window.scrollTo(0, 0));
  const bi = await p.evaluate(() => { const bed = new Set(homeRooms().filter(r => r.kind === 'bedroom').map(r => r.id));
    return allVariants().findIndex(v => bed.has(roomIdOf(v)) && (v.items || []).length); });
  if (bi >= 0) {
    await p.evaluate(i => { showTab('room'); vwOpenVariant(i); }, bi);
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
    await p.waitForTimeout(2500);
    res.bedroom = await p.evaluate(() => {
      const n = document.querySelector('#vrow .vrow-n');
      const rows = [...document.querySelectorAll('#shot .vitems .row .t')].map(t => ({ name: (t.querySelector('b') || {}).textContent, sub: (t.querySelector('span') || {}).textContent || '' }));
      return { style: n && n.textContent, cut: !!(n && n.scrollWidth > n.clientWidth + 1), nw: n && n.clientWidth, sw: n && n.scrollWidth, rows };
    });
    await p.screenshot({ path: `${OUT}/bedroom-${W}-${TAG}.png`, timeout: 90000 }).catch(e => p.log.push('shot: ' + String(e).slice(0, 120)));
  }
  res.log = p.log;
  fs.writeFileSync(`${OUT}/probe-${W}-${TAG}.json`, JSON.stringify(res, null, 1));
  console.log(JSON.stringify(res));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
