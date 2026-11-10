// T-20261109-35/3: «Заменить» в ТУРЕ ПРОБЫ (`/try/<id>/tour/`) — страница узнаёт товар по `sku.name`, а в туре у всех диванов было одно имя.
// БЕСПЛАТНО: данные тура — из фикстуры живого демо, пересобранные как у сборки тура (`trial-tour-data.py`: нейтральные имена,
// ленты — только товары вариантов), обвязка — настоящая (`lib/trial/tour-page.ts:injectTour`), движок/меши — прод `/demo/`, все `/api/*` — 403.
//   python tools/ops/demo-walk/trial-tour-data.py <tour.json> [--old]
//   node tools/ops/demo-walk/trial-replace-check.cjs <WxH> <новая папка> [ru|en] <tour.json> [метка]
// Шаги: гостиная → строка дивана «Заменить» → лента (сколько карточек, какая отмечена «Выбрано») → «Заменить» у первой карточки →
// строка списка и модель в 3D сменились. Плюс строки списка: имена разные у разных товаров, размер в названии один раз, вторая строка —
// цвет (не роль), чип свёрнутой шторки на телефоне — «Мебель · N».
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const esbuild = require(pick('esbuild'));
const PAGE = process.env.PAGE || path.join(ROOT, 'tools/scout/flat215-demo/index.html');
const ORIGIN = 'https://remont-lab.online';
const ID = 'T35probeT35probeT35pr0';
const TOUR = `/try/${ID}/tour/`;
const [W, H] = (process.argv[2] || '1280x800').split('x').map(Number);
const OUT = process.argv[3]; fs.mkdirSync(OUT, { recursive: true });
const LANG = process.argv[4] || 'ru';
const DATA = JSON.parse(fs.readFileSync(process.argv[5], 'utf8'));
const TAG = process.argv[6] || 'new';
const PHONE = W <= 700;
const EN = LANG === 'en';

function loadInject() {
  const out = esbuild.buildSync({ entryPoints: [path.join(ROOT, 'lib/trial/tour-page.ts')], bundle: true, platform: 'node', format: 'cjs',
    write: false, tsconfig: path.join(ROOT, 'tsconfig.json'), logLevel: 'error' });
  const m = { exports: {} };
  new Function('module', 'exports', 'require', out.outputFiles[0].text)(m, m.exports, require);
  return m.exports;
}
const TP = loadInject();

