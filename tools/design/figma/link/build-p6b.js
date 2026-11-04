// design-02 П6б (T-20261104-03): группа «Главная» из экземпляров — книга Mobile.
// CFG = { lang: 'ru'|'en', only: ['02', …] } — какие экраны строить. RU → страница «Screens RU (components)» (280:2),
// EN → «Screens EN (components)» (создаётся в конце списка). Пары «эталон | сборка» по слотам ORDER: эталон x = i·900, сборка x = i·900+415.
// Повторный запуск: узлы экрана (эталон, сборка, подписи) с теми же именами удаляются и строятся заново; 01/05 пилота RU не трогаются,
// только переставляются в свой слот. Откат: удалить созданные рамки (id в ответе) или страницу EN целиком.
// Сцены: 01 первый экран · 02 «ещё» раскрыто (Complex Row expanded + Descriptions / Apartment) · 03 пузырь (i) (Popover / Info поверх,
// абсолютно) · 04 липкая шапка + страница, прокрученная на S (рамка «Page · scrolled» абсолютно, y = −S) · 05/06 конец ленты (как П6а) ·
// 07 вкладка «Минимализм» (лента вкладок прокручена: окно «Tabs · scrolled» с экземпляром, сдвинутым на −S) + Card / Room interior=alt ·
// 28/29 есть избранное (Button / Favorites withCount в шапке, Progress Bar partial, Link / Favorites, цена в карточке).
const CFG = __CFG__;
const G = { root: 12, top: 8, head: -4, ctl: 6, main: 8, intro: 4, stCtl: 6, bottom: 2, lang: 49, desc: 1 };
const L = CFG.lang;
const RU = L === 'ru';
const ORDER = RU ? ['01', '02', '03', '04', '05', '06', '07', '28'] : ['01', '02', '03', '04', '05', '06', '07', '29'];
const REF_PAGE = RU ? '22:2' : '22:44';
const REF = RU
  ? { '01': '22:3', '02': '22:4', '03': '22:5', '04': '22:6', '05': '22:7', '06': '22:8', '07': '22:9', '28': '22:29' }
  : { '01': '22:45', '02': '22:46', '03': '22:47', '04': '22:48', '05': '22:49', '06': '22:50', '07': '22:51', '29': '22:72' };
const C = RU ? {
  bar: '126:8', barSticky: '126:16', complex: '126:42', complexExp: '126:49', desc: '126:71', actions: '126:111',
  progress: '58:12', progressSticky: '58:24', progressPartial: '58:37', hint: '105:411', tabs: '94:44', tabsSticky: '94:57',
  tabSel: '94:90', tabDef: '94:94', room: '64:21', roomAlt: '64:42', soon: '64:124', plan: '64:111', lang: '105:450',
  popover: '58:442', favLink: '105:425', favBtn: '126:90',
} : {
  bar: '126:24', barSticky: '126:32', complex: '126:56', complexExp: '126:63', desc: '126:76', actions: '126:118',
  progress: '58:116', progressSticky: '58:129', progressPartial: '58:154', hint: '105:415', tabs: '94:70', tabsSticky: '94:83',
  tabSel: '94:98', tabDef: '94:102', room: '64:63', roomAlt: '64:84', soon: '64:129', plan: '64:116', lang: '105:454',
  popover: '58:470', favLink: '105:432', favBtn: '126:101',
};
const ROOMS = RU
  ? [['Кухня', '13,2 м²'], ['Спальня 1', '17,5 м²'], ['Спальня 2', '9,7 м²'], ['Санузел 1', '4,4 м²'], ['Санузел 2', '3,9 м²'], ['Прихожая', '9,3 м²']]
  : [['Kitchen', '13.2 m²'], ['Bedroom 1', '17.5 m²'], ['Bedroom 2', '9.7 m²'], ['Bathroom 1', '4.4 m²'], ['Bathroom 2', '3.9 m²'], ['Hallway', '9.3 m²']];
// Сцен-зависимые числа (сверены по эталонам 04.11): прокрутка 04, верх пузыря 03, x второй вкладки в 07, данные «есть избранное».
const N = RU
  ? { scroll04: 296, pop03: 172, tab2x: 0, favSum: ['250 000 ₽', '141 979 ₽'], favPrice: ['137 267 ₽', '141 979 ₽'], favFill: 141979 / 600000 }
  : { scroll04: 363, pop03: 222, tab2x: 56, favSum: ['£4,200', '£1,264'], favPrice: ['£1,222', '£1,264'], favFill: 1264 / 4500 };
const NAME_ID = RU ? '22:29' : '22:72';

