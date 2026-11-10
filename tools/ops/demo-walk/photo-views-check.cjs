// T-20261109-29: «Сделать фото» — уходят ли кадры из браузера (`views`) в заказ фото. БЕСПЛАТНО: /api/render отвечает
// заглушкой-отказом (платная генерация не запускается), /api/render/frame — заглушкой с id = sha256 (на прод ничего не грузится).
//   node tools/ops/demo-walk/photo-views-check.cjs <WxH> <новая папка> [walk,early,stale,home,pre2,pre5,race]
// Сценарии: walk — окно в 3D, сцена готова; early — нажали до готовности 3D; stale — окно открылось в «Фото» (прежнее фото, T-66),
// кнопка на плашке «Вы изменили комнату»; home — кнопка карточки главной (`homeStaleReal`). Годно — заказ с `views` из 2 id (VIEWS).
// T-20261109-32 (кадры заранее): pre2/pre5 — правка → пауза 2/5 с → нажатие; race — вторая правка посреди съёмки первой. Годно — FAST:
// заказ ≤ 1,5 с от нажатия, кадры той расстановки, что при нажатии, ни одна не снималась дважды. По умолчанию — прежние четыре.
// flicker (T-20261109-32/2) — окно в 3D, правка, съёмка заранее: не мигает ли видимый холст (STEADY / FLICKER-…). Движок сцены
// этой копии вместо прода: `node tools/flat3d/build-scene-bundle.mjs --out <папка>` и ENGINE=<папка>.
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
  p.on('response', x => { if (x.status() === 429) p.log.push('error: 429 ' + x.url().slice(0, 120)); });
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  await p.route(/\/demo\/(index\.html)?(\?.*)?$/, r => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: fs.readFileSync(PAGE, 'utf8') }));
  // ENGINE=<папка сборки `build-scene-bundle.mjs --out`> — движок сцены этой копии вместо прода (правка `lib/viewer3d`)
  if (process.env.ENGINE) await p.route(/\/demo\/lib\/(scene\.json|(scene|basket)\.[0-9a-f]+\.js)(\?.*)?$/, r => {
    const f = path.join(process.env.ENGINE, path.basename(new URL(r.request().url()).pathname));
    if (!fs.existsSync(f)) return r.continue();
    return r.fulfill({ status: 200, contentType: f.endsWith('.json') ? 'application/json' : 'text/javascript', body: fs.readFileSync(f) });
  });
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
  const r = { scenario: name, size: W + 'x' + H, before, after, order: b ? { views: b.views, src_id: b.src_id, sheet: b.sheet, sec: +((b.t - t0) / 1000).toFixed(1), ms: b.t - t0 } : null,
    lastCapture: await p.evaluate(() => VW.lastCapture), frames: p.frames.length, console: p.log.filter(l => /кадр|error|Error/.test(l)).slice(-8) };
  r.verdict = b && Array.isArray(b.views) && b.views.length === 2 ? 'VIEWS' : (b ? 'NO-VIEWS' : 'NO-ORDER');
  res.push(r); console.log(JSON.stringify(r));
}
// правка без окна: другой пол — расстановка «изменена», фото комнаты становится прежним (как у покупателя, вернувшегося к комнате)
const edit = (p, k = 1) => p.evaluate(k => { const g = devGroups().find(x => x.kind === 'flooring'); if (g) devSet(g.id, g.variants[k % g.variants.length].id); return !!g; }, k);
// T-20261109-32 — кадры заранее: «правка → пауза → нажатие». Годно: заказ ≤ 1,5 с от нажатия, кадры заказа — той расстановки, что
// при нажатии (ключ кадров начинается с curStateId), ни одна расстановка не снималась дважды (VPF.log: pre/press по ключу)
async function prefetch(b, name, pauseMs, race) {
  const p = await open(b);
  await p.evaluate(() => { shots = shots.filter(x => x.quality !== 'realistic'); openLiveWindow(); });
  await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
  await p.waitForFunction(() => VPF.cap && !VPF.run, null, { timeout: 120000 }).catch(() => {});   // кадры открытого окна сняты
  await p.waitForTimeout(500);
  await edit(p, 1);
  let staleKey = null;
  if (race) {   // вторая правка посреди съёмки первой: заказ должен уйти с кадрами второй
    await p.waitForFunction(() => !!VPF.run, null, { timeout: 30000 }).catch(() => {});
    staleKey = await p.evaluate(() => VPF.run && VPF.run.key.slice(0, 14));
    await edit(p, 2);
  }
  // pauseMs=0 — ждём, пока кадры этой расстановки сняты и загружены: чистая цена нажатия, без скорости рендера машины проверки
  if (pauseMs) await p.waitForTimeout(pauseMs);
  else await p.waitForFunction(() => VPF.cap && VPF.cap.views && VPF.cap.key === vwPreKey() && !VPF.run, null, { timeout: 120000 }).catch(() => {});
  const before = await live(p);
  const pre = await p.evaluate(() => ({ cap: !!VPF.cap, run: !!VPF.run, key: curStateId().slice(0, 14) }));
  await p.screenshot({ path: OUT + `/${name}-${W}-before.png` });
  const t0 = Date.now(); await p.click('#vCta');
  await waitOrder(p, 90000);
  await p.screenshot({ path: OUT + `/${name}-${W}-after.png` });
  await report(p, name, before, t0);
  const r = res[res.length - 1];
  const st = await p.evaluate(() => ({ now: curStateId().slice(0, 14), last: VW.lastCapture, log: VPF.log, captures: VPF.captures,
    capViews: VPF.cap && VPF.cap.views ? VPF.cap.views.map(v => v.id) : null }));
  const shot = {};
  for (const e of st.log) if (e.kind === 'pre' || e.kind === 'press') shot[e.key] = (shot[e.key] || 0) + 1;
  const orderIds = r.order && r.order.views ? r.order.views.map(v => v.id) : null;
  // нажатие → заказ считаем от входа в обработчик кнопки (`job.t0`): щелчок Playwright сам ждёт «устойчивых» кадров анимации, а
  // программный рендер на 375×667 ×2 даёт их раз в сотни мс — это цена проверочной машины, не страницы. clickMs — для сравнения
  const ob = p.bodies.filter(x => x.quality === 'realistic').pop();
  const pressMs = ob && st.last && st.last.t0 ? ob.t - st.last.t0 : (r.order ? r.order.ms : null);
  if (r.order) { r.order.clickMs = r.order.ms; r.order.ms = pressMs; }
  r.prefetch = { pauseMs, pressMs, clickMs: r.order ? r.order.clickMs : null, pre, how: st.last && st.last.pre, staleKey, stateAtPress: pre.key,
    capturedTwice: Object.entries(shot).filter(([, n]) => n > 1).map(([k]) => k), captures: st.captures,
    sameState: !!(st.last && st.last.key && st.last.key.startsWith(pre.key)),
    viewsMatchCache: !!(orderIds && st.capViews && orderIds.join() === st.capViews.join()), log: st.log.slice(-8) };
  // race: нажатие ждёт съёмку новой расстановки (её не было) — годность по кадрам, не по времени: NEWSTATE
  const slow = !race && r.order && r.order.ms > 1500;
  r.verdict = r.verdict === 'VIEWS' && !slow && r.prefetch.sameState && !r.prefetch.capturedTwice.length
    ? (race ? 'NEWSTATE' : 'FAST') : r.verdict + (slow ? '-SLOW' : '') + (r.prefetch.sameState ? '' : '-WRONGSTATE')
      + (r.prefetch.capturedTwice.length ? '-TWICE' : '');
  console.log(JSON.stringify({ scenario: name, prefetch: r.prefetch, verdict: r.verdict }));
  await p.context().close();
}

