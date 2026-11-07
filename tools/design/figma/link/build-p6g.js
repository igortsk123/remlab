// design-02 П6е (T-20261107-61): книга Desktop — окна варианта и боковая панель (RU 09–22, 30; EN 09–23, 31) из экземпляров.
// Ядро главной (page1/rooms/budget/partial) — сокращённая копия build-p6f.js (только ветка «первый экран» и «есть избранное»).
// CFG = { lang: 'ru'|'en', only: ['09', …], wy: {…позиции/прокрутки}, pbSum: число | {furn, upg} }.
// Страницы 121:2 / 135:2; новый ряд ниже прежних: пары «эталон | сборка» по две в строке — x 0|1540 и 3300|4840,
// y = WY0 + ⌊i/2⌋·1100 (RU 16500, EN 18700). Повтор: узлы экрана с теми же именами удаляются и строятся заново. Откат: удалить их.
// Сцена: фон — главная (как 01; у 30/31 — «есть избранное») под Modal / Mask без окошка, поверх — экземпляр Modal / Layout View
// 1320×828 в (60, 36). Что в окне не задать переопределением — вложенный слой скрыт, поверх — отдельный экземпляр.
// Прокрутка списка боковой панели — у её клип-колонки: CENTER + поле (как Mobile П6г).
const CFG = __CFG__;
const RU = CFG.lang === 'ru';
const G = { ctl: 4, pb: 6, hint: 12, tabs: 7, rooms: 13, fav: 12, favHint: 6 };
const C = RU ? {
  bar: '55:8', complex: '55:44', actions: '55:119', favBtn: '55:98', progress: '29:12', progressPartial: '29:37', hint: '52:4', tabs: '35:13',
  room: '25:21', soon: '25:124', plan: '25:111', favLink: '52:18', mask: '37:100', winMask: '151:2',
  win3d: '48:187', winPhoto: '48:368', tagSel: '48:1193', tag: '48:1189', seg3d: '48:1092', segPlan: '48:1101', camera: '48:1147',
  planRoom: '48:1270', rowSel: '26:119', groupHeader: '26:66', floorPicker: '26:21', popLV: '29:436', pbLVprice: '29:270', fullscreen: '37:134',
  replace: '47:190', replaceHeader: '47:389', detail: '37:197', notif: '36:4', notifAct: '36:10', undo: '48:1164', nameCreate: '37:13',
  edTop: '32:6', edBottom: '32:32',
} : {
  bar: '55:24', complex: '55:62', actions: '55:126', favBtn: '55:109', progress: '29:114', progressPartial: '29:150', hint: '52:8', tabs: '35:39',
  room: '25:63', soon: '25:129', plan: '25:116', favLink: '52:25', mask: '37:114', winMask: '151:4',
  win3d: '48:568', winPhoto: '48:762', tagSel: '48:1201', tag: '48:1197', seg3d: '48:1119', segPlan: '48:1128', camera: '48:1154',
  planRoom: '48:1325', rowSel: '26:163', groupHeader: '26:72', floorPicker: '26:42', popLV: '29:475', pbLVprice: '29:321', fullscreen: '37:151',
  replace: '47:380', replaceHeader: '47:395', detail: '37:223', notif: '36:14', notifAct: '36:20', undo: '48:1171', nameCreate: '37:43',
  edTop: '32:12', edBottom: '32:38',
};
const ROOMS = RU
  ? [['Кухня', '13,2'], ['Спальня 1', '17,5'], ['Спальня 2', '9,7'], ['Санузел 1', '4,4'], ['Санузел 2', '3,9'], ['Прихожая', '9,3']]
  : [['Kitchen', '13.2'], ['Bedroom 1', '17.5'], ['Bedroom 2', '9.7'], ['Bathroom 1', '4.4'], ['Bathroom 2', '3.9'], ['Hallway', '9.3']];
const CERT = RU ? 600000 : 4500;
const WT = Object.assign(RU ? { oldName: 'Викс', newName: 'Нумо-Мини 140', oldPrice: '25 990', newPrice: '30 702', realistic: 'Сделать реалистичнее', editPlan: 'Изменить план' }
  : { oldName: 'Викс', newName: 'Нумо-Мини 140', oldPrice: '£231', newPrice: '£273', realistic: 'Make it realistic', editPlan: 'Edit the plan' }, CFG.wt || {});
