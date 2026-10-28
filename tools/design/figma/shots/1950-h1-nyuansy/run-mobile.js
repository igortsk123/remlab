// помощник 1, 26.10: блок «Нюансы» внизу страницы «Как пользоваться» — заметки для дизайнера.
// Запускать ПОСЛЕ howto.js (он пересоздаёт лист целиком): блок дописывается последним в лист с меткой remlab code=howto.
// Повторный запуск заменяет только свой блок (метка remlab code=nyuansy). Текст выше блока не трогается.
// DEV: 'phone' для Mobile, 'desktop' для Desktop — подставить перед вызовом (меняется только пункт «Размеры»).
// Каждый пункт сверен 26.10 с кодом и файлами (см. отчёт помощника 1).
const DEV = 'phone';
await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
await figma.loadFontAsync({ family: 'Inter', style: 'Semi Bold' });
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = (name) => vars.find((v) => v.name === name);
const paint = (name, hex) => {
  const c = { r: parseInt(hex.slice(1, 3), 16) / 255, g: parseInt(hex.slice(3, 5), 16) / 255, b: parseInt(hex.slice(5, 7), 16) / 255 };
  const p = { type: 'SOLID', color: c }; const v = V(name);
  return v ? figma.variables.setBoundVariableForPaint(p, 'color', v) : p;
};
const INK = () => paint('Текст/Основной', '#2B2420');

const page = figma.root.children.find((p) => p.name === 'Как пользоваться');
if (!page) return { err: 'нет страницы «Как пользоваться»' };
await figma.setCurrentPageAsync(page);
const card = page.children.find((c) => c.getSharedPluginData('remlab', 'code') === 'howto');
if (!card) return { err: 'нет листа howto — сначала howto.js' };
for (const n of card.children.filter((c) => c.getSharedPluginData('remlab', 'code') === 'nyuansy')) n.remove();

const size = DEV === 'phone'
  ? 'В этом файле всё снято при ширине 375: основной текст 17 px.'
  : 'В этом файле всё снято при ширине 1440: основной текст 18 px.';
const items = [
  ['Шрифт.', 'На сайте — системный шрифт устройства: SF Pro на iPhone и Mac, Roboto на Android, Segoe UI на Windows. В Фигме — Inter: наш сборщик макетов работает только с ним. Inter чуть шире, поэтому подпись, которая на сайте помещается в строку, здесь может обрезаться «…». Шрифт можно сменить в общих текстовых стилях, но к ним привязана примерно четверть текстов, остальные меняются отдельно.'],
  ['Размеры.', 'Mobile — экран шириной 375, Desktop — 1440. 1 пиксель в Фигме = 1 пиксель на сайте. На сайте основной текст растёт с шириной экрана: от 17 px на телефоне до 20 px на большом мониторе; многие кнопки и подписи тоже. ' + size],
  ['Цвета.', 'Все цвета — из переменных сайта. В Фигме у них русские названия («Текст/Основной»), а имя на сайте (--ink) записано у каждого цвета в поле для кода.'],
  ['Что не снято.', 'Наведение мышью; редкие состояния (например, «не влезет» у метки размера, «фото готовится» в Избранном); кнопку «Сделать реалистичнее» не нажимали — она платная. 3D-сцена — картинка (снимок экрана), а не векторы. Значки — векторы с сайта.'],
  ['Доведено вручную.', 'Эти места отличаются от автоматической выгрузки: обводка выбранного кружка цвета («Образцы», «Карточка товара»); план квартиры разложен на комнаты с подписями внутри; фото в средней карточке «Избранного»; «Изменить расстановку» в две строки («Диалог»); кнопки «Со стороны двери / окна» по ширине подписи.'],
  ['Экраны RU и EN', '— снимки remont-lab.online/demo от 26.10.2026. Сняты на сервере, где нет SF Pro, поэтому шрифт на них другой (DejaVu).'],
];

const b = figma.createFrame(); b.name = 'Нюансы'; b.setSharedPluginData('remlab', 'code', 'nyuansy');
b.layoutMode = 'VERTICAL'; b.primaryAxisSizingMode = 'AUTO'; b.itemSpacing = 12; b.fills = [];
card.appendChild(b); b.layoutAlign = 'STRETCH';
const T = (chars, size, style, name, lh) => {
  const t = figma.createText(); t.fontName = { family: 'Inter', style }; t.fontSize = size; t.characters = chars; t.fills = [INK()];
  t.name = name; t.lineHeight = { value: lh, unit: 'PIXELS' }; b.appendChild(t); t.textAutoResize = 'HEIGHT'; t.layoutAlign = 'STRETCH'; return t;
};
T('Нюансы', 18, 'Semi Bold', 'Подзаголовок', 26);
for (const [lead, text] of items) {
  const t = T(lead + ' ' + text, 16, 'Regular', 'Нюанс «' + lead.replace(/\.$/, '') + '»', 24);
  t.setRangeFontName(0, lead.length, { family: 'Inter', style: 'Semi Bold' });
}

// сверка пункта «Доведено вручную»: где в книге «Со стороны двери»
const where = [];
for (const p of figma.root.children) { if (/Экраны|Как польз|Счастливый/.test(p.name)) continue; await p.loadAsync();
  if (p.findOne((n) => n.type === 'TEXT' && /Со стороны двери/.test(n.characters))) where.push(p.name); }
figma.viewport.scrollAndZoomIntoView([card]);
return { card: card.id, block: b.id, h: Math.round(card.height), last: card.children[card.children.length - 1].name, n: b.children.length, doorPages: where, textW: Math.round(b.width) };
