// design-02 П6е (T-20261104-08): копия build-p6e.js + EN — шкала из двух полос (Furniture and appliances из 4,500, Upgrades из 8,000,
// общий £12,500): partial() ставит общую сумму, суммы легенды и заливку обеих полос; EN 36/37 «без сертификата» (29:239, 29:515).
// Цена в карточке избранного EN — с «£». RU-ветка не менялась.
// design-02 П6д (T-20261104-07): книга Desktop — «Главная» и «Избранное, бюджет, план, диалог» из экземпляров.
// CFG = { lang: 'ru'|'en', only: ['01', …], g: {…зазоры}, n: {…числа} }. RU → «Screens RU (components)», EN → «Screens EN (components)»
// (создаются в конце списка). Слоты: группа «Главная» — столбец x 0 (эталон) | 1540 (сборка), y = i·1100;
// группа «Избранное…» — x 3300 | 4840. Повтор: узлы экрана (эталон, сборка, подписи) с теми же именами удаляются и строятся заново.
// Откат: удалить страницы целиком. Экран 1440×900: корень на авто-раскладке (вертикально, по центру), колонка «Page» 1100
// (элементы 1072 — по центру, т. е. поля 14), внутри только экземпляры; тексты вне компонентов не нужны.
const CFG = __CFG__;
const L = CFG.lang, RU = L === 'ru';
const G = Object.assign({ ctl: 4, pb: 6, hint: 12, tabs: 7, rooms: 13, lang: 57, desc: 8, descPt: 6, descPb: 10, fav: 12, favHint: 6,
  favHead: 14, chips: 9, cards: 10, favLang: 60, emptyHead: 21, emptyPt: 27, emptyLang: 76, back: 12, planCard: 20 }, CFG.g || {});
const HOME = RU ? ['01', '02', '03', '04', '05', '06', '07', '23'] : ['01', '02', '03', '04', '05', '06', '07', '24'];
const REF = RU
  ? { '01': '16:3', '02': '16:4', '03': '16:5', '04': '16:6', '05': '16:7', '06': '16:8', '07': '16:9', '08': '16:10', '23': '16:25' }
  : { '01': '16:41', '02': '16:42', '03': '16:43', '04': '16:44', '05': '16:45', '06': '16:46', '07': '16:47', '08': '16:48', '24': '16:64' };
for (let k = 24; k <= 40; k++) REF[String(k)] = REF[String(k)] || (RU ? (k <= 37 ? '16:' + (k + 2) : null) : '16:' + (k + 40));
const C = RU ? {
  bar: '55:8', barSticky: '55:16', complex: '55:44', complexExp: '55:53', desc: '55:79', actions: '55:119', favBtn: '55:98',
  progress: '29:12', progressSticky: '29:24', progressPartial: '29:37', hint: '52:4', tabs: '35:13', tabSel: '35:59', tabDef: '35:63',
  room: '25:21', roomAlt: '25:42', soon: '25:124', plan: '25:111', lang: '52:43', popover: '29:432', favLink: '52:18',
  favHeader: '48:1531', chip: '48:1545', chipOff: '123:78', cardPhoto: '48:1604', cardNoPhoto: '123:38', cardExc: '48:1629', empty: '48:1713',
  mask: '37:100', rename: '37:30', confirm: '37:73', popCard: '29:440', popPartial: '29:444', popOver: '29:448', progressOver: '29:72',
  progressPartialSticky: '29:50', progressOverSticky: '29:93', back: '52:32', floorCard: '42:72', favBtnEmpty: '55:91',
} : {
  bar: '55:24', barSticky: '55:32', complex: '55:62', complexExp: '55:71', desc: '55:84', actions: '55:126', favBtn: '55:109',
  progress: '29:114', progressSticky: '29:127', progressPartial: '29:150', hint: '52:8', tabs: '35:39', tabSel: '35:67', tabDef: '35:71',
  room: '25:63', roomAlt: '25:84', soon: '25:129', plan: '25:116', lang: '52:47', popover: '29:460', favLink: '52:25',
  favHeader: '48:1538', chip: '48:1549', chipOff: '123:80', cardPhoto: '48:1681', cardNoPhoto: '123:58', cardExc: '48:1706', empty: '48:1717',
  mask: '37:114', rename: '37:60', confirm: '37:83', popCard: '29:479', popPartial: '29:491', popOver: '29:503', progressOver: '29:198',
  progressPartialSticky: '29:165', progressOverSticky: '29:221', back: '52:36', floorCard: '42:144', favBtnEmpty: '55:102',
  progressExcl: '29:239', popExcl: '29:515',
};
const ROOMS = RU
  ? [['Кухня', '13,2'], ['Спальня 1', '17,5'], ['Спальня 2', '9,7'], ['Санузел 1', '4,4'], ['Санузел 2', '3,9'], ['Прихожая', '9,3']]
  : [['Kitchen', '13.2'], ['Bedroom 1', '17.5'], ['Bedroom 2', '9.7'], ['Bathroom 1', '4.4'], ['Bathroom 2', '3.9'], ['Hallway', '9.3']];
