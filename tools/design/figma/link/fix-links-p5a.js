// design-02 П5 (T-20261107-62) п.6, книга Mobile: ссылки внутри Modal / Name Input (85:30 RU, 85:60 EN) — экземпляры Link 107:54/107:58
// с переопределениями сборщика (кегль 14, межстрочный 16, без подчёркивания, ширина 200 с текстом по центру → текст на 6–8 px правее).
// Вернуть к базе Link: текстовый стиль базы (15 / 150 %), подчёркивание, ширина по тексту, текст слева. Цвет «Убрать» (красный) — как был.
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('17:38'));
const base = (await figma.getNodeByIdAsync('107:54')).findOne(n => n.type === 'TEXT');
const out = [];
for (const id of ['237:70', '237:72', '237:82', '237:84']) {
  const l = await figma.getNodeByIdAsync(id); const t = l.findOne(n => n.type === 'TEXT');
  for (const s of t.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
  const b = Math.round(l.width) + 'w fs' + t.fontSize + ' ' + t.textDecoration + ' x' + Math.round(t.x);
  await t.setTextStyleIdAsync(base.textStyleId);
  t.textDecoration = 'UNDERLINE';
  l.primaryAxisAlignItems = 'MIN'; l.primaryAxisSizingMode = 'AUTO';
  out.push(id + ' ' + b + ' → ' + Math.round(l.width) + 'w fs' + t.fontSize + ' ' + t.textDecoration + ' x' + Math.round(t.x));
}
return out;
