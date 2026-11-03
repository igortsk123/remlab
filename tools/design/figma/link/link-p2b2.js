// design-02 П2б2 (T-20261103-05): связывание составных наборов на страницах «Подбор замены», «Карточка товара», «Шторка»,
// «Диалог» (Mobile). Правка НА МЕСТЕ (образец — link-base-pages.js): рамка с меткой remlab/css → экземпляр нужного
// варианта на то же место и того же размера; затем ПЕРЕНОС ПЕРЕОПРЕДЕЛЕНИЙ попарным обходом «старая рамка ↔ экземпляр»:
// тексты (через свойство, если текст к нему привязан), заливки/обводки/тени/скругления/прозрачность/видимость/шрифт.
// Дети сопоставляются по порядку и тегу метки; лишние дети экземпляра скрываются (через BOOLEAN, если привязан),
// лишние дети старой рамки — ошибка структуры. Вложенные экземпляры нужного вида меняются на верный вариант
// (swapComponent) по метке старой рамки (cfg.pick). Набор и варианты НЕ пересоздаются (id сохраняются).
// Повторный запуск безопасен: ищутся только FRAME с меткой из cfg.top. DRY — всё то же, но экземпляр удаляется, рамка остаётся.
//
// Вызов: тело ниже (после строки «--- LINKER ---») хранится в figma.root sharedPluginData remlab/link-p2b2 и
// запускается так: const AF = Object.getPrototypeOf(async function(){}).constructor;
//   return await new AF('cfg', figma.root.getSharedPluginData('remlab','link-p2b2'))(CFG);
// CFG: { page, set, dry, only?:[id варианта], top:{css:{name, expose?, bool?:{prop,def}}}, pick:{css:{RU,EN}} }
// --- LINKER ---
const J = x => JSON.stringify(x);
const tag = n => n.getSharedPluginData('remlab', 'css') || '';
const tname = c => c.split(/[.#\s>:\[]/)[0];
const kind = n => (n.type === 'INSTANCE' || n.type === 'COMPONENT') ? 'FRAME' : n.type;
const rep = { replaced: 0, list: [], ovr: {}, txt: 0, txtProp: 0, hid: [], struct: [], size: [], swap: 0, err: [], notLinked: [] };
const cnt = (k) => { rep.ovr[k] = (rep.ovr[k] || 0) + 1; };
const push = (a, s) => { if (rep[a].length < 40) rep[a].push(s); };
const page = await figma.getNodeByIdAsync(cfg.page);
await figma.setCurrentPageAsync(page);
const set = await figma.getNodeByIdAsync(cfg.set);
if (!set || set.type !== 'COMPONENT_SET') throw new Error('нет набора ' + cfg.set);
const ownerOf = (n, key) => { let p = n.parent; while (p && !(p.type === 'INSTANCE' && p.componentProperties && key in p.componentProperties)) p = p.parent; return p; };
async function loadFonts(t) { const fs = new Map(); for (const g of t.getStyledTextSegments(['fontName'])) fs.set(J(g.fontName), g.fontName); await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f))); }
function setVis(n, v, path) {
  if (n.visible === v) return;
  const key = n.componentPropertyReferences && n.componentPropertyReferences.visible;
  const own = key && ownerOf(n, key);
  if (own) { own.setProperties({ [key]: v }); cnt('boolProp'); } else { n.visible = v; cnt('visible'); }
}
const VIS = ['fills', 'strokes', 'effects', 'opacity', 'strokeWeight', 'cornerRadius', 'strokeAlign',
  'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'itemSpacing', 'primaryAxisAlignItems', 'counterAxisAlignItems'];
const TXT = ['fontSize', 'fontName', 'textDecoration', 'letterSpacing', 'lineHeight', 'textAlignHorizontal', 'textCase'];
async function walk(o, n, lang, path) {
  const t = tag(o) || o.type;
  if (n.type === 'INSTANCE' && n.id !== rep._top.id && cfg.pick[tag(o)]) {
    const want = cfg.pick[tag(o)][lang];
    const mc = await n.getMainComponentAsync();
    if (mc.id !== want) { n.swapComponent(await figma.getNodeByIdAsync(want)); rep.swap++; n = await figma.getNodeByIdAsync(n.id); }
  } else if (o.type === 'FRAME' && n.type !== 'INSTANCE' && cfg.pick[tag(o)]) push('notLinked', path + ' ' + tag(o));
  if (o.type === 'TEXT' && n.type === 'TEXT') {
    if (TXT.some(f => o[f] !== figma.mixed && J(o[f]) !== J(n[f]))) {
      await loadFonts(n); if (o.fontName !== figma.mixed) await figma.loadFontAsync(o.fontName);
      for (const f of TXT) if (o[f] !== figma.mixed && J(o[f]) !== J(n[f])) { n[f] = o[f]; cnt(t + ':' + f); }
    }
    if (o.characters !== n.characters) {
      const key = n.componentPropertyReferences && n.componentPropertyReferences.characters;
      const own = key && ownerOf(n, key);
      if (own) { own.setProperties({ [key]: o.characters }); rep.txtProp++; }
      else { await loadFonts(n); n.characters = o.characters; rep.txt++; }
    }
    n = await figma.getNodeByIdAsync(n.id);
  }
  for (const f of VIS) {
    if (!(f in o) || !(f in n) || o[f] === figma.mixed) continue;
    if (J(o[f]) !== J(n[f])) { try { n[f] = o[f]; cnt(t + ':' + f); } catch (e) { push('err', path + ' ' + f + ': ' + e.message); } }
  }
  if (n.id !== rep._top.id) setVis(n, o.visible, path);
  if ('children' in o && 'children' in n) {
    // дети берутся заново по id родителя на каждом шаге: setProperties делает старые ссылки на слои негодными
    const oc = o.children; let j = 0; const nid = n.id, len = n.children.length;
    for (let i = 0; i < len; i++) {
      const c = (await figma.getNodeByIdAsync(nid)).children[i];
      const oo = oc[j], ct = tag(c) || c.type;
      const ok = oo && kind(oo) === kind(c) && (kind(c) === 'TEXT' || !tag(oo) || !tag(c) || tname(tag(oo)) === tname(tag(c)));
      if (ok) { await walk(oo, c, lang, path + '/' + (tag(oo) || oo.type)); j++; }
      else { setVis(c, false, path); push('hid', path + '/' + ct); }
    }
    n = await figma.getNodeByIdAsync(nid);
    if (j < oc.length) push('struct', path + ': лишние старые ' + oc.slice(j).map(x => tag(x) || x.type).join(','));
  }
  if (n.id !== rep._top.id && 'width' in o && (Math.abs(o.width - n.width) > 0.01 || Math.abs(o.height - n.height) > 0.01)) {
    // Размер слоя ВНУТРИ экземпляра: resize() тут молча не действует (проверено 03.11), поэтому:
    // 1) режимы раскладки и автоподгон текста — как у старого; 2) текст — пробуем FILL (оставляем, если ближе);
    // 3) вложенный экземпляр с горизонтальной раскладкой — «по содержимому» + поровну поля до старой ширины.
    const inAuto = o.parent && o.parent.layoutMode && o.parent.layoutMode !== 'NONE' && o.layoutPositioning !== 'ABSOLUTE';
    try {
      if (n.type === 'TEXT') await loadFonts(n);
      if (inAuto) {
        if (n.layoutSizingHorizontal !== o.layoutSizingHorizontal) { n.layoutSizingHorizontal = o.layoutSizingHorizontal; cnt(t + ':lsh'); }
        if (n.layoutSizingVertical !== o.layoutSizingVertical) { n.layoutSizingVertical = o.layoutSizingVertical; cnt(t + ':lsv'); }
      }
      if (n.type === 'TEXT' && n.textAutoResize !== o.textAutoResize) { n.textAutoResize = o.textAutoResize; cnt(t + ':tar'); }
      if (Math.abs(o.width - n.width) > 0.5) {
        if (n.type === 'TEXT' && inAuto) {
          const prev = n.layoutSizingHorizontal, d0 = Math.abs(o.width - n.width);
          n.layoutSizingHorizontal = 'FILL';
          if (Math.abs(o.width - n.width) < d0) cnt(t + ':fill'); else n.layoutSizingHorizontal = prev;
        } else if (n.type === 'INSTANCE' && n.layoutMode === 'HORIZONTAL') {
          n.primaryAxisSizingMode = 'AUTO';
          const ex = (o.width - n.width) / 2;
          n.paddingLeft = n.paddingLeft + ex; n.paddingRight = n.paddingRight + ex; cnt(t + ':pad');
        }
      }
    } catch (e) { push('err', path + ' size: ' + e.message); }
  }
  if (n.id !== rep._top.id && 'width' in o && (Math.abs(o.width - n.width) > 0.5 || Math.abs(o.height - n.height) > 0.5)) push('size', path + ' ' + o.width.toFixed(1) + 'x' + o.height.toFixed(1) + '→' + n.width.toFixed(1) + 'x' + n.height.toFixed(1));
}
// BOOLEAN-свойства набора (до привязки)
const props = {};
const propKey = name => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === name);
for (const p of Object.values(cfg.top)) if (p.bool) { let k = propKey(p.bool.prop); if (!k && !cfg.dry) k = set.addComponentProperty(p.bool.prop, 'BOOLEAN', p.bool.def); props[p.bool.prop] = k; }

