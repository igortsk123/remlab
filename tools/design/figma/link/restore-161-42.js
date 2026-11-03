// design-02 П2а цикл 2 (T-20261103-03/2): восстановление переопределений экземпляра дизайнера 161:42
// («Счастливый путь» 123:2, main = «Лента стилей» 94:44) после замены рамок-вкладок на экземпляры «Вкладки стиля»
// (link-base-pages.js). Снимок «до» — shots/0311-1423-p2a2/before/designer-161-42.json. Дети — по индексу.
// Корневые переопределения (ширина 351, поля 0, переменные) замена детей не трогает.
const WANT = [
  { grow: 1, lsh: 'FILL', visible: true, text: 'Интерьер' },       // было 94:34 (выбранная)
  { grow: 1, lsh: 'FILL', visible: true, text: 'План квартиры' },  // было 94:36
  { visible: false }, { visible: false }, { visible: false },        // было 94:38 / 94:40 / 94:42
];
figma.skipInvisibleInstanceChildren = false;
const page = await figma.getNodeByIdAsync('123:2');
await figma.setCurrentPageAsync(page);
const inst = await figma.getNodeByIdAsync('161:42');
const out = { done: [] };
for (let i = 0; i < WANT.length; i++) {
  const c = inst.children[i], w = WANT[i];
  if (!c) { out.done.push(i + ' нет ребёнка'); continue; }
  c.visible = w.visible;
  if (w.grow != null) { c.layoutGrow = w.grow; c.layoutSizingHorizontal = w.lsh; }
  if (w.text != null) {
    const t = c.findAll(x => x.type === 'TEXT')[0];
    const ref = t.componentPropertyReferences && t.componentPropertyReferences.characters;
    if (ref) c.setProperties({ [ref]: w.text });
    else {
      for (const s of t.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
      t.characters = w.text;
    }
  }
  const t = c.findAll(x => x.type === 'TEXT')[0];
  out.done.push([c.id, c.visible ? 1 : 0, +c.x.toFixed(2), +c.width.toFixed(2), c.layoutGrow, t && t.characters, t && t.fontName.style].join('|'));
}
out.size = [inst.width, inst.height];
return out;
