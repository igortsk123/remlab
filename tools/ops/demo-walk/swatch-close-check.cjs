// КРУЖОК ЦВЕТА В «3D» НА ТЕЛЕФОНЕ — РЕЗУЛЬТАТ ВИДНО (сторож регресса, T-20261112-104, владелец TG 1244 «закрывать шторку на мобильном,
// чтоб увидеть результат», TG 1272 — из полной шторки не свернула). Шторку сворачивает и выбор снимает сам кружок (`rowSwatch` →
// `swatchShow`, T-104/2), запасом — `vwAfterChange` по `remlab:hist`. Телефон, шторка на средней и на полной (POS) →
// (А) кружок другого цвета в строке списка — цвет сменился, шторка свёрнута, карточки над предметом нет;
// (Б) предмет выбран, кружок в его карточке над предметом — цвет сменился, шторка свёрнута, карточка закрыта;
// (В) кружок цвета, который уже стоит, — шторка свёрнута, цвет тот же. IPHONE=1 — профиль iPhone 13, LOSE=1 — 3D без видеоконтекста.
// След: кто трогал шторку (`vwSheet`/`vwSheetApply` со стеком) — для разбора провала. Бесплатно, на сервер ничего не пишется.
//   STAGE-прокси → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> [V=2] [TAG=after] [LANG_UI=ru|en] node swatch-close-check.cjs [375x667]
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const IPHONE = process.env.IPHONE === '1';
const [W, H] = IPHONE ? [390, 664] : (process.argv[2] || '375x667').split('x').map(Number), PHONE = W <= 700;
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'ru', TAG = (process.env.TAG ? process.env.TAG + '-' : '') + LANG + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));
/* global VW, PINS, items, skuOf, vwItemAt, vwRowOf, vwSelect, vwSheet, colourFamRow, shotRows */
// состояние: шторка, карточка над предметом, выбор, след вызовов шторки
const ST = () => { const sd = document.getElementById('vside'); return { pos: sd && sd.dataset.pos, vis: Math.round(VW.sheetVis || 0), sel: VW.sel,
  card: !!(PINS.rot && !PINS.rot.hidden), who: (window.__sl || []).splice(0) }; };

