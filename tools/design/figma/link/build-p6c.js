// design-02 П6в (T-20261104-04): группа «Избранное, бюджет, план, диалог» из экземпляров — книга Mobile.
// CFG = { lang: 'ru'|'en', only: ['08', …], g: {…переопределения отступов} } — какие экраны строить.
// RU → «Screens RU (components)» (280:2), EN → «Screens EN (components)» (293:2). Второй ряд под группой «Главная» (П6б):
// эталон x = i·900, y = Y0; сборка x = i·900+415. Повтор: узлы экрана (эталон, сборка, подписи) с теми же именами удаляются и
// строятся заново. Откат: удалить рамки ряда y = Y0 (id в ответе).
// Сцены: 08 план (шапка + Link / Back to Styles + Card / Floor Plan) · «главная с избранным» (счётчик в шапке, Progress Bar
// partial/over/upgradesExcluded, Link / Favorites, по желанию Popover / Info поверх, абсолютно) · «прокрутка вниз» с липкой шапкой
// (как 05 в П6б, вариант шкалы *Sticky) · «Избранное» (липкая шапка + Favorites / Header + Tag / Room Filter + Card / Layout +
// Language Switch; поверх — Popover favoriteCard или Modal / Mask с вложенным Modal / Name Input rename / Modal / Confirm).
const CFG = __CFG__;
const G = Object.assign({ root: 12, top: 8, head: -4, ctl: 6, main: 8, intro: 4, stCtl: 6, bottom: 2, lang: 49, desc: 1,
  favTop: 0, favMain: 9, favHead: 14, favCards: 12, favLang: 49, favProgTop: 6,
  emptyHead: 21, emptyGap: 24, emptyLang: 68, planMain: 12, planLinkX: 8 }, CFG.g || {});
const L = CFG.lang, RU = L === 'ru';
const Y0 = 1100;
const ORDER = RU ? ['08', '29', '30', '31', '32', '33', '34', '36', '37', '38', '39', '40', '41', '42']
  : ['08', '30', '31', '32', '33', '34', '35', '37', '38', '39', '40', '41', '42', '43', '44', '45'];
const REF = RU
  ? { '08': '22:10', '29': '22:30', '30': '22:31', '31': '22:32', '32': '22:33', '33': '22:34', '34': '22:35', '36': '22:37',
      '37': '22:38', '38': '22:39', '39': '22:40', '40': '22:41', '41': '22:42', '42': '22:43' }
  : { '08': '22:52', '30': '22:73', '31': '22:74', '32': '22:75', '33': '22:76', '34': '22:77', '35': '22:78', '37': '22:80',
      '38': '22:81', '39': '22:82', '40': '22:83', '41': '22:84', '42': '22:85', '43': '22:86', '44': '22:87', '45': '22:88' };
const C = RU ? {
  bar: '126:8', barSticky: '126:16', complex: '126:42', actions: '126:111', favBtn: '126:90',
  pEmpty: '58:12', pSticky: '58:24', pPartial: '58:37', pPartialSticky: '58:50', pOver: '58:72', pOverSticky: '58:93',
  popPartial: '58:454', popOver: '58:458', popCard: '58:450',
  hint: '105:411', tabs: '94:44', tabsSticky: '94:57', room: '64:21', soon: '64:124', plan: '64:111', lang: '105:450', favLink: '105:425',
  backStyles: '105:439', floorPlan: '86:72', favHeader: '127:7', chipOn: '127:21', chipOff: '299:78',
  cardFav: '127:54', cardTotal: '127:80', cardEx: '127:105', cardNoPhoto: '299:38', empty: '127:189',
  mask: '85:100', mRename: '85:30', mConfirm: '85:73',
} : {
  bar: '126:24', barSticky: '126:32', complex: '126:56', actions: '126:118', favBtn: '126:101',
  pEmpty: '58:116', pSticky: '58:129', pPartial: '58:154', pPartialSticky: '58:169', pOver: '58:204', pOverSticky: '58:227', pUpEx: '58:245',
  popPartial: '58:501', popOver: '58:513', popUpEx: '58:525', popCard: '58:489',
  hint: '105:415', tabs: '94:70', tabsSticky: '94:83', room: '64:63', soon: '64:129', plan: '64:116', lang: '105:454', favLink: '105:432',
  backStyles: '105:443', floorPlan: '86:144', favHeader: '127:14', chipOn: '127:25', chipOff: '299:80',
  cardFav: '127:131', cardTotal: '127:157', cardEx: '127:182', cardNoPhoto: '299:58', empty: '127:193',
  mask: '85:114', mRename: '85:60', mConfirm: '85:83',
};
const ROOMS = RU
  ? [['Кухня', '13,2 м²'], ['Спальня 1', '17,5 м²'], ['Спальня 2', '9,7 м²'], ['Санузел 1', '4,4 м²'], ['Санузел 2', '3,9 м²'], ['Прихожая', '9,3 м²']]
  : [['Kitchen', '13.2 m²'], ['Bedroom 1', '17.5 m²'], ['Bedroom 2', '9.7 m²'], ['Bathroom 1', '4.4 m²'], ['Bathroom 2', '3.9 m²'], ['Hallway', '9.3 m²']];
