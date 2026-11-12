// КРУЖОК ЦВЕТА В «3D» НА ТЕЛЕФОНЕ — РЕЗУЛЬТАТ ВИДНО (сторож регресса, T-20261112-104, владелец TG 1244 «закрывать шторку на мобильном,
// чтоб увидеть результат»). Своего кода нет: шторку сворачивает `vwAfterChange` (любая правка, владелец 17.10), выбор и карточку снимает
// обёртка `tryOn` (`vwSelect(null)`, demo-20 Б4, владелец 22.10 «рамку убирать автоматически» — так и на компьютере). Телефон, шторка
// на средней → (А) кружок другого цвета в строке списка — цвет сменился, шторка свёрнута, карточки над предметом нет;
// (Б) предмет выбран, кружок в его карточке над предметом — цвет сменился, шторка свёрнута, карточка закрыта.
// След: кто трогал шторку (`vwSheet`/`vwSheetApply` со стеком) — для разбора провала. Бесплатно, на сервер ничего не пишется.
//   STAGE-прокси → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> [V=2] [TAG=after] [LANG_UI=ru|en] node swatch-close-check.cjs [375x667]
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const [W, H] = (process.argv[2] || '375x667').split('x').map(Number), PHONE = W <= 700;
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'ru', TAG = (process.env.TAG ? process.env.TAG + '-' : '') + LANG + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));
/* global VW, PINS, items, skuOf, vwItemAt, vwRowOf, vwSelect, vwSheet, colourFamRow, shotRows */
// состояние: шторка, карточка над предметом, выбор, след вызовов шторки
const ST = () => { const sd = document.getElementById('vside'); return { pos: sd && sd.dataset.pos, vis: Math.round(VW.sheetVis || 0), sel: VW.sel,
  card: !!(PINS.rot && !PINS.rot.hidden), who: (window.__sl || []).splice(0) }; };

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errs = [];
  try {
    const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: LANG === 'en' ? 'en-GB' : 'ru-RU' });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(String(e).slice(0, 300)));
    await p.addInitScript(() => { try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
    await p.goto(demoUrl((process.env.BASE || 'http://127.0.0.1:8797/demo/') + '?lang=' + LANG + '&quiz=0&live=force'), { waitUntil: 'load', timeout: 120000 });
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
    await p.evaluate(v => vwOpenVariant(v), +(process.env.V || 2));
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 240000 }); await p.waitForTimeout(2000);
    await p.evaluate(() => { window.__sl = []; for (const n of ['vwSheet', 'vwSheetApply']) { const o = window[n];
      window[n] = function () { window.__sl.push(n + '(' + [...arguments].map(a => typeof a === 'number' ? Math.round(a) : String(a)).join(',') + ') ← ' +
        new Error().stack.split('\n').slice(2, 6).map(s => s.trim().replace(/^at /, '').replace(/\(http[^)]*\)/, '').replace(/https?:\/\/\S+/, '')).join(' < ')); return o.apply(this, arguments); }; } });
    // предмет мебели в 3D, у строки которого есть кружки других цветов (диван, кресло, стул — в первую очередь)
    const target = () => p.evaluate(() => { const cand = [];
      for (let i = 0; i < items.length; i++) { const it = items[i], r = vwRowOf(it); if (!r) continue;
        const sw = [...r.querySelectorAll('.sws [data-sw].sw:not(.on)')]; if (!sw.length) continue;
        cand.push({ i, name: (skuOf(it) || {}).name, role: it.role, k: +r.dataset.k, j: +sw[0].dataset.sw }); }
      return cand.find(c => /диван|кресл|стул/i.test(c.role)) || cand[0] || null; });
    const nameAt = i => p.evaluate(i => (skuOf(items[i]) || {}).name, i);
    const mid = async () => { await p.evaluate(() => { vwSelect(null); vwSheet(1); }); await p.waitForTimeout(800); return p.evaluate(ST); };
    const tapEl = async sel => { const l = p.locator(sel).first(); await l.evaluate(e => e.scrollIntoView({ block: 'center' })); await p.waitForTimeout(300);
      if (PHONE) await l.tap(); else await l.click(); };

    let t = await target();
    if (!t) ok('предмет с кружками цветов не нашёлся', false);
    if (t && PHONE) {
      // А. кружок в строке списка
      const s0 = await mid(); ok('А: шторка на средней', s0.pos === '2', s0);
      await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${t.j}"]`);
      for (const ms of [600, 1800]) { await p.waitForTimeout(ms === 600 ? 600 : 1200); const s = await p.evaluate(ST), nm = await nameAt(t.i);
        ok(`А: кружок в строке — через ${ms} мс цвет новый, шторка свёрнута, карточки нет`, nm !== t.name && s.pos === '0' && !s.card, { was: t.name, now: nm, s }); }
      await p.screenshot({ path: `${OUT}${TAG}-A-row.png` });
      // Б. кружок в карточке над выбранным предметом
      t = await target();
      await mid(); await p.evaluate(i => vwSelect(i), t.i);
      // карточка встаёт с кадром сцены (без видеокарты — до секунд): ждём её, а не фиксированную паузу
      await p.waitForFunction(() => PINS.rot && !PINS.rot.hidden, null, { timeout: 15000 }).catch(() => {}); await p.waitForTimeout(400);
      const s1 = await p.evaluate(ST); ok('Б: предмет выбран, карточка над ним, шторка на средней', s1.card && s1.pos === '2', s1);
      await p.screenshot({ path: `${OUT}${TAG}-B-before.png` });
      if (s1.card) { await tapEl('.vcsws [data-sw].sw:not(.on)');
        for (const ms of [600, 1800]) { await p.waitForTimeout(ms === 600 ? 600 : 1200); const s = await p.evaluate(ST), nm = await nameAt(t.i);
          ok(`Б: кружок в карточке — через ${ms} мс цвет новый, шторка свёрнута, карточка закрыта`, nm !== t.name && s.pos === '0' && !s.card, { was: t.name, now: nm, s }); }
        await p.screenshot({ path: `${OUT}${TAG}-B-card.png` }); }
    } else if (t) ok('проба — только для телефона (ширина ≤ 700)', false, { W });
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
