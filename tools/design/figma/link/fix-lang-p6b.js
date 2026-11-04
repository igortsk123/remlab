// design-02 П6б (T-20261104-03): Language Switch (105:456, страница Home 14:72) — подчёркивание у неактивного языка,
// как на сайте (неактивный — ссылка <a>, tools/scout/flat215-demo/index.html:7662) и на эталонах 22:8 / 22:50.
// RU-вариант 105:450 (текст 105:449): подчеркнуть «English»; EN-вариант 105:454 (текст 105:453): подчеркнуть «Русский».
// Откат: setRangeTextDecoration(…, 'NONE') на тех же диапазонах.
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync('14:72'));
const res = {};
for (const [id, word] of [['105:449', 'English'], ['105:453', 'Русский']]) {
  const t = await figma.getNodeByIdAsync(id);
  for (const s of t.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
  const i = t.characters.indexOf(word);
  t.setRangeTextDecoration(i, i + word.length, 'UNDERLINE');
  res[id] = t.getStyledTextSegments(['textDecoration']).map(s => [s.characters, s.textDecoration]);
}
return res;