// T-20261109-32/2 — МИГАНИЕ ОКНА 3D ПРИ СЪЁМКЕ ЗАРАНЕЕ: человек смотрит на 3D, через 1,5 с после правки страница снимает кадры C1/C2
// на том же холсте. Сцена неподвижна: каждый снимок видимой части холста (~раз в 100 мс) сверяем с итоговым (через 1,5 с после
// съёмки) и с предыдущим — доля пикселей с отличием > 24 по каналу и средняя яркость; на каждом кадре анимации в странице пишем
// canvas.width/height и getBoundingClientRect. Годно — STEADY: во время съёмки ни один снимок не отличается от итога больше 2 %,
// размер буфера и место холста на экране на кадрах анимации не менялись.
async function flicker(b) {
  const sharp = require(NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith('sharp@')) + '/node_modules/sharp');
  const p = await open(b);
  await p.evaluate(() => { shots = shots.filter(x => x.quality !== 'realistic'); openLiveWindow(); });
  await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
  await p.waitForFunction(() => VPF.cap && !VPF.run, null, { timeout: 120000 }).catch(() => {});
  await p.waitForTimeout(800);
  const clip = await p.evaluate(([W, H]) => { const r = LIVE.canvas.getBoundingClientRect();
    const x = Math.max(0, r.x), y = Math.max(0, r.y);
    return { x, y, width: Math.min(W, r.right) - x, height: Math.min(H, r.bottom) - y }; }, [W, H]);
  await p.evaluate(() => { window.__fl = []; const c = LIVE.canvas;
    const f = () => { const r = c.getBoundingClientRect();
      __fl.push([Math.round(performance.now()), c.width, c.height, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height), VPF.run ? 1 : 0]);
      if (__fl.length < 20000) requestAnimationFrame(f); };
    requestAnimationFrame(f); });
  await edit(p, 1);
  const t0 = Date.now(), frames = [];
  let started = null, endAt = 0;   // null, не 0: на телефоне съёмка видна уже на первом шаге (t=0)
  while (Date.now() - t0 < 60000) {
    const ts = Date.now();
    const run = await p.evaluate(() => !!VPF.run);
    frames.push({ t: ts - t0, run, buf: await p.screenshot({ clip, type: 'png' }) });
    if (run && started === null) started = ts - t0;
    if (started !== null && !run && !endAt) endAt = Date.now();
    if (endAt && Date.now() - endAt > 1500) break;
    await p.waitForTimeout(Math.max(0, 100 - (Date.now() - ts)));
  }
  const raw = async buf => (await sharp(buf).removeAlpha().raw().toBuffer({ resolveWithObject: true })).data;
  const fin = await raw(frames[frames.length - 1].buf);
  const diff = (a, z) => { let n = 0; for (let i = 0; i < a.length; i += 3) if (Math.max(Math.abs(a[i] - z[i]), Math.abs(a[i + 1] - z[i + 1]), Math.abs(a[i + 2] - z[i + 2])) > 24) n++; return n / (a.length / 3); };
  const lum = a => { let s = 0; for (let i = 0; i < a.length; i += 3) s += 0.2126 * a[i] + 0.7152 * a[i + 1] + 0.0722 * a[i + 2]; return s / (a.length / 3); };
  let prev = null;
  for (const f of frames) { const a = await raw(f.buf); f.dFinal = +diff(a, fin).toFixed(4); f.dPrev = prev ? +diff(a, prev).toFixed(4) : 0; f.lum = +lum(a).toFixed(1); prev = a; }
  const fl = await p.evaluate(() => __fl);
  // кадр C1 для нейросети — сверить, что переделка отрисовки его не изменила (движок прод ↔ этой копии)
  const c1 = await p.evaluate(async () => { const bl = VPF.cap && VPF.cap.blobs && VPF.cap.blobs[0]; if (!bl) return null;
    const a = new Uint8Array(await bl.arrayBuffer()); let s = ''; for (let i = 0; i < a.length; i += 8192) s += String.fromCharCode.apply(null, a.subarray(i, i + 8192)); return btoa(s); });
  if (c1) fs.writeFileSync(OUT + `/flicker-${W}-c1-frame.jpg`, Buffer.from(c1, 'base64'));
  const sizes = {}, rects = {};
  for (const [, w, h, x, y, rw, rh] of fl) { sizes[w + 'x' + h] = (sizes[w + 'x' + h] || 0) + 1; rects[[x, y, rw, rh].join(',')] = (rects[[x, y, rw, rh].join(',')] || 0) + 1; }
  let gap = 0; for (let i = 1; i < fl.length; i++) gap = Math.max(gap, fl[i][0] - fl[i - 1][0]);
  const during = started === null ? [] : frames.filter(f => f.t >= started && (!endAt || f.t <= endAt - t0));
  const worst = during.reduce((m, f) => (f.dFinal > (m ? m.dFinal : -1) ? f : m), null);
  const name = `flicker-${W}`;
  const save = (f, tag) => f && fs.writeFileSync(OUT + `/${name}-${tag}-t${f.t}.png`, f.buf);
  save(frames[0], '0-edit'); save(during[0], '1-start'); save(worst, '2-worst'); save(frames[frames.length - 1], '3-final');
  const r = { scenario: 'flicker', size: W + 'x' + H, engine: process.env.ENGINE ? 'local' : 'prod', clip, captureStartMs: started,
    captureEndMs: endAt ? endAt - t0 : null, shots: frames.length, shotsDuring: during.length,
    maxDiffDuring: worst ? worst.dFinal : null, worstAt: worst ? worst.t : null,
    lumRange: [Math.min(...frames.map(f => f.lum)), Math.max(...frames.map(f => f.lum))],
    rafFrames: fl.length, rafDuringRun: fl.filter(x => x[7]).length, rafMaxGapMs: gap, canvasSizes: sizes, canvasRects: rects,
    series: frames.map(f => ({ t: f.t, run: f.run ? 1 : 0, dFinal: f.dFinal, dPrev: f.dPrev, lum: f.lum })),
    console: p.log.filter(l => /error|Error/.test(l)).slice(-8) };
  r.verdict = (r.maxDiffDuring !== null && r.maxDiffDuring <= 0.02 && Object.keys(sizes).length === 1 && Object.keys(rects).length === 1)
    ? 'STEADY' : 'FLICKER' + (Object.keys(sizes).length > 1 ? '-SIZE' : '') + (Object.keys(rects).length > 1 ? '-RECT' : '')
      + (r.maxDiffDuring > 0.02 ? '-PIXELS' : '') + (r.maxDiffDuring === null ? '-NOCAPTURE' : '');
  res.push(r);
  console.log(JSON.stringify(Object.assign({}, r, { series: undefined })));
  await p.context().close();
}

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
    if (ONLY.includes('stale')) { // комната правлена, окно открывается в «Фото» (прежнее фото, T-66) → «Сделать фото» на плашке
      const p = await open(b);
      await edit(p); await p.evaluate(() => vwOpenVariant(cur)); await p.waitForTimeout(2500);
      const before = await live(p); await p.screenshot({ path: OUT + `/stale-${W}-before.png` });
      const has = await p.$('#shot .vstale [data-st="show"]');
      if (!has) { res.push({ scenario: 'stale', size: W + 'x' + H, before, verdict: 'SKIP: плашки нет' }); console.log('stale: плашки нет', JSON.stringify(before)); }
      else { const t0 = Date.now(); await has.click(); await p.waitForTimeout(2500); await p.screenshot({ path: OUT + `/stale-${W}-after.png` });
        await waitOrder(p, 90000); await report(p, 'stale', before, t0); }
      await p.context().close();
    }
    if (ONLY.includes('flicker')) await flicker(b);                         // 3D на экране, съёмка заранее — не мигает ли окно
    if (ONLY.includes('ready')) await prefetch(b, 'ready', 0, false);      // правка → кадры готовы → нажатие
    if (ONLY.includes('pre2')) await prefetch(b, 'pre2', 2000, false);     // задание: правка → 2 с → нажатие
    if (ONLY.includes('pre5')) await prefetch(b, 'pre5', 5000, false);     // кадры успели сняться и загрузиться
    if (ONLY.includes('race')) await prefetch(b, 'race', 2000, true);      // правка посреди съёмки → кадры новой расстановки
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
