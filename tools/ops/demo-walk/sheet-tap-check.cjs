// ТАП ПО ПОЛУ НЕ ПОДНИМАЕТ ШТОРКУ (T-20261112-97/3, владелец TG 1175). Телефон, «3D»: шторка на средней →
// (1) тап по полу далеко от шторки — шторка на месте; (2) тап по полу у самого верха шторки (Chrome на телефоне «доводит» касание до
// ближней нажимаемой части — шапки шторки) — шторка на месте; (3) тап по вещи — вещь выбрана, шторка на месте (как было, T-37);
// (4) тап по шапке шторки — шторка открывается до верха (как было). Бесплатно, на сервер ничего не пишется.
//   STAGE-прокси (`stage-proxy.mjs`) → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> LANG_UI=ru|en node sheet-tap-check.cjs [375x667]
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const [W, H] = (process.argv[2] || '375x667').split('x').map(Number);
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'ru', TAG = (process.env.TAG ? process.env.TAG + '-' : '') + LANG + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));

// `who` — кто двигал шторку с прошлого замера (для разбора провала)
// `ev` — что получил холст (нажатия, `walkTap` и его ответ): тап, который до сцены не дошёл, виден сразу
const ST = `(()=>{const sd=document.getElementById('vside'); return {pos:sd.dataset.pos, vis:Math.round(VW.sheetVis||0), sel:VW.sel, pose:LIVE.scene.pose(),
  who:(window.__sl||[]).splice(0), ev:(window.__ev||[]).splice(0)};})()`;
// точка пола (сверху холст, под ней пол, не вещь) в полосе [y0, y1] экрана, середина ширины (у краёв 20 % тап — поворот)
/* global LIVE */
const FLOOR = ([y0, y1]) => { const c = LIVE.canvas.getBoundingClientRect();
  for (let y = Math.min(y1, c.bottom - 4); y >= Math.max(y0, c.top); y -= 2) for (let k = 0; k < 20; k++) {
    const x = Math.round(c.left + (c.right - c.left) * (0.5 + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 0.03));
    if (document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.floorAt(x, y) && LIVE.scene.pick(x, y) < 0) return [x, y]; }
  return null; };

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errs = [];
  try {
    const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: LANG === 'en' ? 'en-GB' : 'ru-RU' });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(String(e).slice(0, 300)));
    await p.addInitScript(() => { try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
    await p.goto(demoUrl((process.env.BASE || 'http://127.0.0.1:8797/demo/') + '?lang=' + LANG + '&quiz=0&live=force'), { waitUntil: 'load', timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
    await p.evaluate(v => vwOpenVariant(v), +(process.env.V || 0));
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 180000 }); await p.waitForTimeout(2000);
    await p.evaluate(() => { window.__sl = []; const o = window.vwSheet;
      window.vwSheet = function () { window.__sl.push('vwSheet(' + [...arguments].join(',') + ') ← ' + new Error().stack.split('\n').slice(2, 5).map(s => s.trim().replace(/\(http[^)]*\)/, '')).join(' < ')); return o.apply(this, arguments); };
      window.__ev = []; const cv = LIVE.canvas, sc = LIVE.scene, wt = sc.walkTap;
      ['pointerdown', 'pointerup', 'pointercancel', 'click'].forEach(n => cv.addEventListener(n, e => window.__ev.push(n + ':' + e.pointerType + '@' + Math.round(e.clientX) + ',' + Math.round(e.clientY)), true));
      if (wt) sc.walkTap = (x, y) => { const r = wt(x, y); window.__ev.push('walkTap→' + r); return r; }; });
    // встать посреди комнаты: со стартовой точки (угол) видимый пол почти весь под шторкой
    await p.evaluate(() => { const r = curRoom(); LIVE.scene.setWalk({ x: r.w / 2, y: r.d / 2, rot: 0 }); }); await p.waitForTimeout(1200);
    const mid = async () => { await p.evaluate(() => { vwSelect(null); vwSheet(1); }); await p.waitForTimeout(700); return p.evaluate(ST); };
    const tapAt = async (q, wait = 1200) => { await p.touchscreen.tap(q[0], q[1]); await p.waitForTimeout(wait); return p.evaluate(ST); };
    const s0 = await mid();
    ok('шторка на средней', s0.pos === '2', s0);
    const sheetTop = await p.evaluate(() => Math.round(innerHeight - VW.sheetVis));   // верх шторки (сдвиг ещё мог доезжать — по цели)

    // 1. пол далеко от шторки (выше её верха на 60+ px)
    const far = await p.evaluate(FLOOR, [sheetTop - 320, sheetTop - 40]);
    if (far) { const s = await tapAt(far); ok('тап по полу далеко от шторки: шторка на месте', s.pos === s0.pos && Math.abs(s.vis - s0.vis) < 3, { at: far, sheetTop, s });
      await p.screenshot({ path: `${OUT}${TAG}-1-floor-far.png` }); }
    else ok('пол далеко от шторки не нашёлся', false, { sheetTop });

    // 2. пол у самого верха шторки (3–12 px над ней)
    const s1 = await mid();
    const near = await p.evaluate(FLOOR, [sheetTop - 12, sheetTop - 3]);
    if (near) { const s = await tapAt(near); ok('тап по полу у верха шторки: шторка на месте', s.pos === s1.pos && Math.abs(s.vis - s1.vis) < 3, { at: near, sheetTop, s });
      await p.screenshot({ path: `${OUT}${TAG}-2-floor-near.png` }); }
    else ok('пол у верха шторки не нашёлся', false, { sheetTop });

    // 3. вещь: выбрана, шторка на месте (как было)
    const s2 = await mid();
    const item = await p.evaluate(() => { const c = LIVE.canvas.getBoundingClientRect(), top = document.getElementById('vside').getBoundingClientRect().top;
      for (let y = top - 20; y > c.top + 60; y -= 8) for (let x = c.left + c.width * 0.22; x < c.left + c.width * 0.78; x += 6) {
        if (document.elementFromPoint(x, y) !== LIVE.canvas) continue; const i = LIVE.scene.pick(x, y); if (i >= 0 && i < items.length) return [Math.round(x), Math.round(y), i]; }
      return null; });
    if (item) { const s = await tapAt(item);
      ok('тап по вещи: вещь выбрана, шторка на месте', s.sel != null && s.pos === s2.pos && Math.abs(s.vis - s2.vis) < 3, { at: item, s });
      await p.screenshot({ path: `${OUT}${TAG}-3-item.png` }); }
    else ok('вещь в кадре не нашлась', false);

    // 4. шапка шторки: тап открывает до верха (как было)
    await mid();
    const grip = await p.evaluate(() => { const g = document.getElementById('vgrip') || document.getElementById('vchip'); const r = g.getBoundingClientRect(); return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]; });
    const s = await tapAt(grip, 1000);
    ok('тап по ручке шторки: открылась до верха', s.pos === '3', { at: grip, s });
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
