// design-02 П2в (T-20261103-07, помощник p2c): связывание составных наборов на страницах «Окно расстановки» (16:2) и
// «Во весь экран» (16:116) книги Mobile. Правка НА МЕСТЕ: наборы и варианты не пересоздаются (id те же).
//
// Основа — link-p2b1.js (сверка-перенос: экземпляр ставится, только если его дерево совпадает с деревом старой рамки;
// остаток отличий после переноса → экземпляр удаляется, рамка остаётся, запись в errors). Отличия от p2b1:
//  - дети сопоставляются по порядку И по метке remlab/css (как в link-p2b2.js): лишний ребёнок экземпляра скрывается
//    переопределением видимости (напр. «Сделать реалистичнее» в шторке состояния «фото»), лишний ребёнок рамки — отказ;
//  - variant: {RU:[id…], EN:[id…]} — круг вариантов базы (иначе — все варианты набора с тем же языком);
//  - skip: [css] — поддеревья, которые не сверяются и не переносятся (вне кадра: список шторки ниже края окна);
//  - size: 'keep' (размер рамки) | 'natural' (размер варианта базы; шторка в окне — рамка 812 в высоту, видна верхняя часть);
//  - у текста сверяются и переносятся также ширина-по-родителю / автоподгон / выравнивание.
// Старая рамка удаляется только после успешной повторной сверки. Повторный запуск безопасен (ищутся FRAME с меткой).
//
// Вызов: тело ниже (после строки «--- LINKER ---») хранится в figma.root sharedPluginData remlab/link-p2c и запускается:
//   const AF = Object.getPrototypeOf(async function(){}).constructor;
//   return await new AF('cfg', figma.root.getSharedPluginData('remlab','link-p2c'))(CFG);
// CFG: { page, dry, owners:[id набора], pairs:[{ css:[…], base, variant?, name, size?, skip?, expose?, bool?:{prop,def} }] }
// --- LINKER ---
figma.skipInvisibleInstanceChildren = false;
const page = await figma.getNodeByIdAsync(cfg.page);
await figma.setCurrentPageAsync(page);
const allVars = await figma.variables.getLocalVariablesAsync();
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => ps === figma.mixed ? 'mixed' : (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => (p.boundVariables && p.boundVariables.color ? vName(p.boundVariables.color.id) : (p.type === 'SOLID' ? [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255)).join(',') : p.type)) + '@' + (+(p.opacity ?? 1).toFixed(2))).join('|');
const tag = n => n.getSharedPluginData('remlab', 'css') || '';
const tname = c => c.split(/[.#\s>:\[]/)[0];
const kind = n => n.type === 'TEXT' ? 'T' : (['FRAME', 'INSTANCE', 'COMPONENT', 'GROUP'].includes(n.type) ? 'F' : n.type);
const isAL = n => n && 'layoutMode' in n && n.layoutMode !== 'NONE';
const alSig = n => isAL(n) ? [n.layoutMode, n.paddingLeft, n.paddingRight, n.paddingTop, n.paddingBottom, n.itemSpacing, n.primaryAxisAlignItems, n.counterAxisAlignItems].join(',') : 'none';
const segs = t => JSON.stringify(t.getStyledTextSegments(['fontName', 'fontSize', 'fills', 'textDecoration']).map(s => [s.start, s.end, s.fontName.family + ' ' + s.fontName.style, s.fontSize, paint(s.fills), s.textDecoration]));
const inFlow = n => isAL(n.parent) && n.layoutPositioning !== 'ABSOLUTE';
const tlSig = t => [inFlow(t) ? t.layoutSizingHorizontal + '/' + t.layoutSizingVertical : '-', t.textAutoResize, t.textAlignHorizontal].join(',');
const D = 0.05;
// правки раскладки текста внутри экземпляра: в том же вызове FILL не держится (03.11: 87:53, 95:1059 — после вызова
// снова FIXED) → список отдаётся наружу (out.tlfix) и применяется ОТДЕЛЬНЫМ вызовом (fix-text-p2c.js)
const TLFIX = [];
// fx: true у пары — отличие тени (effects) не отказ, а переопределение (полоса снизу у «Чипа N предметов» в окне
// состояния «фото» = класс e2on; варианта такого у 76:12 нет, а сам набор на другой странице править нельзя)
let FX = false;
// ключ метки: тег + #id + первый класс («button#vgrip.vgrip» = «button#vgrip.vgrip.e2on», но «div.vtop» ≠ «div#vscroll.vscroll»)
const tkey = c => tname(c) + '#' + ((c.match(/#([\w-]+)/) || [])[1] || '') + '.' + ((c.match(/\.([\w-]+)/) || [])[1] || '');
const compat = (o, i) => kind(o) === kind(i) && (kind(o) === 'T' || !tag(o) || !tag(i) || tkey(tag(o)) === tkey(tag(i)));

// Сопоставление детей: проход по детям экземпляра; ребёнок берёт следующего старого, если совместим, иначе — лишний.
function align(o, i) {
  const oc = 'children' in o ? o.children : [], ic = 'children' in i ? i.children : [];
  const pairs = [], extra = []; let j = 0;
  for (const c of ic) { if (j < oc.length && compat(oc[j], c)) { pairs.push([oc[j], c]); j++; } else extra.push(c); }
  return { pairs, extra, left: oc.slice(j) };
}
function cmp(o, i, root, acc, skip) {
  if (kind(o) !== kind(i)) { acc.fail = 'тип ' + o.id + ' ' + o.type + '≠' + i.type; return acc; }
  if (!root && skip.includes(tag(o))) return acc;
  if ('fills' in o && paint(o.fills) !== paint(i.fills)) { acc.fail = 'заливка ' + o.id + ' ' + paint(o.fills) + '≠' + paint(i.fills); return acc; }
  if ('strokes' in o && (paint(o.strokes) !== paint(i.strokes) || (o.strokes.length && o.strokeWeight !== i.strokeWeight))) { acc.fail = 'обводка ' + o.id; return acc; }
  if ('cornerRadius' in o && o.cornerRadius !== i.cornerRadius) { acc.fail = 'радиус ' + o.id + ' ' + String(o.cornerRadius) + '≠' + String(i.cornerRadius); return acc; }
  if ('effects' in o && JSON.stringify(o.effects) !== JSON.stringify(i.effects)) { if (FX && !root) acc.fx.push(o.id); else { acc.fail = 'тень ' + o.id; return acc; } }
  if ('opacity' in o && Math.abs(o.opacity - i.opacity) > 0.001) { acc.fail = 'прозрачность ' + o.id; return acc; }
  if ('clipsContent' in o && o.type !== 'TEXT' && !root && o.clipsContent !== i.clipsContent) acc.clip.push(o.id);
  if (isAL(o) !== isAL(i)) { acc.fail = 'раскладка ' + o.id + ' ' + alSig(o) + '≠' + alSig(i); return acc; }
  if (alSig(o) !== alSig(i)) acc.al.push(o.id);
  if (!root && o.visible !== i.visible) acc.vis.push(o.id);
  if (!root) {
    if (o.type !== 'TEXT' && (Math.abs(o.width - i.width) > D || Math.abs(o.height - i.height) > D)) acc.size.push(o.id + '=' + (+o.width.toFixed(1)) + 'x' + (+o.height.toFixed(1)) + '/' + (+i.width.toFixed(1)) + 'x' + (+i.height.toFixed(1)));
    if (!inFlow(o) && (Math.abs(o.x - i.x) > D || Math.abs(o.y - i.y) > D)) acc.pos.push(o.id);
  }
  if (o.type === 'TEXT') {
    if (o.characters !== i.characters || segs(o) !== segs(i)) acc.text.push(o.id);
    if (tlSig(o) !== tlSig(i)) acc.tl.push(o.id + ' ' + tlSig(o) + '/' + tlSig(i));
    return acc;
  }
  const a = align(o, i);
  if (a.left.length) { acc.fail = 'лишние старые в ' + o.id + ': ' + a.left.map(x => tag(x) || x.type).join(','); return acc; }
  for (const x of a.extra) if (x.visible) acc.hide.push(x.id + ' ' + (tag(x) || x.type));
  for (const [oo, ii] of a.pairs) { if (acc.fail) break; cmp(oo, ii, false, acc, skip); }
  return acc;
}
const newAcc = () => ({ fail: null, al: [], vis: [], size: [], pos: [], text: [], tl: [], hide: [], clip: [], fx: [] });
const RES = ['al', 'vis', 'size', 'pos', 'text', 'tl', 'hide', 'clip', 'fx'];
const score = a => a.fail ? 1e9 : a.al.length * 3 + a.vis.length + a.size.length + a.pos.length + a.text.length + a.tl.length + a.hide.length * 2 + a.clip.length;

async function loadSegFonts(t) {
  const fs = new Map();
  for (const s of t.getStyledTextSegments(['fontName'])) fs.set(JSON.stringify(s.fontName), s.fontName);
  await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f)));
}
function ownerInstance(n) { let p = n.parent; while (p && p.type !== 'INSTANCE') p = p.parent; return p; }

// Перенос o → i (тот же обход). Узлы экземпляра берутся заново по id после каждого шага (setProperties портит ссылки).
async function apply(o, iid, root, skip) {
  let i = await figma.getNodeByIdAsync(iid);
  if (!root && skip.includes(tag(o))) return;
  if (alSig(o) !== alSig(i) && isAL(o)) {
    for (const k of ['paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'itemSpacing', 'primaryAxisAlignItems', 'counterAxisAlignItems']) if (i[k] !== o[k]) i[k] = o[k];
  }
  if (!root && o.visible !== i.visible) i.visible = o.visible;
  if (FX && !root && 'effects' in o && JSON.stringify(o.effects) !== JSON.stringify(i.effects)) i.effects = o.effects;
  if (!root && o.type !== 'TEXT' && 'clipsContent' in o && o.clipsContent !== i.clipsContent) i.clipsContent = o.clipsContent;
  if (!root && o.type !== 'TEXT') {
    if (Math.abs(o.width - i.width) > D || Math.abs(o.height - i.height) > D) i.resize(Math.max(o.width, 0.01), Math.max(o.height, 0.01));
    if (inFlow(o)) {
      if (i.layoutSizingHorizontal !== o.layoutSizingHorizontal) i.layoutSizingHorizontal = o.layoutSizingHorizontal;
      if (i.layoutSizingVertical !== o.layoutSizingVertical) i.layoutSizingVertical = o.layoutSizingVertical;
    } else if (Math.abs(o.x - i.x) > D || Math.abs(o.y - i.y) > D) { i.x = o.x; i.y = o.y; }
  }
  if (o.type === 'TEXT') {
    if (o.characters !== i.characters || segs(o) !== segs(i)) {
      const ref = i.componentPropertyReferences && i.componentPropertyReferences.characters;
      const own = ref ? ownerInstance(i) : null;
      if (own && segs(o).split('],[').length === 1 && JSON.parse(segs(o))[0].slice(2).join() === JSON.parse(segs(i))[0].slice(2).join()) own.setProperties({ [ref]: o.characters });
      else {
        await loadSegFonts(i); await loadSegFonts(o);
        i.characters = o.characters;
        for (const s of o.getStyledTextSegments(['fontName', 'fontSize', 'fills', 'textDecoration'])) {
          i.setRangeFontName(s.start, s.end, s.fontName); i.setRangeFontSize(s.start, s.end, s.fontSize);
          i.setRangeFills(s.start, s.end, s.fills); i.setRangeTextDecoration(s.start, s.end, s.textDecoration);
        }
      }
      i = await figma.getNodeByIdAsync(iid);
    }
    if (tlSig(o) !== tlSig(i)) {
      TLFIX.push([iid, inFlow(o) ? o.layoutSizingHorizontal : null, inFlow(o) ? o.layoutSizingVertical : null, o.textAutoResize, o.textAlignHorizontal]);
      await loadSegFonts(i);
      if (i.textAutoResize !== o.textAutoResize) i.textAutoResize = o.textAutoResize;
      if (i.textAlignHorizontal !== o.textAlignHorizontal) i.textAlignHorizontal = o.textAlignHorizontal;
      if (inFlow(o)) {
        if (i.layoutSizingHorizontal !== o.layoutSizingHorizontal) i.layoutSizingHorizontal = o.layoutSizingHorizontal;
        if (i.layoutSizingVertical !== o.layoutSizingVertical) i.layoutSizingVertical = o.layoutSizingVertical;
      }
    }
    return;
  }
  const a = align(o, i);
  const todo = a.pairs.map(([oo, ii]) => [oo, ii.id]);
  for (const x of a.extra) if (x.visible) (await figma.getNodeByIdAsync(x.id)).visible = false;
  for (const [oo, id] of todo) await apply(oo, id, false, skip);
}

const out = { page: page.name, dry: !!cfg.dry, done: [], skipped: [], errors: [], props: {}, hidden: [] };
for (const ownerId of cfg.owners) {
  const set = await figma.getNodeByIdAsync(ownerId);
  const roots = set.type === 'COMPONENT_SET' ? set.children : [set];
  for (const p of cfg.pairs) {
    const skip = p.skip || [];
    FX = !!p.fx;
    let boolKey = null;
    if (p.bool && !cfg.dry) {
      const defs = set.componentPropertyDefinitions;
      boolKey = Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === p.bool.prop);
      if (!boolKey && roots.some(v => v.findAll(n => n.type === 'FRAME' && p.css.includes(tag(n))).length)) boolKey = set.addComponentProperty(p.bool.prop, 'BOOLEAN', p.bool.def);
      if (boolKey) out.props[ownerId + ' ' + p.bool.prop] = boolKey;
    }
    const base = await figma.getNodeByIdAsync(p.base);
    for (const v of roots) {
      const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
      const olds = v.findAll(n => n.type === 'FRAME' && !n.id.startsWith('I') && p.css.includes(tag(n)));
      for (const old of olds) {
        if (old.removed) continue;
        let cands;
        if (p.variant) cands = await Promise.all(p.variant[lang].map(id => figma.getNodeByIdAsync(id)));
        else { cands = base.type === 'COMPONENT_SET' ? base.children.filter(c => c.name.includes('Язык=' + lang)) : [base]; if (!cands.length) cands = base.children; }
        let best = null;
        for (const c of cands) { const a = cmp(old, c, true, newAcc(), skip); if (!best || score(a) < score(best.a)) best = { c, a }; }
        const tg = v.id + ' ' + old.id + ' ' + tag(old);
        if (!best || best.a.fail) { out.skipped.push(tg + ': ' + (best ? best.a.fail : 'нет вариантов')); continue; }
        const ov = RES.map(k => k + best.a[k].length).join(' ');
        if (cfg.dry) { out.done.push(tg + ' → ' + best.c.id + ' ' + ov + (best.a.hide.length ? ' hide:' + best.a.hide.join(',') : '')); continue; }
        const parent = old.parent, idx = parent.children.indexOf(old);
        const auto = isAL(parent);
        const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
          lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null, grow: auto ? old.layoutGrow : null,
          align: auto ? old.layoutAlign : null, cons: old.constraints };
        const inst = best.c.createInstance();
        parent.insertChild(idx, inst);
        const iid = inst.id;
        try {
          inst.name = p.name || old.name;
          if (auto && st.pos === 'ABSOLUTE') inst.layoutPositioning = 'ABSOLUTE';
          if (p.size !== 'natural' && (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01)) inst.resize(st.w, st.h);
          if (auto && st.pos !== 'ABSOLUTE') { inst.layoutAlign = st.align; inst.layoutGrow = st.grow; if (p.size !== 'natural') { inst.layoutSizingHorizontal = st.lsh; inst.layoutSizingVertical = st.lsv; } }
          await apply(old, iid, true, skip);
          const live = await figma.getNodeByIdAsync(iid);
          if (!auto || st.pos === 'ABSOLUTE') { live.x = st.x; live.y = st.y; }
          live.constraints = st.cons;
          live.visible = st.visible;
          // метки, BOOLEAN и вывод наружу — ДО итоговой сверки: после isExposedInstance переопределения ширины текста
          // слетали (03.11, 87:53 «From the window» в 2 строки) → после вывода перенос повторяется
          for (const k of old.getSharedPluginDataKeys('remlab')) live.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
          if (boolKey) live.componentPropertyReferences = Object.assign({}, live.componentPropertyReferences || {}, { visible: boolKey });
          if (p.expose) { live.isExposedInstance = true; await apply(old, iid, true, skip); }
          const chk = cmp(old, await figma.getNodeByIdAsync(iid), true, newAcc(), skip);
          const resid = chk.fail || RES.filter(k => chk[k].length).map(k => k + ':' + chk[k].slice(0, 3).join(',')).join(' ');
          const rootOk = p.size === 'natural' ? Math.abs(live.width - st.w) < 0.01 : (Math.abs(live.width - st.w) < 0.01 && Math.abs(live.height - st.h) < 0.01);
          if (resid || !rootOk) { out.errors.push(tg + ' остаток: ' + (resid || '') + (rootOk ? '' : ' корень ' + live.width + 'x' + live.height)); live.remove(); continue; }
          if (best.a.hide.length) out.hidden.push(iid + ': ' + best.a.hide.join(','));
          const oldId = old.id;
          old.remove();
          out.done.push(tg + ' → ' + iid + ' (' + best.c.id + ') ' + ov + (p.size === 'natural' && Math.abs(live.height - st.h) > 0.01 ? ' h ' + st.h + '→' + live.height : ''));
        } catch (e) { out.errors.push(tg + ' ошибка: ' + e.message); const l = await figma.getNodeByIdAsync(iid); if (l) l.remove(); }
      }
    }
  }
}
out.tlfix = TLFIX;
out.n = { done: out.done.length, skipped: out.skipped.length, errors: out.errors.length };
return out;
