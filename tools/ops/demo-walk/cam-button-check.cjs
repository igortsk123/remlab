// ОКОШКИ РАКУРСОВ — ТОЛЬКО ПО КНОПКЕ ФОТО, ПЕРЕКЛЮЧАТЕЛЬ ВИДОВ НА МЕСТЕ (T-20261112-108, владелец TG 1266/1268/1273). «3D»:
// (1) окошек нет, переключатель «От двери / Другой ракурс» виден; (2) переключатель работает (вид 2 → вид 1);
// (3) «Сделать фото» (📷) — окошки есть, переключателя нет, кнопка «Снять эти ракурсы»; (4) «×» — окошки скрыты, переключатель снова;
// (5) 📷 ещё раз и снова — заказ фото уходит с позами окошек (заказ подменён записью: платного нет), окошки скрыты;
// (6) ушли с точки → 📷: ракурс 1 — текущий вид, окошко 2 ждёт; 📷 — второй, заказ с этими позами;
// (7) телефон: шторка до верха — кнопки 📷 не видно; средняя — видна.
//   STAGE-прокси → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> [V=2] [TAG=after] [LANG_UI=ru|en] node cam-button-check.cjs 375x667|1280x800
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const [W, H] = (process.argv[2] || '375x667').split('x').map(Number), PHONE = W <= 700;
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'ru', EN = LANG === 'en', TAG = (process.env.TAG ? process.env.TAG + '-' : '') + LANG + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));
/* global VW, LIVE, VSL, cams, loadCams, vwSheet, vwCamsUi */
const ST = () => { const vis = el => !!el && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden' && el.getBoundingClientRect().width > 0;
  const cm = document.getElementById('vCams'), sl = document.getElementById('vSlots'), cta = document.getElementById('vCta'), tip = document.getElementById('vSlTip');
  return { slots: vis(sl), cams: vis(cm), camOn: cm ? [...cm.querySelectorAll('[data-cam]')].findIndex(b => b.classList.contains('on')) : -2, photo: VW.photo, free: !!VW.free,
    cta: vis(cta), ctaLab: cta ? (cta.getAttribute('aria-label') || cta.textContent || '').trim() : '', tip: tip && !tip.hidden ? tip.textContent : '',
    pick: typeof VSL !== 'undefined' && !!VSL.pick, pos: (document.getElementById('vside') || {}).dataset ? document.getElementById('vside').dataset.pos : null, orders: (window.__orders || []).length }; };

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errs = [];
  try {
    const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: EN ? 'en-GB' : 'ru-RU' });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(String(e).slice(0, 300)));
    await p.addInitScript(() => { try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
    await p.goto(demoUrl((process.env.BASE || 'http://127.0.0.1:8797/demo/') + '?lang=' + LANG + '&quiz=0&live=force'), { waitUntil: 'load', timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
    await p.evaluate(v => vwOpenVariant(v), +(process.env.V || 2));
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 240000 }); await p.waitForTimeout(2500);
    // заказ фото — подмена: пишем позы, что ушли бы в фото; на сервер ничего не уходит
    await p.evaluate(() => { window.__orders = []; window.vwRealistic = function () { window.__orders.push((cams || loadCams()).slice(0, 2).map(c => ({ x: c.x, y: c.y, rot: c.rot, user: !!c.user }))); }; });
    const st = () => p.evaluate(ST);
    // программная 3D грузит процессор — кнопка «стабильной» для Playwright бывает не сразу: обычное нажатие, не вышло за 15 с — без ожидания
    const tap = async sel => { const l = p.locator(sel).first();
      if (PHONE) await l.tap({ timeout: 15000 }).catch(() => l.tap({ force: true })); else await l.click({ timeout: 15000 }).catch(() => l.click({ force: true }));
      await p.waitForTimeout(900); };
    if (PHONE) { await p.evaluate(() => vwSheet(1)); await p.waitForTimeout(800); }
    const shot = n => p.screenshot({ path: `${OUT}${TAG}-${n}.png` });

    // 1. окошек нет, переключатель есть
    let s = await st();
    ok('1: в «3D» окошек нет, переключатель видов виден', !s.slots && s.cams, s); await shot('1-3d');
    if (process.env.ONLY1) throw new Error('ONLY1: только снимок «3D» (было | сейчас)');
    // 2. переключатель работает
    await tap('#vCams [data-cam="1"]'); await p.waitForTimeout(1500); s = await st();
    ok('2: переключатель — вид 2', s.photo === 1 && s.camOn === 1, s);
    await tap('#vCams [data-cam="0"]'); await p.waitForTimeout(1500); s = await st();
    ok('2: переключатель — снова вид 1', s.photo === 0 && s.camOn === 0 && !s.free, s);
    // 3. кнопка фото — окошки
    await tap('#vCta'); await p.waitForTimeout(800); s = await st();
    ok('3: «Сделать фото» — окошки есть, переключателя нет, заказа ещё нет', s.slots && !s.cams && s.orders === 0 && (EN ? /Shoot these views/ : /Снять эти ракурсы/).test(s.ctaLab), s);
    await p.waitForTimeout(2500); await shot('3-slots');
    // 4. «×» — снова переключатель
    await tap('#vSlots [data-sl="x"]'); s = await st();
    ok('4: «×» — окошки скрыты, переключатель снова виден', !s.slots && s.cams && s.orders === 0, s);
    // 5. 📷 и ещё раз — заказ с позами окошек
    await tap('#vCta'); const want = await p.evaluate(() => (cams || loadCams()).slice(0, 2).map(c => ({ x: c.x, y: c.y, rot: c.rot, user: !!c.user })));
    await tap('#vCta'); s = await st();
    const ord = await p.evaluate(() => window.__orders[window.__orders.length - 1] || null);
    ok('5: 📷 ещё раз — заказ ушёл с позами окошек, окошки скрыты', s.orders === 1 && JSON.stringify(ord) === JSON.stringify(want) && !s.slots && s.cams, { s, ord, want });
    // 6. ушли с точки: ракурс 1 — текущий вид, 2 — выбрать, заказ с ними
    // поворот взгляда — как перетаскивание по холсту (`liveWire`: сдвиг ≥ 8 px → `VW.free`)
    await p.evaluate(() => { LIVE.scene.look(120, 0); VW.free = true; vwCamsUi(); }); await p.waitForTimeout(1200);
    s = await st();
    if (s.free) {
      await tap('#vCta'); s = await st();
      ok('6: ушли с точки, 📷 — окошки, ракурс 1 запомнен, второй ждём', s.slots && s.pick && s.orders === 1, s); await shot('6-pick');
      await p.evaluate(() => { LIVE.scene.look(-240, 0); VW.free = true; vwCamsUi(); }); await p.waitForTimeout(900);
      await tap('#vCta'); s = await st();
      const o2 = await p.evaluate(() => window.__orders[window.__orders.length - 1] || null);
      ok('6: 📷 — второй ракурс, заказ ушёл со своими позами, окошки скрыты', s.orders === 2 && o2 && o2.length === 2 && o2.every(c => c.user) && !s.slots && s.cams, { s, o2 });
    } else ok('6: поворот взгляда не увёл с точки (VW.free)', false, s);
    // 7. телефон: шторка до верха — 📷 нет; средняя — есть
    if (PHONE) {
      await p.evaluate(() => vwSheet(3)); await p.waitForTimeout(900); s = await st();
      ok('7: шторка до верха — кнопки фото не видно', s.pos === '3' && !s.cta, s); await shot('7-full');
      await p.evaluate(() => vwSheet(1)); await p.waitForTimeout(900); s = await st();
      ok('7: шторка на средней — кнопка фото видна', s.pos === '2' && s.cta, s);
      await p.evaluate(() => vwSheet(0)); await p.waitForTimeout(900); s = await st();
      ok('7: шторка свёрнута — кнопка фото видна', s.pos === '0' && s.cta, s); await shot('7-min');
    }
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
