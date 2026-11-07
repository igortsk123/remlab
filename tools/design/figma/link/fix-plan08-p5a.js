// design-02 П5 (T-20261107-62) п.6, книга Mobile: экран 08 «План квартиры» (RU 301:730 на 280:2, EN 307:832 на 293:2).
// «Схема Card / Floor Plan ниже на 7 px» и «переключатель языка сдвинут ~20 px» — не компоненты (внутри карточки схема стоит как на
// эталоне), а промежутки сборки: на эталоне «← К стилям» на 4 px выше, до карточки 38 px (у сборки 26), от карточки до текста
// переключателя 69 px (у сборки 51). Правка в сборке: корень gap 12→8, Main gap 12→24, у переключателя поле сверху 28→34.
const CFG = __CFG__; // { page, id }
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync(CFG.page));
const s = await figma.getNodeByIdAsync(CFG.id);
const main = s.children.find(n => n.name === 'Main');
const ls = main.children.find(n => n.type === 'INSTANCE' && n.name === 'Language Switch');
const card = main.children.find(n => n.type === 'INSTANCE' && /Floor Plan/.test(n.name));
const pos = () => ['main@' + Math.round(main.y), 'card@' + Math.round(main.y + card.y), 'ls@' + Math.round(main.y + ls.y) + '+' + ls.paddingTop].join(' ');
const before = pos() + ' gaps ' + s.itemSpacing + '/' + main.itemSpacing;
s.itemSpacing = 8; main.itemSpacing = 24; ls.paddingTop = 34;
return { before, after: pos() + ' gaps ' + s.itemSpacing + '/' + main.itemSpacing };
