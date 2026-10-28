// помощник 1: страница «Как пользоваться» — первая в книге. Повторный запуск заменяет свой лист (метка remlab code=howto).
// Перед вызовом поставить DEV: 'phone' (Mobile) или 'desktop' (Desktop).
const DEV = 'phone';
const BOOK = DEV === 'phone' ? { me: 'Mobile (телефон, ширина 375)', pair: 'Desktop (компьютер, ширина 1440)' } : { me: 'Desktop (компьютер, ширина 1440)', pair: 'Mobile (телефон, ширина 375)' };
await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
await figma.loadFontAsync({ family: 'Inter', style: 'Semi Bold' });
await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = (name) => vars.find((v) => v.name === name);
const paint = (name, hex) => {
  const c = { r: parseInt(hex.slice(1, 3), 16) / 255, g: parseInt(hex.slice(3, 5), 16) / 255, b: parseInt(hex.slice(5, 7), 16) / 255 };
  const p = { type: 'SOLID', color: c }; const v = V(name);
  return v ? figma.variables.setBoundVariableForPaint(p, 'color', v) : p;
};
const INK = () => paint('Текст/Основной', '#2B2420'), MUTED = () => paint('Текст/Второстепенный', '#6E655E'), ACC = () => paint('Бренд/Основной', '#B06A4C');

let page = figma.root.children.find((p) => p.name === 'Как пользоваться') || figma.root.children.find((p) => p.name === 'Page 1');
if (!page) page = figma.createPage();
page.name = 'Как пользоваться';
if (figma.root.children.indexOf(page) !== 0) figma.root.insertChild(0, page);
// «Кнопки» и «Плашки» — сразу за ней, как в Mobile
for (const [nm, i] of [['Кнопки', 1], ['Плашки', 2]]) { const p = figma.root.children.find((x) => x.name === nm); if (p && figma.root.children.indexOf(p) !== i) figma.root.insertChild(i, p); }

// «что где» — собираем из самой книги
const skip = new Set(['Как пользоваться', 'Экраны RU', 'Экраны EN']);
const rows = []; const screens = [];
for (const p of figma.root.children) {
  if (p.name === 'Экраны RU' || p.name === 'Экраны EN') { await p.loadAsync(); screens.push(p.name + ' — ' + p.children.length); continue; }
  if (skip.has(p.name)) continue;
  await p.loadAsync();
  const secs = p.children.filter((c) => c.type === 'SECTION').map((c) => c.name);
  rows.push([p.name, secs]);
}

await figma.setCurrentPageAsync(page);
for (const n of page.children.filter((c) => c.getSharedPluginData('remlab', 'code') === 'howto')) n.remove();

const W = 960, IN = W - 128;
const card = figma.createFrame(); card.name = 'Как пользоваться'; card.setSharedPluginData('remlab', 'code', 'howto');
card.layoutMode = 'VERTICAL'; card.primaryAxisSizingMode = 'AUTO'; card.counterAxisSizingMode = 'FIXED'; card.resize(W, 100);
card.paddingLeft = card.paddingRight = card.paddingTop = card.paddingBottom = 64; card.itemSpacing = 40; card.cornerRadius = 16;
card.fills = [paint('Фон/Карточка', '#FFFFFF')]; card.strokes = [paint('Граница/Обычная', '#E6E1DC')]; card.strokeWeight = 1;
page.appendChild(card); card.x = 0; card.y = 0;

const T = (parent, chars, size, style, color, name, lh) => {
  const t = figma.createText(); t.fontName = { family: 'Inter', style }; t.fontSize = size; t.characters = chars; t.fills = [color()];
  t.name = name; if (lh) t.lineHeight = { value: lh, unit: 'PIXELS' };
  parent.appendChild(t); t.textAutoResize = 'HEIGHT'; t.layoutAlign = 'STRETCH'; return t;
};
const block = (name) => { const f = figma.createFrame(); f.name = name; f.layoutMode = 'VERTICAL'; f.primaryAxisSizingMode = 'AUTO'; f.itemSpacing = 10; f.fills = []; card.appendChild(f); f.layoutAlign = 'STRETCH'; return f; };

