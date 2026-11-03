// design-02 П2а (T-20261103-03/2): для узлов-образцов (RU) найти «близнецов» в EN-варианте того же набора
// (та же метка remlab/css) — тексты и размеры. Только чтение. Одна страница на вызов: PAGE_ID + IDS.
const PAGE_ID = '18:27';
const IDS = ['83:22'];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = {};
for (const id of IDS) {
  const n = await figma.getNodeByIdAsync(id);
  let v = n; while (v && !(v.type === 'COMPONENT' && v.parent && v.parent.type === 'COMPONENT_SET')) v = v.parent;
  if (!v) { out[id] = 'нет варианта'; continue; }
  const css = n.getSharedPluginData('remlab', 'css');
  const ruHits = v.findAll(x => x.getSharedPluginData('remlab', 'css') === css);
  const idx = ruHits.indexOf(n);
  const want = v.name.replace(/Язык=RU/, 'Язык=EN');
  const en = v.parent.children.find(c => c.name === want);
  const enHits = en ? en.findAll(x => x.getSharedPluginData('remlab', 'css') === css) : [];
  const e = enHits[idx];
  const txt = x => x ? x.findAll(t => t.type === 'TEXT').map(t => t.characters).join(' | ') : null;
  out[id] = { css, variant: v.id + ' ' + v.name, ru: { w: n.width, h: n.height, txt: txt(n) }, en: e ? { id: e.id, w: e.width, h: e.height, txt: txt(e) } : null };
}
return out;