const N = Object.assign(RU
  ? { scroll: 67, pop: 158, cert: 600000, favSum: 141979, favPrice: ['137 267', '141 979'], date: ['09.10.2025', '26.10.2026'], cardSum: '250 000',
      fav3: 'Избранное · 3', fav3sub: 'в сертификате: Гостиная, Кухня', favT: 'Избранное', chip2: ['Гостиная · 2', 'Кухня · 1'], card2: '200 000', sum3: 350000 }
  : { scroll: 67, pop: 158, cert: 4500, favSum: 1264, favPrice: ['£1,222', '£1,264'], date: ['09.10.2025', '26.10.2026'], cardSum: '£4,200',
      fav3: 'Favourites · 3', fav3sub: 'in the allowance: Living room, Kitchen', favT: 'Favourites', chip2: ['Living room · 2', 'Kitchen · 1'], card2: '£1,500', sum3: 2600 }, CFG.n || {});
const FAV = RU ? ['08', '24', '25', '26', '27', '28', '29', '31', '32', '33', '34', '35', '36', '37']
  : ['08', '25', '26', '27', '28', '29', '30', '32', '33', '34', '35', '36', '37', '38', '39', '40'];

for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const PAGE_NAME = RU ? 'Screens RU (components)' : 'Screens EN (components)';
let page = figma.root.children.find(p => p.name === PAGE_NAME);
if (!page) { page = figma.createPage(); page.name = PAGE_NAME; }
await figma.setCurrentPageAsync(page);
const V = {};
for (const [k, id] of Object.entries({ bgPage: '5:3', textSecondary: '5:6' })) V[k] = await figma.variables.getVariableByIdAsync('VariableID:' + id);
const SP = {}; // зазоры авто-раскладки — на переменные «1…24» книги, где значение совпадает
for (let k = 38; k <= 55; k++) { const v = await figma.variables.getVariableByIdAsync('VariableID:5:' + k); if (v && v.resolvedType === 'FLOAT') SP[Object.values(v.valuesByMode)[0]] = v; }
const comp = {};
for (const [k, id] of Object.entries(C)) comp[k] = await figma.getNodeByIdAsync(id);
const captionStyle = (await figma.getLocalTextStylesAsync()).find(s => s.name === 'Текст/14 Regular');
const shadow = (await figma.getLocalEffectStylesAsync()).find(s => s.name === (CFG.shadow || 'Тень/e2'));
const fonts = new Set(); // шрифты текстов в экземплярах (переопределение текста требует загруженного шрифта)
for (const k of ['soon', 'room', 'progressPartial', 'tabs', 'tabDef', 'favHeader', 'chip', 'cardPhoto', 'cardExc', 'empty']) { const t0 = comp[k].createInstance();
  for (const t of t0.findAllWithCriteria({ types: ['TEXT'] })) for (const s of t.getStyledTextSegments(['fontName'])) fonts.add(JSON.stringify(s.fontName));
  t0.remove(); }
for (const f of fonts) await figma.loadFontAsync(JSON.parse(f));