for (const v of set.children) {
  if (cfg.only && !cfg.only.includes(v.id)) continue;
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  const olds = v.findAll(n => n.type === 'FRAME' && !!cfg.top[tag(n)]);
  for (const old of olds) {
    if (old.removed) continue;
    const css = tag(old), p = cfg.top[css];
    const want = (cfg.pick[css] || {})[lang];
    if (!want) { push('err', old.id + ' нет pick для ' + css); continue; }
    const base = await figma.getNodeByIdAsync(want);
    const parent = old.parent, idx = parent.children.indexOf(old);
    const auto = parent.layoutMode && parent.layoutMode !== 'NONE';
    const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
      lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null,
      grow: auto ? old.layoutGrow : null, align: auto ? old.layoutAlign : null, cons: old.constraints };
    let inst = base.createInstance();
    parent.insertChild(idx, inst);
    rep._top = inst;
    try {
      inst.name = p.name || old.name;
      if (auto && st.pos === 'ABSOLUTE') inst.layoutPositioning = 'ABSOLUTE';
      if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) inst.resize(st.w, st.h);
      if (auto && st.pos !== 'ABSOLUTE') { inst.layoutAlign = st.align; inst.layoutGrow = st.grow; inst.layoutSizingHorizontal = st.lsh; inst.layoutSizingVertical = st.lsv; }
      else { inst.x = st.x; inst.y = st.y; }
      inst.constraints = st.cons;
      inst.visible = st.visible;
      for (const k of old.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
      await walk(old, inst, lang, css);
      inst = await figma.getNodeByIdAsync(inst.id);
      if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) push('size', 'TOP ' + inst.id + ' ' + st.w + 'x' + st.h + '→' + inst.width + 'x' + inst.height);
      if (p.bool && props[p.bool.prop]) inst.componentPropertyReferences = Object.assign({}, inst.componentPropertyReferences || {}, { visible: props[p.bool.prop] });
      if (p.expose) inst.isExposedInstance = true;
    } catch (e) { push('err', old.id + ' ' + css + ': ' + e.message); const live = await figma.getNodeByIdAsync(inst.id); if (live) live.remove(); continue; }
    rep.replaced++;
    const oldId = old.id;
    if (cfg.dry) inst.remove(); else old.remove();
    push('list', v.id + ' ' + oldId + '→' + (cfg.dry ? '-' : inst.id) + ' ' + want);
  }
}
delete rep._top;
rep.setProps = Object.keys(set.componentPropertyDefinitions);
return rep;
