// ЗАМЕР ЗАГРУЗКИ СТРАНИЦЫ ДЕМО/ТУРА (T-20261112-83, в репо — T-20261112-90): «телефон» 375×667, медленная сеть, процессор ×4,
// холодный кэш. Только чтение страниц. A/B двух папок сборки по N прогонов с медианой и p75 — `page-ab.sh`.
//   URL=<адрес> NETW=slow4g|2mbit CPU=4 TAG=<метка> OUT=<папка/> [NO3D=1] node tools/ops/demo-walk/page-measure.cjs
// Метки: html — пришёл документ; fcp — первый рисунок; data — данные витрины разобраны (D и FLAT есть); lcp — крупнейший кадр;
// ui — главный экран (или опрос) виден; 3d — после нажатия «3D» сцена готова (LIVE.state==='ready').
const fs = require('fs'), path = require('path');
const ROOT = process.cwd();   // корень репо (как у остальных обходов demo-walk)
const pw = require(ROOT + '/node_modules/.pnpm/' + fs.readdirSync(ROOT + '/node_modules/.pnpm').find(d => d.startsWith('playwright-core@')) + '/node_modules/playwright-core');
const URL_ = process.env.URL, TAG = process.env.TAG || 'run', OUT = process.env.OUT || './', CPU = +(process.env.CPU || 4);
const NP = { slow4g: { latency: 150, downloadThroughput: 1638.4 * 1024 / 8, uploadThroughput: 675 * 1024 / 8 },
  '2mbit': { latency: 100, downloadThroughput: 2000 * 1000 / 8, uploadThroughput: 1000 * 1000 / 8 } }[process.env.NETW || 'slow4g'];
const INIT = () => {
  window.__lcp = 0; window.__lt = [];
  try { new PerformanceObserver(l => l.getEntries().forEach(e => { window.__lcp = Math.round(e.startTime); })).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
  try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__lt.push([Math.round(e.startTime), Math.round(e.duration)]))).observe({ type: 'longtask', buffered: true }); } catch (e) {}
};
(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const ctx = await b.newContext({ viewport: { width: 375, height: 667 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'ru-RU' });
  await ctx.addInitScript(INIT);
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
  const cdp = await ctx.newCDPSession(p);
  await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Network.emulateNetworkConditions', { offline: false, ...NP });
  if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
  const REQ = new Map(); let t0 = 0;
  cdp.on('Network.requestWillBeSent', e => REQ.set(e.requestId, { url: e.request.url.replace(/^https?:\/\/[^/]+/, '').split('?')[0].slice(0, 80), t: Date.now() - t0, kb: 0, end: null, type: e.type }));
  cdp.on('Network.responseReceived', e => { const r = REQ.get(e.requestId); if (r) { r.st = e.response.status; r.enc = (e.response.headers['content-encoding'] || e.response.headers['Content-Encoding'] || ''); } });
  cdp.on('Network.loadingFinished', e => { const r = REQ.get(e.requestId); if (r) { r.kb = Math.round(e.encodedDataLength / 1024); r.end = Date.now() - t0; } });
  const M = {};
  t0 = Date.now();
  await p.goto(URL_, { waitUntil: 'commit', timeout: 180000 });
  M.html = Date.now() - t0;
  await p.waitForFunction(() => performance.getEntriesByName('first-contentful-paint').length > 0, null, { timeout: 180000 }).catch(() => {});
  M.fcp = await p.evaluate(() => Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || -1));
  // у тура карточки квартиры (FLAT) нет — ждём только данные витрины
  await p.waitForFunction("typeof D!=='undefined'&&!!D", null, { timeout: 180000 }).catch(e => errs.push('D: ' + String(e).slice(0, 80)));
  M.data = await p.evaluate(() => Math.round(performance.now()));
  // первый экран = первая видимая картинка шириной больше половины экрана догружена (главное фото комнаты)
  await p.waitForFunction(() => [...document.images].some(i => i.complete && i.naturalWidth > 0 && i.getBoundingClientRect().width > 180
    && i.getBoundingClientRect().top < innerHeight && i.offsetParent !== null), null, { timeout: 120000, polling: 100 }).catch(e => errs.push('ui: ' + String(e).slice(0, 80)));
  M.ui = await p.evaluate(() => Math.round(performance.now()));
  const nav = await p.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; return { respEnd: Math.round(n.responseEnd), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd) }; });
  Object.assign(M, nav);
  await p.screenshot({ path: path.join(OUT, `${TAG}-1-first.png`) });
  const ltBefore = await p.evaluate(() => window.__lt.slice());
  M.longtasksMs = ltBefore.reduce((s, x) => s + x[1], 0); M.maxLongtask = Math.max(0, ...ltBefore.map(x => x[1]));
  await p.waitForTimeout(1500);
  M.lcp = await p.evaluate(() => window.__lcp);
  const firstReq = [...REQ.values()].filter(r => r.end != null && r.end <= M.ui + 200);
  M.kbToUi = firstReq.reduce((s, r) => s + r.kb, 0);
  // 3D: открыть первый вариант и нажать «3D»
  if (process.env.NO3D !== '1') {
    try {
      // 3D рисует программный видеоконтекст DEV: замедление процессора снимаем, иначе сцена считается минутами (мерим сеть, не GPU)
      if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
      const c0 = Date.now();
      await p.evaluate(() => vwOpenVariant(0));
      await p.waitForFunction(() => typeof VW !== 'undefined' && VW && document.querySelector('#shot [data-vm="walk"]'), null, { timeout: 60000 });
      if (await p.evaluate(() => VW.mode !== 'walk')) await p.locator('#shot [data-vm="walk"]').click({ timeout: 30000 });
      await p.waitForFunction(() => VW.mode === 'walk' && LIVE.state === 'ready', null, { timeout: 120000, polling: 200 })
        .catch(async e => { M.liveState = await p.evaluate(() => typeof LIVE !== 'undefined' ? [VW.mode, LIVE.state, LIVE.ok] : null); throw e; });
      M.open3d = Date.now() - c0; M.t3dFromStart = Date.now() - t0;
      await p.waitForTimeout(500); await p.screenshot({ path: path.join(OUT, `${TAG}-2-3d.png`) });
    } catch (e) { errs.push('3d: ' + String(e).slice(0, 160)); }
  }
  const all = [...REQ.values()];
  const top = all.filter(r => r.kb >= 20).sort((a, b) => b.kb - a.kb).slice(0, 14).map(r => `${r.kb}КБ ${r.enc || '-'} ${r.t}→${r.end} ${r.url}`);
  const res = { tag: TAG, url: URL_.replace(/k=[^&#]+/, 'k=…'), netw: process.env.NETW || 'slow4g', cpu: CPU, ...M, totalKb: all.reduce((s, r) => s + r.kb, 0), reqs: all.length, errs, top };
  console.log(JSON.stringify(res, null, 1));
  fs.writeFileSync(path.join(OUT, `${TAG}.json`), JSON.stringify({ ...res, all }, null, 1));
  await b.close();
})().catch(e => { console.error(e); process.exit(2); });
