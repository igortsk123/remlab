// design-02 П6д (T-20261104-07): недостающие варианты для экранов «Избранное» — книга Desktop, страница Favorites 8:34
// (копия variants-p6d.js с id Desktop; как в Mobile П6в).
// 1) Card / Layout 48:1708: state=included + photo=false (RU budget=total из 48:1604, EN budget=split из 48:1681) — первая
//    «Колонка» (фото) заменяется копией «Колонки» с надписью «Откройте — покажем в 3D» из excluded-варианта (48:1629 / 48:1706).
// 2) Tag / Room Filter 48:1551: checked=false (RU/EN) — копия checked=true с заливкой/обводкой/цветом текста невыбранного
//    чипа-фильтра 43:88 (RU) / 43:96 (EN), как невыбранные чипы на сайте.
// Повторный запуск: варианты с теми же именами не создаются второй раз. Откат: удалить созданные варианты (id в ответе).
const page = await figma.getNodeByIdAsync('8:34');
await figma.setCurrentPageAsync(page);
for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const out = { created: [], skipped: [] };
const get = id => figma.getNodeByIdAsync(id);

const card = await get('48:1708');
const CARD = [['48:1604', '48:1629', 'lang=ru, state=included, budget=total, photo=false'],
              ['48:1681', '48:1706', 'lang=en, state=included, budget=split, photo=false']];
let cx = Math.max(...card.children.map(c => c.x + c.width)) + 48;
for (const [srcId, phId, name] of CARD) {
  if (card.children.some(c => c.name === name)) { out.skipped.push(name); continue; }
  const src = await get(srcId), ph = await get(phId);
  const v = src.clone(); card.appendChild(v); v.name = name;
  const old = v.children[0]; const neu = ph.children[0].clone();
  v.insertChild(0, neu); old.remove();
  v.x = cx; v.y = src.y;
  out.created.push(v.id + ' ' + name + ' ' + Math.round(v.width) + 'x' + Math.round(v.height));
}
card.resizeWithoutConstraints(Math.max(...card.children.map(c => c.x + c.width)) + 24, card.height);

const tag = await get('48:1551');
const TAG = [['48:1545', '43:88', 'lang=ru, checked=false'], ['48:1549', '43:96', 'lang=en, checked=false']];
let tx = Math.max(...tag.children.map(c => c.x + c.width)) + 48;
for (const [srcId, refId, name] of TAG) {
  if (tag.children.some(c => c.name === name)) { out.skipped.push(name); continue; }
  const src = await get(srcId), ref = await get(refId);
  const v = src.clone(); tag.appendChild(v); v.name = name;
  v.fills = ref.fills; v.strokes = ref.strokes; v.strokeWeight = ref.strokeWeight; v.strokeAlign = ref.strokeAlign;
  const rt = ref.findOne(n => n.type === 'TEXT'), vt = v.findOne(n => n.type === 'TEXT');
  vt.fills = rt.fills; if (rt.textStyleId && rt.textStyleId !== figma.mixed && !vt.textStyleId) { /* стиль текста — как был у чипа */ }
  v.x = tx; v.y = src.y;
  out.created.push(v.id + ' ' + name + ' ' + Math.round(v.width) + 'x' + Math.round(v.height));
}
tag.resizeWithoutConstraints(Math.max(...tag.children.map(c => c.x + c.width)) + 24, tag.height);
out.props = { card: Object.keys(card.componentPropertyDefinitions), tag: Object.entries(tag.componentPropertyDefinitions).map(([k, d]) => k + (d.variantOptions ? '[' + d.variantOptions + ']' : '')) };
return out;
