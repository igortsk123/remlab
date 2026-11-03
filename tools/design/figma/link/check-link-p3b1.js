// design-02 П3б (T-20261103-08, помощник p3b1, книга DESKTOP): копия check-link-p2b1.js (Mobile) со своими id; keep — по id
// узлов (рамки, оставленные сознательно, с причиной). Сверка (только чтение): для каждого набора рамки с метками из pairs
// (сверх keepIds) = 0; слои с меткой — INSTANCE нужного базового набора; BOOLEAN привязан; expose — isExposedInstance;
// имена вариантов не начинаются с «=»; свойства-варианты с одним значением — список. Одна страница на вызов: PAGE_ID.
const PAGE_ID = '7:23';
const CONF = {
  '7:23': { owners: ['29:241', '29:323', '29:517'], pairs: [                      // Бюджет (29:517 «Пузырь» — только имена)                                 // Бюджет
    { css: ['div.cs', 'div.cs.two'], base: '29:241' },
    { css: ['button.vpl-i'], base: '29:427' },
    { css: ['div.cs-bar', 'div.cs-bar.two'], base: '29:372' },
    { css: ['div.cs-ov'], base: '29:391' },
    { css: ['div.cs-lg.two'], base: '29:416' },
  ], keepIds: [
    '29:105',                                   // легенда «ничего не выбрано» EN: у «Легенды» нет такого варианта (ширины 240/146), неподвижный слой
    '29:245', '29:259', '29:273', '29:298',     // «Шкала в окне»: шкала с i.pv / ширины 327 — дерево не совпадает с «Шкалой сертификата»
    '29:253', '29:280', '29:267', '29:305',     // полосы в окне: у одних нет раскладки, у других ширина кусков в экземпляре не меняется
    '29:284', '29:310',                         // легенды в окне: вертикальная раскладка, у базы её нет
  ] },
  '8:47': { owners: ['55:34', '55:73', '55:128'], pairs: [                         // Шапка
    { css: ['button#hmFav.hm-fav'], base: '55:111' },
    { css: ['button#flatMoreBtn.hm-more'], base: '43:60', expose: true },
    { css: ['button#pcMort.btn.round'], base: '43:32', expose: true },
    { css: ['button#pcCons.btn.cta.round'], base: '43:21', expose: true },
  ] },
  '9:20': { owners: ['42:146'], pairs: [ { css: ['div#flatRooms'], base: '42:287' } ] },   // План квартиры
  '8:34': { owners: ['48:1708'], pairs: [                                           // Избранное
    { css: ['button.vpl-i'], base: '29:427' },
    { css: ['button.iconbtn'], base: '43:49', has: 'svg', bool: 'Поделиться' },
    { css: ['button.btn'], base: '92:15', expose: true },
  ] },
  '8:28': { owners: ['32:14', '32:40'], pairs: [                                    // Конструктор
    { css: ['button#consDone.btn'], base: '92:15', expose: true },
    { css: ['button#consShot.btn.primary.round'], base: '92:15', expose: true },
  ] },
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
  const keepIds = C.keepIds || [];
  const r = { set: set.id + ' ' + set.name, framesLeft: [], kept: 0, notInstance: [], wrongMain: [], unbound: [], notExposed: [], ok: 0,
    badNames: [], singleProps: [] };
  const roots = set.type === 'COMPONENT_SET' ? set.children : [set];
  for (const v of roots) {
    if (v.name.startsWith('=')) r.badNames.push(v.id);
    for (const p of C.pairs) {
      const hits = v.findAll(n => !n.id.startsWith('I') && p.css.includes(n.getSharedPluginData('remlab', 'css'))
        && (!p.has || n.type === 'INSTANCE' || n.findAll(x => x.getSharedPluginData('remlab', 'css') === p.has).length > 0));
      for (const n of hits) {
        if (n.type === 'FRAME') { if (keepIds.includes(n.id)) r.kept++; else r.framesLeft.push(n.id); continue; }
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
  if (set.type === 'COMPONENT_SET') for (const [k, d] of Object.entries(defs)) if (d.type === 'VARIANT') { const miss = set.children.filter(v => !v.name.split(', ').some(x => x.startsWith(k + '='))).length; if (miss) (r.uneven = r.uneven || []).push(k + ' нет у ' + miss + ' из ' + set.children.length); }
  r.props = Object.keys(defs);
  const okSet = !r.framesLeft.length && !r.notInstance.length && !r.wrongMain.length && !r.unbound.length && !r.notExposed.length && !r.badNames.length;
  if (!okSet) res.pass = false;
  for (const k of Object.keys(r)) if (Array.isArray(r[k]) && !r[k].length && k !== 'props') delete r[k];
  res.sets.push(r);
}
return res;
