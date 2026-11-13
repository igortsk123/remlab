// КРУЖОК ЦВЕТА В «3D» НА ТЕЛЕФОНЕ — РЕЗУЛЬТАТ ВИДНО (сторож регресса, T-20261112-104, владелец TG 1244 «закрывать шторку на мобильном,
// чтоб увидеть результат», TG 1272 — из полной шторки не свернула). Шторку сворачивает и выбор снимает сам кружок (`rowSwatch` →
// `swatchShow`, T-104/2), запасом — `vwAfterChange` по `remlab:hist`. Телефон, шторка на средней и на полной (POS) →
// (А) кружок другого цвета в строке списка — цвет сменился, шторка свёрнута, карточки над предметом нет;
// (Б) предмет выбран, кружок в его карточке над предметом — цвет сменился, шторка свёрнута, карточка закрыта;
// (В) кружок цвета, который уже стоит, — шторка свёрнута, цвет тот же. IPHONE=1 — профиль iPhone 13, LOSE=1 — 3D без видеоконтекста.
// След: кто трогал шторку (`vwSheet`/`vwSheetApply` со стеком) — для разбора провала. Бесплатно, на сервер ничего не пишется.
//   STAGE-прокси → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> [V=2] [TAG=after] [LANG_UI=ru|en] node swatch-close-check.cjs [375x667]
//   V — номер варианта вручную; без него — первый вариант, где у мебели есть кружки других цветов (номера меняет пересборка)
//   самопроверка меры цвета (без браузера): node swatch-close-check.cjs --selftest
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
// ЦВЕТ В 3D ПО СВЕТЛОТЕ И ОТТЕНКУ (T-20261112-104/4, директор; живой /demo 12.11 23:3x): прежняя мера — доли r:g:b без яркости — путала
// нейтральные серые разной светлоты: «Молочный» в кадре [172,163,154] выходил ближе к «Графитовому» [74,69,65]. Теперь — ΔE CIE76 в Lab.
// Свет сцены сжимает светлоту (молочный темнеет, графит светлеет), поэтому соседние нейтральные кружки (молочный/бежевый, ΔE 6–17) в кадре
// не различить: цвет товара места обязан быть не дальше ближайшего кружка больше чем на COL_TOL, а после замены — ближе к новому, чем к
// прежнему (дефект TG 1272 — «в 3D прежний цвет»). Грубая ошибка (TG 1383: жёлтый товар, в кадре чёрный) — ΔE десятки, FAIL всегда.
const COL_TOL = 12;
const lab = ([r, g, b]) => { const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const [R1, G1, B1] = [r, g, b].map(lin), f = t => t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116;
  const x = f((R1 * 0.4124 + G1 * 0.3576 + B1 * 0.1805) / 0.95047), y = f(R1 * 0.2126 + G1 * 0.7152 + B1 * 0.0722), z = f((R1 * 0.0193 + G1 * 0.1192 + B1 * 0.9505) / 1.08883);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)]; };