async function open(b) {
  const d = JSON.parse(JSON.stringify(DATA));
  d.trial = Object.assign({}, d.trial, { job_id: ID, scale: 'verified' });
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE,
    locale: EN ? 'en-GB' : 'ru-RU' });
  const p = await ctx.newPage();
  p.log = [];
  p.on('console', m => { if (m.type() === 'error') p.log.push('error: ' + m.text().slice(0, 300)); });
  p.on('pageerror', e => p.log.push('pageerror: ' + String(e).slice(0, 300)));
  const html = TP.injectTour(fs.readFileSync(PAGE, 'utf8'), ID, 0);
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith(TOUR), async r => {
    const rel = new URL(r.request().url()).pathname.slice(TOUR.length);
    if (rel === '' || rel === 'index.html') return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    if (rel === 'demo-data.json') return r.fulfill({ status: 200, contentType: 'application/json', headers: { etag: '"v1"' }, body: JSON.stringify(d) });
    if (rel === 'version.json') return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: 0, bundle: 1, rebuild: null, rebuildError: null }) });
    const f = await r.fetch({ url: ORIGIN + '/demo/' + rel + new URL(r.request().url()).search });
    return r.fulfill({ response: f });
  });
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith('/api/'), r => r.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false}' }));
  await p.goto(ORIGIN + TOUR + `?quiz=0&live=force&lang=${LANG}`, { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!D.trial&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForTimeout(1500);
  return p;
}
const ready = p => p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
// строки списка шторки: название, вторая строка, высота, есть ли «Заменить»
const rows = p => p.evaluate(() => [...document.querySelectorAll('#shot .pinlist .row')].map(r => {
  const b = r.querySelector('.t b'), s = r.querySelector('.t > span'), rep = r.querySelector('[data-rep]'), rc = r.getBoundingClientRect();
  return { name: b ? b.textContent.trim() : '', sub: s ? s.textContent.trim() : null, h: Math.round(rc.height), rep: !!rep, k: +r.dataset.k };
}));
const sofaState = p => p.evaluate(() => { const s = items.find(i => i.role === 'диван') || {}; const k = s.sku || {};
  return { name: k.name || '', msid: k.msid || '', w: s.w, d: s.d, live: (LIVE.scene && LIVE.state) || '' }; });

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const r = { tag: TAG, lang: LANG, size: W + 'x' + H };
  try {
    const p = await open(b);
    await p.evaluate(() => { const i = allVariants().findIndex(v => roomIdOf(v) === 'living' && (v.items || []).length);
      if (i < 0) throw new Error('нет гостиной'); vwOpenVariant(i); });
    await ready(p); await p.waitForTimeout(2500);
    r.chip = await p.evaluate(() => { const c = document.getElementById('vchip'); return c ? c.textContent.trim() : null; });
    if (PHONE) await p.screenshot({ path: `${OUT}/${TAG}-${LANG}-${W}-0-collapsed.png` });
    if (PHONE) { await p.evaluate(() => vwSheet(3)); await p.waitForTimeout(800); }
    r.rows = await rows(p);
    const sofaRow = r.rows.find(x => /^(Диван|Sofa)/.test(x.name) && x.rep);
    await p.evaluate(k => { const e = document.querySelector(`#shot .pinlist .row[data-k="${k}"]`); if (e) e.scrollIntoView({ block: 'center' }); }, sofaRow ? sofaRow.k : -1);
    await p.waitForTimeout(600);
    await p.screenshot({ path: `${OUT}/${TAG}-${LANG}-${W}-1-list.png` });
    r.before = await sofaState(p);
    if (!sofaRow) throw new Error('нет строки дивана с «Заменить»');
    await p.click(`#shot .pinlist .row[data-k="${sofaRow.k}"] [data-rep]`);
    await p.waitForTimeout(1200);
    r.picker = await p.evaluate(() => ({ open: document.getElementById('sheet').classList.contains('open'),
      title: document.getElementById('sh-title').textContent.trim(),
      chips: [...document.querySelectorAll('#filters .chip')].map(c => c.textContent.trim() + (c.classList.contains('on') ? ' [on]' : '')),
      cards: [...document.querySelectorAll('#grid .card')].map(c => ({ name: (c.querySelector('.nm') || {}).textContent || '', cur: c.classList.contains('cur'),
        btn: (c.querySelector('.mini') || {}).textContent || '' })),
      hint: (document.querySelector('#grid .hint') || {}).textContent || '', selName: (sel && sel.sku && sel.sku.name) || '' }));
    await p.screenshot({ path: `${OUT}/${TAG}-${LANG}-${W}-2-picker.png` });
    const target = r.picker.cards.findIndex(c => !c.cur);
    if (target >= 0) {
      await p.click(`#grid .card:nth-child(${target + 1}) .mini`);
      await p.waitForTimeout(1500); await ready(p); await p.waitForTimeout(2500);
      r.after = await sofaState(p);
      r.rowsAfter = await rows(p);
      const nr = r.rowsAfter.find(x => x.name === r.picker.cards[target].name || x.name.startsWith(r.picker.cards[target].name));
      if (nr) await p.evaluate(k => { const e = document.querySelector(`#shot .pinlist .row[data-k="${k}"]`); if (e) e.scrollIntoView({ block: 'center' }); }, nr.k);
      await p.waitForTimeout(500);
      await p.screenshot({ path: `${OUT}/${TAG}-${LANG}-${W}-3-after.png` });
      r.picked = r.picker.cards[target].name;
    }
    r.console = p.log.slice(-6);
    await p.context().close();
  } catch (e) { r.error = String(e && e.stack || e).slice(0, 400); }
  finally { await b.close(); }
  // вердикт
  const dimRe = /(\d+×\d+ (см|cm))/g;
  const names = (r.rows || []).map(x => x.name);
  const dbl = names.filter(n => (n.match(dimRe) || []).length > 1);
  const subRole = (r.rows || []).filter(x => x.sub && /^(диван|столик|пуф|торшер|ковёр|стул|sofa|chair|rug)\b/i.test(x.sub));
  const chipOk = !PHONE || (EN ? /^⌃ Furniture · \d+$/ : /^⌃ Мебель · \d+$/).test(r.chip || '');
  const pk = r.picker || {};
  const wrongCur = (pk.cards || []).filter(c => c.cur && c.name !== pk.selName).length;
  const swapped = !!(r.after && r.before && r.after.msid && r.after.msid !== r.before.msid && (r.rowsAfter || []).some(x => x.name === r.picked));
  r.checks = { rows: names.length, doubleDims: dbl, roleInSub: subRole.map(x => x.sub), chipOk, pickerCards: (pk.cards || []).length, wrongCur, swapped };
  r.verdict = !r.error && names.length && !dbl.length && !subRole.length && chipOk && (pk.cards || []).length > 0 && !wrongCur && swapped ? 'OK'
    : 'FAIL' + (r.error ? '-ERROR' : '') + (dbl.length ? '-DOUBLEDIMS' : '') + (subRole.length ? '-ROLESUB' : '') + (chipOk ? '' : '-CHIP')
      + ((pk.cards || []).length ? '' : '-EMPTYFEED') + (wrongCur ? '-WRONGCUR' : '') + (swapped ? '' : '-NOSWAP');
  fs.writeFileSync(`${OUT}/result-${TAG}-${LANG}-${W}x${H}.json`, JSON.stringify(r, null, 1));
  console.log(JSON.stringify({ verdict: r.verdict, chip: r.chip, picker: pk.title, cards: (pk.cards || []).map(c => c.name + (c.cur ? '*' : '')),
    before: r.before && r.before.name, after: r.after && r.after.name, rows: names.slice(0, 6), subs: (r.rows || []).slice(0, 6).map(x => x.sub), err: r.error }));
  console.log(`ИТОГ ${TAG} ${LANG} ${W}x${H}: ${r.verdict}`);
})();
