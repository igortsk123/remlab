// СТОРОЖ ЯЗЫКА /demo (T-20261112-116, владелец TG 1337/1341: «на английском всегда английские слова, на русском — русские»).
// Обходит страницу как покупатель: опрос, главная, пузырь цены, корзина, каждый вариант комнаты (окно, список, пузырь цены), для
// каждой строки списка — окно подбора («Заменить»), карточку товара из ленты и карточку из списка. На каждом экране собирает ВИДИМЫЙ
// текст (узлы и подписи title/aria-label/placeholder/alt):
//   EN — любой узел с кириллицей = дефект;
//   RU — узел, целиком равный английской фразе словаря страницы (`var EX/ROLE/ROOM/STYLE/ATTR` — служебные слова), = дефект;
//        названия товаров и бренды латиницей не дефект — их нет в словаре;
//   оба языка — символ валюты не той, в которой страница пишет цены (`money`), или «руб» при £.
// Выход — `lang-check.json` (дефекты: экран, текст, где) и строка-итог; rc 1 — есть дефекты. Только чтение, без платного.
//   node tools/ops/demo-walk/lang-check.cjs [BASE=https://remont-lab.online/demo/] OUT [en|ru] [375x667] [--shots]
//   (локальная страница до выкладки — BASE от `stage-proxy.mjs`)
const fs = require('fs');
const path = require('path');
const { demoUrl } = require('../demo-url.cjs');
const root = path.resolve(__dirname, '../../..');
const pw = require(path.join(root, 'node_modules/.pnpm/playwright-core@1.51.1/node_modules/playwright-core'));
const args = process.argv.slice(2).filter(a => !a.startsWith('--')), SHOTS = process.argv.includes('--shots');
const BASE = args[0] || 'https://remont-lab.online/demo/', OUT = (args[1] || '.').replace(/\/?$/, '/'), LANG = args[2] || 'en';
const [W, H] = (args[3] || '375x667').split('x').map(Number), PHONE = W <= 700;
fs.mkdirSync(OUT, { recursive: true });

// английские фразы словаря страницы — служебные слова, которых не должно быть в RU
function enPhrases(html) {
  const out = new Set();
  for (const v of ['ROLE', 'STYLE', 'ROOM', 'EX', 'ATTR']) {
    const m = html.match(new RegExp(`var ${v}=\\{([\\s\\S]*?)\\};`));
    if (!m) continue;
    const body = m[1].replace(/^\s*\/\/[^\n]*$/gm, '');
    for (const x of body.matchAll(/'(?:[^'\\]|\\.)*'\s*:\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")/g)) {
      const s = x[1].slice(1, -1).replace(/\\'/g, "'").trim();
      if (/[A-Za-z]{3}/.test(s) && !/[А-Яа-яЁё]/.test(s)) out.add(s);
    }
  }
  return [...out];
}

