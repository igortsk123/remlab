// design-02 П3в (T-20261103-10, Desktop): связывание составных наборов на страницах «Окно расстановки» (9:134) и
// «Во весь экран» (10:98). Копия линкера link-p3b2.js (принят) с правками (их же накладывает в книге вызов-патч из link-p3b2):
//  - рамки ищутся только вне экземпляров (id без «I»): после вложения составного его слои-рамки не трогаются;
//  - cfg.byId: {id старой рамки: id варианта} — явный выбор варианта (состояние «Фото/3D/План», «выбрано» у ценника и т.п.),
//    иначе — cfg.pick[css][язык];
//  - состояние раскладки текстовых слоёв экземпляров после переноса пишется в figma.root remlab/tl-p3c-<набор>
//    (грабля П2в: FILL у текста в экземпляре, заданный в вызове создания, слетает) — сверка/повтор: fix-text-p3c.js.
// Сверка геометрии (cfg.tol, по умолчанию 1.5 px): расхождение — экземпляр удаляется, рамка остаётся (rep.kept).
// Вызов: тело ниже хранится в figma.root sharedPluginData remlab/link-p3c (книга Desktop):
//   const AF = Object.getPrototypeOf(async function(){}).constructor;
//   return await new AF('cfg', figma.root.getSharedPluginData('remlab','link-p3c'))(CFG);
// CFG: { page, set, dry, tol?, skip?:[имя], only?:[id варианта], top:{css:{name, expose?, hug?, bool?:{prop,def}}}, pick:{css:{RU,EN}}, byId? }
// --- LINKER ---
const J = x => JSON.stringify(x);
const tag = n => n.getSharedPluginData('remlab', 'css') || '';
const tname = c => c.split(/[.#\s>:\[]/)[0];
const kind = n => (n.type === 'INSTANCE' || n.type === 'COMPONENT') ? 'FRAME' : n.type;
const TOL = cfg.tol || 1.5;
const TL = []; const rep = { replaced: 0, kept: [], maxD: 0, geo: [], list: [], ovr: {}, txt: 0, txtProp: 0, hid: [], struct: [], size: [], swap: 0, err: [], notLinked: [] };
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
  'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'itemSpacing', 'primaryAxisAlignItems', 'counterAxisAlignItems',
  'strokesIncludedInLayout']; // добавлено 03.11 (П3б2): у «Изменить расстановку» рамка не входила в раскладку
const TXT = ['fontSize', 'fontName', 'textDecoration', 'letterSpacing', 'lineHeight', 'textAlignHorizontal', 'textCase'];
async function walk(o, n, lang, path) {
  const t = tag(o) || o.type;
  rep._pairs.push([o.id, n.id, path]);
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
    if (n.layoutMode === 'NONE' && /^padding|itemSpacing|AlignItems$|strokesIncluded/.test(f)) continue; // у рамки без авто-раскладки поля не действуют
    if (J(o[f]) !== J(n[f])) { try { n[f] = o[f]; cnt(t + ':' + f); } catch (e) { push('err', path + ' ' + f + ': ' + e.message); } }
  }
  if (n.id !== rep._top.id) setVis(n, o.visible, path);
  if ('children' in o && 'children' in n) {
    // дети берутся заново по id родителя на каждом шаге: setProperties делает старые ссылки на слои негодными
    const oc = o.children.filter(x => !(cfg.skip && cfg.skip.includes(x.name) && !('children' in x && x.children.length))); let j = 0; const nid = n.id, len = n.children.length;
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
      if (inAuto && n.parent && n.parent.layoutMode && n.parent.layoutMode !== 'NONE') {
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
  const olds = v.findAll(n => n.type === 'FRAME' && !n.id.startsWith('I') && !!cfg.top[tag(n)]);
  for (const old of olds) {
    if (old.removed) continue;
    const css = tag(old), p = cfg.top[css];
    const want = (cfg.byId && cfg.byId[old.id]) || (cfg.pick[css] || {})[lang];
    if (!want) { push('err', old.id + ' нет pick для ' + css); continue; }
    const base = await figma.getNodeByIdAsync(want);
    const parent = old.parent, idx = parent.children.indexOf(old);
    const auto = parent.layoutMode && parent.layoutMode !== 'NONE';
    const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
      lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null,
      grow: auto ? old.layoutGrow : null, align: auto ? old.layoutAlign : null, cons: old.constraints };
    let inst = base.createInstance();
    parent.insertChild(idx, inst);
    rep._top = inst; rep._pairs = [];
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
      // сверка геометрии: положение от верха и размер каждой пары (видимые слои старой рамки)
      const rel = (x, root) => { const a = x.absoluteTransform, r = root.absoluteTransform; return [a[0][2] - r[0][2], a[1][2] - r[1][2], x.width, x.height]; };
      let worst = 0, wn = '';
      for (const [oid, nid, pth] of rep._pairs) {
        const oo = await figma.getNodeByIdAsync(oid), nn = await figma.getNodeByIdAsync(nid);
        if (!oo || !oo.visible) continue;
        if (!nn) { worst = 99; wn = 'нет слоя ' + pth; break; }
        const isTop = oo.id === old.id;
        const a = isTop ? [old.x, old.y, old.width, old.height] : rel(oo, old), b = isTop ? [inst.x, inst.y, inst.width, inst.height] : rel(nn, inst);
        const d = Math.max(...a.map((x, i) => (isTop && i === 2 && p.hug) || (isTop && auto && st.pos !== 'ABSOLUTE' && i < 2) ? 0 : Math.abs(x - b[i])));
        if (d > worst) { worst = d; wn = pth + ' ' + a.map(x => +x.toFixed(1)) + '→' + b.map(x => +x.toFixed(1)); }
      }
      rep.maxD = Math.max(rep.maxD, worst);
      for (const [, nid] of rep._pairs) { const nn = await figma.getNodeByIdAsync(nid); if (nn && nn.type === 'TEXT' && nn.parent && nn.parent.layoutMode && nn.parent.layoutMode !== 'NONE') TL.push([nid, nn.layoutSizingHorizontal, nn.layoutSizingVertical, nn.textAutoResize]); }
      if (worst > TOL) throw new Error('KEEP ' + worst.toFixed(1) + ' ' + wn);
      if (worst > 0.6) push('geo', old.id + ' ' + worst.toFixed(1) + ' ' + wn);
      if (p.bool && props[p.bool.prop]) inst.componentPropertyReferences = Object.assign({}, inst.componentPropertyReferences || {}, { visible: props[p.bool.prop] });
      if (p.expose) inst.isExposedInstance = true;
    } catch (e) { if (/^KEEP /.test(e.message)) push('kept', old.id + ' ' + css + ' ' + e.message.slice(5)); else push('err', old.id + ' ' + css + ': ' + e.message); const live = await figma.getNodeByIdAsync(inst.id); if (live) live.remove(); continue; }
    rep.replaced++;
    const oldId = old.id;
    if (cfg.dry) inst.remove(); else old.remove();
    push('list', v.id + ' ' + oldId + '→' + (cfg.dry ? '-' : inst.id) + ' ' + want);
  }
}
delete rep._top; delete rep._pairs; if (!cfg.dry) figma.root.setSharedPluginData('remlab', 'tl-p3c-' + cfg.set, JSON.stringify(TL)); rep.tl = TL.length;
rep.setProps = Object.keys(set.componentPropertyDefinitions);
return rep;