const paintVar = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }, 'color', v)];
const gap = (f, n) => { f.itemSpacing = n; if (SP[n]) f.setBoundVariable('itemSpacing', SP[n]); };
const col = (name, g, dir) => { const f = figma.createAutoLayout(dir || 'VERTICAL', { name }); f.fills = []; if (!dir) f.counterAxisAlignItems = 'CENTER'; gap(f, g); return f; };
const add = (p, n, fill) => { p.appendChild(n); if (fill) n.layoutSizingHorizontal = 'FILL'; return n; };
const inst = (k, name) => { const i = comp[k].createInstance(); if (name) i.name = name; return i; };
const sub = (i, origId) => i.findOne(n => n.id.endsWith(';' + origId));
// замена с сохранением стиля; пробел в образце совпадает и с неразрывным (суммы «250 000» в компонентах — через U+00A0/U+202F)
const rep = (t, from, to) => { let k = t.characters.indexOf(from);
  if (k < 0) { const re = new RegExp(from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, '[\\s\\u00a0\\u202f]')); const m = t.characters.match(re);
    if (!m) return false; k = m.index; const sep = (m[0].match(/[\u00a0\u202f]/) || [' '])[0]; from = m[0]; to = to.replace(/ /g, sep); }
  t.insertCharacters(k, to, 'AFTER'); t.deleteCharacters(k + to.length, k + to.length + from.length); return true; };
const repIn = (i, from, to) => { for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) return t.id; return null; };
const caption = (text, x, y, nm) => { const t = figma.createText(); t.textStyleId = captionStyle.id; t.characters = text; t.name = nm;
  t.fills = paintVar(V.textSecondary); t.x = x; t.y = y - 32; page.appendChild(t); return t; };
const screen = (name, x, y) => { const f = figma.createAutoLayout('VERTICAL', { name });
  f.resize(1440, 900); f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
  f.counterAxisAlignItems = 'CENTER'; f.clipsContent = true; f.fills = paintVar(V.bgPage); f.x = x; f.y = y; page.appendChild(f); return f; };
const fixW = (f, w) => { f.resize(w, f.height); // ширина фиксирована, высота — по содержимому (у горизонтальной — по главной оси)
  if (f.layoutMode === 'HORIZONTAL') { f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'AUTO'; }
  else { f.counterAxisSizingMode = 'FIXED'; f.primaryAxisSizingMode = 'AUTO'; } return f; };
const absAt = (s, n, x, y) => { s.appendChild(n); n.layoutPositioning = 'ABSOLUTE'; n.x = x; n.y = y; return n; };

// Сумма и заливка шкалы «есть избранное»: размер слоя во вложенном экземпляре не переопределяется — правое поле части полосы + FILL.
const setFill = (f, share) => { const w = f.parent.width; f.parent.paddingRight = w - Math.max(1, Math.round(w * share)); f.layoutSizingHorizontal = 'FILL'; };
// Сумма «Выбрано …» и заливка полосы по доле от сертификата (слои ищутся по именам — одинаковы во всех вариантах шкалы).
const fmt = v => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, RU ? ' ' : ','); // toLocaleString в песочнице Фигмы без разделителей
const num = (t, v) => { const m = t && t.characters.match(/\d[\d\s\u00a0\u202f,.]*\d|\d/);
  if (m) { const sep = (m[0].match(/[\s\u00a0\u202f]/) || [' '])[0]; rep(t, m[0], fmt(v).replace(/ /g, sep)); } };
