// design-02 П6г (T-20261104-05): группа «Окно варианта, шторка, фото, замена товара, карточка товара, конструктор» — книга Mobile.
// CFG = { lang: 'ru'|'en', only: ['09', …], y: {…позиции наложений}, s: {…прокрутки} } — какие экраны строить.
// RU → «Screens RU (components)» (280:2), EN → «Screens EN (components)» (293:2). Третий ряд под П6в: эталон x = i·900, y = Y0;
// сборка x = i·900+415. Повтор: узлы экрана (эталон, сборка, подписи) с теми же именами в ряду y ≥ Y0−40 удаляются и строятся
// заново. Откат: удалить рамки ряда y = Y0 (id в ответе).
// Основа экрана — один экземпляр целого окна (Modal / Layout View, Drawer / Sheet, Drawer / Replace, Image / Fullscreen) в корневой
// рамке на авто-раскладке; что в окне не задать переопределением (x/y вложенных абсолютных слоёв не переопределяются) — вложенный
// слой скрыт, поверх — отдельный экземпляр (шторка «наполовину», ракурс, план комнаты, подсказка, пузырь, окно, карточка).
// «Прокрутка» списка — у клип-колонки окна: выравнивание CENTER + поле сверху/снизу (смещение = (h + pt − pb − H) / 2).
const CFG = __CFG__;
const L = CFG.lang, RU = L === 'ru';
const Y0 = 2200;
const ORDER = RU ? ['09', '10', '11', '12', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '27', '35']
  : ['09', '10', '11', '12', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28', '36'];
const REF = RU
  ? { '09': '22:11', '10': '22:12', '11': '22:13', '12': '22:14', '14': '22:15', '15': '22:16', '16': '22:17', '17': '22:18', '18': '22:19',
      '19': '22:20', '20': '22:21', '21': '22:22', '22': '22:23', '23': '22:24', '24': '22:25', '25': '22:26', '26': '22:27', '27': '22:28', '35': '22:36' }
  : { '09': '22:53', '10': '22:54', '11': '22:55', '12': '22:56', '14': '22:57', '15': '22:58', '16': '22:59', '17': '22:60', '18': '22:61',
      '19': '22:62', '20': '22:63', '21': '22:64', '22': '22:65', '23': '22:66', '24': '22:67', '25': '22:68', '26': '22:69', '27': '22:70',
      '28': '22:71', '36': '22:79' };
const C = RU ? {
  win3d: '95:386', winPhoto: '95:570', tip: '95:978', camera: '95:1050', segPlan: '95:1004', floorPlan: '95:1165', undo: '95:1067',
  sheetHalf: '77:308', sheetFull: '77:462', rowSel: '76:141', groupHeader: '76:88', floorPicker: '76:34',
  popLV: '58:446', progPrice: '58:276', fullscreen: '87:17', replace: '105:202', detail: '83:26',
  mask: '85:100', nameCreate: '85:13', notif: '89:10', close: '107:103', replaceHeader: '105:463',
} : {
  win3d: '95:773', winPhoto: '95:970', tip: '95:983', camera: '95:1057', segPlan: '95:1031', floorPlan: '95:1220', undo: '95:1074',
  sheetHalf: '77:796', sheetFull: '77:963', rowSel: '76:185', groupHeader: '76:94', floorPicker: '76:55',
  popLV: '58:485', progPrice: '58:327', fullscreen: '87:34', replace: '105:404', detail: '83:52',
  mask: '85:114', nameCreate: '85:43', notif: '89:20', close: '107:111', replaceHeader: '105:469',
};
const W = RU ? { realistic: 'Сделать реалистичнее', editPlan: 'Изменить план', oldPrice: '25 990', newPrice: '30 702' }
  : { realistic: 'Make it realistic', editPlan: 'Edit the plan', oldPrice: '£231', newPrice: '£273' };
Object.assign(W, CFG.w || {});
// Позиции наложений и прокрутки (сверены по эталонам 04.11 сдвигом полос; уточнения — CFG.y / CFG.s).
// EN: шкала бюджета в две строки (94 px) → шторка, ракурс, подсказка, пузырь выше; список «Отделка» ниже.
const Y = Object.assign(RU
  ? { tip: 588, tipX: 15, camHalf: 502, camX: 43, half: 555, pop: 482, planX: 8, planY: 60, fpX: 14, fpY: 156,
      detail: 224, undoX: 10, undoY: 56, name: 307, nameX: 16, notif: 0, notifX: 15 }
  : { tip: 539, tipX: 15, camHalf: 458, camX: 43, half: 505, pop: 336, planX: 8, planY: 60, fpX: 14, fpY: 206,
      detail: 224, undoX: 10, undoY: 56, name: 307, nameX: 16, notif: 0, notifX: 15 }, CFG.y || {});
// RU 23 = 522 (первая карточка — Маре-Мини, как в эталоне), EN 23 = 520. EN 14/15 без прокрутки — см. sheetFull.
const S = Object.assign(RU ? { s14: 300, s15: 139, s23: 522 } : { s14: 300, s15: 139, s23: 520 }, CFG.s || {});

for (const style of ['Regular', 'Medium', 'Bold', 'Semi Bold']) await figma.loadFontAsync({ family: 'Inter', style });
const page = await figma.getNodeByIdAsync(RU ? '280:2' : '293:2');
await figma.setCurrentPageAsync(page);
const vars = {};
for (const [k, id] of Object.entries({ bgPage: 'VariableID:4:3', textSecondary: 'VariableID:4:6' }))
  vars[k] = await figma.variables.getVariableByIdAsync(id);
const comp = {};
for (const [k, id] of Object.entries(C)) comp[k] = await figma.getNodeByIdAsync(id);
const captionStyle = (await figma.getLocalTextStylesAsync()).find(s => s.name === 'Текст/14 Regular');
// Шрифты текстов внутри основ (переопределение текста требует загруженного шрифта).
const fonts = new Set();
for (const k of ['win3d', 'winPhoto', 'sheetFull', 'replace']) { const tmp = comp[k].createInstance(); // у EN-компонентов тексты видны только в экземпляре
  for (const t of tmp.findAllWithCriteria({ types: ['TEXT'] })) for (const s of t.getStyledTextSegments(['fontName'])) fonts.add(JSON.stringify(s.fontName));
  tmp.remove(); }
for (const f of fonts) await figma.loadFontAsync(JSON.parse(f));

const paintVar = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }, 'color', v)];
const inst = (k, name) => { const i = comp[k].createInstance(); if (name) i.name = name; return i; };
const byName = (root, nm) => root.findOne(n => n.name === nm);
const hide = (root, nm) => { const n = byName(root, nm); if (n) n.visible = false; return n; };
const textEq = (root, s) => root.findOne(n => n.type === 'TEXT' && n.characters === s);
const rep = (t, from, to) => { const k = t.characters.indexOf(from); if (k < 0) return false; t.insertCharacters(k, to, 'AFTER'); t.deleteCharacters(k + to.length, k + to.length + from.length); return true; };
const repIn = (i, from, to) => { let c = 0; for (const t of i.findAllWithCriteria({ types: ['TEXT'] })) if (rep(t, from, to)) c++; return c; };
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
const base = (s, k, name) => { const i = inst(k, name); s.appendChild(i); return i; };
const abs = (s, k, name, x, y) => { const i = inst(k, name); s.appendChild(i); i.layoutPositioning = 'ABSOLUTE'; i.x = x; i.y = y; return i; };
// Прокрутка клип-колонки c на S px: CENTER + поле (смещение содержимого = (h + pt − pb − H) / 2 = −S).
const scroll = (c, Spx) => {
  if (c.layoutSizingVertical === 'HUG') c.layoutSizingVertical = 'FILL'; // Drawer / Replace: колонка по содержимому → до низа окна
  const kids = c.children.filter(n => n.visible && n.layoutPositioning !== 'ABSOLUTE');
  const H = kids.reduce((a, n) => a + n.height, 0) + c.itemSpacing * Math.max(0, kids.length - 1);
  const d = H - c.height - 2 * Spx;
  if (Math.abs(d) >= c.height) throw new Error('scroll: поле ' + d + ' ≥ высоты ' + c.height + ' (S=' + Spx + ', H=' + H + ')');
  c.primaryAxisAlignItems = 'CENTER'; c.paddingTop = d > 0 ? d : 0; c.paddingBottom = d < 0 ? -d : 0;
  return { H: Math.round(H), h: Math.round(c.height), pt: c.paddingTop, pb: c.paddingBottom, first: Math.round(c.children[0].y) };
};
const clipCol = root => root.findOne(n => n.type === 'FRAME' && n.clipsContent && n.layoutMode === 'VERTICAL' && n.height > 400 && n !== root);
// EN-шторка 77:963: клип-колонка списка БЕЗ авто-раскладки (и сама шторка без неё) — прокрутку не задать ни полем, ни растяжением.
const clipAny = root => clipCol(root) || root.findOne(n => n.type === 'FRAME' && n.clipsContent && n.height > 400 && n !== root);
const mask = s => {
  const m = abs(s, 'mask', 'Modal / Mask', 0, 0);
  const prop = Object.keys(m.componentProperties).find(k => k.startsWith('showModal')); m.setProperties({ [prop]: false }); return m;
};
const win = (s, k) => base(s, k, 'Modal / Layout View');
const afterReplace = s => {
  const w = win(s, 'win3d');
  const n = repIn(w, W.oldPrice, W.newPrice);
  abs(s, 'undo', 'Space / Undo Redo', Y.undoX, Y.undoY);
  return { w, n };
};
const half = s => {
  const w = win(s, 'win3d'); hide(w, 'Шторка'); hide(w, 'Ракурс камеры');
  abs(s, 'camera', 'Segmented / Camera', Y.camX, Y.camHalf);
  abs(s, 'sheetHalf', 'Drawer / Sheet', 0, Y.half);
};
const planView = s => {
  const w = win(s, 'win3d');
  const seg = byName(w, 'Фото · 3D · План'); seg.swapComponent(comp.segPlan);
  hide(w, 'Ракурс камеры'); hide(w, '3D-кадр');
  const tag = byName(w, 'Ценник'); if (tag) tag.parent.visible = false;
  const t = textEq(w, W.realistic); if (t) t.characters = W.editPlan;
  abs(s, 'floorPlan', 'Floor Plan / Room', Y.planX, Y.planY);
};
// Полная шторка поверх окна: окно 3D (его шторка скрыта) · шторка full · «Закрыть» окна поверх (как на сайте — над шторкой).
const fullBase = s => {
  const w = win(s, 'win3d'); hide(w, 'Шторка');
  const d = abs(s, 'sheetFull', 'Drawer / Sheet', 0, 0); abs(s, 'close', 'Button / Close', 325, 10); return d;
};
const sheetFull = (s, Spx, sel) => {
  const d = fullBase(s);
  const cc = clipCol(d); const r = Spx != null && cc ? scroll(cc, Spx) : (cc ? null : 'без прокрутки (EN 77:963)');
  if (sel) { const rows = d.findAll(n => n.type === 'INSTANCE' && n.name === 'Ряд'); if (rows[sel]) rows[sel].swapComponent(comp.rowSel); }
  return { d, r };
};
const finish = s => {
  const d = fullBase(s); clipAny(d).visible = false;
  const col = figma.createAutoLayout('VERTICAL', { name: 'Finish' }); col.fills = []; s.appendChild(col);
  col.layoutPositioning = 'ABSOLUTE'; col.x = Y.fpX; col.y = Y.fpY; col.itemSpacing = 0;
  col.appendChild(inst('groupHeader', 'List / Group Header')); col.appendChild(inst('floorPicker', 'Drawer / Floor Picker'));
};
const replace = s => base(s, 'replace', 'Drawer / Replace');
// Лист замены прокручен: рамка-окно (клип) · лист замены выше на S и длиннее на S (колонка списка — FILL) · заголовок листа поверх.
const replaceScrolled = (s, Spx) => {
  const vp = figma.createFrame(); vp.name = 'Scroll'; vp.fills = []; vp.clipsContent = true; s.appendChild(vp); vp.resize(375, 812);
  const r = inst('replace', 'Drawer / Replace'); vp.appendChild(r); r.resize(375, 812 + Spx);
  const c = clipCol(r); c.layoutSizingVertical = 'FILL'; r.x = 0; r.y = -Spx;
  abs(s, 'replaceHeader', 'Drawer / Replace Header', 0, 0);
  return { c: Math.round(c.height), r: Math.round(r.height) };
};

