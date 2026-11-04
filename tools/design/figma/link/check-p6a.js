// design-02 П6а: ТОЛЬКО ЧТЕНИЕ — сверка сборок 281:155 / 281:245 на странице «Screens RU (components)» (280:2).
// Для каждой сборки: свои узлы вне экземпляров (по типам), экземпляры верхнего уровня (имя → набор/вариант),
// узлы-картинки (где лежат), экземпляры без главного (оторванные), переопределения.
const page = await figma.getNodeByIdAsync('280:2');
await figma.setCurrentPageAsync(page);
const res = {};
for (const id of ['281:155', '281:245']) {
  const s = await figma.getNodeByIdAsync(id);
  const own = {}; const tops = []; const imgs = []; let nested = 0, broken = 0;
  const inInst = n => { for (let p = n.parent; p && p !== s; p = p.parent) if (p.type === 'INSTANCE') return true; return false; };
  for (const n of s.findAll(() => true)) {
    const ii = inInst(n);
    if ('fills' in n && Array.isArray(n.fills) && n.fills.some(f => f.type === 'IMAGE' && f.visible !== false) && n.visible)
      imgs.push(n.name + (ii ? ' (в экз.)' : ' (СВОЙ)'));
    if (ii) { if (n.type === 'INSTANCE') nested++; continue; }
    if (n.type === 'INSTANCE') {
      const m = await n.getMainComponentAsync();
      if (!m) { broken++; continue; }
      const set = m.parent && m.parent.type === 'COMPONENT_SET' ? m.parent : m;
      tops.push(set.name + ' [' + m.name + ']' + (n.overrides.length ? ' ov' + n.overrides.length : ''));
    } else own[n.type] = (own[n.type] || 0) + 1;
  }
  const uiOwn = Object.entries(own).filter(([t]) => t !== 'FRAME').reduce((a, [, v]) => a + v, 0);
  res[s.name] = { own, ownLeafNonFrame: uiOwn, topInstances: tops.length, nestedInstances: nested, broken, share: (tops.length / (tops.length + uiOwn)).toFixed(2), imgs, tops };
}
return res;
