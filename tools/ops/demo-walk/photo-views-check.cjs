// T-20261109-29: «Сделать реалистичнее» — уходят ли кадры из браузера (`views`) в заказ фото. БЕСПЛАТНО: /api/render отвечает
// заглушкой-отказом (платная генерация не запускается), /api/render/frame — заглушкой с id = sha256 (на прод ничего не грузится).
//   node tools/ops/demo-walk/photo-views-check.cjs <WxH> <новая папка> [walk,early,stale,home]
// Сценарии: walk — окно в 3D, сцена готова; early — нажали до готовности 3D; stale — окно открылось в «Фото» (прежнее фото, T-66),
// кнопка на плашке «Вы изменили комнату»; home — кнопка карточки главной (`homeStaleReal`). Годно — заказ с `views` из 2 id (VIEWS).
// Страница — index.html этой копии (PAGE=путь), данные/движок/реестр — прод (`?live=force`: программный рендер headless).
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pw = require(NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith('playwright-core@')) + '/node_modules/playwright-core');
const { demoUrl } = require('../demo-url.cjs');
const PAGE = process.env.PAGE || path.join(ROOT, 'tools/scout/flat215-demo/index.html');
const BASE = 'https://remont-lab.online/demo/';
const [W, H] = (process.argv[2] || '1280x900').split('x').map(Number);
const OUT = process.argv[3]; fs.mkdirSync(OUT, { recursive: true });
const ONLY = (process.argv[4] || 'walk,early,stale,home').split(',');
const PHONE = W <= 700;
const res = [];