const SCENES = {
  '09': s => { win(s, 'winPhoto'); abs(s, 'tip', 'Tooltip / Onboarding', Y.tipX, Y.tip); },
  '10': s => win(s, 'win3d'), '11': s => win(s, 'win3d'), '12': half,
  '14': s => sheetFull(s, S.s14).r, '15': s => sheetFull(s, S.s15, 1).r,
  '16': s => { half(s); abs(s, 'popLV', 'Popover / Info', 12, Y.pop); }, // эталон: полуоткрытая шторка, (i) поверх ракурса
  '17': planView, '18': s => win(s, 'winPhoto'), '19': s => base(s, 'fullscreen', 'Image / Fullscreen'),
  '20': finish,
  '21': s => { fullBase(s); mask(s); abs(s, 'detail', 'Card / Product Detail', 0, Y.detail); },
  '22': s => replace(s), '23': s => replaceScrolled(s, S.s23),
  '24': s => afterReplace(s).n, '25': s => afterReplace(s).n, '26': s => afterReplace(s).n,
  '27': s => { afterReplace(s); mask(s); abs(s, 'nameCreate', 'Modal / Name Input', Y.nameX, Y.name); },
  // EN 28: на снимке сайта сообщения нет — окно после замены с «сердцем» = выбрано (вариант state=checked).
  '28': s => { const { w } = afterReplace(s); const h = w.findAll(n => n.type === 'INSTANCE' && n.name.startsWith('Кнопка поверх'))[1];
    const k = Object.keys(h.componentProperties).find(x => x.startsWith('state')); h.setProperties({ [k]: 'checked' }); },
  '35': s => { const w = win(s, 'winPhoto'); const p = byName(w, 'Шкала бюджета'); p.swapComponent(comp.progPrice); },
  '36': s => { const w = win(s, 'winPhoto'); const p = byName(w, 'Шкала бюджета'); p.swapComponent(comp.progPrice); },
};

