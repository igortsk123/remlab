// T-20261109-34: «Сделать реалистичнее» в ТУРЕ ПРОБЫ (`/try/<id>/tour/`) — фото только у гостиной/спальни с доверием к размерам
// (`apartment_rooms[].photo_ok`, `trial_bundle.photo_ok`). БЕСПЛАТНО: ручка тура `/api/trial/<id>/photo` и опрос `/api/job` —
// заглушки (платная генерация не запускается), `/api/render/frame` — заглушка с id = sha256 (на прод ничего не грузится).
//   node tools/ops/demo-walk/trial-photo-check.cjs <WxH> <новая папка> [ru|en] [living,bedroom,untrusted]
// Страница — index.html этой копии с НАСТОЯЩЕЙ обвязкой тура (`lib/trial/tour-page.ts:injectTour`, собрана esbuild), данные —
// фикстура `tests/fixtures/trial-tour-furnished.json` (+ trial и photo_ok), движок/меши/картинки — прод `/demo/` (`?live=force`).
// Годно: living/bedroom — PHOTO: заказ ушёл в ручку тура с `views` из 2 id, в `/api/render` — ни одного заказа, фото-заглушка
// легла в ленту; untrusted — NOTE: кнопки нет, тихая строка «Фото — после уточнения размеров» видна, заказов и съёмки заранее нет.
// Плюс песочница: прямой POST страницы в `/api/render` получает 403 от обвязки тура (до сети не доходит).
// REAL_FRAMES=1 — кадры уходят в бесплатную загрузку прода (`/api/render/frame`), тело заказа — `order-<комната>-….json`: по нему
// платная проба шлёт заказ в копию сервиса кадров (сама проба по-прежнему ничего не заказывает).
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const esbuild = require(pick('esbuild'));
const PAGE = process.env.PAGE || path.join(ROOT, 'tools/scout/flat215-demo/index.html');
const ORIGIN = 'https://remont-lab.online';
const ID = 'T34probeT34probeT34pr0';              // 22 знака — формат TOKEN_RE
const TOUR = `/try/${ID}/tour/`;
const [W, H] = (process.argv[2] || '1280x900').split('x').map(Number);
const OUT = process.argv[3]; fs.mkdirSync(OUT, { recursive: true });
const LANG = process.argv[4] || 'ru';
const ONLY = (process.argv[5] || 'living,bedroom,untrusted,refused').split(',');
const PHONE = W <= 700;
const res = [];

// обвязка тура — из исходника (тот же код, что отдаёт `/try/<id>/tour/`)
function loadInject() {
  const out = esbuild.buildSync({ entryPoints: [path.join(ROOT, 'lib/trial/tour-page.ts')], bundle: true, platform: 'node', format: 'cjs',
    write: false, tsconfig: path.join(ROOT, 'tsconfig.json'), logLevel: 'error' });
  const m = { exports: {} };
  new Function('module', 'exports', 'require', out.outputFiles[0].text)(m, m.exports, require);
  return m.exports;
}
const TP = loadInject();
const FIX = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/fixtures/trial-tour-furnished.json'), 'utf8'));
function data(ok) {
  const d = JSON.parse(JSON.stringify(FIX));
  d.trial = Object.assign({}, d.trial, { job_id: ID, scale: ok.scale || 'verified' });
  for (const r of d.apartment_rooms) r.photo_ok = !!ok[r.id];
  return d;
}