const P = Object.assign({ S: 113, Sphoto: 113, pop: [990, 96], detail: [460, 106], replaceX: 980, S18: 522, undo: [70, 810],
  notif: null, name: [530, 350], fin: [986, 182], plan: [72, 96] }, RU ? {} : { Sphoto: 101, fin: [986, 232], fav23: 1264 }, CFG.wy || {});
const WIN = RU ? ['09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '30']
  : ['09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '31'];
const WY0 = RU ? 16500 : 18700, WX = 60, WY = 36;

for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const page = await figma.getNodeByIdAsync(RU ? '121:2' : '135:2');
await figma.setCurrentPageAsync(page);
const V = {};
for (const [k, id] of Object.entries({ bgPage: '5:3', textSecondary: '5:6' })) V[k] = await figma.variables.getVariableByIdAsync('VariableID:' + id);
const SP = {};
for (let k = 38; k <= 55; k++) { const v = await figma.variables.getVariableByIdAsync('VariableID:5:' + k); if (v && v.resolvedType === 'FLOAT') SP[Object.values(v.valuesByMode)[0]] = v; }
const comp = {};
for (const [k, id] of Object.entries(C)) comp[k] = await figma.getNodeByIdAsync(id);
const captionStyle = (await figma.getLocalTextStylesAsync()).find(s => s.name === 'Текст/14 Regular');
const fonts = new Set();
for (const k of ['soon', 'room', 'progressPartial', 'win3d', 'winPhoto', 'pbLVprice', 'notif', 'notifAct']) { const t0 = comp[k].createInstance();
  for (const t of t0.findAllWithCriteria({ types: ['TEXT'] })) for (const s of t.getStyledTextSegments(['fontName'])) fonts.add(JSON.stringify(s.fontName));
  t0.remove(); }
for (const f of fonts) await figma.loadFontAsync(JSON.parse(f));

const paintVar = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }, 'color', v)];
const gap = (f, n) => { f.itemSpacing = n; if (SP[n]) f.setBoundVariable('itemSpacing', SP[n]); };
const col = (name, g, dir) => { const f = figma.createAutoLayout(dir || 'VERTICAL', { name }); f.fills = []; if (!dir) f.counterAxisAlignItems = 'CENTER'; gap(f, g); return f; };
const add = (p, n, fill) => { p.appendChild(n); if (fill) n.layoutSizingHorizontal = 'FILL'; return n; };
const inst = (k, name) => { const i = comp[k].createInstance(); if (name) i.name = name; return i; };
const rep = (t, from, to) => { let k = t.characters.indexOf(from);
  if (k < 0) { const re = new RegExp(from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, '[\\s\\u00a0\\u202f]')); const m = t.characters.match(re);
    if (!m) return false; k = m.index; const sep = (m[0].match(/[\u00a0\u202f]/) || [' '])[0]; from = m[0]; to = to.replace(/ /g, sep); }
  t.insertCharacters(k, to, 'AFTER'); t.deleteCharacters(k + to.length, k + to.length + from.length); return true; };
const repIn = (i, from, to) => { for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) return t.id; return null; };
const repAll = (i, from, to) => { let c = 0; for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) c++; return c; };
const caption = (text, x, y, nm) => { const t = figma.createText(); t.textStyleId = captionStyle.id; t.characters = text; t.name = nm;
  t.fills = paintVar(V.textSecondary); t.x = x; t.y = y - 32; page.appendChild(t); return t; };
const screen = (name, x, y) => { const f = figma.createAutoLayout('VERTICAL', { name });
  f.resize(1440, 900); f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
  f.counterAxisAlignItems = 'CENTER'; f.clipsContent = true; f.fills = paintVar(V.bgPage); f.x = x; f.y = y; page.appendChild(f); return f; };
const fixW = (f, w) => { f.resize(w, f.height);
  if (f.layoutMode === 'HORIZONTAL') { f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'AUTO'; }
  else { f.counterAxisSizingMode = 'FIXED'; f.primaryAxisSizingMode = 'AUTO'; } return f; };
const absAt = (s, n, x, y) => { s.appendChild(n); n.layoutPositioning = 'ABSOLUTE'; n.x = x; n.y = y; return n; };
const setFill = (f, share) => { const w = f.parent.width; f.parent.paddingRight = w - Math.max(1, Math.round(w * share)); f.layoutSizingHorizontal = 'FILL'; };
const fmt = v => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, RU ? ' ' : ',');
const num = (t, v) => { const m = t && t.characters.match(/\d[\d\s\u00a0\u202f,.]*\d|\d/);
  if (m) { const sep = (m[0].match(/[\s\u00a0\u202f]/) || [' '])[0]; rep(t, m[0], fmt(v).replace(/ /g, sep)); } };
