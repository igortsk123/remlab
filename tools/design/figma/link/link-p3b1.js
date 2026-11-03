// design-02 П3б (T-20261103-08, помощник p3b1): КНИГА DESKTOP — копия link-p2b1.js (Mobile, T-20261103-04) со своими id.
// Страницы Бюджет, Шапка, План квартиры, Избранное, Конструктор (на «Главной» пар нет). Добавлено: rr — радиус корня
// переносится переопределением (кнопка «Готово — посмотреть в окне» = «Кнопка: Основная», но скругление 23, а не 12).
// Исходное описание: связывание составных наборов (книга Mobile). Правка НА МЕСТЕ: наборы и варианты не пересоздаются.
//
// Отличие от link-base-pages.js — «сверка-перенос»: рамка заменяется экземпляром, только если её дерево совпадает с
// деревом варианта базы (те же типы, число детей, заливки/обводки/радиусы, раскладка). Вариант базы выбирается сам —
// с тем же языком и наименьшим числом отличий. Отличия-данные переносятся переопределениями: тексты (с разметкой
// шрифтов), размеры рамок/векторов (ширины сегментов шкалы), положение детей вне авто-раскладки, видимость.
// После переноса — повторная сверка; остались отличия → экземпляр удаляется, рамка остаётся (запись в errors).
// Старая рамка удаляется только после успешной сверки. Повторный запуск безопасен (ищутся только FRAME с меткой).
//
// Запуск: PAGE_ID → CONF[PAGE_ID]; DRY = true — только отчёт (без правок).
// pair: css — метки remlab/css рамок; base — набор базы; name — имя слоя-экземпляра; size: 'keep' (размер рамки,
//   FIXED/FILL как было) | 'hug' (ширина по тексту, как в вебе); expose — вывести вложенный наружу; has — у рамки
//   должен быть потомок с такой меткой (отбор, напр. кнопка-значок с svg, а не с «⋯»); bool — {prop, def}:
//   BOOLEAN-свойство набора-владельца на видимость экземпляра.
const PAGE_ID = '7:23';
const DRY = true;
const CONF = {
  '7:23': { owners: ['29:241', '29:323'], pairs: [                                // Бюджет
    { css: ['div.cs', 'div.cs.two'], base: '29:241', name: 'Шкала сертификата' },  // в «Шкале в окне» — если дерево совпадёт
    { css: ['button.vpl-i'], base: '29:427', name: 'Кнопка (i)' },
    { css: ['div.cs-bar', 'div.cs-bar.two'], base: '29:372', name: 'Полоса сертификата' },
    { css: ['div.cs-ov'], base: '29:391', name: 'Строка доплаты' },
    { css: ['div.cs-lg.two'], base: '29:416', name: 'Легенда' },
  ] },
  '8:47': { owners: ['55:34', '55:73', '55:128'], pairs: [                        // Шапка
    { css: ['button#hmFav.hm-fav'], base: '55:111', name: 'Кнопка избранного' },
    { css: ['button#flatMoreBtn.hm-more'], base: '43:60', name: 'Ссылка «Подробнее»', expose: true },
    { css: ['button#pcMort.btn.round'], base: '43:32', name: 'Капсула «Ипотека»', expose: true },
    { css: ['button#pcCons.btn.cta.round'], base: '43:21', name: 'Капсула «Консультация»', expose: true },
  ] },
  '9:20': { owners: ['42:146'], pairs: [                                         // План квартиры
    { css: ['div#flatRooms'], base: '42:287', name: 'План квартиры' },
  ] },
  '8:34': { owners: ['48:1708'], pairs: [                                        // Избранное
    { css: ['button.vpl-i'], base: '29:427', name: 'Кнопка (i)' },
    { css: ['button.iconbtn'], base: '43:49', name: 'Поделиться', has: 'svg', bool: { prop: 'Поделиться', def: true } },
    { css: ['button.btn'], base: '92:15', name: 'Кнопка «Открыть»', expose: true },
  ] },
  '8:28': { owners: ['32:14', '32:40'], pairs: [                                 // Конструктор
    { css: ['button#consDone.btn'], base: '92:15', name: 'Кнопка «Готово»', size: 'hug', expose: true },
    { css: ['button#consShot.btn.primary.round'], base: '92:15', name: 'Кнопка «Готово — посмотреть в окне»', expose: true, rr: true }, // ширина как была: по тексту было бы +15 px (текст 235 шире поля 220)
  ] },
};
const C = CONF[PAGE_ID];
figma.skipInvisibleInstanceChildren = false;
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const allVars = await figma.variables.getLocalVariablesAsync();
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => ps === figma.mixed ? 'mixed' : (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => (p.boundVariables && p.boundVariables.color ? vName(p.boundVariables.color.id) : (p.type === 'SOLID' ? [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255)).join(',') : p.type)) + '@' + (+(p.opacity ?? 1).toFixed(2))).join('|');
const kind = n => n.type === 'TEXT' ? 'T' : (['FRAME', 'INSTANCE', 'COMPONENT', 'GROUP'].includes(n.type) ? 'F' : n.type);
const isAL = n => 'layoutMode' in n && n.layoutMode !== 'NONE';
const alSig = n => isAL(n) ? [n.layoutMode, n.paddingLeft, n.paddingRight, n.paddingTop, n.paddingBottom, n.itemSpacing, n.primaryAxisAlignItems, n.counterAxisAlignItems].join(',') : 'none';
const segs = t => JSON.stringify(t.getStyledTextSegments(['fontName', 'fontSize', 'fills', 'textDecoration']).map(s => [s.start, s.end, s.fontName.family + ' ' + s.fontName.style, s.fontSize, paint(s.fills), s.textDecoration]));
const D = 0.05;

