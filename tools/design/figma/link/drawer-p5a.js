// design-02 П5 (T-20261107-62), книга Mobile, страница Drawer (15:46). Пункты 1–3 брифа brief-p5a.md.
// 1) EN-шторка: клип-колонки списка 77:494 / 77:661 / 77:828 (EN collapsed/half/full) — на авто-раскладку, как RU 77:21/77:175/77:329
//    (вертикально, gap 0, поля 0, MIN/MIN, размер прежний FIXED); шкала 77:800 (EN full) — на авто-раскладку, как RU 77:312
//    (поля 6/10/7/10, gap 0, распорки «Отступ» 1×5 и 1×4 — промежутки как были). Вид тот же.
// 2) List / Item Row 76:187 — заголовок (Inter 16, межстрочный 40 px, 1 строка) → Inter Bold, межстрочный 20 px, до 2 строк.
// 3) Drawer / Sheet 77:965 — BOOLEAN `showFinishes` (по умолчанию да): показ входа в группу «Отделка и ремонт» и распорки под ним.
//    Выкл. — список начинается с мебели («раскрытая Мебель», эталон 16).
// Повтор безопасен: каждый шаг проверяет, сделан ли он. Откат: обратные значения из ответа (before).
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('15:46'));
const out = { clip: {}, scale: null, titles: [], prop: null, bound: [] };
// 1
for (const id of ['77:494', '77:661', '77:828']) {
  const c = await figma.getNodeByIdAsync(id);
  if (c.layoutMode !== 'NONE') { out.clip[id] = 'уже AL'; continue; }
  const w = c.width, h = c.height, kids = c.children.map(k => k.id + '@' + Math.round(k.y));
  c.layoutMode = 'VERTICAL'; c.primaryAxisSizingMode = 'FIXED'; c.counterAxisSizingMode = 'FIXED';
  c.itemSpacing = 0; c.paddingTop = c.paddingBottom = c.paddingLeft = c.paddingRight = 0;
  c.primaryAxisAlignItems = 'MIN'; c.counterAxisAlignItems = 'MIN'; c.resize(w, h);
  out.clip[id] = { before: kids.join(','), after: c.children.map(k => k.id + '@' + Math.round(k.y)).join(','), size: Math.round(c.width) + 'x' + Math.round(c.height) };
}
{
  const s = await figma.getNodeByIdAsync('77:800');
  if (s.layoutMode === 'NONE') {
    const before = s.children.map(k => k.id + '@' + Math.round(k.x) + ',' + Math.round(k.y)).join(' ');
    const [a, b, c] = s.children; // Строка сумм 6..26 · Полоса 31..39 · Легенда 43..87, низ 94
    const g1 = Math.round(b.y - (a.y + a.height)), g2 = Math.round(c.y - (b.y + b.height)), pb = Math.round(s.height - (c.y + c.height));
    const w = s.width, pt = Math.round(a.y), pl = Math.round(a.x), pr = Math.round(w - a.x - a.width); // до включения AL (потом x/y = 0)
    s.layoutMode = 'VERTICAL'; s.primaryAxisSizingMode = 'AUTO'; s.counterAxisSizingMode = 'FIXED'; s.itemSpacing = 0;
    s.paddingTop = pt; s.paddingLeft = pl; s.paddingRight = pr; s.paddingBottom = pb; // (первый прогон 07.11 записал 0 → поправлено 6/10/7/10)
    s.primaryAxisAlignItems = 'MIN'; s.counterAxisAlignItems = 'MIN';
    const sp = (hh, at) => { const f = figma.createFrame(); f.name = 'Отступ'; f.fills = []; f.resize(1, hh); s.insertChild(at, f); return f.id; };
    const s1 = sp(g1, 1), s2 = sp(g2, 3);
    s.resize(w, s.height);
    out.scale = { before, gaps: [g1, g2, pb], spacers: [s1, s2], after: s.children.map(k => k.id + '@' + Math.round(k.x) + ',' + Math.round(k.y)).join(' '), size: Math.round(s.width) + 'x' + Math.round(s.height) };
  } else out.scale = 'уже AL';
}
// 2
await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });
await figma.loadFontAsync({ family: 'Inter', style: 'Semi Bold' });
const set = await figma.getNodeByIdAsync('76:187');
for (const v of set.children) {
  const t = v.findAll(n => n.type === 'TEXT' && n.fontSize === 16 && n.lineHeight.unit === 'PIXELS' && (n.lineHeight.value === 40 || (n.lineHeight.value === 20 && n.maxLines === 2)));
  for (const n of t) {
    const b = n.fontName.style + '/' + n.lineHeight.value + '/' + n.maxLines + '/' + Math.round(n.height);
    n.fontName = { family: 'Inter', style: 'Bold' }; n.lineHeight = { unit: 'PIXELS', value: 20 }; n.textTruncation = 'ENDING'; n.maxLines = 2;
    out.titles.push(v.id + ':' + n.id + ' ' + b + ' → Bold/20/2/' + Math.round(n.height) + ' row' + Math.round(v.height));
  }
}
// 3
const sheet = await figma.getNodeByIdAsync('77:965');
let key = Object.keys(sheet.componentPropertyDefinitions).find(k => k.startsWith('showFinishes#'));
if (!key) key = sheet.addComponentProperty('showFinishes', 'BOOLEAN', true);
out.prop = key;
for (const v of sheet.children) {
  const g = v.findOne(n => n.type === 'INSTANCE' && n.mainComponent && ['76:73', '76:79'].includes(n.mainComponent.id));
  if (!g) { out.bound.push(v.id + ' нет входа'); continue; }
  const col = g.parent, sib = col.parent.children, nx = sib[sib.indexOf(col) + 1];
  col.componentPropertyReferences = { visible: key };
  if (nx && nx.name === 'Отступ') nx.componentPropertyReferences = { visible: key };
  out.bound.push(v.id + ':' + col.id + (nx && nx.name === 'Отступ' ? '+' + nx.id : ''));
}
return out;
