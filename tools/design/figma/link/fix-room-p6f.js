// design-02 П6е (T-20261104-08): книга Desktop, страница Room (9:28) — Card / Room 25:86, все 4 варианта:
// затемнение под подписью фото — как на сайте `.hm-room .hm-ph .ttl` (tools/scout/flat215-demo/index.html:238):
// linear-gradient(transparent, rgba(0,0,0,.55)) сверху вниз на ряду подписи «Ряд» (первая «Колонка» → «Ряд» с текстом).
// Так же сделано в Mobile (fix-room-p6b.js, Card / Room 64:86). Повтор безопасен (заливка перезаписывается).
// Откат: fills=[] у рядов из ответа.
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('9:28'));
const set = await figma.getNodeByIdAsync('25:86');
if (!set || set.type !== 'COMPONENT_SET') throw new Error('set 25:86');
const grad = [{
  type: 'GRADIENT_LINEAR', gradientTransform: [[0, 1, 0], [-1, 0, 1]],
  gradientStops: [{ position: 0, color: { r: 0, g: 0, b: 0, a: 0 } }, { position: 1, color: { r: 0, g: 0, b: 0, a: 0.55 } }],
}];
const res = { rows: [] };
for (const v of set.children) {
  const colm = v.children.find(c => c.type === 'FRAME' && c.name === 'Колонка');
  const row = colm && colm.children.find(c => c.type === 'FRAME' && c.name === 'Ряд' && c.findOne(t => t.type === 'TEXT'));
  if (!row) throw new Error('row in ' + v.id);
  const was = row.fills.length;
  row.fills = grad;
  res.rows.push(v.id + '→' + row.id + ' ' + Math.round(row.width) + 'x' + Math.round(row.height) + ' was=' + was);
}
return res;
