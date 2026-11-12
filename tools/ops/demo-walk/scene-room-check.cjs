// СТОРОЖ «СТЕНЫ СЦЕНЫ = КОМНАТА ДАННЫХ» (T-20261112-108/2, заказ владельца f24c0cc7, TG 1284/1315): побывал в 3D спальни 1, открыл гостиную —
// кадры фото снимались прежней сценой спальни (окно на стене дивана). Путь покупателя: (1) 3D спальни 1 построена; (2) окно гостиной
// (set6, без входа в 3D — так открывают с главной); (3) кадры фото (`vwCaptureViews`, без выгрузки) — сцена в момент съёмки должна быть
// сценой ГОСТИНОЙ: размеры и проёмы `LIVE.room` = `curRoom()`; (4) правка: кадр несёт подпись комнаты (`cap.room`) = подписи комнаты
// заказа (`roomOf` варианта) — по ней сервер отказывает чужим кадрам (`draft_trial.py:views_room_mismatch`); (5) заглушка «Фото»/окошки
// (`vwPreOk`) не опираются на сцену другой комнаты. Кадры C1/C2 — в OUT для глаза: в гостиной окно на западной (левой от дивана) стене.
// Запись на прод нет: POST в /api/(render|events|draft|photo|lead|fav) отклоняется в браузере, выгрузка кадров подменена.
//   STAGE-прокси → BASE=http://127.0.0.1:8799/demo/ OUT=<папка/> [TAG=fix] [LANG_UI=en|ru] node scene-room-check.cjs 375x667|1280x800
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const [W, H] = (process.argv[2] || '375x667').split('x').map(Number), PHONE = W <= 700;
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'en', EN = LANG === 'en', TAG = (process.env.TAG ? process.env.TAG + '-' : '') + LANG + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));
/* global D, cur, allVariants, roomIdOf, roomOf, curRoom, vwOpenVariant, VW, vwMode, LIVE, vwCaptureViews, vwUploadViews, vwPreOk, roomSig, liveHere */
// подпись комнаты — та же, что `roomSig` страницы (на странице до правки её нет — считаем здесь)
const SIG = () => { window.__sig = R => !R ? '' : Math.round(+R.w || 0) + 'x' + Math.round(+R.d || 0) + '|' +
  (R.openings || []).map(o => [o.kind, o.wall, Math.round(+o.offset_cm || 0), Math.round(+o.width_cm || 0)].join(':')).sort().join(';'); };

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errs = [];
  try {
    const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: EN ? 'en-GB' : 'ru-RU' });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
    p.setDefaultTimeout(90000);
    await p.route(/\/api\/render\/frame/, r => r.request().method() === 'POST'
      ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'f'.repeat(64) }) }) : r.continue());
    await p.route(/\/api\/(render|events|draft|photo|lead|fav)(?!\/frame)/, r => r.request().method() === 'GET' ? r.continue() : r.abort());
    await p.addInitScript(() => { try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
    await p.goto(demoUrl((process.env.BASE || 'http://127.0.0.1:8799/demo/') + '?lang=' + LANG + '&quiz=0&live=force'), { waitUntil: 'load', timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
    await p.evaluate(SIG);
    const ix = await p.evaluate(() => { const vs = allVariants();
      return { bed: vs.findIndex(v => roomIdOf(v) === 'bedroom-1'), liv: vs.findIndex(v => v.id === 'set6'), ids: [...new Set(vs.map(roomIdOf))] }; });
    ok('в данных есть спальня 1 и гостиная set6', ix.bed >= 0 && ix.liv >= 0, ix);
    if (ix.bed < 0 || ix.liv < 0) throw new Error('нет вариантов');
    // (1) 3D спальни 1
    await p.evaluate(i => vwOpenVariant(i), ix.bed); await p.waitForTimeout(1500);
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready' && LIVE.room === curRoom(), null, { timeout: 240000 });
    const bed = await p.evaluate(() => window.__sig(LIVE.room));
    ok('3D спальни 1 построена', /window:north/.test(bed), bed);
    // (2) окно гостиной — без входа в 3D
    await p.evaluate(i => vwOpenVariant(i), ix.liv); await p.waitForTimeout(2500);
    const liv = await p.evaluate(() => ({ room: window.__sig(curRoom()), order: window.__sig(roomOf(allVariants()[cur])), mode: VW.mode,
      live: window.__sig(LIVE.room), pre: typeof vwPreOk === 'function' ? vwPreOk() : null, here: typeof liveHere === 'function' ? !!liveHere() : null }));
    ok('окно гостиной: комната данных — гостиная', /^439x325\|/.test(liv.room) && liv.room === liv.order, liv);
    if (liv.here !== null) ok('сцена спальни не считается сценой гостиной (liveHere)', liv.live === liv.room || liv.here === false, liv);
    await p.screenshot({ path: `${OUT}${TAG}-1-living.png` }).catch(() => {});
    // (3) кадры фото — какой сценой сняты
    const cap = await p.evaluate(async () => {
      const c = await vwCaptureViews({ noUpload: true });
      const at = { live: window.__sig(LIVE.room), room: window.__sig(curRoom()) };
      if (!c) return { none: true, ...at };
      const toUrl = bl => new Promise(r => { const f = new FileReader(); f.onload = () => r(f.result); f.readAsDataURL(bl); });
      const frames = await Promise.all(c.blobs.map(toUrl));
      let views = null; try { views = (await vwUploadViews(c)).views; } catch (e) { views = String(e); }
      return { ...at, cap: c.room === undefined ? null : c.room, views, frames, sig: typeof roomSig === 'function' ? roomSig(curRoom()) : null };
    });
    ok('кадры сняты', !cap.none, cap.none ? cap : undefined);
    ok('стены сцены при съёмке = комната данных (гостиная)', cap.live === cap.room, { live: cap.live, room: cap.room });
    if (cap.frames) cap.frames.forEach((u, k) => fs.writeFileSync(`${OUT}${TAG}-cap-C${k + 1}.jpg`, Buffer.from(u.split(',')[1], 'base64')));
    // (4) подпись кадра для сервера (правка): совпадает с комнатой заказа, у каждого кадра
    if (cap.sig !== null && !cap.none) {
      ok('подпись страницы = подпись сторожа', cap.sig === cap.room, { page: cap.sig, probe: cap.room });
      ok('кадр несёт комнату заказа (cap.room)', cap.cap === liv.order, { cap: cap.cap, order: liv.order });
      ok('выгруженные кадры подписаны комнатой', Array.isArray(cap.views) && cap.views.length >= 2 && cap.views.every(v => v.room === liv.order), cap.views);
    }
    // (5) снова 3D гостиной — сцена перестроена под гостиную
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 240000 }).catch(() => {});
    const back = await p.evaluate(() => ({ live: window.__sig(LIVE.room), room: window.__sig(curRoom()) }));
    ok('3D гостиной — стены гостиной', back.live === back.room, back);
  } catch (e) { R.push('FAIL упала ' + String(e).slice(0, 300)); }
  await b.close();
  if (errs.length) R.push('INFO pageerror ' + JSON.stringify(errs.slice(0, 3)));
  const bad = R.filter(s => s.startsWith('FAIL')).length;
  R.push((bad ? 'СТОРОЖ FAIL' : 'СТОРОЖ OK') + ' ' + TAG + ' (' + bad + ' FAIL)');
  fs.writeFileSync(`${OUT}${TAG}-scene-room.log`, R.join('\n') + '\n'); console.log(R.join('\n'));
  process.exit(bad ? 1 : 0);
})();