async function open(b, d) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE,
    locale: LANG === 'en' ? 'en-GB' : 'ru-RU' });
  const p = await ctx.newPage();
  p.log = []; p.orders = []; p.renders = []; p.frames = []; p.polls = 0;
  p.on('console', m => { const t = m.text(); if (m.type() === 'warning' || m.type() === 'error' || /кадр/.test(t)) p.log.push(m.type() + ': ' + t.slice(0, 300)); });
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  const html = TP.injectTour(fs.readFileSync(PAGE, 'utf8'), ID, 0);
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith(TOUR), async r => {
    const rel = new URL(r.request().url()).pathname.slice(TOUR.length);
    if (rel === '' || rel === 'index.html') return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    if (rel === 'demo-data.json') return r.fulfill({ status: 200, contentType: 'application/json', headers: { etag: '"v1"' }, body: JSON.stringify(d) });
    if (rel === 'version.json') return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: 0, bundle: 1, rebuild: null, rebuildError: null }) });
    const f = await r.fetch({ url: ORIGIN + '/demo/' + rel + new URL(r.request().url()).search });   // общие файлы витрины
    return r.fulfill({ response: f });
  });
  if (process.env.ENGINE) await p.route(/\/lib\/(scene\.json|(scene|basket)\.[0-9a-f]+\.js)(\?.*)?$/, r => {
    const f = path.join(process.env.ENGINE, path.basename(new URL(r.request().url()).pathname));
    if (!fs.existsSync(f)) return r.continue();
    return r.fulfill({ status: 200, contentType: f.endsWith('.json') ? 'application/json' : 'text/javascript', body: fs.readFileSync(f) });
  });
  await p.route(/\/api\/events/, r => r.fulfill({ status: 204, body: '' }));
  await p.route(/\/probe34\/c1\.jpg/, r => r.fulfill({ status: 200, contentType: 'image/jpeg', body: p.frames[0] ? p.frames[0].buf : Buffer.alloc(0) }));
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith('/api/'), r => {
    const u = new URL(r.request().url()), m = r.request().method();
    const json = (o, s = 200) => r.fulfill({ status: s, contentType: 'application/json', body: JSON.stringify(o) });
    if (u.pathname === '/api/render/frame' && process.env.REAL_FRAMES) {   // для платной пробы: кадр — в бесплатную загрузку прода
      return r.fetch().then(async f => { const j = await f.json(); p.frames.push({ id: j.id, bytes: j.bytes, buf: r.request().postDataBuffer() });
        return json(j, f.status()); });
    }
    if (u.pathname === '/api/render/frame') {
      const buf = r.request().postDataBuffer() || Buffer.alloc(0), id = crypto.createHash('sha256').update(buf).digest('hex');
      p.frames.push({ id, bytes: buf.length, buf });
      return json({ id, bytes: buf.length });
    }
    if (u.pathname === `/api/trial/${ID}/photo` && m === 'POST') {
      let j = {}; try { j = JSON.parse(r.request().postData() || '{}'); } catch (e) {}
      fs.writeFileSync(OUT + `/order-${j.room_id}-${LANG}-${W}.json`, r.request().postData() || '');   // тело заказа — как есть
      p.orders.push({ t: Date.now(), room_id: j.room_id, views: j.views || null, quality: j.quality, room: j.room && { w: j.room.w, d: j.room.d },
        items: (j.items || []).length, keys: Object.keys(j).sort() });
      if (p.refuse) return json({ ok: false, code: p.refuse, error: 'фото товаров на листе 3 из 5 — платный вызов не делаю' }, 422);
      return json({ ok: true, job: 'probe34' });
    }
    if (u.pathname === '/api/job') {   // ход задания: «в очереди» → готово (фото-заглушка = кадр C1 из браузера)
      if (++p.polls < 2) return json({ status: 'running', queue: 1, eta: 20 });
      return json({ shots: [{ camera: 'C1', url: '/probe34/c1.jpg' }], url: '/probe34/c1.jpg', model: 'probe', diag: {} });
    }
    if (u.pathname.startsWith('/api/render')) p.renders.push({ path: u.pathname, method: m });
    return json({ ok: false, code: 'probe', error: 'проба T-34' }, 403);
  });
  await p.goto(ORIGIN + TOUR + `?quiz=0&live=force&lang=${LANG}`, { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!D.trial&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForTimeout(1500);
  return p;
}
const cta = p => p.evaluate(() => { const c = document.getElementById('vCta'), n = document.getElementById('vCtaNote');
  const vis = e => !!(e && !e.hidden && e.offsetParent !== null && e.getBoundingClientRect().height > 0);
  return { cta: vis(c), ctaText: c ? c.textContent.trim() : null, note: vis(n), noteText: n ? n.textContent.trim() : null,
    room: roomIdOf(allVariants()[cur] || {}), here: trPhotoHere(), mode: VW.mode, state: LIVE.state || '', err: VJ.err || null }; });
async function toRoom(p, room) {
  await p.evaluate(room => { const i = allVariants().findIndex(v => roomIdOf(v) === room && (v.items || []).length);
    if (i < 0) throw new Error('нет варианта ' + room);
    shots = shots.filter(x => x.quality !== 'realistic'); vwOpenVariant(i); }, room);
  await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
  await p.waitForTimeout(2500);
}
// песочница тура: прямой заказ в `/api/render` отсекает обвязка (403 до сети)
const sandbox = p => p.evaluate(async () => { const r = await fetch('/api/render', { method: 'POST', body: '{}' }); return r.status; });

async function trusted(b, name, room) {
  const p = await open(b, data({ living: true, 'bedroom-2': true }));
  await toRoom(p, room);
  const before = await cta(p);
  await p.screenshot({ path: OUT + `/${name}-${LANG}-${W}-before.png` });
  const t0 = Date.now();
  if (before.cta) await p.click('#vCta');
  for (let t = 0; t < 120 && !p.orders.length; t++) await p.waitForTimeout(500);
  for (let t = 0; t < 30; t++) { if (await p.evaluate(() => shots.some(x => x.quality === 'realistic'))) break; await p.waitForTimeout(500); }
  await p.waitForTimeout(1500);
  await p.screenshot({ path: OUT + `/${name}-${LANG}-${W}-after.png` });
  const o = p.orders[0] || null, got = await p.evaluate(() => shots.filter(x => x.quality === 'realistic').length);
  const r = { scenario: name, lang: LANG, size: W + 'x' + H, before, order: o && Object.assign({}, o, { sec: +((o.t - t0) / 1000).toFixed(1) }),
    orders: p.orders.length, renders: p.renders, frames: p.frames.length, realisticShots: got, sandboxRender: await sandbox(p),
    after: await cta(p), console: p.log.filter(l => /error|Error/.test(l)).slice(-6) };
  const ok = before.cta && o && Array.isArray(o.views) && o.views.length === 2 && o.views.every(v => /^[0-9a-f]{64}$/.test(v.id))
    && o.room_id === room && o.quality === 'realistic' && !p.renders.length && got > 0 && r.sandboxRender === 403;
  r.verdict = ok ? 'PHOTO' : 'FAIL' + (before.cta ? '' : '-NOBUTTON') + (o ? '' : '-NOORDER') + (o && (o.views || []).length !== 2 ? '-NOVIEWS' : '')
    + (p.renders.length ? '-RENDER' : '') + (got ? '' : '-NOSHOT') + (r.sandboxRender === 403 ? '' : '-SANDBOX');
  res.push(r); console.log(JSON.stringify(r));
  await p.context().close();
}

async function untrusted(b) {
  // та же квартира, масштаб «по площади»: photo_ok=false у всех комнат (сборщик так и отдаёт, `trial_bundle.photo_ok`)
  const p = await open(b, data({ scale: 'area' }));
  const out = [];
  for (const room of ['living', 'bedroom-2']) {
    await toRoom(p, room);
    await p.waitForTimeout(3000);   // съёмка заранее у «без доверия» не должна начаться (vwPreOk)
    const s = await cta(p);
    await p.screenshot({ path: OUT + `/untrusted-${room}-${LANG}-${W}.png` });
    out.push(s);
  }
  // и программный вызов «Сделать реалистичнее» мимо кнопки — отказ без заказа
  const forced = await p.evaluate(() => vwRealistic());
  await p.waitForTimeout(1500);
  const want = LANG === 'en' ? /Photo — after the sizes are confirmed/ : /Фото — после уточнения размеров/;
  const r = { scenario: 'untrusted', lang: LANG, size: W + 'x' + H, rooms: out, forced, orders: p.orders.length, renders: p.renders,
    frames: p.frames.length, sandboxRender: await sandbox(p), console: p.log.filter(l => /error|Error/.test(l)).slice(-6) };
  const ok = out.every(s => !s.cta && s.note && want.test(s.noteText || '')) && !p.orders.length && !p.renders.length && !p.frames.length && r.sandboxRender === 403;
  r.verdict = ok ? 'NOTE' : 'FAIL' + (out.some(s => s.cta) ? '-BUTTON' : '') + (out.some(s => !s.note) ? '-NONOTE' : '')
    + (p.orders.length ? '-ORDER' : '') + (p.frames.length ? '-PREFETCH' : '') + (p.renders.length ? '-RENDER' : '');
  res.push(r); console.log(JSON.stringify(r));
  await p.context().close();
}

// отказ сервиса кадров до оплаты (`no_product_sheet`, текст сервера — русский): человек видит фразу тура на языке страницы, не текст сервера
async function refused(b) {
  const p = await open(b, data({ living: true, 'bedroom-2': true }));
  p.refuse = 'no_product_sheet';
  await toRoom(p, 'bedroom-2');
  await p.click('#vCta');
  for (let t = 0; t < 120 && !p.orders.length; t++) await p.waitForTimeout(500);
  await p.waitForTimeout(2000);
  await p.screenshot({ path: OUT + `/refused-${LANG}-${W}.png` });
  const e = await p.evaluate(() => { const x = document.getElementById('vCtaErr'); return { err: x ? x.textContent.trim() : null, vj: VJ.err || null }; });
  const want = LANG === 'en' ? /not enough product pictures/ : /не хватает снимков товаров/;
  const r = { scenario: 'refused', lang: LANG, size: W + 'x' + H, orders: p.orders.length, shown: e, renders: p.renders };
  r.verdict = p.orders.length === 1 && want.test(e.err || e.vj || '') && !/платный вызов/.test(e.err || '') ? 'TEXT' : 'FAIL';
  res.push(r); console.log(JSON.stringify(r));
  await p.context().close();
}

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    if (ONLY.includes('living')) await trusted(b, 'living', 'living');
    if (ONLY.includes('bedroom')) await trusted(b, 'bedroom', 'bedroom-2');
    if (ONLY.includes('untrusted')) await untrusted(b);
    if (ONLY.includes('refused')) await refused(b);
  } catch (e) { console.log('FAIL probe: ' + (e && e.stack || e)); }
  finally { await b.close(); }
  fs.writeFileSync(OUT + `/result-${LANG}-${W}x${H}.json`, JSON.stringify(res, null, 1));
  console.log('ИТОГ ' + LANG + ' ' + W + 'x' + H + ': ' + res.map(r => r.scenario + '=' + r.verdict).join(' · '));
})();
