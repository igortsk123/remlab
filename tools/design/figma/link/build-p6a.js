// design-02 П6а (T-20261104-02): пилот «экраны из экземпляров» — книга Mobile, страница «Screens RU (components)».
// Создаёт страницу (в конец), копии эталонов 22:3 / 22:7 (дубликаты рамок-картинок) и две сборки из экземпляров.
// Повторный запуск: страницу с тем же именем очищает (на ней только наше) и строит заново.
// Откат: удалить страницу «Screens RU (components)». Другие страницы не меняются.
// G — отступы (подобраны по сверке с эталоном 04.11): { root: 12, top: 8, head: -4, ctl: 6, main: 8, intro: 4, stCtl: 6, bottom: 2, lang: 49 }
// (первый прогон шёл с bottom 5 / lang 46, затем точечно поправлено в книге на 2 / 49).
const G = __G__;
const PAGE_NAME = 'Screens RU (components)';
const V = {
  bgPage: 'VariableID:4:3', textSecondary: 'VariableID:4:6',
  sp: { 6: 'VariableID:4:43', 12: 'VariableID:4:49' },
};
const C = { // варианты (id) — RU
  bar: '126:8', barSticky: '126:16', complex: '126:42', actions: '126:111',
  progress: '58:12', progressSticky: '58:24', hint: '105:411',
  tabs: '94:44', tabsSticky: '94:57', room: '64:21', soon: '64:124', plan: '64:111', lang: '105:450',
};
const ROOMS = [['Кухня', '13,2'], ['Спальня 1', '17,5'], ['Спальня 2', '9,7'], ['Санузел 1', '4,4'], ['Санузел 2', '3,9'], ['Прихожая', '9,3']];

await Promise.all([
  figma.loadFontAsync({ family: 'Inter', style: 'Regular' }),
  figma.loadFontAsync({ family: 'Inter', style: 'Medium' }),
  figma.loadFontAsync({ family: 'Inter', style: 'Bold' }),
]);
let page = figma.root.children.find(p => p.name === PAGE_NAME);
if (!page) page = figma.createPage();
page.name = PAGE_NAME;
await figma.setCurrentPageAsync(page);
for (const ch of [...page.children]) ch.remove();

const vars = {};
for (const [k, id] of Object.entries({ bgPage: V.bgPage, textSecondary: V.textSecondary, sp6: V.sp[6], sp12: V.sp[12] }))
  vars[k] = await figma.variables.getVariableByIdAsync(id);
const comp = {};
for (const [k, id] of Object.entries(C)) comp[k] = await figma.getNodeByIdAsync(id);
const captionStyle = (await figma.getLocalTextStylesAsync()).find(s => s.name === 'Текст/14 Regular');

const paintVar = v => [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }, 'color', v)];
const gap = (f, n) => { f.itemSpacing = n; const v = n === 12 ? vars.sp12 : n === 6 ? vars.sp6 : null; if (v) f.setBoundVariable('itemSpacing', v); };
const col = (name, g) => { const f = figma.createAutoLayout('VERTICAL', { name }); f.fills = []; f.counterAxisAlignItems = 'CENTER'; gap(f, g); return f; };
const add = (parent, node, fill) => { parent.appendChild(node); if (fill) node.layoutSizingHorizontal = 'FILL'; return node; };
const inst = (k, name) => { const i = comp[k].createInstance(); if (name) i.name = name; return i; };
// Текст из нескольких кусков разного стиля: заменить кусок i на parts[i], стиль куска сохраняется (переопределение, не отвязка).
const setParts = (t, parts) => {
  const segs = t.getStyledTextSegments(['fontName']);
  for (let i = segs.length - 1; i >= 0; i--) {
    if (parts[i] == null) continue;
    t.insertCharacters(segs[i].end, parts[i], 'BEFORE');
    t.deleteCharacters(segs[i].start, segs[i].end);
  }
};
const sub = (i, origId) => i.findOne(n => n.id.endsWith(';' + origId));
const caption = (text, x, y) => {
  const t = figma.createText(); t.textStyleId = captionStyle.id; t.characters = text;
  t.fills = paintVar(vars.textSecondary); t.x = x; t.y = y; page.appendChild(t); return t;
};
const screen = (name, x) => {
  const f = figma.createAutoLayout('VERTICAL', { name });
  f.resize(375, 812); f.primaryAxisSizingMode = 'FIXED'; f.counterAxisSizingMode = 'FIXED';
  f.counterAxisAlignItems = 'CENTER'; f.clipsContent = true; f.fills = paintVar(vars.bgPage);
  f.x = x; f.y = 0; page.appendChild(f); return f;
};
// Лента контента главной (общая для 01 и 05): карточка гостиной, 6 комнат «появится следующим шагом», план, переключатель языка.
const content = parent => {
  const c = add(parent, col('Content', G.lang), false);
  const rooms = col('Rooms', 12); add(c, rooms, false);
  add(rooms, inst('room', 'Card / Room'));
  for (const [n, a] of ROOMS) {
    const s = add(rooms, inst('soon', 'Card / Coming Soon · ' + n));
    setParts(sub(s, '64:122'), [n + ' ', '· ' + a + ' м²']);
  }
  add(rooms, inst('plan', 'Card / Plan Tile'));
  const lang = add(c, inst('lang', 'Language Switch'));
  return { c, rooms, lang };
};