const W = RU ? { room: 'Гостиная', kitchen: 'Кухня', inCert: 'в сертификате: Гостиная', inCert2: 'в сертификате: Гостиная, Кухня' }
  : { room: 'Living room', kitchen: 'Kitchen', inCert: 'in the allowance: Living room', inCert2: 'in the allowance: Living room, Kitchen' };
// Сцен-зависимые числа и позиции (сверены по эталонам 04.11; уточнения — CFG.g / CFG.y).
const Y = Object.assign(RU ? { pop33: 172, pop38: 202, popCard: 426, modal31: 250, modal41: 291 }
  : { popCard: 476, pop34: 222, pop39: 252, pop42: 201, modal32: 250, modal44: 322 }, CFG.y || {});

for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const page = await figma.getNodeByIdAsync(RU ? '280:2' : '293:2');
await figma.setCurrentPageAsync(page);
const vars = {};
for (const [k, id] of Object.entries({ bgPage: 'VariableID:4:3', textSecondary: 'VariableID:4:6', sp6: 'VariableID:4:43', sp12: 'VariableID:4:49' }))
  vars[k] = await figma.variables.getVariableByIdAsync(id);
const comp = {};
for (const [k, id] of Object.entries(C)) comp[k] = await figma.getNodeByIdAsync(id);
const captionStyle = (await figma.getLocalTextStylesAsync()).find(s => s.name === 'Текст/14 Regular');