const head = block('Заголовок');
T(head, 'Как пользоваться этой книгой', 40, 'Bold', INK, 'Заголовок', 48);
T(head, 'UI-кит remlab: детали сайта remont-lab.online, собранные из живой вёрстки.\nЭта книга — ' + BOOK.me + '. Пара к ней — книга ' + BOOK.pair + '.', 18, 'Regular', MUTED, 'Подзаголовок', 28);

const parts = [
  ['Откуда детали', 'Каждая деталь снята с настоящего сайта (выгрузка 26.10.2026, 16:53) и собрана заново. Слои можно править, цвета и скругления привязаны к переменным файла, фото — настоящие картинки, значки — векторы. Шрифт — Inter: он на несколько пикселей шире шрифта сайта, поэтому подписи иногда чуть шире, чем на сайте.'],
  ['Как устроена страница', 'Одна страница — одна группа деталей: «Кнопки», «Шторка», «Бюджет» и так далее. Секции стоят одна под другой. У каждой секции сверху название, а под ним строка «что это»: где эта деталь на сайте и зачем она.'],
  ['Как читать таблицу вариантов', 'Внутри секции варианты стоят строгой таблицей. Строка — язык: верхняя RU, под ней EN. Столбец — состояние: обычное, выбрано, наведено и т. п. Над каждым вариантом подпись «язык · состояние». Все варианты секции — один набор компонентов: справа, в свойствах, их переключают («Язык», «Состояние» и другие).'],
  ['Как взять деталь в свой макет', 'Перетащите нужный вариант из набора или найдите его по имени во вкладке Assets. Важно: страницы этой книги пересобираются с сайта, и ручные правки на них при пересборке пропадут. Свои правки делайте в копии или в своём файле.'],
  ['Экраны RU и Экраны EN', 'Последние две страницы — целые экраны сайта по шагам сценария (' + screens.join(', ') + '). С ними сверяют детали; эти страницы не пересобираются.'],
  ['Служебные данные', 'У слоёв есть скрытые служебные пометки (общие данные плагина, пространство «remlab»): адрес фото на сайте (src) и как оно вписано (fit), исходный стиль (css), код детали (code), экран, с которого она снята (screen), имя варианта (variant). В макете их не видно, их читает сборщик. Не удаляйте их.'],
];
for (const [h, body] of parts) { const b = block(h); T(b, h, 22, 'Semi Bold', INK, 'Заголовок блока', 30); T(b, body, 16, 'Regular', INK, 'Текст', 26); }

const list = block('Что где'); list.itemSpacing = 14;
T(list, 'Что где', 22, 'Semi Bold', ACC, 'Заголовок блока', 30);
for (const [name, secs] of rows) {
  const t = T(list, name + ' — ' + (secs.length ? secs.length + ' ' + (secs.length === 1 ? 'секция' : secs.length < 5 ? 'секции' : 'секций') + ': ' + secs.join(', ') : 'пока пусто'), 15, 'Regular', INK, 'Страница «' + name + '»', 24);
  t.setRangeFontName(0, name.length, { family: 'Inter', style: 'Semi Bold' });
}

T(card, 'Как пересобрать страницу с сайта — файл tools/design/figma/README.md в репозитории remlab.', 14, 'Regular', MUTED, 'Подвал', 22);
figma.viewport.scrollAndZoomIntoView([card]);
return { page: page.name, index: figma.root.children.indexOf(page), id: card.id, h: Math.round(card.height), rows: rows.length, screens, boundVars: ['Текст/Основной', 'Текст/Второстепенный', 'Бренд/Основной', 'Фон/Карточка', 'Граница/Обычная'].filter((n) => !!V(n)) };
