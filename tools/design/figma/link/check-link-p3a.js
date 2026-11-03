// design-02 П3а (T-20261103-06): копия check-link.js под книгу Desktop. Исходник (T-20261103-02; T-20261103-03/2): сверка связывания составного набора (только чтение).
// Для каждого варианта набора: 0 рамок с метками из pairs; каждый слой с меткой — INSTANCE, его главный компонент
// лежит в нужном базовом наборе (и, если задан variant, — нужный вариант по языку); BOOLEAN-свойства набора есть и
// привязаны во ВСЕХ вариантах; вложенные с expose — isExposedInstance. Плюс сводка свойств базовых наборов.
// Одна страница на вызов: PAGE_ID → CONF[PAGE_ID].
const PAGE_ID = '9:28';
const CONF = {
  '9:28': { set: '25:86', bases: ['43:10', '43:49', '25:105'], pairs: [      // Комната / Карточка комнаты (Desktop)
    { css: 'button.btn.cta',  base: '43:10', variant: { RU: '43:4', EN: '43:8' },   expose: true,  bool: null },
    { css: 'button.iconbtn',  base: '43:49', variant: { RU: '43:40', EN: '43:47' }, expose: false, bool: 'Поделиться' },
    { css: 'button.hm-heart', base: '25:105', variant: { RU: '25:91', EN: '25:99' }, expose: false, bool: 'Сердечко' },
  ] },
  '9:108': { set: '35:54', bases: ['35:73'], pairs: [                         // Вкладки стилей / Лента стилей
    { css: 'button.hm-tab.on', base: '35:73', variant: { RU: '35:59', EN: '35:67' }, expose: true, bool: null },
    { css: 'button.hm-tab',    base: '35:73', variant: { RU: '35:63', EN: '35:71' }, expose: true, bool: null },
  ] },
  '9:122': { set: '36:22', bases: ['43:60'], only: /с кнопкой/, pairs: [    // Уведомление: кнопка есть только «с кнопкой»
    { css: 'button.toastact', base: '43:60', variant: { RU: '92:107', EN: '92:110' }, expose: true, bool: null },
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
