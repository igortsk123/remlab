// design-02 П2а цикл 2 (T-20261103-03/2): связывание наборов на БАЗОВЫХ страницах — рамки «как кнопка» внутри
// наборов → экземпляры базовых компонентов. Образец — link-room-card.js; отличие: текст старой рамки переносится в
// экземпляр (через свойство, если текст базы к нему привязан, иначе прямой правкой characters), размер — как у старой
// рамки (FIXED: ширина с сайта; hug базы дал бы +1…+5 px). Набор и варианты НЕ пересоздаются (id сохраняются).
// Повторный запуск безопасен: ищутся только FRAME с меткой remlab/css. Одна страница на вызов: CONF[PAGE_ID].
//
// ВНИМАНИЕ: «Лента стилей» 94:44 — главный компонент экземпляра дизайнера 161:42 («Счастливый путь» 123:2). Замена
// детей сбрасывает его переопределения по старым id → после запуска восстановить restore-161-42.js (снимок «до» —
// shots/0311-1423-p2a2/before/designer-161-42.json).
const PAGE_ID = '15:104';
const CONF = {
  '15:104': { set: '94:85', pairs: [                                     // Вкладки стилей / Лента стилей
    { css: 'button.hm-tab.on', base: '94:104', variant: { RU: '94:90', EN: '94:98' },  name: 'Вкладка', expose: true },
    { css: 'button.hm-tab',    base: '94:104', variant: { RU: '94:94', EN: '94:102' }, name: 'Вкладка', expose: true },
  ] },
  '15:118': { set: '89:22', pairs: [                                     // Уведомление: кнопка действия = Ссылка/Жирная
    { css: 'button.toastact',  base: '107:60', variant: { RU: '221:119', EN: '221:122' }, name: 'Действие', expose: true },
  ] },
};
const C = CONF[PAGE_ID];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const set = await figma.getNodeByIdAsync(C.set);
if (!set || set.type !== 'COMPONENT_SET') throw new Error('нет набора ' + C.set);
const out = { replaced: [], skipped: [], textSet: [], errors: [] };
async function loadFonts(t) {
  const fs = new Map();
  for (const s of t.getStyledTextSegments(['fontName'])) fs.set(JSON.stringify(s.fontName), s.fontName);
  await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f)));
}
const firstText = n => n.findAll(x => x.type === 'TEXT')[0];

for (const v of set.children) {
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  for (const p of C.pairs) {
    const olds = v.findAll(n => n.type === 'FRAME' && n.getSharedPluginData('remlab', 'css') === p.css);
    if (!olds.length) { out.skipped.push(v.id + ': нет рамок ' + p.css); continue; }
    const base = await figma.getNodeByIdAsync(p.variant[lang]);
    for (const old of olds) {
      const parent = old.parent, idx = parent.children.indexOf(old);
      const auto = parent.layoutMode && parent.layoutMode !== 'NONE';
      const ot = firstText(old);
      const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
        lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null,
        grow: auto ? old.layoutGrow : null, align: auto ? old.layoutAlign : null, cons: old.constraints, txt: ot ? ot.characters : null };
      const inst = base.createInstance();
      parent.insertChild(idx, inst);
      inst.name = p.name;
      if (auto && st.pos === 'ABSOLUTE') inst.layoutPositioning = 'ABSOLUTE';
      if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) inst.resize(st.w, st.h);
      if (auto && st.pos !== 'ABSOLUTE') {
        inst.layoutAlign = st.align; inst.layoutGrow = st.grow;
        inst.layoutSizingHorizontal = st.lsh; inst.layoutSizingVertical = st.lsv;
      } else { inst.x = st.x; inst.y = st.y; }
      inst.constraints = st.cons;
      inst.visible = st.visible;
      for (const k of old.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
      if (p.expose) inst.isExposedInstance = true;
      // текст
      const it = firstText(inst);
      if (st.txt != null && it && it.characters !== st.txt) {
        const ref = it.componentPropertyReferences && it.componentPropertyReferences.characters;
        if (ref) { inst.setProperties({ [ref]: st.txt }); out.textSet.push(inst.id + ' prop «' + st.txt + '»'); }
        else { await loadFonts(it); it.characters = st.txt; out.textSet.push(inst.id + ' chars «' + st.txt + '»'); }
      }
      if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) out.errors.push(inst.id + ' размер ' + inst.width + 'x' + inst.height + ' ≠ ' + st.w + 'x' + st.h);
      const oldId = old.id;
      old.remove();
      out.replaced.push([v.id, oldId, inst.id, base.id, idx, inst.width + 'x' + inst.height].join(' '));
    }
  }
}
return out;