// v: число (RU — сумма; EN — только «мебель», улучшения 0) или { furn, upg } (EN). EN: общий «Chosen» = furn+upg,
// легенда «X / 4,500» и «Y / 8,000», заливка частей полосы по долям; часть с нулём — заливка скрыта.
const partial = (p, v) => {
  const t = p.findOne(n => n.type === 'TEXT' && n.name === 'Выбрано');
  if (RU) { num(t, v); const f = p.findOne(n => n.type === 'FRAME' && n.name === 'Выбрано (заливка)'); if (f) setFill(f, v / N.cert); return; }
  const o = typeof v === 'number' ? { furn: v, upg: 0 } : v; num(t, o.furn + o.upg);
  const leg = p.findAll(n => n.type === 'TEXT' && n.name === 'Выбрано / доступно');
  [o.furn, o.upg].forEach((x, k) => { if (leg[k]) num(leg[k], x); });
  const fills = p.findAll(n => n.type === 'FRAME' && n.name === 'Выбрано (заливка)');
  [[o.furn, 4500], [o.upg, 8000]].forEach(([x, cap], k) => { const f = fills[k]; if (!f) return;
    if (x <= 0) f.visible = false; else setFill(f, Math.min(1, x / cap)); });
};
const money = v => RU ? fmt(v) : '£' + fmt(v);
const rooms = (parent, o) => {
  const row = add(parent, col('Rooms', 12, 'HORIZONTAL'), false); row.counterAxisAlignItems = 'MIN';
  const room = add(row, inst(o.alt ? 'roomAlt' : 'room', 'Card / Room'));
  if (o.price) repIn(room, N.favPrice[0], N.favPrice[1]);
  const list = add(row, col('Rooms · next', 12), false);
  ROOMS.forEach(([n, a], k) => { const s = add(list, inst('soon', 'Card / Coming Soon · ' + n)); if (k) { repIn(s, ROOMS[0][0], n); repIn(s, ROOMS[0][1], a); } });
  add(list, inst('plan', 'Card / Plan Tile'));
  return row;
};
// Колонка Page (1100) без общего зазора: группы Top / Budget / Intro / Rooms, у каждой свой зазор полем сверху (как на сайте).
const page1 = (parent, o) => {
  const pg = add(parent, col('Page', 0), false); fixW(pg, 1100);
  const grp = (name, g) => { const f = add(pg, col(name, g), false); fixW(f, 1100); return f; };
  const top = grp('Top', G.ctl);       // шапка + ряд ЖК/кнопок
  const mid = grp('Budget', 0);        // шкала (+ ссылка «Избранное»)
  const intro = grp('Intro', G.tabs);  // подсказка + вкладки
  favBar(add(top, inst('bar', 'Header / Apartment Bar')), o);
  if (o.favPage) return favPage(pg, top, mid, intro, o);
  const ctl = add(top, col('Controls', 0, 'HORIZONTAL'), false); fixW(ctl, 1072); ctl.counterAxisAlignItems = o.expanded ? 'MIN' : 'CENTER';
  if (o.expanded) {
    const cx = add(ctl, col('Complex', G.desc), false); cx.counterAxisAlignItems = 'MIN'; cx.layoutSizingHorizontal = 'FILL'; cx.paddingTop = G.descPt;
    add(cx, inst('complexExp', 'Header / Complex Row'), true); add(cx, inst('desc', 'Descriptions / Apartment'));
  } else add(ctl, inst('complex', 'Header / Complex Row'), true);
  add(ctl, inst('actions', 'Header / Actions'));
  budget(mid, o);
  if (o.fav) { gap(mid, G.fav); const l = add(mid, inst('favLink', 'Link / Favorites')); if (o.link) repIn(l, '· 1', '· ' + o.link); }
  if (o.plan) { intro.counterAxisAlignItems = 'MIN'; intro.paddingLeft = 14; gap(intro, G.planCard); intro.paddingTop = G.back;
    if (SP[G.back]) intro.setBoundVariable('paddingTop', SP[G.back]); add(intro, inst('back', 'Link / Back to Styles')); add(intro, inst('floorCard', 'Card / Floor Plan'));
    mid.paddingTop = G.pb; return pg; }
  add(intro, inst('hint', 'Home / Hint'));
  const tabs = add(intro, inst('tabs', 'Tabs'));
  if (o.tab2) {
    const t = tabs.children.filter(n => n.type === 'INSTANCE'); const txt = x => x.findOne(n => n.type === 'TEXT');
    const l0 = txt(t[0]).characters, l2 = txt(t[2]).characters;
    t[0].swapComponent(comp.tabDef); t[2].swapComponent(comp.tabSel); txt(t[0]).characters = l0; txt(t[2]).characters = l2;
  }
  const r = rooms(pg, o);
  // зазоры между группами — полями сверху групп (рамки раскладки, не экземпляры)
  const pads = [[mid, o.expanded ? G.descPb : G.pb], [intro, o.fav ? G.favHint : G.hint], [r, G.rooms]];
  for (const [f, v] of pads) { f.paddingTop = v; if (SP[v]) f.setBoundVariable('paddingTop', SP[v]); }
  return pg;
};
const favBar = (bar, o) => { if (o.fav) { const b = bar.findOne(n => n.type === 'INSTANCE' && n.name === 'Кнопка избранного'); b.swapComponent(comp.favBtn);
  if (o.link) repIn(b, '1', String(o.link)); } return bar; };
const budget = (mid, o, sticky) => { const k0 = o.pb || (o.fav ? 'progressPartial' : 'progress'); const k = sticky ? k0 + 'Sticky' : k0;
  const pb = add(mid, inst(k, 'Progress Bar')); if (o.sum) partial(pb, o.sum); return pb; };