const paintVar = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }, 'color', v)];
const gap = (f, n) => { f.itemSpacing = n; const v = n === 12 ? vars.sp12 : n === 6 ? vars.sp6 : null; if (v) f.setBoundVariable('itemSpacing', v); };
const col = (name, g) => { const f = figma.createAutoLayout('VERTICAL', { name }); f.fills = []; f.counterAxisAlignItems = 'CENTER'; gap(f, g); return f; };
const add = (parent, node, fill) => { parent.appendChild(node); if (fill) node.layoutSizingHorizontal = 'FILL'; return node; };
const inst = (k, name) => { const i = comp[k].createInstance(); if (name) i.name = name; return i; };
const sub = (i, origId) => i.findOne(n => n.id.endsWith(';' + origId));
const rep = (t, from, to) => { const k = t.characters.indexOf(from); if (k < 0) return false; t.insertCharacters(k, to, 'AFTER'); t.deleteCharacters(k + to.length, k + to.length + from.length); return true; };
const repIn = (i, from, to) => { for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) return t.id; return null; };
const caption = (text, x, nm) => {
  const t = figma.createText(); t.textStyleId = captionStyle.id; t.characters = text; t.name = nm;
  t.fills = paintVar(vars.textSecondary); t.x = x; t.y = Y0 - 32; page.appendChild(t); return t;
};
const screen = (name, x) => {
  const f = figma.createAutoLayout('VERTICAL', { name });
  f.resize(375, 812); f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
  f.counterAxisAlignItems = 'CENTER'; f.clipsContent = true; f.fills = paintVar(vars.bgPage);
  f.x = x; f.y = Y0; page.appendChild(f); return f;
};
const abs = (s, node, x, y) => { s.appendChild(node); node.layoutPositioning = 'ABSOLUTE'; node.x = x; node.y = y; return node; };
// Сумма в шкале: первое число строки (разделитель тысяч — из исходного текста) → to.
const repNum = (t, to) => {
  const m = t.characters.match(/\d[\d\s  ,.]*\d/); if (!m) return false;
  const sep = (m[0].match(/[\s  ]/) || [' '])[0]; to = to.replace(/ /g, sep);
  t.insertCharacters(m.index, to, 'AFTER'); t.deleteCharacters(m.index + to.length, m.index + to.length + m[0].length); return true;
};
// Заливка полосы во вложенном экземпляре: правое поле части + FILL у заливки (грабля П6б: resize в экземпляре молча игнорируется).
const setFill = (f, share) => { const w = f.parent.width; f.parent.paddingRight = w - Math.max(1, Math.round(w * share)); f.layoutSizingHorizontal = 'FILL'; };
const firstText = p => p.findAllWithCriteria({ types: ['TEXT'] })[0];
// Шкала: вариант + (по желанию) своя сумма/заливка. RU — заливка 58:338 в партиале; EN — 58:357 + легенда (как П6б).
const progress = (parent, key, sum) => {
  const p = add(parent, inst(key, 'Progress Bar'));
  if (sum) {
    repNum(firstText(p), sum.text);
    if (RU) setFill(sub(p, '58:338'), sum.share);
    else { setFill(sub(p, '58:357'), sum.share); const u = sub(p, '58:359'); if (u) u.visible = false; repIn(p, '1,200', '1,264'); repIn(p, '3,000', '0'); }
  }
  return p;
};
const SUM = { fav1: RU ? { text: '141 979', share: 141979 / 600000 } : { text: '1,264', share: 1264 / 4500 }, ru350: { text: '350 000', share: 350000 / 600000 } };
const bar = (parent, key, count) => {
  const b = add(parent, inst(key, 'Header / Apartment Bar'));
  if (count) {
    const h = b.findOne(n => n.type === 'INSTANCE' && n.name === 'Кнопка избранного'); h.swapComponent(comp.favBtn);
    const t = h.findOne(n => n.type === 'TEXT' && n.parent.name === 'Счётчик'); if (t && count !== 1) t.characters = String(count);
  }
  return b;
};
const content = (parent) => {
  const c = add(parent, col('Content', G.lang), false);
  const rooms = col('Rooms', 12); add(c, rooms, false);
  add(rooms, inst('room', 'Card / Room'));
  for (const [n, a] of ROOMS) {
    const s = add(rooms, inst('soon', 'Card / Coming Soon · ' + n));
    if (RU) s.setProperties({ 'title#287:0': n, 'area#287:3': a });
    else { s.findOne(x => x.name === 'title').characters = n; s.findOne(x => x.name === 'area').characters = a; }
  }
  add(rooms, inst('plan', 'Card / Plan Tile'));
  add(c, inst('lang', 'Language Switch'));
  return c;
};
// Верх главной: шапка (+счётчик) · строка ЖК · действия · шкала.
const homeTop = (s, o) => {
  const topc = add(s, col('Top', G.top), true);
  const head = add(topc, col('Header', G.head), true);
  bar(head, 'bar', o.count);
  add(head, inst('complex', 'Header / Complex Row'));
  const ctl = add(topc, col('Controls', G.ctl), true);
  add(ctl, inst('actions', 'Header / Actions'));
  progress(ctl, o.prog, o.sum);
  return topc;
};
const home = (s, o) => {
  gap(s, G.root); homeTop(s, o);
  const main = add(s, col('Main', G.main), true);
  const fl = add(main, inst('favLink', 'Link / Favorites'));
  if (o.count && o.count !== 1) repIn(fl, '· 1', '· ' + o.count);
  const intro = add(main, col('Intro', G.intro), true);
  add(intro, inst('hint', 'Home / Hint'));
  add(intro, inst('tabs', 'Tabs'));
  content(main);
  if (o.pop) abs(s, inst(o.pop, 'Popover / Info'), 12, o.popY);
};
const sticky = (s, o) => {
  const st = add(s, col('Sticky Header', 0), false); st.fills = paintVar(vars.bgPage);
  st.layoutPositioning = 'ABSOLUTE'; st.x = 0; st.y = 0; st.resize(375, 10);
  st.counterAxisSizingMode = 'FIXED'; st.primaryAxisSizingMode = 'AUTO';
  st.constraints = { horizontal: 'STRETCH', vertical: 'MIN' };
  bar(st, 'barSticky', o.count).layoutSizingHorizontal = 'FILL';
  const st2 = add(st, col('Sticky Controls', G.stCtl), true);
  progress(st2, o.prog, o.sum);
  if (o.tabs !== false) add(st2, inst('tabsSticky', 'Tabs'));
  return st;
};
const scrolled = (s, o) => { s.primaryAxisAlignItems = 'MAX'; s.paddingBottom = G.bottom; content(s); sticky(s, o); };
// «Избранное»: липкая шапка (без вкладок) в потоке · заголовок · фильтры · карточки · язык.
const favs = (s, o) => {
  gap(s, G.favTop);
  const top = add(s, col('Sticky Header', 0), true);
  bar(top, 'barSticky', o.count).layoutSizingHorizontal = 'FILL';
  const st2 = add(top, col('Sticky Controls', G.stCtl), true);
  st2.paddingTop = G.favProgTop; progress(st2, o.prog, o.sum);
  const main = add(s, col('Main', o.empty ? G.emptyGap : G.favMain), true); main.paddingTop = o.empty ? G.emptyHead : G.favHead;
  const h = add(main, inst('favHeader', 'Favorites / Header'));
  if (o.count === 0) { repIn(h, ' · 1', ''); const st = h.findAllWithCriteria({ types: ['TEXT'] })[2]; if (st) st.visible = false; }
  else if (o.count !== 1) { repIn(h, '· 1', '· ' + o.count); repIn(h, W.inCert, W.inCert2); }
  if (o.empty) { add(main, inst('empty', 'Empty / Favorites')); }
  else {
    const chips = figma.createAutoLayout('HORIZONTAL', { name: 'Filters' }); chips.fills = []; gap(chips, 6);
    add(main, chips, true); chips.paddingLeft = 12;
    const on = inst('chipOn', 'Tag / Room Filter'); chips.appendChild(on);
    if (o.count === 3) repIn(on, '· 1', '· 2');
    if (o.count > 1) { const off = inst('chipOff', 'Tag / Room Filter'); chips.appendChild(off); repIn(off, W.room, W.kitchen); }
    const cards = add(main, col('Cards', G.favCards), false);
    for (const k of o.cards) add(cards, inst(k, 'Card / Layout'));
  }
  main.paddingBottom = o.empty ? G.emptyLang : G.favLang; // отступ до языка — полем Main
  add(s, inst('lang', 'Language Switch'));
  if (o.popCard) { const pc = abs(s, inst('popCard', 'Popover / Info'), 24, o.popCard); pc.resize(326, pc.height); } // как на сайте: 24..350
  if (o.modal) {
    const m = abs(s, inst('mask', 'Modal / Mask'), 0, 0);
    const prop = Object.keys(m.componentProperties).find(k => k.startsWith('showModal')); m.setProperties({ [prop]: false });
    // Окно — отдельным экземпляром поверх маски: вложенный экземпляр после swap держит размер 343x199 и обрезает
    // окно «переименовать» (311), а x/y вложенного не переопределить (relative-transform).
    abs(s, inst(o.modal, 'Modal'), 16, o.modalY != null ? o.modalY : 250);
  }
};
const plan = s => {
  gap(s, G.root); homeTop(s, { prog: 'pEmpty' });
  const main = add(s, col('Main', G.planMain), true);
  const row = figma.createAutoLayout('HORIZONTAL', { name: 'Back' }); row.fills = []; add(main, row, true); row.paddingLeft = G.planLinkX;
  const b = inst('backStyles', 'Link / Back to Styles'); row.appendChild(b);
  const card = add(main, inst('floorPlan', 'Card / Floor Plan'));
  const lg = add(main, inst('lang', 'Language Switch'));
  return { main, b, card, lg };
};
const FAV1 = { count: 1, prog: 'pPartialSticky', sum: SUM.fav1, cards: ['cardFav'] };
const SCENES = RU ? {
  '08': plan,
  '29': s => favs(s, FAV1), '30': s => favs(s, { ...FAV1, popCard: Y.popCard }), '31': s => favs(s, { ...FAV1, modal: 'mRename', modalY: Y.modal31 }),
  '32': s => home(s, { count: 1, prog: 'pPartial' }), '33': s => home(s, { count: 1, prog: 'pPartial', pop: 'popPartial', popY: Y.pop33 }),
  '34': s => scrolled(s, { count: 1, prog: 'pPartialSticky' }),
  '36': s => favs(s, { count: 1, prog: 'pPartialSticky', cards: ['cardNoPhoto'] }),
  '37': s => home(s, { count: 2, prog: 'pOver' }), '38': s => home(s, { count: 2, prog: 'pOver', pop: 'popOver', popY: Y.pop38 }),
  '39': s => scrolled(s, { count: 2, prog: 'pOverSticky' }),
  '40': s => favs(s, { count: 3, prog: 'pPartialSticky', sum: SUM.ru350, cards: ['cardEx', 'cardNoPhoto'] }),
  '41': s => favs(s, { count: 3, prog: 'pPartialSticky', sum: SUM.ru350, cards: ['cardEx', 'cardNoPhoto'], modal: 'mConfirm', modalY: Y.modal41 }),
  '42': s => favs(s, { count: 0, prog: 'pSticky', empty: true }),
} : {
  '08': plan,
  '30': s => favs(s, { ...FAV1, prog: 'pPartial' }), '31': s => favs(s, { ...FAV1, prog: 'pPartial', popCard: Y.popCard }),
  '32': s => favs(s, { ...FAV1, prog: 'pPartial', modal: 'mRename', modalY: Y.modal32 }),
  '33': s => home(s, { count: 2, prog: 'pPartial' }), '34': s => home(s, { count: 2, prog: 'pPartial', pop: 'popPartial', popY: Y.pop34 }),
  '35': s => scrolled(s, { count: 2, prog: 'pPartialSticky' }),
  '37': s => favs(s, { count: 2, prog: 'pPartial', cards: ['cardNoPhoto'] }),
  '38': s => home(s, { count: 2, prog: 'pOver' }), '39': s => home(s, { count: 2, prog: 'pOver', pop: 'popOver', popY: Y.pop39 }),
  '40': s => scrolled(s, { count: 2, prog: 'pOverSticky' }),
  '41': s => home(s, { count: 2, prog: 'pUpEx' }), '42': s => home(s, { count: 2, prog: 'pUpEx', pop: 'popUpEx', popY: Y.pop42 }),
  '43': s => favs(s, { count: 3, prog: 'pPartial', cards: ['cardEx', 'cardNoPhoto'] }),
  '44': s => favs(s, { count: 3, prog: 'pPartial', cards: ['cardEx', 'cardNoPhoto'], modal: 'mConfirm', modalY: Y.modal44 }),
  '45': s => favs(s, { count: 0, prog: 'pEmpty', empty: true }),
};

