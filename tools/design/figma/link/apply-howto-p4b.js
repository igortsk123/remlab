// design-02 П4б (T-20261103-12): ЗАПИСЬ — тексты «Как пользоваться» (страница 0:1) по howto-<книга>.json.
// Подставить EDITS = [[id, старый, новый, жирное до, после]] и ADD = {after, text, bold, name}.
// Оформление: жирное начало и обычный хвост берутся из самого текста (первый и последний отрезок) и
// накладываются заново; новая строка «Нюансов» — копия ADD.after, ставится сразу за ней. Повтор безопасен.
const EDITS = __EDITS__;
const ADD = __ADD__;
const page = await figma.getNodeByIdAsync('0:1');
await figma.setCurrentPageAsync(page);
const F = ['fontName', 'fontSize', 'fills', 'lineHeight', 'letterSpacing', 'textDecoration', 'textCase'];
const nodes = {};
for (const [id, o, n, b0] of EDITS) {
  const t = await figma.getNodeByIdAsync(id);
  if (!t || t.type !== 'TEXT') throw new Error('нет текста ' + id);
  if (t.characters !== o && t.characters !== n) throw new Error(id + ': текст не старый и не новый');
  if (t.characters === o) {
    const s = t.getStyledTextSegments(F);
    if (s.length !== 2 || s[0].end !== b0) throw new Error(id + ': отрезки ' + s.map(x => x.end).join(','));
  }
  nodes[id] = t;
}
const restyle = async (t, text, bold, sA, sB) => {
  await figma.loadFontAsync(sA.fontName); await figma.loadFontAsync(sB.fontName);
  t.characters = text;
  for (const [s, a, b] of [[sB, 0, text.length], [sA, 0, bold]]) {
    t.setRangeFontName(a, b, s.fontName); t.setRangeFontSize(a, b, s.fontSize); t.setRangeFills(a, b, s.fills);
    t.setRangeLineHeight(a, b, s.lineHeight); t.setRangeLetterSpacing(a, b, s.letterSpacing);
    t.setRangeTextDecoration(a, b, s.textDecoration); t.setRangeTextCase(a, b, s.textCase);
  }
};
const res = [];
for (const [id, o, n, b0, b1] of EDITS) {
  const t = nodes[id];
  if (t.characters === n) { res.push([id, 'уже']); continue; }
  const s = t.getStyledTextSegments(F);
  await restyle(t, n, b1, s[0], s[1]);
  const s2 = t.getStyledTextSegments(['fontName']);
  res.push([id, s2.map(x => x.end + ':' + x.fontName.style).join(',')]);
}
// новая строка «Нюансов»
const ref = await figma.getNodeByIdAsync(ADD.after);
const par = ref.parent;
let added = par.children.find(c => c.type === 'TEXT' && c.characters === ADD.text);
if (!added) {
  const s = ref.getStyledTextSegments(F);
  added = ref.clone();
  par.insertChild(par.children.indexOf(ref) + 1, added);
  added.name = ADD.name;
  await restyle(added, ADD.text, ADD.bold, s[0], s[s.length - 1]);
}
return JSON.stringify({ res, added: [added.id, par.children.map(c => c.id).join(','), Math.round(added.height)] });
