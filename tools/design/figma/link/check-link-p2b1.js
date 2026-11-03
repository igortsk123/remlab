// design-02 П2б (T-20261103-04, помощник p2b1): сверка связывания на страницах Бюджет, Шапка, План квартиры,
// Избранное, Конструктор (только чтение). Копия check-link.js, расширена: несколько наборов на страницу, метки списком,
// отбор has (кнопка-значок со svg, а не «⋯»), keep — рамки, оставленные сознательно (нет подходящей базы, см. отчёт).
// Для каждого набора: рамки с метками из pairs (сверх keep) = 0; слои с меткой — INSTANCE нужного базового набора;
// BOOLEAN привязан; expose — isExposedInstance; имена вариантов не начинаются с «=»; свойства-варианты без
// единственного значения. Одна страница на вызов: PAGE_ID → CONF[PAGE_ID].
const PAGE_ID = '11:23';
const CONF = {
  '11:23': { owners: ['58:247', '58:329'], pairs: [                                // Бюджет
    { css: ['div.cs', 'div.cs.two'], base: '58:247' },
    { css: ['button.vpl-i'], base: '58:437' },
    { css: ['div.cs-bar', 'div.cs-bar.two'], base: '58:378' },
    { css: ['div.cs-ov'], base: '58:397' },
    { css: ['div.cs-lg.two'], base: '58:426' },
  ], keep: { '58:329': ['div.cs', 'div.cs.two', 'div.cs-bar', 'div.cs-bar.two'] } }, // в окне: доп. сегмент i.pv / ширины 327
  '14:47': { owners: ['126:34', '126:65', '126:120'], pairs: [                     // Шапка
    { css: ['button#hmFav.hm-fav'], base: '126:103' },
    { css: ['button#flatMoreBtn.hm-more'], base: '107:60', expose: true },
    { css: ['button#pcMort.btn.round'], base: '107:32', expose: true },
    { css: ['button#pcCons.btn.cta.round'], base: '107:21', expose: true },
  ] },
  '15:2': { owners: ['86:146'], pairs: [ { css: ['div#flatRooms'], base: '86:287' } ] }, // План квартиры
  '14:34': { owners: ['127:184'], pairs: [                                         // Избранное
    { css: ['button.vpl-i'], base: '58:437' },
    { css: ['button.iconbtn'], base: '107:49', has: 'svg', bool: 'Поделиться' },
    { css: ['button.btn'], base: '221:15', expose: true },
  ] },
  '14:28': { owners: ['83:69'], pairs: [ { css: ['button#consDone.btn'], base: '221:15', expose: true } ] }, // Конструктор
};
const C = CONF[PAGE_ID];
figma.skipInvisibleInstanceChildren = false;
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const res = { page: page.name, sets: [], pass: true };
for (const ownerId of C.owners) {
  const set = await figma.getNodeByIdAsync(ownerId);
  const defs = set.componentPropertyDefinitions;
  const keyOf = n => Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === n);
  const keep = (C.keep && C.keep[ownerId]) || [];
  const r = { set: set.id + ' ' + set.name, framesLeft: [], kept: 0, notInstance: [], wrongMain: [], unbound: [], notExposed: [], ok: 0,
    badNames: [], singleProps: [] };
  const roots = set.type === 'COMPONENT_SET' ? set.children : [set];
  for (const v of roots) {
    if (v.name.startsWith('=')) r.badNames.push(v.id);
    for (const p of C.pairs) {
      const hits = v.findAll(n => !n.id.startsWith('I') && p.css.includes(n.getSharedPluginData('remlab', 'css'))
        && (!p.has || n.type === 'INSTANCE' || n.findAll(x => x.getSharedPluginData('remlab', 'css') === p.has).length > 0));
      for (const n of hits) {
        if (n.type === 'FRAME') { if (p.css.some(c => keep.includes(c))) r.kept++; else r.framesLeft.push(n.id); continue; }
        if (n.type !== 'INSTANCE') { r.notInstance.push(n.id + ' ' + n.type); continue; }
        const mc = await n.getMainComponentAsync();
        const setId = mc && mc.parent && mc.parent.type === 'COMPONENT_SET' ? mc.parent.id : (mc && mc.id);
        if (setId !== p.base) r.wrongMain.push(n.id + ' ' + setId);
        if (p.bool) { const k = keyOf(p.bool); if (!k || !n.componentPropertyReferences || n.componentPropertyReferences.visible !== k) r.unbound.push(n.id); }
        if (p.expose && !n.isExposedInstance) r.notExposed.push(n.id);
        r.ok++;
      }
    }
  }
  for (const [k, d] of Object.entries(defs)) if (d.type === 'VARIANT' && d.variantOptions.length < 2) r.singleProps.push(k + '=' + d.variantOptions.join(''));
  r.props = Object.keys(defs);
  const okSet = !r.framesLeft.length && !r.notInstance.length && !r.wrongMain.length && !r.unbound.length && !r.notExposed.length && !r.badNames.length;
  if (!okSet) res.pass = false;
  for (const k of Object.keys(r)) if (Array.isArray(r[k]) && !r[k].length && k !== 'props') delete r[k];
  res.sets.push(r);
}
return res;
