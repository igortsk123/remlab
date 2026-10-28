// помощник 1: страница «Как пользоваться» — первая в книге. Текст утверждён владельцем (через ведущего 26.10), не менять.
// Повторный запуск заменяет свой лист (метка remlab code=howto). DEV не нужен: текст одинаковый в обеих книгах.
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
const INK = () => paint('Текст/Основной', '#2B2420'), MUTED = () => paint('Текст/Второстепенный', '#6E655E');

let page = figma.root.children.find((p) => p.name === 'Как пользоваться') || figma.root.children.find((p) => p.name === 'Page 1');
if (!page) page = figma.createPage();
page.name = 'Как пользоваться';
if (figma.root.children.indexOf(page) !== 0) figma.root.insertChild(0, page);
for (const [nm, i] of [['Счастливый путь', 1], ['Кнопки', 2], ['Плашки', 3]]) { const p = figma.root.children.find((x) => x.name === nm); if (p && figma.root.children.indexOf(p) !== i) figma.root.insertChild(i, p); }

// «Что где» — из самой книги; служебные страницы описаны одной строкой ниже списка
const skip = new Set(['Как пользоваться', 'Экраны RU', 'Экраны EN', 'Счастливый путь', 'Архив']);
const rows = [];
for (const p of figma.root.children) {
  if (skip.has(p.name)) continue;
  await p.loadAsync();
  rows.push([p.name, p.children.filter((c) => c.type === 'SECTION').map((c) => c.name)]);
}

await figma.setCurrentPageAsync(page);
for (const n of page.children.filter((c) => c.getSharedPluginData('remlab', 'code') === 'howto')) n.remove();

const TW = 640, PAD = 64;
const card = figma.createFrame(); card.name = 'Как пользоваться'; card.setSharedPluginData('remlab', 'code', 'howto');
card.layoutMode = 'VERTICAL'; card.primaryAxisSizingMode = 'AUTO'; card.counterAxisSizingMode = 'FIXED'; card.resize(TW + PAD * 2, 100);
card.paddingLeft = card.paddingRight = card.paddingTop = card.paddingBottom = PAD; card.itemSpacing = 32; card.cornerRadius = 16;
card.fills = [paint('Фон/Карточка', '#FFFFFF')]; card.strokes = [paint('Граница/Обычная', '#E6E1DC')]; card.strokeWeight = 1;
page.appendChild(card); card.x = 0; card.y = 0;

const T = (parent, chars, size, style, color, name, lh) => {
  const t = figma.createText(); t.fontName = { family: 'Inter', style }; t.fontSize = size; t.characters = chars; t.fills = [color()];
  t.name = name; if (lh) t.lineHeight = { value: lh, unit: 'PIXELS' };
  parent.appendChild(t); t.textAutoResize = 'HEIGHT'; t.layoutAlign = 'STRETCH'; return t;
};
const block = (name, gap) => { const f = figma.createFrame(); f.name = name; f.layoutMode = 'VERTICAL'; f.primaryAxisSizingMode = 'AUTO'; f.itemSpacing = gap || 10; f.fills = []; card.appendChild(f); f.layoutAlign = 'STRETCH'; return f; };

T(card, 'Как пользоваться', 32, 'Bold', INK, 'Заголовок', 40);

const parts = [
  ['Можно смело:', [
    'менять цвета, шрифты, размеры, отступы, скругления, тени. Лучше через общие цвета и стили: тогда поменяется везде сразу;',
    'двигать, добавлять и убирать элементы в компонентах и на экранах;',
    'добавлять новые компоненты, варианты, страницы, рисовать свои экраны.',
  ]],
  ['Лучше не трогать:', [
    'названия компонентов, вариантов, экранов, цветов и стилей: по ним я нахожу, что изменилось. Если очень нужно переименовать, напишите в описании старое название;',
    'не удалять компоненты, а переносить на страницу «Архив»;',
    'не вписывать цвет вручную, а брать из общих цветов;',
    'картинки на страницах «Экраны» это снимки сайта для сравнения, их не правим. Свою версию рисуем рядом.',
  ]],
];
for (const [h, items] of parts) {
  const b = block(h.replace(':', ''), 8);
  T(b, h, 18, 'Semi Bold', INK, 'Подзаголовок', 26);
  for (const it of items) T(b, '•  ' + it, 16, 'Regular', INK, 'Пункт', 24);
}
const after = block('После правок', 8);
const ta = T(after, 'После правок: пара слов в комментарии в Фигме, что поменяли.', 16, 'Regular', INK, 'Текст', 24);
ta.setRangeFontName(0, 'После правок:'.length, { family: 'Inter', style: 'Semi Bold' }); ta.setRangeFontSize(0, 'После правок:'.length, 18);

const list = block('Что где', 12);
T(list, 'Что где', 18, 'Semi Bold', INK, 'Подзаголовок', 26);
for (const [name, secs] of rows) {
  const n = secs.length;
  const t = T(list, name + ' — ' + (n ? n + ' ' + (n % 10 === 1 && n % 100 !== 11 ? 'секция' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'секции' : 'секций') + ': ' + secs.join(', ') : 'пока пусто'), 16, 'Regular', INK, 'Страница «' + name + '»', 24);
  t.setRangeFontName(0, name.length, { family: 'Inter', style: 'Semi Bold' });
}
T(list, 'Счастливый путь — весь сценарий по шагам; Экраны RU и Экраны EN — снимки сайта для сравнения.', 16, 'Regular', MUTED, 'Служебные страницы', 24);

figma.viewport.scrollAndZoomIntoView([card]);
return { pages: figma.root.children.map((p) => p.name), id: card.id, h: Math.round(card.height), empty: rows.filter((r) => !r[1].length).map((r) => r[0]) };
