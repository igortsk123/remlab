// помощник 1: итоговая проверка книги, ТОЛЬКО ЧТЕНИЕ. Порядок страниц, наборы вне секций, секции с подписью и «что это»,
// пустые плашки фото/значков. check.js — отдельными вызовами (audit-check.js).
const SERV = new Set(['Как пользоваться', 'Счастливый путь', 'Экраны RU', 'Экраны EN']);
const want = ['Как пользоваться', 'Счастливый путь'];
const names = figma.root.children.map((p) => p.name);
const n = names.length;
const order = names[0] === 'Как пользоваться' && names[1] === 'Счастливый путь' && names[n - 2] === 'Экраны RU' && names[n - 1] === 'Экраны EN'
  && names.slice(2, n - 2).every((x) => !SERV.has(x));
const hasImg = (x) => Array.isArray(x.fills) && x.fills.some((f) => f.type === 'IMAGE');
const rows = []; const loose = []; const bad = []; const empty = [];
for (const p of figma.root.children) {
  await p.loadAsync();
  for (const s of p.findAllWithCriteria({ types: ['COMPONENT_SET'] })) {
    let a = s.parent, inSec = false; while (a && a.type !== 'PAGE') { if (a.type === 'SECTION') { inSec = true; break; } a = a.parent; }
    if (!inSec) loose.push([p.name, s.name, s.id]);
  }
  // пустые плашки: «Фото»/«кадр» без картинки (ни в себе, ни внутри), «Иконка»/«Значок» без векторов/картинки/текста
  for (const x of p.findAll((x) => /Фото|кадр|Иконка|Значок/i.test(x.name) && (x.type === 'RECTANGLE' || x.type === 'FRAME' || x.type === 'INSTANCE'))) {
    if (x.visible === false) continue;
    const kids = 'findAll' in x ? x.findAll(() => true) : [];
    const photo = /Фото|кадр/i.test(x.name);
    const ok = hasImg(x) || kids.some((k) => hasImg(k)) || (!photo && kids.some((k) => k.type === 'VECTOR' || k.type === 'BOOLEAN_OPERATION' || k.type === 'TEXT' || k.type === 'ELLIPSE' || k.type === 'STAR' || k.type === 'POLYGON' || k.type === 'LINE'))
      || (photo && kids.some((k) => /Фото|кадр/i.test(k.name)));  // обёртка: картинка во вложенном «Фото» — проверится сама
    if (!ok) empty.push([p.name, x.name, x.type, x.id]);
  }
  if (SERV.has(p.name)) continue;
  const secs = p.children.filter((c) => c.type === 'SECTION');
  let noSay = 0;
  for (const s of secs) {
    const say = s.children.find((c) => c.type === 'TEXT' && c.name === 'Что это');
    const okName = s.name && !/^Section/.test(s.name);
    const okSay = say && say.characters.trim() && say.characters.trim() !== s.name;
    if (!okName || !okSay) { noSay++; bad.push([p.name, s.name, okName ? '' : 'нет названия', okSay ? '' : (say ? 'строка = названию' : 'нет «что это»')]); }
    if (!s.children.some((c) => c.type === 'COMPONENT_SET')) bad.push([p.name, s.name, 'в секции нет набора']);
  }
  rows.push([p.name, secs.length, noSay]);
}
return { order, pages: names, looseSets: loose, sections: rows, badSections: bad, emptyPlates: empty.slice(0, 40), emptyCount: empty.length };