const partial = (p, v) => { // RU — сумма; EN — { furn, upg } (две полосы: из 4,500 и 8,000)
  const t = p.findOne(n => n.type === 'TEXT' && n.name === 'Выбрано');
  if (RU) { num(t, v); const f = p.findOne(n => n.type === 'FRAME' && n.name === 'Выбрано (заливка)'); if (f) setFill(f, v / CERT); return; }
  const o = typeof v === 'number' ? { furn: v, upg: 0 } : v; num(t, o.furn + o.upg);
  const leg = p.findAll(n => n.type === 'TEXT' && n.name === 'Выбрано / доступно'); [o.furn, o.upg].forEach((x, k) => { if (leg[k]) num(leg[k], x); });
  const fills = p.findAll(n => n.type === 'FRAME' && n.name === 'Выбрано (заливка)');
  [[o.furn, 4500], [o.upg, 8000]].forEach(([x, cap], k) => { const f = fills[k]; if (!f) return; if (x <= 0) f.visible = false; else setFill(f, Math.min(1, x / cap)); });
};
// Главная — фон под окном (первый экран; o.fav — «есть избранное», как RU 23 / EN 24)
const page1 = (parent, o) => {
  const pg = add(parent, col('Page', 0), false); fixW(pg, 1100);
  const grp = (name, g) => { const f = add(pg, col(name, g), false); fixW(f, 1100); return f; };
  const top = grp('Top', G.ctl), mid = grp('Budget', 0), intro = grp('Intro', G.tabs);
  const bar = add(top, inst('bar', 'Header / Apartment Bar'));
  if (o.fav) bar.findOne(n => n.type === 'INSTANCE' && n.name === 'Кнопка избранного').swapComponent(comp.favBtn);
  const ctl = add(top, col('Controls', 0, 'HORIZONTAL'), false); fixW(ctl, 1072); ctl.counterAxisAlignItems = 'CENTER';
  add(ctl, inst('complex', 'Header / Complex Row'), true); add(ctl, inst('actions', 'Header / Actions'));
  add(mid, inst(o.fav ? 'progressPartial' : 'progress', 'Progress Bar'));
  if (o.fav) { gap(mid, G.fav); add(mid, inst('favLink', 'Link / Favorites')); }
  add(intro, inst('hint', 'Home / Hint')); add(intro, inst('tabs', 'Tabs'));
  const row = add(pg, col('Rooms', 12, 'HORIZONTAL'), false); row.counterAxisAlignItems = 'MIN';
  add(row, inst('room', 'Card / Room'));
  const list = add(row, col('Rooms · next', 12), false);
  ROOMS.forEach(([n, a], k) => { const s = add(list, inst('soon', 'Card / Coming Soon · ' + n)); if (k) { repIn(s, ROOMS[0][0], n); repIn(s, ROOMS[0][1], a); } });
  add(list, inst('plan', 'Card / Plan Tile'));
  for (const [f, v] of [[mid, G.pb], [intro, o.fav ? G.favHint : G.hint], [row, G.rooms]]) { f.paddingTop = v; if (SP[v]) f.setBoundVariable('paddingTop', SP[v]); }
  return pg;
};
const maskOff = (s, k = 'mask') => { const m = absAt(s, inst(k, 'Modal / Mask'), 0, 0); m.setProperties({ [Object.keys(m.componentProperties).find(k => k.startsWith('showModal'))]: false }); return m; };
const mainOf = n => { try { return n.mainComponent && n.mainComponent.id; } catch (e) { return null; } };
const byMain = (root, id) => root.findAll(n => n.type === 'INSTANCE' && mainOf(n) === id);
const panelOf = w => w.findOne(n => n.name === 'Боковая панель (кадр)');
const listClip = w => panelOf(w).findOne(n => n.type === 'FRAME' && n.clipsContent && n.height > 400);
const scrollCol = (c, Spx) => { // содержимое клип-колонки вверх на Spx: CENTER + поле (смещение = (h + pt − pb − H) / 2)
  const kids = c.children.filter(n => n.visible && n.layoutPositioning !== 'ABSOLUTE');
  const H = kids.reduce((a, n) => a + n.height, 0) + c.itemSpacing * Math.max(0, kids.length - 1);
  const d = H - c.height - 2 * Spx;
  c.primaryAxisAlignItems = 'CENTER'; c.paddingTop = d > 0 ? d : 0; c.paddingBottom = d < 0 ? -d : 0;
  return 'H' + Math.round(H) + ' h' + Math.round(c.height) + ' pt' + c.paddingTop + ' pb' + c.paddingBottom;
};
const win = (s, k, o = {}) => { page1(s, o.bg || {}); maskOff(s, 'winMask'); return absAt(s, inst(k, 'Modal / Layout View'), WX, WY); };
const tags = w => [...byMain(w, C.tag), ...byMain(w, C.tagSel)];
const replaced = w => { const n = repAll(w, WT.oldPrice, WT.newPrice) + repAll(w, WT.oldName, WT.newName);
  const row = panelOf(w).findAll(r => r.type === 'INSTANCE' && r.name === 'Ряд' && r.findOne(t => t.type === 'TEXT' && t.characters.includes(WT.newName)))[0];
  if (row) { const k = Object.keys(row.componentProperties).find(x => x.startsWith('showSwatch4')); if (k) row.setProperties({ [k]: true }); }
  return n; };