(async () => {
  const b = await pw.chromium.launch();
  const ctx = await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, isMobile: PHONE, hasTouch: PHONE,
    locale: LANG === 'en' ? 'en-GB' : 'ru-RU' });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
  await p.addInitScript(() => { try { localStorage.setItem('remlab-sheet-hint-v1', '1'); } catch (e) {} });
  const EN_SET = LANG === 'ru' ? enPhrases(await (await ctx.request.get(BASE)).text()) : [];
  const bad = [], seen = new Set(), screens = [];
  let n = 0;
  // видимый текст экрана: узлы и подписи; EN — кириллица, RU — английская фраза словаря целиком
  const collect = async (screen) => {
    const found = await p.evaluate(({ lang, en }) => {
      const EN = new Set(en), out = [];
      const vis = e => { for (let x = e; x && x !== document.body; x = x.parentElement) { const s = getComputedStyle(x);
        if (s.display === 'none' || s.visibility === 'hidden' || x.hidden) return false; }
        const r = e.getClientRects(); return r.length > 0 && [...r].some(q => q.width > 0 && q.height > 0); };
      const where = e => { const a = []; for (let x = e; x && x !== document.body && a.length < 4; x = x.parentElement)
        a.unshift(x.tagName.toLowerCase() + (x.id ? '#' + x.id : '') + (x.classList.length ? '.' + [...x.classList].slice(0, 2).join('.') : '')); return a.join('>'); };
      // ВАЛЮТА — одна на странице (директор T-116: «Replaced: sofa · +2 000 ₽» в EN при ценах в £): символ цен берём у самой
      // страницы (`money`, валюта — из карточки застройщика, ADR-0254), любой другой символ или «руб» в тексте — дефект
      let cur = ''; try { cur = (String(money(1000)).match(/[₽£€]/) || [''])[0]; } catch (e) { /* страница без цен */ }
      const wrongCur = t => { const m = t.match(/[₽£€]|руб/g); return !!cur && !!m && m.some(x => (x === 'руб' ? '₽' : x) !== cur); };
      const badText = t => wrongCur(t) || (lang === 'en' ? /[А-Яа-яЁё]/.test(t) : EN.has(t.replace(/\s+/g, ' ').trim()));
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let t;
      while ((t = w.nextNode())) {
        const pe = t.parentElement, s = t.nodeValue.trim();
        if (!s || !pe || /SCRIPT|STYLE|NOSCRIPT|TEMPLATE/.test(pe.tagName) || pe.closest('#langSw')) continue;
        if (badText(s) && vis(pe)) out.push({ text: s.slice(0, 160), where: where(pe) });
      }
      for (const e of document.querySelectorAll('[title],[aria-label],[placeholder],[alt]')) {
        if (!vis(e)) continue;
        for (const a of ['title', 'aria-label', 'placeholder', 'alt']) { const v = e.getAttribute(a);
          if (v && badText(v)) out.push({ text: v.slice(0, 160), where: where(e) + '@' + a }); }
      }
      return out;
    }, { lang: LANG, en: EN_SET });
    screens.push(screen);
    for (const f of found) {
      const key = f.text + '|' + f.where.replace(/\[.*?\]/g, '');
      if (seen.has(key)) continue;
      seen.add(key); bad.push({ screen, ...f });
    }
    if (SHOTS && found.length) await p.screenshot({ path: `${OUT}${String(++n).padStart(3, '0')}-${screen.replace(/[^\w.-]+/g, '_').slice(0, 60)}.png` });
  };
  const wait = ms => p.waitForTimeout(ms);
  const tap = async sel => { const l = p.locator(sel).first(); if (!(await l.count())) return false;
    await l.evaluate(e => e.scrollIntoView({ block: 'center' })); await wait(200);
    try { if (PHONE) await l.tap({ timeout: 5000 }); else await l.click({ timeout: 5000 }); } catch (e) { await l.evaluate(e => e.click()); }
    return true; };
  const ready = () => p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });

  // 1. опрос-знакомство (первый экран нового покупателя)
  await p.goto(BASE + (BASE.includes('?') ? '&' : '?') + 'lang=' + LANG + '&live=0&quiz=1', { waitUntil: 'load', timeout: 120000 });
  await ready(); await wait(2500);
  await collect('опрос');
  // 2. главная без опроса
  await p.goto(demoUrl(BASE + (BASE.includes('?') ? '&' : '?') + 'lang=' + LANG + '&live=0'), { waitUntil: 'load', timeout: 120000 });
  await ready(); await wait(2500);
  await collect('главная');
  if (await tap('#hmCert .vpl-i')) { await wait(500); await collect('главная · пузырь цены'); await tap('#hmCert .vpl-i'); await wait(300); }
  try { await p.evaluate(() => window.__basket && window.__basket.open('living')); await wait(1500); await collect('корзина'); } catch (e) { /* нет корзины */ }
  await p.goto(demoUrl(BASE + (BASE.includes('?') ? '&' : '?') + 'lang=' + LANG + '&live=0'), { waitUntil: 'load', timeout: 120000 });
  await ready(); await wait(1500);
  // 3. варианты комнат
  const nv = await p.evaluate(() => allVariants().length);
  for (let vi = 0; vi < nv; vi++) {
    const vid = await p.evaluate(v => { vwOpenVariant(v); return allVariants()[v].id; }, vi);
    try { await p.waitForFunction(() => document.querySelectorAll('#shotbody .pinlist .row').length > 0, null, { timeout: 30000 }); }
    catch (e) { await collect(`вариант ${vid}: окно (списка нет)`); continue; }
    await wait(1200);
    await collect(`вариант ${vid}: окно`);
    if (PHONE) { await p.evaluate(() => { const x = [...document.querySelectorAll('#shot button')].find(e => /Мебель и|Furniture/.test(e.innerText)); if (x) x.click(); }); await wait(1000); }
    await collect(`вариант ${vid}: список`);
    if (await tap('#vsum .vpl-i')) { await wait(400); await collect(`вариант ${vid}: пузырь цены`); await tap('#vsum .vpl-i'); await wait(300); }
    const rows = await p.evaluate(() => [...document.querySelectorAll('#shotbody .pinlist .row')].map(r => ({ k: +r.dataset.k,
      rep: !!r.querySelector('[data-rep]'), name: (shotRows[+r.dataset.k] || {}).name || '' })));
    for (const r of rows) {
      const row = `#shotbody .pinlist .row[data-k="${r.k}"]`;
      // карточка товара из списка
      if (await tap(row + ' .t b')) { await wait(700);
        if (await p.evaluate(() => !!document.querySelector('#itemCard.on, #itemCard:not([hidden])'))) await collect(`вариант ${vid}: карточка «${r.name.slice(0, 40)}»`);
        await p.evaluate(() => { if (typeof itemCardClose === 'function') itemCardClose(); }); await wait(300); }
      if (!r.rep) continue;
      // окно подбора («Заменить») и карточка товара ленты
      await p.evaluate(k => { const x = document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] [data-rep]`); if (x) x.click(); }, r.k);
      try { await p.waitForSelector('#sheet.on #grid .card, #grid .card', { timeout: 15000 }); } catch (e) { /* пустая лента */ }
      await wait(700);
      await collect(`вариант ${vid}: подбор «${r.name.slice(0, 40)}»`);
      if (await tap('#grid .card:not(.cur) img')) { await wait(700); await collect(`вариант ${vid}: карточка ленты «${r.name.slice(0, 40)}»`);
        await p.evaluate(() => { if (typeof itemCardClose === 'function') itemCardClose(); }); await wait(300); }
      await p.evaluate(() => { const x = document.getElementById('sh-close'); if (x && x.offsetParent) x.click(); }); await wait(500);
    }
    fs.writeFileSync(OUT + 'lang-check.json', JSON.stringify({ partial: true, done_variants: vi + 1, bad }, null, 1));   // ход — после каждой комнаты
  }
  const res = { base: BASE, lang: LANG, size: `${W}x${H}`, screens: screens.length, defects: bad.length, page_errors: errs.slice(0, 5), bad };
  fs.writeFileSync(OUT + 'lang-check.json', JSON.stringify(res, null, 1));
  console.log(`${LANG} ${W}x${H}: экранов ${screens.length}, ${LANG === 'en' ? 'узлов с кириллицей' : 'английских служебных слов'} ${bad.length}` +
    (bad.length ? '\n' + bad.slice(0, 40).map(x => `  ${x.screen} · «${x.text}» · ${x.where}`).join('\n') : ''));
  await b.close();
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
