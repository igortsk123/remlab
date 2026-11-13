// «✥» У КАРТИНЫ — ПО СТЕНЕ (T-20261112-97, владелец TG 865: «перемещать вдоль стены, повесить на любую стену»). Бесплатно, на сервер
// ничего не пишется. В 3D выбрать картину → «Переместить» → картина идёт по стене за курсором/пальцем: (1) вдоль той же стены —
// зелёная кайма, поставили — место в `sku.wall_at`, номер состояния и история ↶ сменились, сцена перестроилась и картина там;
// (2) на соседнюю стену — висит на ней лицом в комнату; (3) на окно/дверь — красная кайма и причина, щелчок/касание не вешает;
// (4) тап по полу в режиме картины — картина в руке, ходьба не сломана; «Отмена» — после неё тап по полу ведёт камеру.
//   /demo:  STAGE-прокси (`stage-proxy.mjs`) → BASE=http://127.0.0.1:8797/demo/ OUT=<папка/> node pic-wall-check.cjs 375x667 [V=0]
//   живой:  BASE=https://remont-lab.online/demo/ [PAGE=<свой index.html>] OUT=<папка/> V=-1 node pic-wall-check.cjs 375x667 (LANG_UI=en)
//   тур:    TOUR=<tour.json из trial-tour-data.py> PAGE=<сборка index.html> LIB=<сборка/lib> OUT=… node pic-wall-check.cjs 1280x800
//           (в тур подставляются картины гостиной из DECOR=<demo-data.json>: сборка тура декор пока не кладёт — `trial_bundle.py`)
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '../../..');
const NM = fs.realpathSync(path.join(ROOT, 'node_modules'));
const pick = name => NM + '/.pnpm/' + fs.readdirSync(NM + '/.pnpm').find(d => d.startsWith(name + '@')) + '/node_modules/' + name;
const pw = require(pick('playwright-core'));
const { demoUrl } = require('../demo-url.cjs');
const [W, H] = (process.argv[2] || '1280x800').split('x').map(Number), PHONE = W <= 700;
const OUT = (process.env.OUT || require('os').tmpdir() + '/').replace(/\/?$/, '/'); fs.mkdirSync(OUT, { recursive: true });
const LANG = process.env.LANG_UI || 'ru', TOUR = process.env.TOUR, TAG = (TOUR ? 'tour' : 'demo') + '-' + W;
const R = []; const ok = (n, c, i) => R.push((c ? 'OK  ' : 'FAIL') + ' ' + n + (i === undefined ? '' : ' ' + JSON.stringify(i)));

