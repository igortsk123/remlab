// design-02 П6б (T-20261104-03): сборки 01/05 (281:155, 281:245, страница 280:2) — 6+6 карточек Card / Coming Soon
// перевести на TEXT-свойства title / area (раньше — переопределение куска текста 64:122, слоя больше нет).
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('280:2'));
await figma.loadFontAsync({ family: 'Inter', style: 'Bold' }); await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
const AREA = { 'Кухня': '13,2', 'Спальня 1': '17,5', 'Спальня 2': '13,2', 'Санузел 1': '4,4', 'Санузел 2': '3,9', 'Прихожая': '9,3' };
const out = [];
for (const sid of ['281:155', '281:245']) {
  const s = await figma.getNodeByIdAsync(sid);
  for (const i of s.findAllWithCriteria({ types: ['INSTANCE'] }).filter(i => i.name.startsWith('Card / Coming Soon · '))) {
    const n = i.name.replace('Card / Coming Soon · ', '');
    i.setProperties({ 'title#287:0': n, 'area#287:3': AREA[n] + ' м²' });
    const t = i.findOne(x => x.name === 'title'), a = i.findOne(x => x.name === 'area');
    out.push(i.id + ' ' + t.characters + ' · ' + a.characters + ' ov' + i.overrides.length);
  }
}
return out;
