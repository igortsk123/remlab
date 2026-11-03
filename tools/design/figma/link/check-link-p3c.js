// design-02 П3в (T-20261103-10): сверка связывания на страницах «Окно расстановки» (9:134) и «Во весь экран» (10:98) книги
// Desktop (только чтение). Копия check-link.js / check-link-p2c.js с id Desktop. Для каждого набора и варианта: 0 рамок с метками
// из pairs (вне экземпляров; keep — сколько рамок оставлено честно, с ними набор проходит); каждый слой с меткой — INSTANCE
// нужного базового набора (и варианта по языку, если задан); BOOLEAN привязан; expose — isExposedInstance.
// Плюс сводка: какие метки остались рамками (контейнеры без базы) — для отчёта. Одна страница на вызов: PAGE_ID.
const PAGE_ID = '9:134';
const CONF = {
  '9:134': [
    { set: '48:1139', pairs: [
      { css: 'button.on', base: '92:40', variant: { RU: ['92:23'], EN: ['92:31'] }, expose: true },
      { css: 'button', base: '92:40', variant: { RU: ['92:25'], EN: ['92:33'] }, expose: true }] },
    { set: '48:1156', pairs: [
      { css: 'button.on', base: '92:40', variant: { RU: ['92:27'], EN: ['92:35'] }, expose: true },
      { css: 'button', base: '92:40', variant: { RU: ['92:29'], EN: ['92:37'] }, expose: true }] },
    { set: '48:1173', pairs: [
      { css: 'button#vhBack', base: '92:67', variant: { RU: ['92:50'], EN: ['92:58'] } },
      { css: 'button#vhFwd', base: '92:67', variant: { RU: ['92:56'], EN: ['92:64'] } }] },
    { set: '48:1082', pairs: [
      { css: 'div#vsum.vplate', base: '29:323', variant: { RU: ['29:256'], EN: ['29:295'] }, expose: true },
      { css: 'button#vCta.btn.primary.vcta', base: '48:1214', variant: { RU: ['48:1208'], EN: ['48:1212'] }, expose: true, bool: 'Сделать реалистичнее' },
      { css: 'button.vopts-row', base: '26:59', variant: { RU: ['26:51'], EN: ['26:57'] }, expose: true },
      { css: 'div.row', base: '26:165' },
      // внутри строк — только экземпляры (кружки, +N, шкала): рамок-копий быть не должно
      ...['button.sw.on', 'button.sw', 'button.swn', 'div.cs', 'div.cs.two', 'button.vpl-i', 'div.cs-bar', 'div.cs-bar.two', 'div.cs-lg.two']
        .map(css => ({ css, base: null, opt: true }))] },
    { set: '48:764', pairs: [
      { css: 'div.vmodes', base: '48:1139', expose: true },
      { css: 'div#vCams.vcams', base: '48:1156', variant: { RU: ['48:1147'], EN: ['48:1154'] }, expose: true },
      { css: 'span.vpin', base: '48:1203', expose: true, opt: true }, // ценники — только в состоянии «3D»
      // боковая панель: в «3D» — экземпляр 48:1082 целиком; в «фото» (2 шт.) — рамка: верхний блок без «Сделать
      // реалистичнее» 20 px против 76 у панели → сдвиг 56 px; её части внутри связаны (строки ниже)
      { css: 'div#vside.vside', base: '48:1082', variant: { RU: ['48:916'], EN: ['48:1080'] }, expose: true, keep: 2 },
      { css: 'div#vsum.vplate', base: '29:323', variant: { RU: ['29:256'], EN: ['29:295'] }, expose: true, opt: true },
      { css: 'button.vopts-row', base: '26:59', variant: { RU: ['26:51'], EN: ['26:57'] }, expose: true, opt: true },
      { css: 'div.row', base: '26:165', opt: true },
      { css: 'button#shotx.xclose', base: '43:117', variant: { RU: ['43:103'], EN: ['43:111'] } },
      { css: 'button#vShare.vtopbtn', base: '43:150', variant: { RU: ['43:125'], EN: ['43:140'] } },
      { css: 'button#vFav.vtopbtn.vfav', base: '43:150', variant: { RU: ['43:129'], EN: ['43:144'] } },
      { css: 'button#vzBtn.vzbtn', base: '48:1184', variant: { RU: ['48:1178'], EN: ['48:1182'] }, bool: 'Во весь экран', opt: true },
      ...['button#vCta.btn.primary.vcta', 'button.sw.on', 'button.sw', 'button.swn', 'div.cs', 'div.cs.two', 'button.vpl-i', 'div.cs-bar',
        'div.cs-bar.two', 'div.cs-lg.two', 'button', 'button.on'].map(css => ({ css, base: null, opt: true }))] },
  ],
  '10:98': [
    { set: '37:170', pairs: [
      { css: 'button.on', base: '92:40', variant: { RU: ['92:27'], EN: ['92:35'] }, expose: true },
      { css: 'button', base: '92:40', variant: { RU: ['92:29'], EN: ['92:37'] }, expose: true }] },
    { set: '37:153', pairs: [
      { css: 'button.vzx', base: '43:117', variant: { RU: ['92:121'], EN: ['92:124'] } },
      { css: 'button.vzarr.l', base: '92:95', variant: { RU: ['92:86'], EN: ['92:90'] } },
      { css: 'button.vzarr.r', base: '92:95', variant: { RU: ['92:88'], EN: ['92:92'] } },
      { css: 'div.vzcams', base: '37:170', variant: { RU: ['37:161'], EN: ['37:168'] }, expose: true },
      ...['button', 'button.on'].map(css => ({ css, base: null, opt: true }))] },
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
  const kept = {};
  for (const v of set.children) {
    const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
    for (const p of PAIRS) {
      const hits = v.findAll(n => !n.id.startsWith('I') && n.getSharedPluginData('remlab', 'css') === p.css); // I… — слои внутри экземпляров
      if (!hits.length) { if (!p.opt) res.missing.push(v.id + ' ' + p.css); continue; }
      for (const n of hits) {
        if (n.type === 'FRAME') {
          if (p.keep && (kept[p.css] || 0) < p.keep) { kept[p.css] = (kept[p.css] || 0) + 1; continue; }
          res.framesLeft++; res.framesBy[p.css] = (res.framesBy[p.css] || 0) + 1; continue; }
        if (n.type !== 'INSTANCE') { res.notInstance.push(n.id + ' ' + n.type); continue; }
        if (!p.base) { res.wrongMain.push(n.id + ' экземпляр с меткой ' + p.css + ' вне базы'); continue; }
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
  if (Object.keys(kept).length) res.kept = kept;
  for (const k of ['notInstance', 'wrongMain', 'unbound', 'notExposed', 'missing']) if (!res[k].length) delete res[k]; else res[k] = res[k].slice(0, 10);
  res.instances = set.findAll(n => n.type === 'INSTANCE' && !n.id.startsWith('I')).length;
  res.props = Object.keys(defs).map(k => k.replace(/#[^#]*$/, ''));
  res.pass = res.framesLeft === 0 && !res.notInstance && !res.wrongMain && !res.unbound && !res.notExposed && !res.missing;
  out.push(res);
}
return out;