const created = [];
// Эталоны — дубликаты рамок-картинок (не ссылки).
const refs = [['22:3', 0], ['22:7', 900]];
for (const [id, x] of refs) {
  const o = await figma.getNodeByIdAsync(id);
  const d = o.clone(); page.appendChild(d); d.x = x; d.y = 0; d.name = 'эталон · ' + o.name; d.locked = true;
  created.push(d.id, caption('эталон — снимок сайта 26.10', x, -32).id);
}

// 01 Главная: первый экран.
const s1 = screen('01 Главная: первый экран', 415);
created.push(s1.id, caption('сборка из компонентов', 415, -32).id);
// Корень: [Top: Header + Controls] → [Main: Intro (подсказка + вкладки) → Content]. Отступы — gap вложенных колонок.
gap(s1, G.root);
const topc = add(s1, col('Top', G.top), true);
const head = add(topc, col('Header', G.head), true); // < 0: строка ЖК на сайте заходит под нижнее поле шапки
add(head, inst('bar', 'Header / Apartment Bar'));
add(head, inst('complex', 'Header / Complex Row'));
const ctl = add(topc, col('Controls', G.ctl), true);
add(ctl, inst('actions', 'Header / Actions'));
add(ctl, inst('progress', 'Progress Bar'));
const main = add(s1, col('Main', G.main), true);
const intro = add(main, col('Intro', G.intro), true);
add(intro, inst('hint', 'Home / Hint'));
add(intro, inst('tabs', 'Tabs'));
const c1 = content(main);

// 05 Главная: прокрутка к комнатам — закреплённая шапка (абсолютно, поверх) над лентой, прокрученной до конца
// (лента прижата к низу экрана: primaryAxisAlignItems = MAX + нижнее поле; верх карточки гостиной уходит под шапку).
const s5 = screen('05 Главная: прокрутка к комнатам', 1315);
created.push(s5.id, caption('сборка из компонентов', 1315, -32).id);
s5.primaryAxisAlignItems = 'MAX'; s5.paddingBottom = G.bottom;
const c5 = content(s5);
const st = add(s5, col('Sticky Header', 0), false); st.fills = paintVar(vars.bgPage);
st.layoutPositioning = 'ABSOLUTE'; st.x = 0; st.y = 0; st.resize(375, 10);
st.counterAxisSizingMode = 'FIXED'; st.primaryAxisSizingMode = 'AUTO';
st.constraints = { horizontal: 'STRETCH', vertical: 'MIN' };
add(st, inst('barSticky', 'Header / Apartment Bar'), true);
const st2 = add(st, col('Sticky Controls', G.stCtl), true);
add(st2, inst('progressSticky', 'Progress Bar'));
add(st2, inst('tabsSticky', 'Tabs'));

// Второй проход: FILL у экземпляров на всю ширину (грабля П2в — в вызове создания слетает).
for (const f of [s1, s5]) for (const i of f.findAllWithCriteria({ types: ['INSTANCE'] }))
  if (Math.round(i.width) === 375 && i.parent !== f && i.parent.layoutSizingHorizontal === 'FILL') i.layoutSizingHorizontal = 'FILL';
const top = f => f.findAllWithCriteria({ types: ['INSTANCE'] }).filter(i => i.parent.type !== 'INSTANCE')
  .map(i => i.name.replace(/^.* \/ /, '') + ' y=' + Math.round(i.absoluteTransform[1][2]) + ' h=' + Math.round(i.height) + (Math.round(i.width) === 351 ? '' : ' w=' + Math.round(i.width))).join(' | ');
return { page: page.id, s1: s1.id, s5: s5.id, created, y1: top(s1), y5: top(s5) };