// Экран «Избранное»: шапка · шкала · заголовок «← Назад · Избранное» · чипы комнат · карточки расстановок; язык — внизу корня.
const favPage = (pg, top, mid, intro, o) => {
  budget(mid, o); intro.remove(); mid.paddingTop = G.pb; if (SP[G.pb]) mid.setBoundVariable('paddingTop', SP[G.pb]);
  const hw = add(pg, col('Favorites · head', 0), false); fixW(hw, 1100); hw.paddingTop = o.headPt ?? G.favHead;
  const h = add(hw, inst('favHeader', 'Favorites / Header'));
  if (o.head) { const ts = h.findAllWithCriteria({ types: ['TEXT'] }); ts[1].characters = o.head[0]; if (o.head[1]) ts[2].characters = o.head[1]; else ts[2].visible = false; }
  const wrap = (name, g, pt) => { const f = add(pg, col(name, g, 'HORIZONTAL'), false); fixW(f, 1072); f.paddingTop = pt; if (SP[pt]) f.setBoundVariable('paddingTop', SP[pt]); return f; };
  if (o.empty) { const e = add(pg, col('Favorites · empty', 0), false); fixW(e, 1100); e.paddingTop = G.emptyPt; add(e, inst('empty', 'Empty / Favorites')); return pg; }
  const chips = wrap('Room Filter', 8, G.chips);
  (o.chips || [[1]]).forEach(([on, txt]) => { const c = add(chips, inst(on ? 'chip' : 'chipOff', 'Tag / Room Filter')); if (txt) c.findOne(n => n.type === 'TEXT').characters = txt; });
  const cards = wrap('Layouts', 12, G.cards); cards.counterAxisAlignItems = 'MIN';
  for (const c of o.cards) { const i = add(cards, inst(c.k, 'Card / Layout')); for (const [a, b] of c.rep || []) repIn(i, a, b); }
  return pg;
};
const sticky = (s, o = {}) => {
  const st = col('Sticky Header', 0); st.fills = paintVar(V.bgPage); if (shadow) st.effectStyleId = shadow.id;
  absAt(s, st, 170, 0); fixW(st, 1100); st.paddingBottom = G.stickyPb || 6; if (SP[st.paddingBottom]) st.setBoundVariable('paddingBottom', SP[st.paddingBottom]);
  favBar(add(st, inst('barSticky', 'Header / Apartment Bar')), o); budget(st, o, true);
  return st;
};
const SCENES = {
  '01': s => page1(s, {}),
  '02': s => page1(s, { expanded: true }),
  '03': s => { page1(s, {}); absAt(s, inst('popover', 'Popover / Info'), 184, N.pop); },
  '04': s => { const w = col('Page · scrolled', 0); absAt(s, w, 0, -N.scroll); fixW(w, 1440);
    page1(w, {}); w.paddingBottom = 0; gap(w, G.lang); add(w, inst('lang', 'Language Switch')); sticky(s); },
  '07': s => page1(s, { alt: true, tab2: true }),
};
SCENES['05'] = SCENES['04']; SCENES['06'] = SCENES['04'];
SCENES[RU ? '23' : '24'] = s => page1(s, { fav: true, alt: CFG.favAlt, sum: N.favSum, price: true });
const langEnd = (s, g) => { gap(s, g); add(s, inst('lang', 'Language Switch')); };
const scrolled = (s, o, S) => { const w = col('Page · scrolled', 0); absAt(s, w, 0, -S); fixW(w, 1440);
  page1(w, o); gap(w, G.lang); add(w, inst('lang', 'Language Switch')); sticky(s, o); };
const F1 = { fav: true, favPage: true, sum: N.favSum, cards: [{ k: 'cardPhoto', rep: [[N.date[0], N.date[1]], [N.cardSum, money(N.favSum)]] }] };
const F3 = { fav: true, favPage: true, link: 3, sum: N.sum3, head: [N.fav3, N.fav3sub], chips: [[1, N.chip2[0]], [0, N.chip2[1]]],
  cards: [{ k: 'cardExc' }, { k: 'cardNoPhoto', rep: [[N.cardSum, N.card2]] }] };
const P27 = { fav: true, link: CFG.p27link }, P32 = { fav: true, link: 2, pb: 'progressOver' };
const MAP = RU ? { fav: '24', favPop: '25', rename: '26', home: '27', homePop: '28', homeSticky: '29', favNoPhoto: '31', over: '32', overPop: '33',
    overSticky: '34', fav3: '35', confirm: '36', empty: '37' }
  : { fav: '25', favPop: '26', rename: '27', home: '28', homePop: '29', homeSticky: '30', favNoPhoto: '32', over: '33', overPop: '34',
    overSticky: '35', fav3: '38', confirm: '39', empty: '40', excl: '36', exclPop: '37' };
