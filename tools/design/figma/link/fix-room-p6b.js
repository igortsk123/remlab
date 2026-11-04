// design-02 П6б (T-20261104-03): мелочи компонентов на странице «Room» (15:10) книги Mobile.
// 1) Card / Room (64:86, 4 варианта): затемнение под подписью фото — как на сайте `.hm-room .hm-ph .ttl`
//    (tools/scout/flat215-demo/index.html:239): linear-gradient(transparent, rgba(0,0,0,.55)) сверху вниз на ряду подписи «Ряд».
// 2) Card / Coming Soon (64:131, 2 варианта): одна смешанная строка «Кухня · 13,2 м²» → ряд «Title» на авто-раскладке
//    (выравнивание по базовой линии) из трёх текстов: title (Bold 15) · разделитель « · » (пробел Bold 15 + «· » Medium 12,5) ·
//    area (Medium 12,5); TEXT-свойства `title`, `area` привязаны к первому и третьему. Описание — строка JSX (naming.json rules.description).
// Повторный запуск безопасен: градиент перезаписывается; ряд «Title» уже есть → пропуск.
// Откат: fills=[] у рядов 64:7/64:28/64:49/64:70; в 64:124/64:129 — вернуть одну строку (стили выше) и удалить свойства.
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('15:10'));
for (const style of ['Bold', 'Medium', 'Semi Bold', 'Regular']) await figma.loadFontAsync({ family: 'Inter', style });
const res = { gradient: [], soon: {}, mutated: [] };

// 1. Градиент.
const grad = [{
  type: 'GRADIENT_LINEAR', gradientTransform: [[0, 1, 0], [-1, 0, 1]],
  gradientStops: [{ position: 0, color: { r: 0, g: 0, b: 0, a: 0 } }, { position: 1, color: { r: 0, g: 0, b: 0, a: 0.55 } }],
}];
for (const id of ['64:7', '64:28', '64:49', '64:70']) {
  const row = await figma.getNodeByIdAsync(id);
  if (!row || row.name !== 'Ряд') throw new Error('row ' + id);
  row.fills = grad; res.gradient.push(id);
}

// 2. Card / Coming Soon.
const set = await figma.getNodeByIdAsync('64:131');
const V = { ink: await figma.variables.getVariableByIdAsync('VariableID:4:5'), muted: await figma.variables.getVariableByIdAsync('VariableID:4:6') };
const paint = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', v)];
const boldStyle = 'S:552cd4148038a00181e309dbe4f6ab896e01611f,';
const mk = (chars, kind) => {
  const t = figma.createText();
  if (kind === 'bold') { t.textStyleId = boldStyle; t.characters = chars; t.fills = paint(V.ink); }
  else { t.fontName = { family: 'Inter', style: 'Medium' }; t.characters = chars; t.fontSize = 12.5; t.lineHeight = { unit: 'PERCENT', value: 150 }; t.letterSpacing = { unit: 'PIXELS', value: 0 }; t.fills = paint(V.muted); }
  t.textAutoResize = 'WIDTH_AND_HEIGHT'; return t;
};
let titleKey = Object.keys(set.componentPropertyDefinitions).find(k => k.startsWith('title#'));
let areaKey = Object.keys(set.componentPropertyDefinitions).find(k => k.startsWith('area#'));
if (!titleKey) titleKey = set.addComponentProperty('title', 'TEXT', 'Кухня');
if (!areaKey) areaKey = set.addComponentProperty('area', 'TEXT', '13,2 м²');
for (const [vid, tid] of [['64:124', '64:122'], ['64:129', '64:127']]) {
  const v = await figma.getNodeByIdAsync(vid);
  if (v.children.some(c => c.name === 'Title')) { res.soon[vid] = 'skip'; continue; }
  const old = await figma.getNodeByIdAsync(tid);
  const segs = old.getStyledTextSegments(['fontName']);
  const name = segs[0].characters.trimEnd();
  const area = segs[1].characters.replace(/^·\s*/, '');
  const oldW = old.width, oldH = old.height;
  const row = figma.createAutoLayout('HORIZONTAL', { name: 'Title' });
  row.fills = []; row.itemSpacing = 0; row.counterAxisAlignItems = 'BASELINE';
  v.insertChild(v.children.indexOf(old), row);
  const tT = mk(name, 'bold'); tT.name = 'title'; row.appendChild(tT);
  const sep = mk(' · ', 'medium'); sep.name = 'Separator';
  sep.setRangeTextStyleId(0, 1, boldStyle); sep.setRangeFills(0, 1, paint(V.ink)); row.appendChild(sep);
  const tA = mk(area, 'medium'); tA.name = 'area'; row.appendChild(tA);
  tT.componentPropertyReferences = { characters: titleKey };
  tA.componentPropertyReferences = { characters: areaKey };
  old.remove();
  res.soon[vid] = { row: row.id, title: tT.id, sep: sep.id, area: tA.id, oldW: Math.round(oldW * 10) / 10, newW: Math.round(row.width * 10) / 10, oldH, newH: row.height, titleNow: tT.characters, areaNow: tA.characters };
  res.mutated.push(vid, row.id, tT.id, sep.id, tA.id);
}
// Проверка «EN не переписан значением RU по умолчанию» (грабля П1: свойство одно на набор).
const en = await figma.getNodeByIdAsync('64:129');
const enT = en.findOne(n => n.name === 'title'), enA = en.findOne(n => n.name === 'area');
res.enAfter = [enT && enT.characters, enA && enA.characters];
const ru = await figma.getNodeByIdAsync('64:124');
res.ruAfter = [ru.findOne(n => n.name === 'title').characters, ru.findOne(n => n.name === 'area').characters];
const cur = set.description.replace(/^&lt;Card&gt;.*?&lt;\/Card&gt;\n?/, '').replace(/^<Card>.*?<\/Card>\n?/, '');
set.description = '<Card title="Кухня" extra="13,2 м²">появится следующим шагом</Card>\n' + cur + '. Свойства: title — название комнаты, area — площадь';
res.desc = set.description; res.keys = [titleKey, areaKey];
return res;