async function open(b) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: 'ru-RU' });
  const p = await ctx.newPage();
  p.log = []; p.bodies = []; p.frames = [];
  p.on('console', m => { const t = m.text(); if (m.type() === 'warning' || m.type() === 'error' || /кадр/.test(t)) p.log.push(m.type() + ': ' + t.slice(0, 300)); });
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  await p.route(/\/demo\/(index\.html)?(\?.*)?$/, r => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: fs.readFileSync(PAGE, 'utf8') }));
  await p.route(/\/api\/events/, r => r.fulfill({ status: 204, body: '' }));
  await p.route(/\/api\/(render|draft|warm)/, r => {
    const u = new URL(r.request().url());
    if (u.pathname === '/api/render/frame') {
      const buf = r.request().postDataBuffer() || Buffer.alloc(0), id = crypto.createHash('sha256').update(buf).digest('hex');
      p.frames.push({ id, bytes: buf.length });
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id, bytes: buf.length }) });
    }
    if (u.pathname === '/api/render' && r.request().method() === 'POST') {
      let j = {}; try { j = JSON.parse(r.request().postData() || '{}'); } catch (e) {}
      p.bodies.push({ t: Date.now(), quality: j.quality, views: j.views || null, src_id: j.src_id || null, sheet: j.sheet || null, clay: j.clay || null });
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 'probe', error: 'проба T-29: платный вызов не делаем' }) });
    }
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 'probe', error: 'проба' }) });
  });
  await p.goto(demoUrl(BASE + '?live=force&lang=ru'), { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForFunction("typeof SHOTS_LOADED!=='undefined'&&SHOTS_LOADED", null, { timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(1500);
  return p;
}
const live = p => p.evaluate(() => ({ ok: LIVE.ok, scene: !!LIVE.scene, state: LIVE.state || '', loading: !!LIVE.loading, mode: VW.mode,
  canvasIn: !!(LIVE.canvas && LIVE.canvas.isConnected), touch: isTouchUI() }));
async function waitOrder(p, ms) {
  for (let t = 0; t < ms / 500 && !p.bodies.some(x => x.quality === 'realistic'); t++) await p.waitForTimeout(500);
  await p.waitForTimeout(800);
}
async function report(p, name, before, t0) {
  const b = p.bodies.filter(x => x.quality === 'realistic').pop() || null;
  const after = await live(p);
  const r = { scenario: name, size: W + 'x' + H, before, after, order: b ? { views: b.views, src_id: b.src_id, sheet: b.sheet, sec: +((b.t - t0) / 1000).toFixed(1) } : null,
    lastCapture: await p.evaluate(() => VW.lastCapture), frames: p.frames.length, console: p.log.filter(l => /кадр|error|Error/.test(l)).slice(-8) };
  r.verdict = b && Array.isArray(b.views) && b.views.length === 2 ? 'VIEWS' : (b ? 'NO-VIEWS' : 'NO-ORDER');
  res.push(r); console.log(JSON.stringify(r));
}
// правка без окна: другой пол — расстановка «изменена», фото комнаты становится прежним (как у покупателя, вернувшегося к комнате)
const edit = p => p.evaluate(() => { const g = devGroups().find(x => x.kind === 'flooring'); if (g) devSet(g.id, g.variants[1].id); return !!g; });

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    if (ONLY.includes('walk')) { // окно в 3D (фото нет), сцена готова → кнопка в шторке
      const p = await open(b);
      await p.evaluate(() => { shots = shots.filter(x => x.quality !== 'realistic'); openLiveWindow(); });
      await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
      await p.waitForTimeout(1500);
      const before = await live(p); await p.screenshot({ path: OUT + `/walk-${W}-before.png` });
      const t0 = Date.now(); await p.click('#vCta'); await p.waitForTimeout(2500); await p.screenshot({ path: OUT + `/walk-${W}-after.png` });
      await waitOrder(p, 60000); await report(p, 'walk', before, t0); await p.context().close();
    }
    if (ONLY.includes('early')) { // окно в 3D, кнопку жмут, пока сцена ещё грузится
      const p = await open(b);
      await p.evaluate(() => { shots = shots.filter(x => x.quality !== 'realistic'); openLiveWindow(); });
      await p.waitForSelector('#vCta:not([hidden])', { timeout: 20000 }).catch(() => {});
      const before = await live(p); const t0 = Date.now(); await p.click('#vCta');
      await waitOrder(p, 90000); await p.screenshot({ path: OUT + `/early-${W}-after.png` }); await report(p, 'early', before, t0); await p.context().close();
    }
    if (ONLY.includes('stale')) { // комната правлена, окно открывается в «Фото» (прежнее фото, T-66) → «Сделать реалистичнее» на плашке
      const p = await open(b);
      await edit(p); await p.evaluate(() => vwOpenVariant(cur)); await p.waitForTimeout(2500);
      const before = await live(p); await p.screenshot({ path: OUT + `/stale-${W}-before.png` });
      const has = await p.$('#shot .vstale [data-st="show"]');
      if (!has) { res.push({ scenario: 'stale', size: W + 'x' + H, before, verdict: 'SKIP: плашки нет' }); console.log('stale: плашки нет', JSON.stringify(before)); }
      else { const t0 = Date.now(); await has.click(); await p.waitForTimeout(2500); await p.screenshot({ path: OUT + `/stale-${W}-after.png` });
        await waitOrder(p, 90000); await report(p, 'stale', before, t0); }
      await p.context().close();
    }
    if (ONLY.includes('home')) { // кнопка на карточке главной (`homeStaleReal`): окно открывается и съёмка сразу
      const p = await open(b);
      await edit(p); const before = await live(p); const t0 = Date.now();
      await p.evaluate(() => homeStaleReal(cur)); await p.waitForTimeout(2500); await p.screenshot({ path: OUT + `/home-${W}-after.png` });
      await waitOrder(p, 90000); await report(p, 'home', before, t0); await p.context().close();
    }
  } catch (e) { console.log('FAIL probe: ' + (e && e.stack || e)); }
  finally { await b.close(); }
  fs.writeFileSync(OUT + `/result-${W}x${H}.json`, JSON.stringify(res, null, 1));
  console.log('ИТОГ ' + W + 'x' + H + ': ' + res.map(r => r.scenario + '=' + r.verdict).join(' · '));
})();