async function openDemo(b) {
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: 'ru-RU' });
  const p = await ctx.newPage();
  // живой /demo (BASE=https://remont-lab.online/demo/): запись гасится; PAGE=<index.html> — своя страница поверх живых данных и lib
  // (проверка правки до выкладки, T-20261112-97/2); компьютер без видеокарты — признак «слабой» сцены снят флагом __FULL3D (как T-92)
  const PAGE = process.env.PAGE && !TOUR ? fs.readFileSync(process.env.PAGE, 'utf8') : null;
  if (/^https:/.test(process.env.BASE || '')) await p.route('**/*', async r => { const q = r.request(), u = new URL(q.url());
    if (q.method() !== 'GET' || /\/api\/(events|render|job)/.test(u.pathname)) return r.fulfill({ status: 204, body: '' });
    if (PAGE && (u.pathname === '/demo/' || u.pathname === '/demo/index.html')) return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: PAGE });
    if (!PHONE && /\/scene\.[0-9a-f]{12}\.js/.test(u.pathname)) { const res = await r.fetch(); return r.fulfill({ response: res, body: (await res.text()).replace('return/swiftshader|llvmpipe|software|microsoft basic/i.test(', 'return!globalThis.__FULL3D&&/swiftshader|llvmpipe|software|microsoft basic/i.test(') }); }
    return r.continue(); });
  await p.addInitScript(() => { window.__FULL3D = true; try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
  await p.goto(demoUrl((process.env.BASE || 'http://127.0.0.1:8797/demo/') + '?lang=' + LANG + '&quiz=0&live=force'), { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
  return p;
}
async function openTour(b) {
  const esbuild = require(pick('esbuild'));
  const out = esbuild.buildSync({ entryPoints: [path.join(ROOT, 'lib/trial/tour-page.ts')], bundle: true, platform: 'node', format: 'cjs',
    write: false, tsconfig: path.join(ROOT, 'tsconfig.json'), logLevel: 'error' });
  const m = { exports: {} }; new Function('module', 'exports', 'require', out.outputFiles[0].text)(m, m.exports, require);
  const ID = 'T97probeT97probeT97pr0', ORIGIN = 'https://remont-lab.online', TP = `/try/${ID}/tour/`, LIB = process.env.LIB;
  const d = JSON.parse(fs.readFileSync(TOUR, 'utf8')); d.trial = Object.assign({}, d.trial, { job_id: ID, scale: 'verified' });
  const src = JSON.parse(fs.readFileSync(process.env.DECOR, 'utf8')).variants.find(v => (v.decor || []).some(x => /^картина/.test(x.role)));
  const arts = src.decor.filter(x => /^картина/.test(x.role)).map(x => ({ ...x, sku: { ...x.sku, img: '/demo/' + x.sku.img, img_art: x.sku.img_art && '/demo/' + x.sku.img_art } }));
  d.variants.forEach(v => { if ((v.items || []).some(i => /^диван/.test(i.role))) v.decor = arts.map(x => JSON.parse(JSON.stringify(x))); });
  const html = m.exports.injectTour(fs.readFileSync(process.env.PAGE, 'utf8'), ID, 0);
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: 'ru-RU' });
  const p = await ctx.newPage();
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith(TP), async r => {
    const rel = new URL(r.request().url()).pathname.slice(TP.length);
    if (rel === '' || rel === 'index.html') return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    if (rel === 'demo-data.json') return r.fulfill({ status: 200, contentType: 'application/json', headers: { etag: '"v1"' }, body: JSON.stringify(d) });
    if (rel === 'version.json') return r.fulfill({ status: 200, contentType: 'application/json', body: '{"version":0,"bundle":1,"rebuild":null,"rebuildError":null}' });
    if (rel.startsWith('lib/') && fs.existsSync(path.join(LIB, rel.slice(4)))) return r.fulfill({ status: 200, contentType: 'text/javascript', body: fs.readFileSync(path.join(LIB, rel.slice(4))) });
    return r.fulfill({ response: await r.fetch({ url: ORIGIN + '/demo/' + rel + new URL(r.request().url()).search }) });
  });
  await p.route(u => u.origin === ORIGIN && u.pathname.startsWith('/api/'), r => r.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false}' }));
  await p.goto(ORIGIN + TP + `?quiz=0&live=force&lang=${LANG}`, { waitUntil: 'load', timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!D.trial&&typeof allVariants==='function'&&allVariants().length>0", null, { timeout: 90000 });
  return p;
}

// точки стен под сценой (сетка 10 px): где на экране какая стена, вдоль и высота — то, что видит курсор (`scene.wallAt`); только где
// сверху сам холст — под шторкой, полоской переноса и кнопками палец до стены не дойдёт (T-97/2 п.4: касание уходило в кнопку)
const SCAN = `(()=>{const c=LIVE.canvas.getBoundingClientRect(), out=[]; for(let y=c.top+6;y<c.bottom-6;y+=10)for(let x=c.left+6;x<c.right-6;x+=10){
  if(document.elementFromPoint(x,y)!==LIVE.canvas)continue;
  const w=LIVE.scene.wallAt(x,y); if(w)out.push({x,y,wall:w.wall,along:w.along,z:w.z});} return out;})()`;
const ST = `(()=>{const m=VW.mv, j=m?m.j:VW.artJ, x=((allVariants()[cur]||{}).decor||[])[j]||{}; return {mv:!!m, ok:m?m.ok:null, why:m?m.why:null, spot:m?m.spot:null,
  bar:(document.querySelector('#vcarry:not([hidden]) .vct')||{}).textContent||'', at:(x.sku||{}).wall_at||null, id:curStateId(), live:LIVE.state,
  now:LIVE.scene.artSpot(VW.artI), pose:LIVE.scene.pose(), sel:VW.sel};})()`;

(async () => {
  const b = await pw.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errs = [];
  try {
    const p = TOUR ? await openTour(b) : await openDemo(b);
    p.on('pageerror', e => errs.push(String(e).slice(0, 300)));
    const shot = async n => { let last = '';
      for (let k = 0; k < 4; k++) { try { await p.screenshot({ path: `${OUT}${TAG}-${n}.png`, timeout: 30000 }); return; } catch (e) { last = String(e).slice(0, 160); await p.waitForTimeout(1500); } }
      ok(`снимок ${n}`, false, last); };
    // полоска переноса целиком на сцене, «Отмена» внутри неё, текст не под кнопкой
    const barFit = async n => { const r = await p.evaluate(() => { const b = document.getElementById('vcarry'), t = b && b.querySelector('.vct'), x = b && b.querySelector('.vcx');
      if (!b || b.hidden) return null; const R = e => { const c = e.getBoundingClientRect(); return [c.left, c.right, c.top, c.bottom].map(Math.round); };
      return { b: R(b), t: R(t), x: R(x) }; });
      ok(`полоска (${n}): «Отмена» внутри, текст не под ней`, !!r && r.x[0] >= r.b[0] && r.x[1] <= r.b[1] + 1 && r.t[1] <= r.x[0] + 1 && r.b[0] >= 0 && r.b[1] <= W, r); };
    await p.evaluate(v => { const i = v >= 0 ? v : allVariants().findIndex(x => (x.decor || []).some(isWallArt)); vwOpenVariant(i); }, TOUR ? -1 : +(process.env.V || 0));
    await p.evaluate(() => { if (VW.mode !== 'walk') vwMode('walk'); });
    await p.waitForFunction(() => LIVE.scene && LIVE.state === 'ready', null, { timeout: 180000 }); await p.waitForTimeout(2000);
    if (PHONE) { await p.evaluate(() => vwSheet && vwSheet(1)); await p.waitForTimeout(600); }
    const info = await p.evaluate(() => { const ds = (allVariants()[cur] || {}).decor || [], j = ds.findIndex(isWallArt), i = vwDecIndex(j);
      VW.artJ = j; VW.artI = i; return { j, i, spot: LIVE.scene.artSpot(i), room: (({ w, d, openings }) => ({ w, d, openings }))(curRoom()), h: (vwItemAt(i) || {}).h }; });
    ok('картина висит на стене (есть место в сцене)', !!info.spot, info.spot);
    if (!info.spot) throw new Error('нет картины');
    // встать посреди комнаты (ближайшее место, где можно стоять) — от стены соседние стены и дверь у плеча не видны; до «взять»
    // тур — квартира из нескольких комнат, план комнаты сдвинут от угла квартиры: там встаём, где камера стояла при открытии (в комнате)
    const home = TOUR ? await p.evaluate(() => { const q = LIVE.scene.pose(); return { x: q.x, y: q.y }; }) : { x: info.room.w / 2, y: info.room.d / 2 };
    const start = async () => p.evaluate(h => { if (VW.mv) vwCarryCancel(); LIVE.scene.setWalk({ x: h.x, y: h.y, rot: 0 });
      vwSelect(VW.artI); return vwCarryStart(); }, home).then(async v => { await p.waitForTimeout(800); return v; });
    const st = () => p.evaluate(ST);
    // повернуть камеру, пока стена wall (и место along ± 60) не окажется в кадре
    const face = async (wall, along) => {
      let best = null;
      for (let k = 0; k < 12; k++) {
        const pts = (await p.evaluate(SCAN)).filter(q => q.wall === wall && (along == null || Math.abs(q.along - along) < 60));
        if (!best || pts.length > best.n) best = { n: pts.length, k };
        if (pts.length > 150) return pts;
        await p.evaluate(() => LIVE.scene.turn(30)); await p.waitForTimeout(500);
      }
      await p.evaluate(n => LIVE.scene.turn(30 * n), (best.k - 12 + 24) % 12); await p.waitForTimeout(600);
      return (await p.evaluate(SCAN)).filter(q => q.wall === wall && (along == null || Math.abs(q.along - along) < 60));
    };
    const near = (pts, along, z) => pts.slice().sort((a, c) => Math.hypot(a.along - along, a.z - z) - Math.hypot(c.along - along, c.z - z))[0];
    // «повесить сюда»: телефон — касание стены (тот же путь, что пальцем), компьютер — курсор и щелчок
    const hangAtPt = async q => { if (PHONE) await p.touchscreen.tap(q.x, q.y); else { await p.mouse.move(q.x, q.y); await p.waitForTimeout(200); await p.mouse.click(q.x, q.y); } await p.waitForTimeout(400); };
    const hover = async q => { if (PHONE) await p.evaluate(([x, y]) => vwArtAt(x, y), [q.x, q.y]); else await p.mouse.move(q.x, q.y); await p.waitForTimeout(500); };
    const settle = () => p.waitForFunction(() => LIVE.state === 'ready', null, { timeout: 120000 }).then(() => p.waitForTimeout(1200));

    // 0. ЖЕСТ ПАЛЬЦЕМ (телефон): настоящие касания (CDP touchStart/Move/End), от середины картины на треть ширины экрана в сторону, где
    // стена дальше свободна. Картина идёт за пальцем по стене: сдвиг в руке ≥ 45 см (повесить ли там — правило стены, не жест)
    if (PHONE) {
      ok('взяли картину (жест)', await start()); await face(info.spot.wall, info.spot.along);
      const c = await p.evaluate(i => { const pn = (LIVE.scene.pins() || []).find(q => q.index === i), cr = LIVE.canvas.getBoundingClientRect();
        return pn && pn.box ? [cr.left + (pn.box[0] + pn.box[2]) / 2, cr.top + (pn.box[1] + pn.box[3]) / 2] : null; }, info.i);
      const idg = (await st()).id;
      if (c) { const cdp = await p.context().newCDPSession(p), dx = Math.round(W * 0.33) * (c[0] > W / 2 ? -1 : 1), t0 = info.spot;
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: c[0], y: c[1] }] });
        for (let k = 1; k <= 12; k++) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: c[0] + dx * k / 12, y: c[1] }] }); await p.waitForTimeout(25); }
        const g = await st(); await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await p.waitForTimeout(500);
        const d = g.spot ? Math.abs(g.spot.along - t0.along) : 0;
        ok(`жест пальцем на треть экрана (${Math.abs(dx)} px): картина в руке сдвинулась вдоль стены ≥ 45 см`, g.mv && !!g.spot && g.spot.wall === info.spot.wall && d >= 45, { сдвиг: Math.round(d), why: g.why, spot: g.spot });
        await shot('3b-gesture');
        await settle().catch(() => {}); await p.evaluate(id => { if (VW.mv) vwCarryCancel(); if (curStateId() !== id) histBack(); }, idg); await settle().catch(() => {});
      } else ok('картина на экране для жеста', false);
    }

    // 1. вдоль той же стены
    const s0 = info.spot, id0 = (await st()).id;
    ok('взяли картину «Переместить»', await start());
    let pts = await face(s0.wall, s0.along);
    pts = (await p.evaluate(SCAN)).filter(q => q.wall === s0.wall);
    if (!pts.length) { await p.waitForTimeout(1500); await face(s0.wall, null); pts = (await p.evaluate(SCAN)).filter(q => q.wall === s0.wall); }
    // СКОЛЬКО ДАЁТ СТЕНА (T-20261112-97/2): свободные места по правилу сцены (`scene.artDrag`, то же, что у жеста), шаг 5 см на высоте
    // картины. В гостиной /demo у картины с одной стороны вторая картина пары, с другой торшер: свободно 75–130 при месте 120 — сдвиг
    // больше 45 там нельзя по правилу, и прежний критерий «≥ 25 по ближней видимой точке» давал ложный FAIL «16 см за жест»
    const reach = await p.evaluate(s0 => { const R = curRoom(), L = /north|south/.test(s0.wall) ? R.w : R.d; let lo = 0, hi = 0;
      for (let a = 5; a <= 120; a += 5) { const r = LIVE.scene.artDrag({ wall: s0.wall, along: s0.along + a, elev: s0.elev }); if (s0.along + a > L || !r || r.why) break; hi = a; }
      for (let a = 5; a <= 120; a += 5) { const r = LIVE.scene.artDrag({ wall: s0.wall, along: s0.along - a, elev: s0.elev }); if (s0.along - a < 0 || !r || r.why) break; lo = a; }
      LIVE.scene.artDrag(s0); return { lo, hi }; }, s0);
    R.push('INFO стена картины свободна от места: −' + reach.lo + ' / +' + reach.hi + ' см');
    // камера — к свободной стороне стены (на 375 и при другом ракурсе стена видна кусками); цель по высоте — середина картины
    // (`vwArtAt`: середина под курсором → низ = z − h/2), а не выше: там свободной стены в кадре меньше
    const side = reach.lo >= reach.hi ? -1 : 1, zc = s0.elev + info.h / 2;
    if (Math.max(reach.lo, reach.hi) >= 20) { await face(s0.wall, s0.along + side * Math.max(reach.lo, reach.hi) * 0.6); const p2 = (await p.evaluate(SCAN)).filter(q => q.wall === s0.wall);
      if (p2.length) pts = p2; else { await face(s0.wall, s0.along); pts = (await p.evaluate(SCAN)).filter(q => q.wall === s0.wall); } }
    const seen = pts.filter(q => Math.abs(q.z - zc) <= 15 && q.along >= s0.along - reach.lo && q.along <= s0.along + reach.hi).reduce((m, q) => Math.max(m, Math.abs(q.along - s0.along)), 0);
    const need = Math.round(Math.min(45, Math.max(reach.lo, reach.hi), seen) - 5);
    R.push('INFO свободное место в кадре до ' + Math.round(seen) + ' см → порог ' + need);
    // в свободную сторону: у пары соседняя картина рядом — к ней нельзя («Мешает другая картина»), это и есть правило
    let t1 = null, s = null;
    const das = [reach.hi >= reach.lo ? Math.min(reach.hi, 70) : -Math.min(reach.lo, 70), reach.hi >= reach.lo ? -Math.min(reach.lo, 70) : Math.min(reach.hi, 70), 45, -45, 30, -30].filter(d => d);
    for (const da of das) {
      const q = near(pts, s0.along + da, zc);
      if (!q) continue;
      await hover(q); s = await st();
      if (s.ok) { t1 = q; break; }
      if (!R.some(x => /к соседней картине/.test(x))) ok('к соседней картине пары — нельзя, причина на полоске', s.why !== 'art' || /картина/.test(s.bar), { why: s.why, bar: s.bar });
    }
    if (!pts.length) throw new Error('стена картины не в кадре: ' + JSON.stringify(await p.evaluate(() => ({ mv: !!VW.mv, pose: LIVE.scene.pose(),
      c: LIVE.scene.wallAt(innerWidth / 2, innerHeight / 3) }))));
    if (!t1) t1 = near(pts, s0.along + 45, s0.elev + info.h / 2 + 15);
    ok(`вдоль стены: зелёная кайма, та же стена, сдвиг ≥ ${need} см (45 или сколько даёт стена в кадре)`, s.mv && s.ok && s.spot.wall === s0.wall && Math.abs(s.spot.along - s0.along) >= need, s);
    await barFit('вдоль стены'); await shot('1-along');
    if (PHONE) await p.evaluate(() => vwCarryDrop()); else await p.mouse.click(t1.x, t1.y);
    await settle(); s = await st();
    ok('повесили: место в товаре, номер состояния другой, сцена — там же', !s.mv && s.at && s.at.wall === s0.wall && s.id !== id0 && s.now
      && Math.abs(s.now.along - s.at.along) < 1 && Math.abs(s.now.elev - s.at.elev) < 1, { at: s.at, now: s.now, live: s.live });
    await shot('1-along-hung');
    const id1 = s.id, at1 = s.at;
    // история: ↶ — картина там, где была; ↷ — снова на новом месте
    await p.evaluate(() => histBack()); await settle(); s = await st();
    ok('↶: прежнее место', !s.at && s.now && Math.abs(s.now.along - s0.along) < 1 && s.id === id0, { at: s.at, now: s.now });
    await p.evaluate(() => histFwd()); await settle(); s = await st();
    ok('↷: снова новое место', s.at && s.at.along === at1.along && s.id === id1, s.at);

    // 2. соседняя стена
    const ADJ = { south: ['west', 'east'], north: ['west', 'east'], west: ['south', 'north'], east: ['south', 'north'] }[s0.wall];
    let done = false;
    for (const wall of ADJ) {
      ok(`взяли снова (${wall})`, await start());
      pts = await face(wall, null);
      const cand = (await p.evaluate(SCAN)).filter(q => q.wall === wall && q.z > 130 && q.z < 185);
      cand.sort((a, c) => Math.abs(a.x - W / 2) - Math.abs(c.x - W / 2));
      // 90 точек по всей видимой стене (на 1280 точек тысячи: каждая вторая из ближних к середине не доставала до свободного места)
      const stepK = Math.max(2, Math.ceil(cand.length / 90));
      for (const q of cand.filter((_, k) => k % stepK === 0).slice(0, 90)) {
        await p.evaluate(([x, y]) => vwArtAt(x, y), [q.x, q.y]);
        if ((await st()).ok) { await hover(q); s = await st(); if (!s.ok) continue;
          await shot('2-adjacent'); await hangAtPt(q); await settle(); s = await st();
          ok(`на соседнюю стену (${wall}): висит там лицом в комнату`, !s.mv && s.at && s.at.wall === wall && s.now && s.now.wall === wall, { at: s.at, now: s.now });
          await shot('2-adjacent-hung'); done = true; break; }
      }
      if (done) break;
      await p.evaluate(() => vwCarryCancel());
    }
    ok('нашлась свободная соседняя стена', done);

    // 3. окно и дверь — красная кайма, причина, не вешается
    for (const kind of ['window', 'door']) {
      const o = (info.room.openings || []).find(x => x.kind === kind || (kind === 'window' && x.kind === 'balcony'));
      if (!o) { ok(`${kind}: в комнате нет — пропуск`, true); continue; }
      const mid = o.offset_cm + o.width_cm / 2;
      ok(`взяли снова (${kind})`, await start());
      const before = await st();
      pts = await face(o.wall, mid);
      const q = near((await p.evaluate(SCAN)).filter(x => x.wall === o.wall), mid, kind === 'window' ? (o.sill_cm || 90) + 60 : 150);
      if (!q) { ok(`${kind}: стена не в кадре`, false); await p.evaluate(() => vwCarryCancel()); continue; }
      await hover(q); s = await st();
      ok(`${kind}: красная кайма и причина на полоске`, s.mv && !s.ok && ['opening', 'swing'].includes(s.why) && /окно|двер|window|door/i.test(s.bar), { why: s.why, bar: s.bar, spot: s.spot });
      await barFit(kind); await shot(`3-${kind}-refused`);
      await hangAtPt(q); s = await st();
      ok(`${kind}: щелчок/касание не вешает — картина в руке, место прежнее`, s.mv && JSON.stringify(s.at) === JSON.stringify(before.at), { mv: s.mv, at: s.at });
      await p.evaluate(() => vwCarryCancel());
    }

    // 4. тап по полу в режиме картины и после «Отмены»
    const sheet0 = PHONE ? await p.evaluate(() => { if (VW.mv) vwCarryCancel(); return document.getElementById('vside').dataset.pos; }) : null;
    ok('взяли снова (пол)', await start());
    const floor = await p.evaluate(() => { const c = LIVE.canvas.getBoundingClientRect();
      for (let y = c.bottom - 20; y > c.top; y -= 12) for (let x = c.left + 20; x < c.right - 20; x += 24)
        if (document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.floorAt(x, y) && !LIVE.scene.wallAt(x, y)) return [x, y];
      return null; });
    const pose0 = (await st()).pose, at0 = (await st()).at;
    if (floor) {
      if (PHONE) await p.touchscreen.tap(floor[0], floor[1]); else await p.mouse.click(floor[0], floor[1]);
      await p.waitForTimeout(900); s = await st();
      ok('тап по полу с картиной в руке: картина в руке, место и камера не сбились', s.mv && JSON.stringify(s.at) === JSON.stringify(at0)
        && Math.hypot(s.pose.x - pose0.x, s.pose.y - pose0.y) < 1, { mv: s.mv, pose: s.pose });
      const xr = await p.evaluate(() => { const r = document.querySelector('#vcarry .vcx').getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
        const top = document.elementFromPoint(x, y); return { r: [r.left, r.top, r.right, r.bottom].map(Math.round), vh: innerHeight, sy: scrollY, top: top ? top.className || top.tagName : null }; });
      ok('«Отмена» на экране и сверху', xr.r[1] >= 0 && xr.r[3] <= xr.vh && /vcx/.test(xr.top), xr);
      // T-97/2 п.2: шторку подняли до верха с предметом в руке — она встаёт на средней, «Отмена» остаётся на экране (мебель — тот же путь)
      if (PHONE) { await p.evaluate(() => vwSheet(3)); await p.waitForTimeout(700);
        const up = await p.evaluate(() => { const r = document.querySelector('#vcarry .vcx').getBoundingClientRect(), t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { r: [r.left, r.top, r.right, r.bottom].map(Math.round), pos: document.getElementById('vside').dataset.pos, top: t ? t.className || t.tagName : null }; });
        ok('шторку подняли с картиной в руке: шторка не выше средней, «Отмена» на экране', up.pos !== '3' && up.r[1] >= 0 && /vcx/.test(up.top), up); }
      await p.evaluate(() => document.querySelector('#vcarry .vcx').click()); await p.waitForTimeout(400);
      s = await st(); ok('«Отмена»: картина не в руке, место то же', !s.mv && JSON.stringify(s.at) === JSON.stringify(at0));
      // T-20261112-97/2: «Отмена» — шторка там же, где была при «✥» (с картиной в руке её поднимали — после отмены не остаётся поднятой)
      if (PHONE) { await p.waitForTimeout(500); const pos = await p.evaluate(() => document.getElementById('vside').dataset.pos);
        ok(`«Отмена»: шторка как до «✥» (была ${sheet0}, стала ${pos})`, pos === sheet0, { sheet0, pos }); }
      await p.evaluate(() => vwSelect(null)); await p.waitForTimeout(300);
      // пол посередине кадра (крайние 20 % — поворот), сверху холст, а не кнопки поверх него
      const fl2 = await p.evaluate(() => { const c = LIVE.canvas.getBoundingClientRect();
        // дальний пол — сверху вниз: ближний (у ног, у шторки) ходьба по правилу не берёт — цель ближе 20 см или за столиком (`viewer.goTo`)
        for (let y = c.top + 10; y < c.bottom; y += 10) for (const fx of [0.5, 0.4, 0.6, 0.3, 0.7]) { const x = c.left + (c.right - c.left) * fx;
          // не у самого верха шторки: касание там Chrome «доводит» до её шапки, а шапка такое касание гасит (TG 1175) — ни шага, ни шторки
          if ((!VW_PHONE() || y < document.getElementById('vside').getBoundingClientRect().top - 40) && document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.floorAt(x, y) && LIVE.scene.pick(x, y) < 0) return [x, y]; }
        return null; });
      if (!fl2) throw new Error('пол в кадре после «Отмены» не нашёлся');
      if (PHONE) await p.touchscreen.tap(fl2[0], fl2[1]); else await p.mouse.click(fl2[0], fl2[1]);
      await p.waitForTimeout(2500); s = await st();
      ok('после «Отмены» тап по полу ведёт камеру (ходьба жива)', Math.hypot(s.pose.x - pose0.x, s.pose.y - pose0.y) > 5, { from: pose0, to: s.pose });
    } else ok('пол в кадре не нашёлся', false);
    await shot('4-after-cancel');
  } catch (e) { ok('проба упала', false, String(e).slice(0, 400)); }
  ok('без ошибок страницы', !errs.length, errs.slice(0, 5));
  await b.close();
  const txt = R.join('\n'); fs.writeFileSync(`${OUT}${TAG}-result.txt`, txt + '\n'); console.log(txt);
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})();