// Сравнение старой рамки o и узла экземпляра i. root — корень (его размер/место задаёт вставка).
function cmp(o, i, root, acc) {
  if (kind(o) !== kind(i)) { acc.fail = 'тип ' + o.id + ' ' + o.type + '≠' + i.type; return acc; }
  if ('fills' in o && paint(o.fills) !== paint(i.fills)) { acc.fail = 'заливка ' + o.id + ' ' + paint(o.fills) + '≠' + paint(i.fills); return acc; }
  if ('strokes' in o && (paint(o.strokes) !== paint(i.strokes) || (o.strokes.length && o.strokeWeight !== i.strokeWeight))) { acc.fail = 'обводка ' + o.id; return acc; }
  if ('cornerRadius' in o && o.cornerRadius !== i.cornerRadius && !(root && acc.rr)) { acc.fail = 'радиус ' + o.id + ' ' + String(o.cornerRadius) + '≠' + String(i.cornerRadius); return acc; }
  if ('opacity' in o && Math.abs(o.opacity - i.opacity) > 0.001) { acc.fail = 'прозрачность ' + o.id; return acc; }
  if (isAL(o) !== isAL(i)) { acc.fail = 'раскладка ' + o.id + ' ' + alSig(o) + '≠' + alSig(i); return acc; }
  if (alSig(o) !== alSig(i)) acc.al.push(o.id);
  if (o.visible !== i.visible) acc.vis.push(o.id);
  if (!root) {
    if (o.type !== 'TEXT' && (Math.abs(o.width - i.width) > D || Math.abs(o.height - i.height) > D)) acc.size.push(o.id + '=' + (+o.width.toFixed(1)) + 'x' + (+o.height.toFixed(1)) + '/' + (+i.width.toFixed(1)) + 'x' + (+i.height.toFixed(1)));
    const freeParent = !isAL(o.parent) || o.layoutPositioning === 'ABSOLUTE';
    if (freeParent && (Math.abs(o.x - i.x) > D || Math.abs(o.y - i.y) > D)) acc.pos.push(o.id);
  }
  if (o.type === 'TEXT') {
    if (o.characters !== i.characters) acc.text.push(o.id);
    else if (segs(o) !== segs(i)) acc.text.push(o.id);
    return acc;
  }
  const oc = 'children' in o ? o.children : [], ic = 'children' in i ? i.children : [];
  if (oc.length !== ic.length) { acc.fail = 'детей ' + o.id + ' ' + oc.length + '≠' + ic.length; return acc; }
  for (let k = 0; k < oc.length && !acc.fail; k++) cmp(oc[k], ic[k], false, acc);
  return acc;
}
const newAcc = rr => ({ fail: null, al: [], vis: [], size: [], pos: [], text: [], rr: !!rr });
const score = a => a.fail ? 1e9 : a.al.length * 3 + a.vis.length + a.size.length + a.pos.length + a.text.length;

