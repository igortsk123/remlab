// T-93/2: снимки страницы /test/cutout-hd/ на проде — телефон 375×667 и компьютер 1280×900.
const { chromium } = require('/home/pakar/igor/remlab/node_modules/@playwright/test');
(async () => {
  const b = await chromium.launch();
  const out = '/home/pakar/remlab-logs/t93-1119/shots';
  for (const [name, vp] of [['phone', { width: 375, height: 667 }], ['desk', { width: 1280, height: 900 }]]) {
    const p = await b.newPage({ viewport: vp });
    const errs = [];
    p.on('pageerror', e => errs.push(String(e)));
    p.on('response', r => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url()); });
    await p.goto('https://remont-lab.online/test/cutout-hd/', { waitUntil: 'networkidle' });
    await p.screenshot({ path: `${out}/${name}-top.png` });
    await p.evaluate(() => document.querySelector('.pair').scrollIntoView());
    await p.screenshot({ path: `${out}/${name}-pair1.png` });
    const nohd = await p.$('.nohd');
    if (nohd) { await nohd.scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -200)); await p.screenshot({ path: `${out}/${name}-nohd.png` }); }
    for (let y = 0; y < 30000; y += 600) { await p.evaluate(v => window.scrollTo(0, v), y); await p.waitForTimeout(120); }
    await p.waitForLoadState('networkidle');
    const n = await p.$$eval('.pair', a => a.length);
    const broken = await p.$$eval('img', a => a.filter(i => !i.complete || i.naturalWidth === 0).length);
    console.log(name, 'карточек', n, 'битых картинок', broken, 'ошибки', JSON.stringify(errs));
    await p.close();
  }
  await b.close();
})();
