// design-02 (T-20261103-02; по страницам — T-20261103-03/2): сверка связывания составного набора (только чтение).
// Для каждого варианта набора: 0 рамок с метками из pairs; каждый слой с меткой — INSTANCE, его главный компонент
// лежит в нужном базовом наборе (и, если задан variant, — нужный вариант по языку); BOOLEAN-свойства набора есть и
// привязаны во ВСЕХ вариантах; вложенные с expose — isExposedInstance. Плюс сводка свойств базовых наборов.
// Одна страница на вызов: PAGE_ID → CONF[PAGE_ID].
const PAGE_ID = '15:10';
const CONF = {
  '15:10': { set: '64:86', bases: ['107:10', '107:49', '64:105'], pairs: [    // Комната / Карточка комнаты
    { css: 'button.btn.cta',  base: '107:10', expose: true,  bool: null },
    { css: 'button.iconbtn',  base: '107:49', expose: false, bool: 'Поделиться' },
    { css: 'button.hm-heart', base: '64:105', expose: false, bool: 'Сердечко' },
  ] },
  '15:104': { set: '94:85', bases: ['94:104'], pairs: [                       // Вкладки стилей / Лента стилей
    { css: 'button.hm-tab.on', base: '94:104', variant: { RU: '94:90', EN: '94:98' },  expose: true, bool: null },
    { css: 'button.hm-tab',    base: '94:104', variant: { RU: '94:94', EN: '94:102' }, expose: true, bool: null },
  ] },
  '15:118': { set: '89:22', bases: ['107:60'], only: /с кнопкой/, pairs: [  // Уведомление: кнопка есть только «с кнопкой»
    { css: 'button.toastact', base: '107:60', variant: { RU: '221:119', EN: '221:122' }, expose: true, bool: null },
  ] },
};
const { set: SET_ID, bases: BASE_SETS, pairs: PAIRS, only } = CONF[PAGE_ID];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const set = await figma.getNodeByIdAsync(SET_ID);
const defs = set.componentPropertyDefinitions;
const keyOf = n => Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === n);
const res = { set: set.id + ' ' + set.name, setProps: Object.keys(defs), framesLeft: 0, notInstance: [], wrongMain: [], unbound: [], notExposed: [], missing: [], ok: 0, variants: [] };
for (const v of set.children) {
  const row = { id: v.id, name: v.name, nested: [] };
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  for (const p of PAIRS) {
    const hits = v.findAll(n => !n.id.startsWith('I') && n.getSharedPluginData('remlab', 'css') === p.css); // I… — слои внутри экземпляров
    if (!hits.length) { if (!only || only.test(v.name)) res.missing.push(v.id + ' ' + p.css); continue; }
    for (const n of hits) {
      if (n.type === 'FRAME') { res.framesLeft++; continue; }
      if (n.type !== 'INSTANCE') { res.notInstance.push(n.id + ' ' + n.type); continue; }
      const mc = await n.getMainComponentAsync();
      const setId = mc && mc.parent && mc.parent.type === 'COMPONENT_SET' ? mc.parent.id : (mc && mc.id);
      if (setId !== p.base || (p.variant && mc.id !== p.variant[lang])) res.wrongMain.push({ node: n.id, main: mc && mc.id, set: setId, want: p.variant ? p.variant[lang] : p.base });
      if (p.bool) { const k = keyOf(p.bool); if (!k || !n.componentPropertyReferences || n.componentPropertyReferences.visible !== k) res.unbound.push(n.id + ' → ' + p.bool); }
      if (p.expose && !n.isExposedInstance) res.notExposed.push(n.id);
      row.nested.push({ id: n.id, main: mc && mc.id, w: n.width, h: n.height });
      res.ok++;
    }
  }
  res.variants.push(row);
}
res.baseProps = {};
for (const id of BASE_SETS) { const s = await figma.getNodeByIdAsync(id); res.baseProps[id] = { name: s.name, props: Object.keys(s.componentPropertyDefinitions), variants: s.children.length }; }
res.pass = res.framesLeft === 0 && !res.notInstance.length && !res.wrongMain.length && !res.unbound.length && !res.notExposed.length && !res.missing.length;
return res;
