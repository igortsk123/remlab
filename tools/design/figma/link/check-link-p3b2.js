// design-02 П3б2 (T-20261103-09): сверка связывания книги Desktop на страницах «Подбор замены», «Карточка товара», «Диалог»,
// «Шторка» (только чтение). Копия check-link-p2b2.js (Mobile) с id Desktop; плюс keep: число рамок, оставленных честно
// (решение «лучше честно оставить, чем сдвинуть»), — с ними набор проходит, если рамок ровно столько.
// Для каждого набора и варианта: 0 рамок с метками из pairs (кроме keep); каждый слой с меткой — INSTANCE из нужного
// базового набора (и нужного варианта по языку, если задан variant); BOOLEAN привязан; expose — isExposedInstance.
// Одна страница на вызов: PAGE_ID → CONF[PAGE_ID].
const PAGE_ID = '9:2';
const CONF = {
  '9:2': [ // Подбор замены
    { set: '47:397', pairs: [{ css: 'button#sh-close.xclose', base: '43:117', variant: { RU: '43:103', EN: '43:111' } }] },
    { set: '47:451', pairs: [
      { css: 'span.badge.b-ok', base: '43:169', variant: { RU: '43:155', EN: '43:163' } },
      { css: 'button.mini', base: '43:79', variant: { RU: '43:65', EN: '43:73' }, expose: true },
      { css: 'a.mini.link', base: '43:79', variant: { RU: '43:69', EN: '43:77' }, expose: true }] },
    { set: '47:382', pairs: [
      { css: 'header', base: '47:397', variant: { RU: '47:389', EN: '47:395' } },
      { css: 'button.chip.on', base: '43:98', variant: { RU: '43:84', EN: '43:92' }, expose: true },
      { css: 'button.chip', base: '43:98', variant: { RU: '43:88', EN: '43:96' }, expose: true },
      { css: 'button.colchip.on', base: '47:420', variant: { RU: '47:403', EN: '47:413' } },
      { css: 'button.colchip', base: '47:420', variant: { RU: '47:408', EN: '47:418' } },
      // 4 карточки (47:118, 47:142, 47:308, 47:332) оставлены рамками: название выше на 10.7 px, чем в «Карточке товара»
      { css: 'div.card', base: '47:451', variant: { RU: '47:435', EN: '47:449' }, keep: 4 },
      // внутри оставленных карточек — экземпляры (внутри связанных карточек слои с id I… не считаются)
      { css: 'span.badge.b-ok', base: '43:169', variant: { RU: '43:155', EN: '43:163' }, opt: true },
      { css: 'span.badge.b-tight', base: '43:169', variant: { RU: '43:159', EN: '43:167' }, opt: true },
      { css: 'button.mini', base: '43:79', variant: { RU: '43:65', EN: '43:73' }, expose: true, opt: true },
      { css: 'a.mini.link', base: '43:79', variant: { RU: '43:69', EN: '43:77' }, expose: true, opt: true }] },
  ],
  '11:204': [ // Карточка товара
    { set: '37:225', pairs: [
      { css: 'button.ic-x', base: '43:117', variant: { RU: '43:107', EN: '43:115' } },
      { css: 'button.btn.primary.ic-sw', base: '92:15', variant: { RU: '92:2', EN: '92:8' }, expose: true },
      { css: 'a.btn', base: '92:15', variant: { RU: '92:4', EN: '92:10' }, expose: true },
      { css: 'button.sw.on', base: '39:20', variant: { RU: '39:9', EN: '39:18' } },
      { css: 'button.sw', base: '39:20', variant: { RU: '39:6', EN: '39:15' } }] },
  ],
  '11:4': [ // Диалог
    { set: '37:62', pairs: [
      { css: 'button#favOk.btn.primary', base: '92:15', variant: { RU: '92:2', EN: '92:8' }, expose: true },
      { css: 'button#favNo.btn.ghost', base: '92:15', variant: { RU: '92:6', EN: '92:12' }, expose: true },
      { css: 'button#favExcl.lnk.favexcl', base: '43:60', variant: { RU: '43:54', EN: '43:58' }, expose: true, opt: true },
      { css: 'button#favDel.lnk.favdel', base: '43:60', variant: { RU: '43:54', EN: '43:58' }, expose: true, opt: true }] },
    { set: '37:85', pairs: [
      { css: 'button.btn.primary', base: '92:15', variant: { RU: '92:2', EN: '92:8' }, expose: true },
      { css: 'button.btn.ghost', base: '92:15', variant: { RU: '92:6', EN: '92:12' }, expose: true }] },
    { set: '37:116', pairs: [{ css: 'div.favbox', base: '37:62', variant: { RU: '37:13', EN: '37:43' }, expose: true, bool: 'Окно' }] },
  ],
  '9:64': [ // Шторка
    { set: '26:44', pairs: [
      { css: 'button.vfl.on', base: '39:43', variant: { RU: '39:26', EN: '39:36' }, expose: true },
      { css: 'button.vfl', base: '39:43', variant: { RU: '39:31', EN: '39:41' }, expose: true }] },
    { set: '26:74', pairs: [{ css: 'button#vOptsBack.vopts-back', base: '43:60', variant: { RU: '92:101', EN: '92:104' }, expose: true }] },
    { set: '26:165', pairs: [  // после rows-autolayout-p3b2: + 2 скрытых кружка (BOOLEAN «Кружок 4/5») и «+N» в span.sws
      { css: 'button.sw.on', base: '39:20', variant: { RU: '39:3', EN: '39:12' }, opt: true },
      { css: 'button.sw', base: '39:20', variant: { RU: '39:6', EN: '39:15' }, opt: true },
      { css: 'button.swn', base: '92:82', variant: { RU: '92:77', EN: '92:79' }, bool: 'Счётчик +N', opt: true },
      { css: 'span.sws', frame: true, bool: 'Образцы цвета', opt: true }] },
  ],
};

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = [];
for (const { set: SET_ID, pairs: PAIRS } of CONF[PAGE_ID]) {
  const set = await figma.getNodeByIdAsync(SET_ID);
  const defs = set.componentPropertyDefinitions;
  const keyOf = n => Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === n);
  const res = { set: set.id + ' ' + set.name, framesLeft: 0, framesBy: {}, notInstance: [], wrongMain: [], unbound: [], notExposed: [], missing: [], ok: 0 };
  for (const v of set.children) {
    const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
    for (const p of PAIRS) {
      const hits = v.findAll(n => !n.id.startsWith('I') && n.getSharedPluginData('remlab', 'css') === p.css); // I… — слои внутри экземпляров
      if (!hits.length) { if (!p.opt) res.missing.push(v.id + ' ' + p.css); continue; }
      for (const n of hits) {
        if (p.frame) { if (p.bool) { const k = keyOf(p.bool); if (!k || !n.componentPropertyReferences || n.componentPropertyReferences.visible !== k) res.unbound.push(n.id + ' → ' + p.bool); } res.ok++; continue; }
        if (n.type === 'FRAME') { res.framesBy[p.css] = (res.framesBy[p.css] || 0) + 1; if (res.framesBy[p.css] > (p.keep || 0)) res.framesLeft++; else res.kept = (res.kept || 0) + 1; continue; }
        if (n.type !== 'INSTANCE') { res.notInstance.push(n.id + ' ' + n.type); continue; }
        const mc = await n.getMainComponentAsync();
        const setId = mc && mc.parent && mc.parent.type === 'COMPONENT_SET' ? mc.parent.id : (mc && mc.id);
        if (setId !== p.base || (p.variant && mc.id !== p.variant[lang])) res.wrongMain.push({ node: n.id, main: mc && mc.id, set: setId, want: p.variant ? p.variant[lang] : p.base });
        if (p.bool) { const k = keyOf(p.bool); if (!k || !n.componentPropertyReferences || n.componentPropertyReferences.visible !== k) res.unbound.push(n.id + ' → ' + p.bool); }
        if (p.expose && !n.isExposedInstance) res.notExposed.push(n.id);
        res.ok++;
      }
    }
  }
  for (const k of ['notInstance', 'wrongMain', 'unbound', 'notExposed', 'missing']) if (!res[k].length) delete res[k]; else res[k] = res[k].slice(0, 10);
  res.pass = res.framesLeft === 0 && !res.notInstance && !res.wrongMain && !res.unbound && !res.notExposed && !res.missing;
  out.push(res);
}
return out;
