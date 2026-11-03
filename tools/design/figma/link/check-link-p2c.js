// design-02 П2в (T-20261103-07): сверка связывания на страницах «Окно расстановки» (16:2) и «Во весь экран» (16:116)
// книги Mobile (только чтение). Для каждого набора и варианта: 0 рамок с метками из pairs (вне экземпляров); каждый слой
// с меткой — INSTANCE нужной базы (и нужного варианта, если задан); expose; BOOLEAN привязан. Пары внутри шторки
// (строки, образцы, шкала, чип, «Сделать реалистичнее»…) проверяются по факту: вся шторка — экземпляр «Шторки» 77:965.
// Плюс сводка: какие метки остались рамками (контейнеры без базы) — для отчёта. Одна страница на вызов: PAGE_ID.
const PAGE_ID = '16:2';
const CONF = {
  '16:2': [
    { set: '95:1042', pairs: [
      { css: 'button.on', base: '221:48', variant: { RU: ['221:23'], EN: ['221:35'] }, expose: true },
      { css: 'button', base: '221:48', variant: { RU: ['221:25'], EN: ['221:37'] }, expose: true }] },
    { set: '95:1059', pairs: [
      { css: 'button.on', base: '221:48', variant: { RU: ['221:27'], EN: ['221:39'] }, expose: true },
      { css: 'button', base: '221:48', variant: { RU: ['221:29'], EN: ['221:41'] }, expose: true }] },
    { set: '95:1076', pairs: [
      { css: 'button#vhBack', base: '221:79', variant: { RU: ['221:62', '221:64'], EN: ['221:70', '221:72'] } },
      { css: 'button#vhFwd', base: '221:79', variant: { RU: ['221:66', '221:68'], EN: ['221:74', '221:76'] } }] },
    { set: '95:972', pairs: [
      { css: 'div#vside.vside', base: '77:965', variant: { RU: ['77:154'], EN: ['77:629'] }, expose: true },
      { css: 'div.vmodes', base: '95:1042', expose: true },
      { css: 'div#vCams.vcams', base: '95:1059', expose: true },
      { css: 'span.vpin', base: '95:1098', expose: true, opt: true }, // ценники — только в состоянии «3D»
      { css: 'button#vzBtn.vzbtn', base: '95:1087', bool: 'Во весь экран', opt: true },
      { css: 'button#shotx.xclose', base: '107:117', variant: { RU: ['107:103'], EN: ['107:111'] } },
      { css: 'button#vShare.vtopbtn', base: '107:150' },
      { css: 'button#vFav.vtopbtn.vfav', base: '107:150' },
      // внутри шторки — не должно остаться ни одной рамки-копии (всё пришло экземпляром 77:965)
      ...['i#vpill.vpill', 'div#vsum.vplate', 'div.cs', 'div.cs.two', 'button.vpl-i', 'div.cs-bar', 'div.cs-bar.two', 'div.cs-lg.two',
        'button#vgrip.vgrip', 'button#vgrip.vgrip.e2on', 'button#vCta.btn.primary.vcta', 'button.vopts-row', 'div.row', 'button.sw.on',
        'button.sw', 'button.swn'].map(css => ({ css, base: null, opt: true }))] },
  ],
  '16:116': [
    { set: '87:53', pairs: [
      { css: 'button.on', base: '221:48', variant: { RU: ['221:31'], EN: ['221:43'] }, expose: true },
      { css: 'button', base: '221:48', variant: { RU: ['221:33'], EN: ['221:45'] }, expose: true }] },
    { set: '87:36', pairs: [
      { css: 'button.vzx', base: '107:117', variant: { RU: ['221:133'], EN: ['221:136'] } },
      { css: 'button.vzarr.l', base: '221:107', variant: { RU: ['221:98'], EN: ['221:102'] } },
      { css: 'button.vzarr.r', base: '221:107', variant: { RU: ['221:100'], EN: ['221:104'] } },
      { css: 'div.vzcams', base: '87:53', variant: { RU: ['87:44'], EN: ['87:51'] }, expose: true }] },
  ],
};
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = [];
for (const { set: SET_ID, pairs: PAIRS } of CONF[PAGE_ID]) {
  const set = await figma.getNodeByIdAsync(SET_ID);
  const defs = set.componentPropertyDefinitions;
  const keyOf = n => Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === n);
  const res = { set: set.id + ' ' + set.name, framesLeft: 0, framesBy: {}, notInstance: [], wrongMain: [], unbound: [], notExposed: [], missing: [], ok: 0, otherFrames: {} };
  const known = new Set(PAIRS.map(p => p.css));
  for (const v of set.children) {
    const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
    for (const p of PAIRS) {
      const hits = v.findAll(n => !n.id.startsWith('I') && n.getSharedPluginData('remlab', 'css') === p.css); // I… — слои внутри экземпляров
      if (!hits.length) { if (!p.opt) res.missing.push(v.id + ' ' + p.css); continue; }
      for (const n of hits) {
        if (n.type === 'FRAME') { res.framesLeft++; res.framesBy[p.css] = (res.framesBy[p.css] || 0) + 1; continue; }
        if (n.type !== 'INSTANCE') { res.notInstance.push(n.id + ' ' + n.type); continue; }
        if (!p.base) { res.wrongMain.push(n.id + ' вне шторки'); continue; }
        const mc = await n.getMainComponentAsync();
        const setId = mc && mc.parent && mc.parent.type === 'COMPONENT_SET' ? mc.parent.id : (mc && mc.id);
        if (setId !== p.base || (p.variant && !p.variant[lang].includes(mc.id))) res.wrongMain.push({ node: n.id, main: mc && mc.id, set: setId });
        if (p.bool) { const k = keyOf(p.bool); if (!k || !n.componentPropertyReferences || n.componentPropertyReferences.visible !== k) res.unbound.push(n.id + ' → ' + p.bool); }
        if (p.expose && !n.isExposedInstance) res.notExposed.push(n.id);
        res.ok++;
      }
    }
    for (const f of v.findAll(n => n.type === 'FRAME' && !n.id.startsWith('I'))) {
      const c = f.getSharedPluginData('remlab', 'css') || '(без метки)';
      if (!known.has(c)) res.otherFrames[c] = (res.otherFrames[c] || 0) + 1;
    }
  }
  for (const k of ['notInstance', 'wrongMain', 'unbound', 'notExposed', 'missing']) if (!res[k].length) delete res[k]; else res[k] = res[k].slice(0, 10);
  res.instances = set.findAll(n => n.type === 'INSTANCE' && !n.id.startsWith('I')).length;
  res.pass = res.framesLeft === 0 && !res.notInstance && !res.wrongMain && !res.unbound && !res.notExposed && !res.missing;
  out.push(res);
}
return out;
