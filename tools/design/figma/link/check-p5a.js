// design-02 П5 (T-20261107-62): ТОЛЬКО ЧТЕНИЕ — сверка ВСЕХ сборок на страницах __PAGES__ (логика check-p6g.js):
// сборка = рамка верхнего уровня, имя не начинается с «эталон». Считаем: свои не-рамки вне экземпляров (должно быть 0),
// оторванные экземпляры (без главного, 0), видимые узлы-картинки вне экземпляров (0). Выдаём итог и только нарушителей.
const out = {};
for (const pid of __PAGES__) {
  const page = await figma.getNodeByIdAsync(pid); await figma.setCurrentPageAsync(page);
  const builds = page.children.filter(n => n.type === 'FRAME' && !/^эталон/.test(n.name) && /^\d\d /.test(n.name));
  let tot = { builds: builds.length, tops: 0, nested: 0, own: 0, broken: 0, imgOwn: 0, imgInInst: 0 }; const bad = [];
  for (const s of builds) {
    let own = 0, broken = 0, imgOwn = 0;
    const walk = async (n, inInst) => {
      for (const c of n.children || []) {
        const img = 'fills' in c && Array.isArray(c.fills) && c.fills.some(f => f.type === 'IMAGE' && f.visible !== false) && c.visible;
        if (inInst) { if (c.type === 'INSTANCE') tot.nested++; if (img) tot.imgInInst++; await walk(c, true); continue; }
        if (c.type === 'INSTANCE') { const m = await c.getMainComponentAsync(); if (!m) broken++; else tot.tops++; await walk(c, true); }
        else { if (c.type !== 'FRAME') own++; if (img) imgOwn++; await walk(c, false); }
      }
    };
    await walk(s, false);
    tot.own += own; tot.broken += broken; tot.imgOwn += imgOwn;
    if (own || broken || imgOwn) bad.push(s.id + ' ' + s.name.slice(0, 20) + ' own=' + own + ' broken=' + broken + ' imgOwn=' + imgOwn);
  }
  out[pid + ' ' + page.name] = JSON.stringify(tot) + (bad.length ? ' НАРУШЕНИЯ: ' + bad.join('; ') : ' — чисто');
}
return out;