const afterReplace = (s, o) => { const w = win(s, 'win3d', o); const n = replaced(w); absAt(s, inst('undo', 'Space / Undo Redo'), P.undo[0], P.undo[1]); return { w, n }; };
const SC = {
  '09': s => { win(s, 'win3d'); },
  '10': s => { const w = win(s, 'win3d'); // выбран журнальный стол: ценник «выбран» + строка «выбрано», список прокручен
    const t = tags(w).find(n => n.findOne(x => x.type === 'TEXT' && /11[\s\u00a0\u202f]?990|£107/.test(x.characters)));
    if (t) { const tx = t.findOne(x => x.type === 'TEXT').characters; t.swapComponent(comp.tagSel); t.findOne(x => x.type === 'TEXT').characters = tx; }
    const rows = panelOf(w).findAll(n => n.type === 'INSTANCE' && n.name === 'Ряд' && n.height > 90); if (rows[1]) rows[1].swapComponent(comp.rowSel);
    return scrollCol(listClip(w), P.S); },
  '11': s => { const w = win(s, 'win3d'); const r = scrollCol(listClip(w), P.S); absAt(s, inst('popLV', 'Popover / Info'), P.pop[0], P.pop[1]); return r; },
  '12': s => { const w = win(s, 'win3d'); const seg = byMain(w, C.seg3d)[0]; if (seg) seg.swapComponent(comp.segPlan);
    for (const n of [...byMain(w, C.camera), ...tags(w)]) n.visible = false;
    const img = w.findOne(n => n.name === '3D-кадр'); if (img) img.visible = false;
    const hint = w.findOne(n => n.type === 'TEXT' && /^3D/.test(n.characters)); if (hint) hint.parent.visible = false;
    for (const t of w.findAllWithCriteria({ types: ['TEXT'] })) if (t.characters === WT.realistic) t.characters = WT.editPlan;
    const r = scrollCol(listClip(w), P.S); absAt(s, inst('planRoom', 'Floor Plan / Room'), P.plan[0], P.plan[1]); return r; },
  '13': s => { const w = win(s, 'winPhoto'); return scrollCol(listClip(w), P.Sphoto); },
  '14': s => { absAt(s, inst('fullscreen', 'Image / Fullscreen'), 0, 0); },
  '15': s => { const w = win(s, 'win3d'); listClip(w).visible = false; // «Отделка и ремонт» раскрыта: «← Назад · Отделка» + выбор пола
    const f = col('Finish', 0); f.counterAxisAlignItems = 'MIN'; absAt(s, f, P.fin[0], P.fin[1]);
    f.appendChild(inst('groupHeader', 'List / Group Header')); f.appendChild(inst('floorPicker', 'Drawer / Floor Picker')); },
  '16': s => { win(s, 'win3d'); maskOff(s); absAt(s, inst('detail', 'Card / Product Detail'), P.detail[0], P.detail[1]); },
  '17': s => { win(s, 'win3d'); maskOff(s); absAt(s, inst('replace', 'Drawer / Replace'), P.replaceX, 0); },
  '18': s => { win(s, 'win3d'); maskOff(s); // лист замены прокручен: рамка-окно (клип) · лист выше на S18 и длиннее на S18 · заголовок поверх
    const vp = figma.createFrame(); vp.name = 'Scroll'; vp.fills = []; vp.clipsContent = true; absAt(s, vp, P.replaceX, 0); vp.resize(460, 900);
    const r = inst('replace', 'Drawer / Replace'); vp.appendChild(r); r.resize(460, 900 + P.S18);
    const c = r.findOne(n => n.type === 'FRAME' && n.clipsContent && n.height > 400); if (c) c.layoutSizingVertical = 'FILL'; r.x = 0; r.y = -P.S18;
    absAt(s, inst('replaceHeader', 'Drawer / Replace Header'), P.replaceX, 0); return c ? 'clip h' + Math.round(c.height) : 'no clip'; },
  '19': s => { afterReplace(s); if (P.notif) absAt(s, inst('notif', 'Notification'), P.notif[0], P.notif[1]); },
  '20': s => afterReplace(s).n,
  '21': s => { // окно поверх конструктора планировки
    absAt(s, inst('edTop', 'Editor / Top Bar'), 0, 0); absAt(s, inst('edBottom', 'Editor / Bottom Bar'), 0, 829); maskOff(s, 'winMask');
    const w = absAt(s, inst('win3d', 'Modal / Layout View'), WX, WY); replaced(w); absAt(s, inst('undo', 'Space / Undo Redo'), P.undo[0], P.undo[1]); },
  '22': s => { afterReplace(s); maskOff(s); absAt(s, inst('nameCreate', 'Modal / Name Input'), P.name[0], P.name[1]); },
  '23': s => { const { w } = afterReplace(s); if (P.notif23) absAt(s, inst('notifAct', 'Notification'), P.notif23[0], P.notif23[1]);
    if (P.fav23) { // сохранено в избранное: сердце окна «отмечено», шкала окна «с ценой» — мебель P.fav23 (EN 23); делалось двумя вызовами — swap и числа
      const h = w.findOne(n => n.type === 'INSTANCE' && n.componentProperties && n.componentProperties.icon && n.componentProperties.icon.value === 'favorite'); if (h) h.setProperties({ state: 'checked' });
      const pb = panelOf(w).findOne(n => n.type === 'INSTANCE' && n.name === 'Шкала в окне'); if (pb) { pb.swapComponent(comp.pbLVprice); partial(pb, { furn: P.fav23, upg: 0 }); } } },
  'pb': s => { const w = win(s, 'winPhoto', { bg: { fav: true } }); // «Плашка окна»: шкала окна «с ценой», сумма как на эталоне
    const pb = panelOf(w).findOne(n => n.type === 'INSTANCE' && n.name === 'Шкала в окне');
    if (pb) { pb.swapComponent(comp.pbLVprice); if (CFG.pbSum) partial(pb, CFG.pbSum); }
    return pb ? pb.findAllWithCriteria({ types: ['TEXT'] }).map(t => t.characters).join('/') : 'no pb'; },
};

const out = { page: page.id, screens: {} };
for (const key of CFG.only) {
  const wi = WIN.indexOf(key); const xr = (wi % 2) * 3300, y = WY0 + Math.floor(wi / 2) * 1100;
  const o = await figma.getNodeByIdAsync('16:' + ((RU ? 2 : 40) + Number(key)));
  for (const n of [...page.children]) if (n.name === o.name || n.name === 'эталон · ' + o.name || n.name.startsWith('caption · ' + key + ' ')) n.remove();
  const d = o.clone(); page.appendChild(d); d.x = xr; d.y = y; d.name = 'эталон · ' + o.name; d.locked = true;
  caption(RU ? 'эталон — снимок сайта 26.10' : 'reference — site snapshot 26.10', xr, y, 'caption · ' + key + ' ref');
  const s = screen(o.name, xr + 1540, y);
  caption(RU ? 'сборка из компонентов' : 'built from components', xr + 1540, y, 'caption · ' + key + ' build');
  let info; try { info = (SC[key] || SC.pb)(s); } catch (e) { info = 'ERR ' + e.message; }
  out.screens[key] = { ref: d.id, build: s.id, info: typeof info === 'string' || typeof info === 'number' ? info : undefined };
}
return out;