for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const PAGE_NAME = RU ? 'Screens RU (components)' : 'Screens EN (components)';
let page = figma.root.children.find(p => p.name === PAGE_NAME);
if (!page) { page = figma.createPage(); page.name = PAGE_NAME; }
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
// Заменить кусок текста, сохранив стиль первого символа куска (переопределение, не отвязка).
const rep = (t, from, to) => { const k = t.characters.indexOf(from); if (k < 0) return false; t.insertCharacters(k, to, 'AFTER'); t.deleteCharacters(k + to.length, k + to.length + from.length); return true; };
const repIn = (i, from, to) => { for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) return t.id; return null; };
const caption = (text, x, nm) => {
  const t = figma.createText(); t.textStyleId = captionStyle.id; t.characters = text; t.name = nm;
  t.fills = paintVar(vars.textSecondary); t.x = x; t.y = -32; page.appendChild(t); return t;
};
const screen = (name, x) => {
  const f = figma.createAutoLayout('VERTICAL', { name });
  f.resize(375, 812); f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
  f.counterAxisAlignItems = 'CENTER'; f.clipsContent = true; f.fills = paintVar(vars.bgPage);
  f.x = x; f.y = 0; page.appendChild(f); return f;
};
const content = (parent, o) => {
  const c = add(parent, col('Content', G.lang), false);
  const rooms = col('Rooms', 12); add(c, rooms, false);
  const room = add(rooms, inst(o.alt ? 'roomAlt' : 'room', 'Card / Room'));
  if (o.fav) repIn(room, N.favPrice[0], N.favPrice[1]);
  for (const [n, a] of ROOMS) {
    const s = add(rooms, inst('soon', 'Card / Coming Soon · ' + n));
    if (RU) s.setProperties({ 'title#287:0': n, 'area#287:3': a });
    else { s.findOne(x => x.name === 'title').characters = n; s.findOne(x => x.name === 'area').characters = a; } // EN-вариант без свойств (одно на набор — как П1)
  }
  add(rooms, inst('plan', 'Card / Plan Tile'));
  add(c, inst('lang', 'Language Switch'));
  return c;
};
// Progress Bar partial → сумма и заливка «есть избранное». Сумма: первое число в строке (разделитель тысяч — неразрывный пробел,
// берётся из исходного текста). Заливка: размер слоя внутри вложенного экземпляра полосы не переопределяется (resize молча
// игнорируется) — ширина задаётся правым полем части полосы + FILL у заливки (переопределения, не отвязка).
const repNum = (t, to) => {
  const m = t.characters.match(/\d[\d\s\u00a0\u202f,.]*\d/); if (!m) return false;
  const sep = (m[0].match(/[\s\u00a0\u202f]/) || [' '])[0]; to = to.replace(/ /g, sep);
  t.insertCharacters(m.index, to, 'AFTER'); t.deleteCharacters(m.index + to.length, m.index + to.length + m[0].length); return true;
};
const setFill = (f, share) => { const w = f.parent.width; f.parent.paddingRight = w - Math.max(1, Math.round(w * share)); f.layoutSizingHorizontal = 'FILL'; };
const partial = p => {
  repNum(p.findOne(n => n.id.endsWith(RU ? ';58:28' : ';58:133')), N.favSum[1].replace(/[^\d ,]/g, '').trim());
  if (RU) setFill(sub(p, '58:338'), N.favFill);
  else { // EN split: легенда варианта partial — «1,200 / 4,500» и «3,000 / 8,000» → 1,264 и 0 (эталон 22:72)
    setFill(sub(p, '58:357'), N.favFill); const u = sub(p, '58:359'); if (u) u.visible = false;
    repIn(p, '1,200', '1,264'); repIn(p, '3,000', '0');
  }
};
const flow = (parent, o) => {
  const topc = add(parent, col('Top', G.top), true);
  const head = add(topc, col('Header', G.head), true);
  const bar = add(head, inst('bar', 'Header / Apartment Bar'));
  if (o.fav) bar.findOne(n => n.type === 'INSTANCE' && n.name === 'Кнопка избранного').swapComponent(comp.favBtn);
  if (o.expanded) {
    const cx = add(head, col('Complex', G.desc), true);
    add(cx, inst('complexExp', 'Header / Complex Row'));
    add(cx, inst('desc', 'Descriptions / Apartment'));
  } else add(head, inst('complex', 'Header / Complex Row'));
  const ctl = add(topc, col('Controls', G.ctl), true);
  add(ctl, inst('actions', 'Header / Actions'));
  const pb = add(ctl, inst(o.fav ? 'progressPartial' : 'progress', 'Progress Bar'));
  if (o.fav) partial(pb);
  const main = add(parent, col('Main', G.main), true);
  if (o.fav) add(main, inst('favLink', 'Link / Favorites'));
  const intro = add(main, col('Intro', G.intro), true);
  add(intro, inst('hint', 'Home / Hint'));
  if (o.tabScroll) {
    const win = add(intro, figma.createAutoLayout('HORIZONTAL', { name: 'Tabs · scrolled' }), false);
    win.resize(375, 44); win.primaryAxisSizingMode = 'FIXED'; win.counterAxisSizingMode = 'FIXED'; win.clipsContent = true; win.fills = [];
    const t = inst('tabs', 'Tabs'); win.appendChild(t); t.layoutPositioning = 'ABSOLUTE';
    const tabs = t.children.filter(n => n.type === 'INSTANCE');
    // Свап варианта сбрасывает надпись (у default-варианта текст не на свойстве label) — запомнить и вернуть текстом; ширина — HUG.
    const txt = x => x.findOne(n => n.type === 'TEXT');
    const l0 = txt(tabs[0]).characters, l2 = txt(tabs[2]).characters;
    tabs[0].swapComponent(comp.tabDef); tabs[2].swapComponent(comp.tabSel);
    txt(tabs[0]).characters = l0; txt(tabs[2]).characters = l2;
    for (const x of [tabs[0], tabs[2]]) x.layoutSizingHorizontal = 'HUG';
    const S = t.paddingLeft + tabs[0].width + t.itemSpacing - N.tab2x;
    t.resize(375 + S, t.height); t.x = -S; t.y = 0;
    o.tabInfo = 'S=' + Math.round(S) + ' ' + tabs.map(x => x.findOne(n => n.type === 'TEXT').characters + ':' + Math.round(x.width)).join(',');
  } else add(intro, inst('tabs', 'Tabs'));
  content(main, o);
  return { topc, main };
};
const sticky = s => {
  const st = add(s, col('Sticky Header', 0), false); st.fills = paintVar(vars.bgPage);
  st.layoutPositioning = 'ABSOLUTE'; st.x = 0; st.y = 0; st.resize(375, 10);
  st.counterAxisSizingMode = 'FIXED'; st.primaryAxisSizingMode = 'AUTO';
  st.constraints = { horizontal: 'STRETCH', vertical: 'MIN' };
  add(st, inst('barSticky', 'Header / Apartment Bar'), true);
  const st2 = add(st, col('Sticky Controls', G.stCtl), true);
  add(st2, inst('progressSticky', 'Progress Bar'));
  add(st2, inst('tabsSticky', 'Tabs'));
  return st;
};
const SCENES = {
  '01': s => { gap(s, G.root); flow(s, {}); },
  '02': s => { gap(s, G.root); flow(s, { expanded: true }); },
  '03': s => {
    gap(s, G.root); flow(s, {});
    const p = add(s, inst('popover', 'Popover / Info'), false); p.layoutPositioning = 'ABSOLUTE'; p.x = 12; p.y = N.pop03;
  },
  '04': s => {
    const pg = add(s, col('Page · scrolled', G.root), false); pg.layoutPositioning = 'ABSOLUTE';
    pg.resize(375, 10); pg.counterAxisSizingMode = 'FIXED'; pg.primaryAxisSizingMode = 'AUTO'; pg.x = 0; pg.y = -N.scroll04;
    flow(pg, {}); sticky(s);
  },
  '05': s => { s.primaryAxisAlignItems = 'MAX'; s.paddingBottom = G.bottom; content(s, {}); sticky(s); },
  '07': s => { const o = { alt: true, tabScroll: true }; gap(s, G.root); flow(s, o); TABINFO = o.tabInfo; },
};
SCENES['06'] = SCENES['05'];
SCENES[RU ? '28' : '29'] = s => { gap(s, G.root); flow(s, { fav: true }); };