async function loadSegFonts(t) {
  const fs = new Map();
  for (const s of t.getStyledTextSegments(['fontName'])) fs.set(JSON.stringify(s.fontName), s.fontName);
  await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f)));
}
function ownerInstance(n) { let p = n.parent; while (p && p.type !== 'INSTANCE') p = p.parent; return p; }

// Перенос данных o → i (тот же обход).
async function apply(o, i, root) {
  if (alSig(o) !== alSig(i) && isAL(o)) {
    for (const k of ['paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom', 'itemSpacing', 'primaryAxisAlignItems', 'counterAxisAlignItems']) if (i[k] !== o[k]) i[k] = o[k];
  }
  if (o.visible !== i.visible) i.visible = o.visible;
  if (!root && o.type !== 'TEXT') {
    if (Math.abs(o.width - i.width) > D || Math.abs(o.height - i.height) > D) {
      i.resize(Math.max(o.width, 0.01), Math.max(o.height, 0.01));
    }
    if (isAL(o.parent) && o.layoutPositioning !== 'ABSOLUTE') {
      if (i.layoutSizingHorizontal !== o.layoutSizingHorizontal) i.layoutSizingHorizontal = o.layoutSizingHorizontal;
      if (i.layoutSizingVertical !== o.layoutSizingVertical) i.layoutSizingVertical = o.layoutSizingVertical;
    } else if (Math.abs(o.x - i.x) > D || Math.abs(o.y - i.y) > D) { try { i.x = o.x; i.y = o.y; } catch (e) { /* неподвижный слой в экземпляре — остаток поймает повторная сверка */ } }
  }
  if (o.type === 'TEXT') {
    if (o.characters !== i.characters || segs(o) !== segs(i)) {
      const ref = i.componentPropertyReferences && i.componentPropertyReferences.characters;
      const own = ref ? ownerInstance(i) : null;
      if (own && segs(o).split('],[').length === 1) own.setProperties({ [ref]: o.characters });
      else {
        await loadSegFonts(i); await loadSegFonts(o);
        i.characters = o.characters;
        for (const s of o.getStyledTextSegments(['fontName', 'fontSize', 'fills', 'textDecoration'])) {
          i.setRangeFontName(s.start, s.end, s.fontName); i.setRangeFontSize(s.start, s.end, s.fontSize);
          i.setRangeFills(s.start, s.end, s.fills); i.setRangeTextDecoration(s.start, s.end, s.textDecoration);
        }
      }
    }
    return;
  }
  const oc = 'children' in o ? o.children : [], ic = 'children' in i ? i.children : [];
  for (let k = 0; k < oc.length; k++) await apply(oc[k], ic[k], false);
}

