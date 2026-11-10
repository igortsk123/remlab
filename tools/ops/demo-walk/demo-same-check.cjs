// /demo не изменился (T-20261109-34): та же витрина с index.html «до» (A) и «после» (B) — снимки экранов попарно, доля разных пикселей.
//   node tools/ops/demo-walk/demo-same-check.cjs <A.html> <B.html> <WxH> <новая папка>
// Состояния: главная; окно комнаты в «Фото» (прежнее фото и плашка); окно в 3D со шторкой и «Сделать реалистичнее» — холст 3D
// скрыт (программный рендер не детерминирован), сравниваем всё вокруг. Данные/движок — прод, `/api/*` — заглушки (платного нет).
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core')), sharp = require(pick('sharp'));
const { demoUrl } = require('../demo-url.cjs');
const [A, B, size, OUT] = process.argv.slice(2);
const [W, H] = size.split('x').map(Number), PHONE = W <= 700;
fs.mkdirSync(OUT, { recursive: true });

async function shots(b, page, tag) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, isMobile: PHONE, hasTouch: PHONE, locale: 'ru-RU' });
  const p = await ctx.newPage();
  await p.addInitScript(() => { Math.random = (() => { let s = 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; })(); });
  await p.route(/\/demo\/(index\.html)?(\?.*)?$/, r => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: fs.readFileSync(page, 'utf8') }));
  await p.route(/\/api\//, r => r.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false,"code":"probe"}' }));
  await p.goto(demoUrl('https://remont-lab.online/demo/?live=force&lang=ru'), { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  await p.waitForFunction("typeof SHOTS_LOADED!=='undefined'&&SHOTS_LOADED", null, { timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(3000);
  const freeze = () => p.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}' });
  await freeze();
  const out = {};
  out.home = await p.screenshot();
  await p.evaluate(() => vwOpenVariant(cur)); await p.waitForTimeout(3500);
  out.photo = await p.screenshot();
  await p.evaluate(() => { shots = shots.filter(x => x.quality !== 'realistic'); openLiveWindow(); });
  await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 150000 }).catch(() => {});
  await p.waitForTimeout(3000);
  await p.evaluate(() => { document.querySelectorAll('canvas').forEach(c => { c.style.visibility = 'hidden'; }); });
  await p.waitForTimeout(500);
  out.walk = await p.screenshot();
  out.cta = await p.evaluate(() => { const c = document.getElementById('vCta'); return { cta: !!(c && !c.hidden), text: c && c.textContent.trim(),
    note: !!document.getElementById('vCtaNote'), trial: document.body.classList.contains('trial') }; });
  for (const k of ['home', 'photo', 'walk']) fs.writeFileSync(path.join(OUT, `${k}-${W}-${tag}.png`), out[k]);
  await ctx.close();
  return out;
}
async function diff(a, b) {
  const ra = await sharp(a).removeAlpha().raw().toBuffer({ resolveWithObject: true }), rb = await sharp(b).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  if (ra.info.width !== rb.info.width || ra.info.height !== rb.info.height) return { px: -1, share: 1 };
  let n = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1; const w = ra.info.width;
  for (let i = 0; i < ra.data.length; i += 3) if (ra.data[i] !== rb.data[i] || ra.data[i + 1] !== rb.data[i + 1] || ra.data[i + 2] !== rb.data[i + 2]) {
    n++; const k = i / 3, x = k % w, y = (k - x) / w; x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return { px: n, share: +(n / (ra.data.length / 3)).toFixed(5), box: n ? [x0, y0, x1, y1] : null };   // рамка отличий — где искать
}
(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const sa = await shots(b, A, 'A'), sb = await shots(b, B, 'B');
    const r = { size, cta: { A: sa.cta, B: sb.cta } };
    for (const k of ['home', 'photo', 'walk']) r[k] = await diff(sa[k], sb[k]);
    r.verdict = ['home', 'photo', 'walk'].every(k => r[k].px === 0) && JSON.stringify(sa.cta) === JSON.stringify(sb.cta) ? 'SAME' : 'DIFF';
    fs.writeFileSync(path.join(OUT, `same-${W}.json`), JSON.stringify(r, null, 1));
    console.log(JSON.stringify(r));
  } catch (e) { console.log('FAIL probe: ' + (e && e.stack || e)); }
  finally { await b.close(); }
})();