const deltaE = (a, b) => { const p = lab(a), q = lab(b); return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]); };
/** Вердикт по среднему цвету предмета в кадре: `sw` — кружки семьи {name, rgb}, `cur` — товар места, `prev` — товар до замены (или null). */
function judgeColour(mean, sw, cur, prev) {
  const near = sw.map(f => ({ name: f.name, rgb: f.rgb, dE: Math.round(10 * deltaE(mean, f.rgb)) / 10 })).sort((a, b) => a.dE - b.dE);
  const c = near.find(f => f.name === cur), pv = prev && prev !== cur ? near.find(f => f.name === prev) : null;
  if (!c) return { ok: false, why: 'у товара места нет кружка', near };
  const gap = Math.round(10 * (c.dE - near[0].dE)) / 10;
  if (gap > COL_TOL) return { ok: false, why: `ΔE до цвета места ${c.dE} — дальше ближайшего (${near[0].name}, ${near[0].dE}) на ${gap} > ${COL_TOL}`, near };
  if (pv && pv.dE <= c.dE) return { ok: false, why: `в кадре ближе прежний цвет: ΔE прежнего ${pv.dE} ≤ нового ${c.dE}`, near };
  return { ok: true, why: near[0].name === cur ? 'ближайший — цвет места' : `цвет места в допуске: ΔE ${c.dE}, ближайший ${near[0].dE} (+${gap} ≤ ${COL_TOL})` +
    (pv ? `, прежний дальше (${pv.dE})` : ''), near };
}
if (process.argv.includes('--selftest')) {
  // заглушки: кружки дивана «Риббл-1» и замеры живого /demo 12.11; серые разной светлоты; жёлтый против чёрного (TG 1383)
  const RIB = [{ name: 'Графитовый', rgb: [74, 69, 65] }, { name: 'Молочный', rgb: [215, 210, 203] }, { name: 'Бежевый', rgb: [182, 179, 174] }];
  const YB = [{ name: 'Жёлтый', rgb: [228, 196, 48] }, { name: 'Чёрный', rgb: [28, 28, 30] }];
  const cases = [
    ['молочный в кадре [172,163,154], место — Молочный, был Графитовый', [172, 163, 154], RIB, 'Молочный', 'Графитовый', true],
    ['молочный в кадре — ближе к «Молочному», чем к «Графитовому»', [172, 163, 154], RIB, 'Молочный', null, true],
    ['графит в кадре [99,94,87], место — Графитовый, был Молочный', [99, 94, 87], RIB, 'Графитовый', 'Молочный', true],
    ['серые разной светлоты: в кадре светлый, место — Графитовый (замена не дошла)', [172, 163, 154], RIB, 'Графитовый', 'Молочный', false],
    ['серые разной светлоты: в кадре тёмный, место — Молочный', [99, 94, 87], RIB, 'Молочный', 'Графитовый', false],
    ['жёлтый против чёрного: место — Жёлтый, в кадре чёрный', [36, 34, 33], YB, 'Жёлтый', 'Чёрный', false],
    ['жёлтый против чёрного: место — Жёлтый, в кадре жёлтый под светом сцены', [176, 150, 52], YB, 'Жёлтый', 'Чёрный', true],
  ];
  let bad = 0;
  for (const [n, m, sw, cur, prev, want] of cases) { const v = judgeColour(m, sw, cur, prev); const good = v.ok === want; if (!good) bad++;
    console.log(`${good ? 'OK  ' : 'FAIL'} ${n}: ${v.ok ? 'норма' : 'дефект'} — ${v.why} · ${v.near.map(f => f.name + ' ' + f.dE).join(', ')}`); }
  console.log(bad ? `САМОПРОВЕРКА: ${bad} FAIL` : `САМОПРОВЕРКА OK (${cases.length})`);
  process.exit(bad ? 1 : 0);
}
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
    // ВАРИАНТ — ПО СОСТАВУ, НЕ ПО НОМЕРУ (T-20261112-104/4: в сборке 13.11 у варианта №2 — гостиной без кружков — «предмет не нашёлся»;
    // номера и состав вариантов меняет каждая пересборка): V задан — он; иначе первый вариант, где у строки мебели есть кружки других
    // цветов (сиденья — диван, кресло, стул — в первую очередь)
    const hasSw = () => p.evaluate(() => { let any = 0; for (let i = 0; i < items.length; i++) { const it = items[i], r = vwRowOf(it);
      if (r && r.querySelector('.sws [data-sw].sw:not(.on)')) any = Math.max(any, /диван|кресл|стул/i.test(it.role) ? 2 : 1); } return any; });
    let VI = process.env.V === undefined || process.env.V === '' ? -1 : +process.env.V;
    if (VI < 0) { const nv = await p.evaluate(() => allVariants().length); let bs = 0;
      for (let v = 0; v < nv && bs < 2; v++) { await p.evaluate(v => vwOpenVariant(v), v);
        try { await p.waitForFunction(() => document.querySelectorAll('#shotbody .pinlist .row').length > 0, null, { timeout: 30000 }); } catch (e) { continue; }
        await p.waitForTimeout(500); const s = await hasSw(); if (s > bs) { bs = s; VI = v; } }
      if (VI < 0) VI = 0; }
    R.push(`INFO вариант ${VI} (${await p.evaluate(v => allVariants()[v].id, VI)})${process.env.V ? ' — задан V' : ' — первый с кружками у мебели'}`);
    await p.evaluate(v => vwOpenVariant(v), VI);
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
    // ЦВЕТ ПРЕДМЕТА В 3D ЧИСЛОМ (T-20261112-104/3, директор: «проверка цвета дивана в кадре числом, не на глаз»): через ≥3 с после нажатия
    // (модель цвета успевает загрузиться) — точки кадра, где сцена отдаёт этот предмет (`LIVE.scene.pick`, только где сверху сам холст,
    // не ценник), средний цвет пикселей снимка → ближайший по оттенку (доли r:g:b, без яркости — свет сцены её меняет) кружок семьи
    // обязан быть цветом товара места. Кружков-цветов (`swatch`) у семьи нет — INFO, не меряем; без видеоконтекста — тоже
    const sharp = require(pick('sharp'));
    const col3d = async (lbl, i, prev = null) => {
      if (process.env.LOSE === '1') { R.push(`INFO ${lbl}: 3D без видеоконтекста — цвет в кадре не меряем`); return; }
      await p.waitForTimeout(3000);
      let last = null;
      for (let tr = 0; tr < 3; tr++) {
        const g = await p.evaluate(i => { const cv = LIVE.canvas, r = cv.getBoundingClientRect(), pts = [];
          for (let y = r.top + 5; y < Math.min(r.bottom, innerHeight); y += 10) for (let x = r.left + 5; x < Math.min(r.right, innerWidth); x += 10) {
            if (document.elementFromPoint(x, y) !== cv) continue; if (LIVE.scene.pick(x, y) === i) pts.push([x, y]); }
          const it = items[i], sku = skuOf(it) || {}, fam = colourFamRow(sku, it.role) || [], tmp = document.createElement('i'); document.body.appendChild(tmp);
          const rgb = s => { tmp.style.color = ''; tmp.style.color = s; const m = getComputedStyle(tmp).color.match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number) : null; };
          const sw = fam.filter(f => f.swatch).map(f => ({ name: f.name, rgb: rgb(f.swatch) })).filter(f => f.rgb); tmp.remove();
          return { pts, dpr: devicePixelRatio, cur: sku.name, sw }; }, i);
        if (g.sw.length < 2) { R.push(`INFO ${lbl}: у семьи нет кружков-цветов — цвет в кадре не меряем`); return; }
        const shot = await p.screenshot(), { data, info } = await sharp(shot).raw().toBuffer({ resolveWithObject: true });
        const m = [0, 0, 0]; let n = 0;
        for (const [x, y] of g.pts) { const px = Math.round(x * g.dpr), py = Math.round(y * g.dpr); if (px >= info.width || py >= info.height) continue;
          const o = (py * info.width + px) * info.channels; for (let c = 0; c < 3; c++) m[c] += data[o + c]; n++; }
        const mean = m.map(v => Math.round(v / Math.max(1, n))), v = judgeColour(mean, g.sw, g.cur, prev);
        last = { points: n, mean, cur: g.cur, prev, ok: v.ok, why: v.why, near: v.near.slice(0, 4) };
        if (n >= 30 && v.ok) break;
        await p.waitForTimeout(3000);
      }
      ok(`${lbl}: цвет предмета в 3D (среднее по ${last.points} точкам, ΔE CIE76) — цвет товара места, не прежний`, last.points >= 30 && last.ok, last);
    };
    // ШТОРКА — ОПРОСОМ (T-20261112-104/4): было два снимка состояния через 600 и 1800 мс — на медленной машине (программная графика, 4 браузера)
    // шторка сворачивалась к 700–900 мс, и строка «600 мс» краснела без дефекта. Теперь — опрос каждые 100 мс до SHEET_MS от нажатия;
    // в строке — фактическое время; FAIL — только если за SHEET_MS не свернулось
    const SHEET_MS = 2000;
    const settle = async (t0, i, cond) => { const who = []; for (;;) { const s = await p.evaluate(ST), nm = await nameAt(i); who.push(...s.who);
      const ms = Date.now() - t0; if (cond(s, nm) || ms >= SHEET_MS) return { s: { ...s, who: who.slice(0, 6) }, nm, ms, hit: cond(s, nm) };
      await p.waitForTimeout(100); } };
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
      { const t0 = Date.now(), r = await settle(t0, t.i, (s, nm) => nm !== t.name && s.pos === '0' && !s.card);
        ok(`А${tg}: кружок в строке — за ${r.ms} мс цвет новый, шторка свёрнута, карточки нет (предел ${SHEET_MS} мс)`, r.hit, { was: t.name, now: r.nm, s: r.s }); }
      await p.screenshot({ path: `${OUT}${TAG}-A-${fn}-tap.png` });
      await col3d(`А${tg}`, t.i, t.name);
      await p.screenshot({ path: `${OUT}${TAG}-A-${fn}.png` });
      // В. кружок цвета, который уже стоит (снимок владельца TG 1272: терракотовый уже выбран, шторка полная) — шторка всё равно
      // сворачивается, чтобы цвет было видно в 3D; цвет не меняется
      const s2 = await mid(q), on = await p.evaluate(k => { const b = document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] .sws [data-sw].sw.on`);
        return b ? b.dataset.sw : null; }, t.k), nm0 = await nameAt(t.i);
      if (on == null) ok(`В${tg}: у строки нет отмеченного кружка`, false, s2);
      else { await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${on}"]`);
        await p.waitForTimeout(900); const s3 = await p.evaluate(ST), nm1 = await nameAt(t.i);
        ok(`В${tg}: кружок уже выбранного цвета — шторка свёрнута, цвет тот же`, s2.pos === PDATA[q] && s3.pos === '0' && nm1 === nm0, { before: s2.pos, nm0, nm1, s: s3 });
        await col3d(`В${tg}`, t.i);
        await p.screenshot({ path: `${OUT}${TAG}-C-${fn}.png` }); }
      // Г. путь владельца (TG 1272): предмет выбран на сцене (строка подсвечена, карточка над ним), шторка раскрыта — кружок в СТРОКЕ списка
      t = await target();
      await mid(q); await p.evaluate(i => vwHighlight(i), t.i); await p.waitForTimeout(500);
      if ((await p.evaluate(ST)).pos !== PDATA[q]) { await p.evaluate(x => vwSheet(x), q); await p.waitForTimeout(800); }
      const s4 = await p.evaluate(ST);
      ok(`Г${tg}: предмет выбран, строка подсвечена, шторка до нажатия`, s4.sel === t.i && s4.pos === PDATA[q], s4);
      await p.screenshot({ path: `${OUT}${TAG}-D-${fn}-before.png` });
      await tapEl(`#shotbody .pinlist .row[data-k="${t.k}"] .sws [data-sw="${t.j}"]`);
      { const t0 = Date.now(), r = await settle(t0, t.i, (s, nm) => nm !== t.name && s.pos === '0' && !s.card && s.sel == null);
        ok(`Г${tg}: кружок в строке выбранного — за ${r.ms} мс цвет новый, шторка свёрнута, выбор снят (предел ${SHEET_MS} мс)`, r.hit, { was: t.name, now: r.nm, s: r.s }); }
      // снимок Г — после ≥3 с и замера цвета (директор T-104/3: прежний снимок шёл через 1,8 с; цвет у него был верный — коричневый)
      await col3d(`Г${tg}`, t.i, t.name);
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
        const t0 = Date.now(), r = await settle(t0, t.i, (s, nm) => nm !== t.name && s.pos === '0' && !s.card);
        ok(`Б${tg}: кружок в карточке — за ${r.ms} мс цвет новый, шторка свёрнута, карточка закрыта (предел ${SHEET_MS} мс)`, r.hit, { was: t.name, now: r.nm, s: r.s });
        await p.screenshot({ path: `${OUT}${TAG}-B-${fn}.png` }); }
    }
    if (t && !PHONE) ok('проба — только для телефона (ширина ≤ 700)', false, { W });
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