const P36 = { fav: true, link: 2, pb: 'progressExcl' };
const maskOff = s => { const m = absAt(s, inst('mask', 'Modal / Mask'), 0, 0); m.setProperties({ [Object.keys(m.componentProperties).find(k => k.startsWith('showModal'))]: false }); };
const SC2 = {
  fav: s => { page1(s, F1); langEnd(s, G.favLang); },
  favPop: s => { page1(s, F1); langEnd(s, G.favLang); absAt(s, inst('popCard', 'Popover / Info'), CFG.popCardX ?? 195, CFG.popCardY ?? 440); },
  rename: s => { page1(s, F1); langEnd(s, G.favLang); maskOff(s); absAt(s, inst('rename', 'Modal / Name Input'), CFG.modalX ?? 530, CFG.renameY ?? 308); },
  home: s => page1(s, P27),
  homePop: s => { page1(s, P27); absAt(s, inst('popPartial', 'Popover / Info'), 184, CFG.popHomeY ?? 163); },
  homeSticky: s => scrolled(s, P27, CFG.s29 ?? 113),
  favNoPhoto: s => { page1(s, Object.assign({}, F1, { sum: null, link: CFG.npLink, head: CFG.npHead, chips: CFG.npChips, cards: [{ k: 'cardNoPhoto' }] })); langEnd(s, G.favLang); },
  over: s => page1(s, P32),
  overPop: s => { page1(s, P32); absAt(s, inst('popOver', 'Popover / Info'), 184, CFG.popOverY ?? 193); },
  overSticky: s => scrolled(s, P32, CFG.s34 ?? 143),
  fav3: s => { page1(s, F3); langEnd(s, G.favLang); },
  confirm: s => { page1(s, F3); langEnd(s, G.favLang); maskOff(s); absAt(s, inst('confirm', 'Modal / Confirm'), CFG.modalX ?? 530, CFG.confirmY ?? 356); },
  empty: s => { page1(s, { favPage: true, empty: true, pb: 'progress', head: [N.favT, null], headPt: G.emptyHead }); langEnd(s, G.emptyLang); },
  excl: s => page1(s, P36),
  exclPop: s => { page1(s, P36); absAt(s, inst('popExcl', 'Popover / Info'), 184, CFG.popExclY ?? 190); },
};
for (const [k, key] of Object.entries(MAP)) SCENES[key] = SC2[k];
SCENES['08'] = s => page1(s, { plan: true }); // План квартиры: шапка · шкала · «← К стилям» · Card / Floor Plan

const out = { page: page.id, screens: {} };
for (const key of CFG.only) {
  const hi = HOME.indexOf(key); const xr = hi >= 0 ? 0 : 3300, y = (hi >= 0 ? hi : FAV.indexOf(key)) * 1100;
  const o = await figma.getNodeByIdAsync(REF[key]);
  for (const n of [...page.children]) if (n.name === o.name || n.name === 'эталон · ' + o.name || n.name.startsWith('caption · ' + key + ' ')) n.remove();
  const d = o.clone(); page.appendChild(d); d.x = xr; d.y = y; d.name = 'эталон · ' + o.name; d.locked = true;
  caption(RU ? 'эталон — снимок сайта 26.10' : 'reference — site snapshot 26.10', xr, y, 'caption · ' + key + ' ref');
  const s = screen(o.name, xr + 1540, y);
  caption(RU ? 'сборка из компонентов' : 'built from components', xr + 1540, y, 'caption · ' + key + ' build');
  let info; try { info = SCENES[key](s); } catch (e) { info = 'ERR ' + e.message; }
  const tops = s.findAllWithCriteria({ types: ['INSTANCE'] }).filter(n => n.parent.type !== 'INSTANCE')
    .map(n => n.name.replace(/^.* \/ /, '').slice(0, 12) + ' y' + Math.round(n.absoluteTransform[1][2] - y) + ' h' + Math.round(n.height));
  out.screens[key] = { ref: d.id, build: s.id, err: typeof info === 'string' ? info : undefined, tops: CFG.tops ? tops.join(' | ') : undefined };
}
return out;
