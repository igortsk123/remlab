// design-02 П2б2 (T-20261103-05): сверка связывания на страницах «Подбор замены», «Карточка товара», «Диалог», «Шторка»
// (только чтение). Копия check-link.js, расширена: несколько наборов на страницу; пара с opt:true может отсутствовать
// в части вариантов (метки «tight», выбранный чип, строки без образцов). Для каждого набора и варианта: 0 рамок с метками
// из pairs; каждый слой с меткой — INSTANCE из нужного базового набора (и нужного варианта по языку, если задан variant);
// BOOLEAN привязан; expose — isExposedInstance. Одна страница на вызов: PAGE_ID → CONF[PAGE_ID].
const PAGE_ID = '14:109';
const CONF = {
  '14:109': [ // Подбор замены
    { set: '105:471', pairs: [{ css: 'button#sh-close.xclose', base: '107:117', variant: { RU: '107:103', EN: '107:111' } }] },
    { set: '105:527', pairs: [
      { css: 'span.badge.b-ok', base: '105:697', opt: true },
      { css: 'span.badge.b-tight', base: '105:697', opt: true },
      { css: 'button.mini', base: '107:79', variant: { RU: '107:65', EN: '107:73' }, expose: true },
      { css: 'a.mini.link', base: '107:79', variant: { RU: '107:69', EN: '107:77' }, expose: true }] },
    { set: '105:406', pairs: [
      { css: 'header', base: '105:471' },
      { css: 'button.chip.on', base: '107:98', variant: { RU: '107:84', EN: '107:92' }, expose: true, opt: true },
      { css: 'button.chip', base: '107:98', variant: { RU: '107:88', EN: '107:96' }, expose: true },
      { css: 'button.colchip.on', base: '105:494', opt: true },
      { css: 'button.colchip', base: '105:494', opt: true },
      { css: 'div.card', base: '105:527' }] },
  ],
  '18:27': [ // Карточка товара
    { set: '83:54', pairs: [
      { css: 'button.ic-x', base: '107:117', variant: { RU: '107:107', EN: '107:115' } },
      { css: 'button.btn.primary.ic-sw', base: '221:15', variant: { RU: '221:2', EN: '221:8' }, expose: true },
      { css: 'a.btn', base: '221:15', variant: { RU: '221:4', EN: '221:10' }, expose: true },
      { css: 'button.sw.on', base: '108:20', opt: true },
      { css: 'button.sw', base: '108:20', opt: true }] },
  ],
  '17:38': [ // Диалог
    { set: '85:62', pairs: [
      { css: 'button#favOk.btn.primary', base: '221:15', expose: true, opt: true },
      { css: 'button#favNo.btn.ghost', base: '221:15', expose: true, opt: true },
      { css: 'button#favExcl.lnk.favexcl', base: '107:60', expose: true, opt: true },
      { css: 'button#favDel.lnk.favdel', base: '107:60', expose: true, opt: true }] },
    { set: '85:85', pairs: [
      { css: 'button.btn.primary', base: '221:15', expose: true },
      { css: 'button.btn.ghost', base: '221:15', expose: true }] },
    { set: '85:116', pairs: [{ css: 'div.favbox', base: '85:62', expose: true, bool: 'Окно' }] },
  ],
  '15:46': [ // Шторка
    { set: '76:187', pairs: [  // после rows-autolayout-p2b2: + 2 скрытых кружка и «+N» в span.sws
      { css: 'button.sw.on', base: '108:20', variant: { RU: '108:3', EN: '108:12' }, opt: true },
      { css: 'button.sw', base: '108:20', opt: true },
      { css: 'button.swn', base: '221:94', opt: true }] },
    { set: '76:57', pairs: [
      { css: 'button.vfl.on', base: '108:43', variant: { RU: '108:26', EN: '108:36' }, expose: true },
      { css: 'button.vfl', base: '108:43', variant: { RU: '108:31', EN: '108:41' }, expose: true }] },
    { set: '76:96', pairs: [{ css: 'button#vOptsBack.vopts-back', base: '107:60', variant: { RU: '221:113', EN: '221:116' }, expose: true }] },
    // 77:965: ожидаемо остаются рамками 7 (решение ведущего 03.11 «лучше честно оставить»): строки 77:93, 77:247, 77:401
    // (подпись в 2 строки в браузере, в Figma — в 1) и vsum/vgrip в «на весь экран» 77:311, 77:323, 77:799, 77:822.
    { set: '77:965', pairs: [
      { css: 'i#vpill.vpill', base: '76:66', variant: { RU: '76:61', EN: '76:64' } },
      { css: 'div#vsum.vplate', base: '58:329', expose: true },
      { css: 'button#vgrip.vgrip', base: '76:12' },
      { css: 'button#vCta.btn.primary.vcta', base: '95:1109', variant: { RU: '95:1103', EN: '95:1107' }, expose: true },
      { css: 'button.vopts-row', base: '76:81', opt: true, expose: true },
      { css: 'div.row', base: '76:187', opt: true },
      { css: 'button.sw.on', base: '108:20', opt: true },
      { css: 'button.sw', base: '108:20', opt: true },
      { css: 'button.swn', base: '221:94', opt: true }] },
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
        if (n.type === 'FRAME') { res.framesLeft++; res.framesBy[p.css] = (res.framesBy[p.css] || 0) + 1; continue; }
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
