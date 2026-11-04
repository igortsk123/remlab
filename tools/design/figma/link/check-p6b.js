// design-02 П6б: ТОЛЬКО ЧТЕНИЕ — сверка сборок на странице __PAGE__ (ids __IDS__).
// Для каждой сборки: свои узлы вне экземпляров (по типам; FRAME — рамки раскладки), свои не-рамки (должно быть 0),
// экземпляры верхнего уровня, вложенные, оторванные (без главного), узлы-картинки (СВОЙ = вне экземпляра — должно быть 0).
const page = await figma.getNodeByIdAsync('__PAGE__');
await figma.setCurrentPageAsync(page);
const res = {};
for (const id of __IDS__) {
  const s = await figma.getNodeByIdAsync(id);
  const own = {}; let tops = 0, nested = 0, broken = 0, imgOwn = 0, imgInInst = 0;
  const inInst = n => { for (let p = n.parent; p && p !== s; p = p.parent) if (p.type === 'INSTANCE') return true; return false; };
  for (const n of s.findAll(() => true)) {
    const ii = inInst(n);
    if ('fills' in n && Array.isArray(n.fills) && n.fills.some(f => f.type === 'IMAGE' && f.visible !== false) && n.visible) { if (ii) imgInInst++; else imgOwn++; }
    if (ii) { if (n.type === 'INSTANCE') nested++; continue; }
    if (n.type === 'INSTANCE') { const m = await n.getMainComponentAsync(); if (!m) broken++; else tops++; }
    else own[n.type] = (own[n.type] || 0) + 1;
  }
  const ownNonFrame = Object.entries(own).filter(([t]) => t !== 'FRAME').reduce((a, [, v]) => a + v, 0);
  res[s.name.slice(0, 2)] = [id, 'frames=' + (own.FRAME || 0), 'ownNonFrame=' + ownNonFrame, 'top=' + tops, 'nested=' + nested, 'broken=' + broken, 'imgOwn=' + imgOwn, 'imgInInst=' + imgInInst].join(' ');
}
return res;