(async () => {
  // IPHONE=1 — движок Safari (webkit) и профиль «iPhone 13» (T-20261112-104/2, снимок владельца — iPhone): свой размер экрана профиля
  // webkit без системных библиотек не встаёт (на DEV их нет, ставить — sudo) → chromium с профилем iPhone: агент iOS, касания, экран
  const cr = () => pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  let b = null;
  if (IPHONE) try { b = await pw.webkit.launch(); R.push('INFO движок: webkit'); } catch (e) { R.push('INFO движок: chromium с профилем iPhone 13 (webkit не встал: ' + String(e.message || e).split('\n')[0].slice(0, 80) + ')'); }
  if (!b) b = await cr();
  const errs = [];
  try {
    const ctx = await b.newContext(IPHONE ? { ...pw.devices['iPhone 13'], locale: LANG === 'en' ? 'en-GB' : 'ru-RU' }
      : { viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: LANG === 'en' ? 'en-GB' : 'ru-RU' });
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
    // LOSE=1 — сцена 3D теряет видеоконтекст, как на iPhone при нехватке памяти (снимки владельца TG 1272: 21:47 диван в 3D прежнего
    // цвета, 21:49 «3D does not open on this device»): смена цвета обязана свернуть шторку и тогда
    if (process.env.LOSE === '1') { const lost = await p.evaluate(() => { const c = LIVE.canvas, gl = c && (c.getContext('webgl2') || c.getContext('webgl')),
      x = gl && gl.getExtension('WEBGL_lose_context'); if (x) x.loseContext(); return !!x; }); R.push('INFO видеоконтекст сцены потерян: ' + lost);
      await p.waitForTimeout(1500); }
    // предмет мебели в 3D, у строки которого есть кружки других цветов (диван, кресло, стул — в первую очередь)
    const target = async () => (await target1(process.env.PICK || '')) || target1('');   // нужный цвет уже стоит — любой другой
    const target1 = pk => p.evaluate(pick => { const cand = [];
      for (let i = 0; i < items.length; i++) { const it = items[i], r = vwRowOf(it); if (!r) continue;
        // PICK — цвет по названию товара (владелец TG 1272: «Сорен» → терракотовый), иначе первый другой
        const fam = colourFamRow(skuOf(it) || {}, it.role) || [];
        const sw = [...r.querySelectorAll('.sws [data-sw].sw:not(.on)')].filter(b => !pick || ((fam[+b.dataset.sw] || {}).name || '').includes(pick));
        if (!sw.length) continue;
        cand.push({ i, name: (skuOf(it) || {}).name, role: it.role, k: +r.dataset.k, j: +sw[0].dataset.sw }); }
      return cand.find(c => /диван|кресл|стул/i.test(c.role)) || cand[0] || null; }, pk);
    const nameAt = i => p.evaluate(i => (skuOf(items[i]) || {}).name, i);
    const mid = async (pos = 1) => { await p.evaluate(q => { vwSelect(null); vwSheet(q); }, pos); await p.waitForTimeout(800); return p.evaluate(ST); };
    const tapEl = async sel => { const l = p.locator(sel).first(); await l.evaluate(e => e.scrollIntoView({ block: 'center' })); await p.waitForTimeout(300);
      if (PHONE) await l.tap(); else await l.click(); };

    let t = await target();
    if (!t) ok('предмет с кружками цветов не нашёлся', false);
    // положения шторки до нажатия (T-20261112-104/2, владелец TG 1272: из полной не сворачивалась): 1 — средняя, 3 — полная
    const POSES = (process.env.POS || '1,3').split(',').map(Number), PNAME = { 1: 'средняя', 3: 'полная' }, PDATA = { 1: '2', 3: '3' };
    for (const q of (t && PHONE ? POSES : [])) {
      const tg = `[${PNAME[q]}]`, fn = `${q === 3 ? 'full' : 'mid'}`;
      // А. кружок в строке списка — палец по-настоящему, после прокрутки списка (на полной строка может быть ниже экрана)
      t = await target();
      const s0 = await mid(q); ok(`А${tg}: шторка до нажатия`, s0.pos === PDATA[q], s0);
      await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${t.j}"]`);
      await p.screenshot({ path: `${OUT}${TAG}-A-${fn}-tap.png` });
      for (const ms of [600, 1800]) { await p.waitForTimeout(ms === 600 ? 600 : 1200); const s = await p.evaluate(ST), nm = await nameAt(t.i);
        ok(`А${tg}: кружок в строке — через ${ms} мс цвет новый, шторка свёрнута, карточки нет`, nm !== t.name && s.pos === '0' && !s.card, { was: t.name, now: nm, s }); }
      await p.screenshot({ path: `${OUT}${TAG}-A-${fn}.png` });
      // В. кружок цвета, который уже стоит (снимок владельца TG 1272: терракотовый уже выбран, шторка полная) — шторка всё равно
      // сворачивается, чтобы цвет было видно в 3D; цвет не меняется
      const s2 = await mid(q), on = await p.evaluate(k => { const b = document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] .sws [data-sw].sw.on`);
        return b ? b.dataset.sw : null; }, t.k), nm0 = await nameAt(t.i);
      if (on == null) ok(`В${tg}: у строки нет отмеченного кружка`, false, s2);
      else { await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${on}"]`);
        await p.waitForTimeout(900); const s3 = await p.evaluate(ST), nm1 = await nameAt(t.i);
        ok(`В${tg}: кружок уже выбранного цвета — шторка свёрнута, цвет тот же`, s2.pos === PDATA[q] && s3.pos === '0' && nm1 === nm0, { before: s2.pos, nm0, nm1, s: s3 });
        await p.screenshot({ path: `${OUT}${TAG}-C-${fn}.png` }); }
      // Г. путь владельца (TG 1272): предмет выбран на сцене (строка подсвечена, карточка над ним), шторка раскрыта — кружок в СТРОКЕ списка
      t = await target();
      await mid(q); await p.evaluate(i => vwHighlight(i), t.i); await p.waitForTimeout(500);
      if ((await p.evaluate(ST)).pos !== PDATA[q]) { await p.evaluate(x => vwSheet(x), q); await p.waitForTimeout(800); }
      const s4 = await p.evaluate(ST);
      ok(`Г${tg}: предмет выбран, строка подсвечена, шторка до нажатия`, s4.sel === t.i && s4.pos === PDATA[q], s4);
      await p.screenshot({ path: `${OUT}${TAG}-D-${fn}-before.png` });
      await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${t.j}"]`);
      for (const ms of [600, 1800]) { await p.waitForTimeout(ms === 600 ? 600 : 1200); const s = await p.evaluate(ST), nm = await nameAt(t.i);
        ok(`Г${tg}: кружок в строке выбранного — через ${ms} мс цвет новый, шторка свёрнута, выбор снят`, nm !== t.name && s.pos === '0' && !s.card && s.sel == null, { was: t.name, now: nm, s }); }
      await p.screenshot({ path: `${OUT}${TAG}-D-${fn}.png` });
      // Б. кружок в карточке над выбранным предметом (на полной шторке карточка — над краем шторки, если сцена видна)
      t = await target();
      await mid(q === 3 ? 1 : q); await p.evaluate(i => vwSelect(i), t.i);
      // карточка встаёт с кадром сцены (без видеокарты — до секунд): ждём её, а не фиксированную паузу
      await p.waitForFunction(() => PINS.rot && !PINS.rot.hidden, null, { timeout: 15000 }).catch(() => {}); await p.waitForTimeout(400);
      if (q === 3) { await p.evaluate(() => vwSheet(3)); await p.waitForTimeout(800); }
      const s1 = await p.evaluate(ST);
      // полная шторка закрывает весь экран: карточка над предметом под ней, пальцем её не достать (снимок `*-B-full-before.png`)
      const cover = q === 3 && s1.vis >= await p.evaluate(() => innerHeight) - 4;
      if (q === 3 && (!s1.card || cover)) { ok(`Б${tg}: карточки над предметом при полной шторке не видно (шторка закрыла сцену) — случай не бывает`, true, s1); continue; }
      // без видеоконтекста (LOSE=1) кадра сцены нет — и карточки над предметом нет: случай не проверяется
      if (process.env.LOSE === '1' && !s1.card) { R.push(`INFO Б${tg}: 3D без видеоконтекста — карточки над предметом нет, случай не проверяется`); continue; }
      // кружок карточки — под пальцем (не закрыт шторкой и не за краем экрана); нет — на этой высоте экрана карточка без кружков
      const hit = s1.card && await p.locator('.vcsws [data-sw].sw:not(.on)').first().isVisible() && await p.evaluate(() => { const b = document.querySelector('.vcsws [data-sw].sw:not(.on)'); if (!b) return false;
        const r = b.getBoundingClientRect(); if (!r.width || r.bottom <= 0 || r.top >= innerHeight) return false;
        const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!e && (e === b || b.contains(e)); });
      if (s1.card && !hit) { ok(`Б${tg}: карточка есть, но кружка в ней не достать (закрыт шторкой или за краем) — случай не бывает`, true, s1); continue; }
      ok(`Б${tg}: предмет выбран, карточка над ним, шторка до нажатия`, s1.card && s1.pos === PDATA[q], s1);
      await p.screenshot({ path: `${OUT}${TAG}-B-${fn}-before.png` });
      if (s1.card) { await tapEl('.vcsws [data-sw].sw:not(.on)');
        for (const ms of [600, 1800]) { await p.waitForTimeout(ms === 600 ? 600 : 1200); const s = await p.evaluate(ST), nm = await nameAt(t.i);
          ok(`Б${tg}: кружок в карточке — через ${ms} мс цвет новый, шторка свёрнута, карточка закрыта`, nm !== t.name && s.pos === '0' && !s.card, { was: t.name, now: nm, s }); }
        await p.screenshot({ path: `${OUT}${TAG}-B-${fn}.png` }); }
    }
    if (t && !PHONE) ok('проба — только для телефона (ширина ≤ 700)', false, { W });
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
