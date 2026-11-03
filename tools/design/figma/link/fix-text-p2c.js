// design-02 П2в (T-20261103-07): второй проход для текста внутри экземпляров — раскладка (FILL/FIXED/HUG), автоподгон,
// выравнивание. В том же вызове, где экземпляр создан, FILL у текста-слоя экземпляра не держится (после вызова снова FIXED),
// отдельным вызовом — держится. Вход — out.tlfix из link-p2c.js: [[id слоя, lsh, lsv, textAutoResize, textAlignHorizontal]].
const PAGE_ID = '16:2';
const FIX = []; // ← out.tlfix
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = { ok: [], miss: [] };
for (const [id, lsh, lsv, tar, al] of FIX) {
  const t = await figma.getNodeByIdAsync(id);
  if (!t) { out.miss.push(id); continue; }
  for (const s of t.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
  if (t.textAutoResize !== tar) t.textAutoResize = tar;
  if (t.textAlignHorizontal !== al) t.textAlignHorizontal = al;
  if (lsh && t.layoutSizingHorizontal !== lsh) t.layoutSizingHorizontal = lsh;
  if (lsv && t.layoutSizingVertical !== lsv) t.layoutSizingVertical = lsv;
  out.ok.push(id + ' ' + t.layoutSizingHorizontal + ' ' + Math.round(t.width) + 'x' + Math.round(t.height));
}
return out;
