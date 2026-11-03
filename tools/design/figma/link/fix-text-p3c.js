// design-02 П3в (T-20261103-10, Desktop): второй проход для текста внутри экземпляров после link-p3c (грабля П2в: FILL/HUG у
// текста-слоя экземпляра, заданный в вызове создания, может слететь после вызова). Читает figma.root remlab/tl-p3c-<набор>
// ([[id, lsh, lsv, textAutoResize]] — как было сразу после переноса), сравнивает с текущим и при расхождении ставит заново.
// Отдельный вызов после каждого боевого прогона link-p3c. Одна страница на вызов: PAGE_ID + SET.
const PAGE_ID = '9:134';
const SET = '48:1082';
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const TL = JSON.parse(figma.root.getSharedPluginData('remlab', 'tl-p3c-' + SET) || '[]');
const out = { n: TL.length, same: 0, fixed: [], miss: 0, err: [] };
for (const [id, lsh, lsv, tar] of TL) {
  const t = await figma.getNodeByIdAsync(id);
  if (!t) { out.miss++; continue; }
  if (t.layoutSizingHorizontal === lsh && t.layoutSizingVertical === lsv && t.textAutoResize === tar) { out.same++; continue; }
  const was = [t.layoutSizingHorizontal, t.layoutSizingVertical, t.textAutoResize].join('/');
  try {
    for (const s of t.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
    if (t.textAutoResize !== tar) t.textAutoResize = tar;
    if (t.layoutSizingHorizontal !== lsh) t.layoutSizingHorizontal = lsh;
    if (t.layoutSizingVertical !== lsv) t.layoutSizingVertical = lsv;
    out.fixed.push(id + ' ' + was + '→' + [lsh, lsv, tar].join('/'));
  } catch (e) { out.err.push(id + ': ' + e.message); }
}
return out;