let TABINFO = null;
const out = { page: page.id, screens: {} };
const refPage = await figma.getNodeByIdAsync(REF_PAGE);
for (const key of CFG.only) {
  const i = ORDER.indexOf(key); const xr = i * 900, xb = xr + 415;
  const o = await figma.getNodeByIdAsync(REF[key]);
  for (const n of [...page.children]) if (n.name === o.name || n.name === 'эталон · ' + o.name || n.name.startsWith('caption · ' + key + ' ')) n.remove();
  const d = o.clone(); page.appendChild(d); d.x = xr; d.y = 0; d.name = 'эталон · ' + o.name; d.locked = true;
  caption('эталон — снимок сайта 26.10', xr, 'caption · ' + key + ' ref');
  const s = screen(o.name, xb);
  caption('сборка из компонентов', xb, 'caption · ' + key + ' build');
  SCENES[key](s);
  for (const f of s.findAllWithCriteria({ types: ['INSTANCE'] }))
    if (Math.round(f.width) === 375 && f.parent !== s && f.parent.type !== 'INSTANCE' && f.parent.layoutSizingHorizontal === 'FILL' && f.layoutPositioning !== 'ABSOLUTE') f.layoutSizingHorizontal = 'FILL';
  const tops = s.findAllWithCriteria({ types: ['INSTANCE'] }).filter(n => n.parent.type !== 'INSTANCE')
    .map(n => n.name.replace(/^.* \/ /, '').slice(0, 14) + ' y' + Math.round(n.absoluteTransform[1][2]) + ' h' + Math.round(n.height));
  out.screens[key] = { ref: d.id, build: s.id, tab: key === '07' ? TABINFO : undefined, tops: tops.join(' | ') };
}
// RU: пилот 01/05 — в свои слоты (0 и 4).
if (RU) {
  const mv = [['281:151', 0], ['281:152', 0], ['281:155', 415], ['281:156', 415], ['281:153', 3600], ['281:154', 3600], ['281:245', 4015], ['281:246', 4015]];
  for (const [id, x] of mv) { const n = await figma.getNodeByIdAsync(id); if (n) n.x = x; }
}
return out;