const out = { page: page.id, screens: {} };
for (const key of CFG.only) {
  const i = ORDER.indexOf(key); const xr = i * 900, xb = xr + 415;
  const o = await figma.getNodeByIdAsync(REF[key]);
  for (const n of [...page.children]) if (n.y >= Y0 - 40 && (n.name === o.name || n.name === 'эталон · ' + o.name || n.name.startsWith('caption · d' + key + ' '))) n.remove();
  const d = o.clone(); page.appendChild(d); d.x = xr; d.y = Y0; d.name = 'эталон · ' + o.name; d.locked = true;
  caption(RU ? 'эталон — снимок сайта 26.10' : 'reference — site snapshot 26.10', xr, 'caption · d' + key + ' ref');
  const s = screen(o.name, xb);
  caption(RU ? 'сборка из компонентов' : 'built from components', xb, 'caption · d' + key + ' build');
  let info; try { info = SCENES[key](s); } catch (e) { info = 'ERR ' + e.message; }
  const tops = s.children.map(n => n.name.replace(/^.* \/ /, '').slice(0, 10) + (n.layoutPositioning === 'ABSOLUTE' ? ' @' + Math.round(n.x) + ',' + Math.round(n.y) : '') + ' ' + Math.round(n.width) + 'x' + Math.round(n.height));
  out.screens[key] = { ref: d.id, build: s.id, tops: tops.join(' | '), info: info && typeof info === 'object' && !info.type ? info : (typeof info === 'number' ? info : undefined) };
}
return out;