const out = { page: page.id, screens: {} };
for (const key of CFG.only) {
  const i = ORDER.indexOf(key); const xr = i * 900, xb = xr + 415;
  const o = await figma.getNodeByIdAsync(REF[key]);
  for (const n of [...page.children]) if (n.y >= Y0 - 40 && (n.name === o.name || n.name === 'эталон · ' + o.name || n.name.startsWith('caption · c' + key + ' '))) n.remove();
  const d = o.clone(); page.appendChild(d); d.x = xr; d.y = Y0; d.name = 'эталон · ' + o.name; d.locked = true;
  caption('эталон — снимок сайта 26.10', xr, 'caption · c' + key + ' ref');
  const s = screen(o.name, xb);
  caption('сборка из компонентов', xb, 'caption · c' + key + ' build');
  SCENES[key](s);
  for (const f of s.findAllWithCriteria({ types: ['INSTANCE'] }))
    if (Math.round(f.width) === 375 && f.parent !== s && f.parent.type !== 'INSTANCE' && f.parent.layoutSizingHorizontal === 'FILL' && f.layoutPositioning !== 'ABSOLUTE') f.layoutSizingHorizontal = 'FILL';
  const tops = s.findAllWithCriteria({ types: ['INSTANCE'] }).filter(n => n.parent.type !== 'INSTANCE')
    .map(n => n.name.replace(/^.* \/ /, '').slice(0, 10) + ' y' + Math.round(n.absoluteTransform[1][2] - Y0) + ' h' + Math.round(n.height));
  out.screens[key] = { ref: d.id, build: s.id, tops: tops.join(' | ') };
}
return out;
