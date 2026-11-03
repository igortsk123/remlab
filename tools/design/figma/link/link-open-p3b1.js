// design-02 П3б (T-20261103-08, помощник p3b1, книга Desktop): «Открыть» в «Избранное/Карточка расстановки» (48:1708).
// Рамка-рисунок button.btn здесь БЕЗ авто-раскладки (текст 197 px по центру, y=13 в рамке 237x38), а база
// «Кнопки/Кнопка» вариант «Обычная» (92:4 RU / 92:10 EN) — с авто-раскладкой, поэтому общий link-p3b1.js её пропускает
// («раскладка»). Здесь: экземпляр того же места и размера (FIXED 237x38), текст — через свойство «Текст» (или
// переопределением, если у варианта текст не привязан), отступы экземпляра подогнаны так, чтобы надпись стояла там же:
// сверху = y текста (13), снизу = 38 − 13 − 19 = 6, слева/справа = как у рамки (20/20). Сверка: центр надписи по X и
// её верх по Y совпадают со старыми (±0,05), иначе экземпляр удаляется, рамка остаётся. Вывод наружу (expose).
// Повторный запуск безопасен (ищутся только FRAME с меткой). Страница «Избранное» 8:34.
const PAGE_ID = '8:34';
const SET_ID = '48:1708';
const BASE = { RU: '92:4', EN: '92:10' };
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const set = await figma.getNodeByIdAsync(SET_ID);
const out = { done: [], errors: [] };
const D = 0.05;
for (const v of set.children) {
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  const olds = v.findAll(n => n.type === 'FRAME' && !n.id.startsWith('I') && n.getSharedPluginData('remlab', 'css') === 'button.btn');
  for (const old of olds) {
    const ot = old.findAll(x => x.type === 'TEXT')[0];
    const parent = old.parent, idx = parent.children.indexOf(old);
    const base = await figma.getNodeByIdAsync(BASE[lang]);
    const inst = base.createInstance();
    parent.insertChild(idx, inst);
    inst.name = 'Кнопка «Открыть»';
    inst.resize(old.width, old.height);
    inst.layoutSizingHorizontal = old.layoutSizingHorizontal; inst.layoutSizingVertical = old.layoutSizingVertical;
    inst.layoutGrow = old.layoutGrow; inst.layoutAlign = old.layoutAlign; inst.constraints = old.constraints;
    inst.paddingLeft = ot.x; inst.paddingRight = old.width - ot.x - ot.width;
    inst.paddingTop = ot.y; inst.paddingBottom = old.height - ot.y - ot.height;
    const it = inst.findAll(x => x.type === 'TEXT')[0];
    const ref = it.componentPropertyReferences && it.componentPropertyReferences.characters;
    if (it.characters !== ot.characters) {
      if (ref) inst.setProperties({ [ref]: ot.characters });
      else { await figma.loadFontAsync(it.fontName); it.characters = ot.characters; }
    }
    const it2 = inst.findAll(x => x.type === 'TEXT')[0];
    const oc = ot.x + ot.width / 2, ic = it2.x + it2.width / 2;
    const ok = Math.abs(oc - ic) < D && Math.abs(ot.y - it2.y) < D && Math.abs(inst.width - old.width) < 0.01 && Math.abs(inst.height - old.height) < 0.01
      && it2.characters === ot.characters;
    if (!ok) { out.errors.push(v.id + ' ' + old.id + ' центр ' + oc + '/' + ic + ' y ' + ot.y + '/' + it2.y + ' ' + inst.width + 'x' + inst.height); inst.remove(); continue; }
    for (const k of old.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
    inst.isExposedInstance = true;
    const oldId = old.id;
    old.remove();
    out.done.push(v.id + ' ' + oldId + ' → ' + inst.id + ' (' + base.id + ')' + (ref ? ' prop' : ' chars'));
  }
}
return out;