const out = { page: page.name, dry: DRY, done: [], skipped: [], errors: [], props: {}, hug: [] };
for (const ownerId of C.owners) {
  const set = await figma.getNodeByIdAsync(ownerId);
  const roots = set.type === 'COMPONENT_SET' ? set.children : [set];
  for (const p of C.pairs) {
    let boolKey = null;
    if (p.bool && !DRY) {
      const defs = set.componentPropertyDefinitions;
      boolKey = Object.keys(defs).find(k => k.replace(/#[^#]*$/, '') === p.bool.prop);
      if (!boolKey) boolKey = set.addComponentProperty(p.bool.prop, 'BOOLEAN', p.bool.def);
      out.props[ownerId + ' ' + p.bool.prop] = boolKey;
    }
    const base = await figma.getNodeByIdAsync(p.base);
    for (const v of roots) {
      const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
      const olds = v.findAll(n => n.type === 'FRAME' && !n.id.startsWith('I') && p.css.includes(n.getSharedPluginData('remlab', 'css'))
        && (!p.has || n.findAll(x => x.getSharedPluginData('remlab', 'css') === p.has).length > 0));
      for (const old of olds) {
        if (old.removed) continue; // уже удалена вместе с внешней
        // выбор варианта базы: тот же язык (если в базе есть такой), наименьшее число отличий
        let cands = base.children.filter(c => c.name.includes('Язык=' + lang));
        if (!cands.length) cands = base.children;
        let best = null;
        for (const c of cands) {
          const a = cmp(old, c, true, newAcc(p.rr));
          if (!best || score(a) < score(best.a)) best = { c, a };
        }
        const tag = v.id + ' ' + old.id + ' ' + p.css[0];
        if (!best || best.a.fail) { out.skipped.push(tag + ': ' + (best ? best.a.fail : 'нет вариантов')); continue; }
        const ov = ['al', 'vis', 'size', 'pos', 'text'].map(k => k + best.a[k].length).join(' ');
        if (DRY) { out.done.push(tag + ' → ' + best.c.id + ' ' + ov); continue; }
        // вставка
        const parent = old.parent, idx = parent.children.indexOf(old);
        const auto = isAL(parent);
        const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
          lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null, grow: auto ? old.layoutGrow : null,
          align: auto ? old.layoutAlign : null, cons: old.constraints };
        const inst = best.c.createInstance();
        parent.insertChild(idx, inst);
        inst.name = p.name;
        if (auto && st.pos === 'ABSOLUTE') inst.layoutPositioning = 'ABSOLUTE';
        // размер корня — ДО переноса (иначе ограничения детей корня без авто-раскладки съедят перенесённые размеры)
        if (p.size !== 'hug') {
          if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) inst.resize(st.w, st.h);
          if (auto && st.pos !== 'ABSOLUTE') { inst.layoutAlign = st.align; inst.layoutGrow = st.grow; inst.layoutSizingHorizontal = st.lsh; inst.layoutSizingVertical = st.lsv; }
        }
        await apply(old, inst, true);
        if (p.rr && inst.cornerRadius !== old.cornerRadius) inst.cornerRadius = old.cornerRadius; // скругление корня — переопределением
        // hug: ширина по тексту, высота — как была (у базы «Кнопка» высота FIXED 44; HUG дал бы 43)
        if (p.size === 'hug' && auto && st.pos !== 'ABSOLUTE') { inst.layoutAlign = st.align; inst.layoutGrow = st.grow; inst.layoutSizingHorizontal = 'HUG'; if (Math.abs(inst.height - st.h) > 0.01) inst.resize(inst.width, st.h); inst.layoutSizingVertical = st.lsv; }
        // NB: у EN-варианта базы «Кнопка» (221:10) текст не привязан к свойству «Текст» — apply() ставит его переопределением
        if (!auto || st.pos === 'ABSOLUTE') { inst.x = st.x; inst.y = st.y; }
        inst.constraints = st.cons;
        inst.visible = st.visible;
        // повторная сверка (корень — без размера)
        const chk = cmp(old, inst, true, newAcc());
        const resid = chk.fail || ['al', 'vis', 'size', 'pos', 'text'].filter(k => chk[k].length).map(k => k + ':' + chk[k].slice(0, 3).join(',')).join(' ');
        const rootOk = p.size === 'hug' ? Math.abs(inst.height - st.h) < 0.01 : (Math.abs(inst.width - st.w) < 0.01 && Math.abs(inst.height - st.h) < 0.01);
        if (resid || !rootOk) { out.errors.push(tag + ' остаток: ' + (resid || '') + (rootOk ? '' : ' корень ' + inst.width + 'x' + inst.height)); inst.remove(); continue; }
        if (p.size === 'hug' && Math.abs(inst.width - st.w) > 0.01) out.hug.push(inst.id + ' ' + st.w + '→' + (+inst.width.toFixed(2)));
        for (const k of old.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
        if (boolKey) inst.componentPropertyReferences = Object.assign({}, inst.componentPropertyReferences || {}, { visible: boolKey });
        if (p.expose) inst.isExposedInstance = true;
        const oldId = old.id;
        old.remove();
        out.done.push(tag + ' → ' + inst.id + ' (' + best.c.id + ') ' + ov);
      }
    }
  }
}
out.n = { done: out.done.length, skipped: out.skipped.length, errors: out.errors.length };
return out;
