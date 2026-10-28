// Страница «Уведомление» (помощник 3, 26.10): после build-all — кнопка «Перейти →» / «Open →» в строке текста, как на сайте.
// Зачем: на сайте кнопка стоит в строке внутри текста (index.html:836 `.msg .toastact{margin-left:10px}`, :2988); выгрузка
// даёт текст-блок во всю высоту и кнопку поверх его последней строки — в Фигме это «текст на тексте».
// Делаем: строки текста раскладываем так же, как браузер (жадно по словам в ширину плашки), все строки кроме последней —
// один текст по центру; последняя строка + кнопка — ряд по центру с отступом 10. Шрифт Inter — переносы считаются по нему.
// v2 (19:10): в Desktop выгрузка считает такой текст одной строкой высотой 42 (межстрочный 42) — правим межстрочный на
// 21 (на сайте 15 px × 1,35, index.html:831; в Mobile выгрузка даёт 21). Плашка выросла — набор и секция растут следом,
// иначе низ плашки обрезается краем набора.
const PAGE = typeof PAGE_NAME !== 'undefined' ? PAGE_NAME : 'Уведомление';
const page = figma.root.children.find((p) => p.name === PAGE);
await figma.setCurrentPageAsync(page);
const res = [];
for (const v of page.findAllWithCriteria({ types: ['COMPONENT'] })) {
  const btn = v.children.find((n) => n.type === 'FRAME' && /toastact/.test(n.getSharedPluginData('remlab', 'css')));
  const t = v.children.find((n) => n.type === 'TEXT');
  if (!btn || !t) continue;
  await figma.loadFontAsync(t.fontName);
  for (const s of btn.findAllWithCriteria({ types: ['TEXT'] })) await figma.loadFontAsync(s.fontName);
  if (t.lineHeight.unit === 'PIXELS' && t.lineHeight.value > t.fontSize * 1.9) t.lineHeight = { unit: 'PIXELS', value: Math.round(t.fontSize * 1.4) };
  const W = v.width - 32, lh = t.lineHeight.unit === 'PIXELS' ? t.lineHeight.value : 21;
  const probe = t.clone(); v.appendChild(probe); probe.textAutoResize = 'WIDTH_AND_HEIGHT';
  const wOf = (s) => { probe.characters = s; return probe.width; };
  const words = t.characters.split(' ');
  const lines = []; let cur = '';
  for (const w of words) { const c = cur ? cur + ' ' + w : w; if (cur && wOf(c) > W) { lines.push(cur); cur = w; } else cur = c; }
  // кнопка — неразрывный кусок шириной кнопки + 10 слева
  let last = cur;
  if (wOf(last) + 10 + btn.width > W) { lines.push(last); last = ''; }
  probe.remove();
  const box = figma.createAutoLayout('VERTICAL', { name: 'Текст с кнопкой', itemSpacing: 0 });
  box.counterAxisAlignItems = 'CENTER'; box.fills = [];
  v.appendChild(box); box.x = 16; box.y = 11;
  if (lines.length) {
    const a = t.clone(); a.characters = lines.join(' '); a.name = 'Текст';
    box.appendChild(a); a.textAutoResize = 'HEIGHT'; a.resize(W, a.height);
    if (Math.abs(a.height - lines.length * lh) > 1) res.push(['перенос не совпал', v.name, a.height, lines.length]);
  }
  const row = figma.createAutoLayout('HORIZONTAL', { name: 'Последняя строка и кнопка', itemSpacing: 10 });
  row.counterAxisAlignItems = 'CENTER'; row.fills = [];
  box.appendChild(row);
  if (last) { const b2 = t.clone(); b2.characters = last; b2.name = 'Текст — последняя строка'; row.appendChild(b2); b2.textAutoResize = 'WIDTH_AND_HEIGHT'; }
  btn.name = 'Кнопка'; row.appendChild(btn);
  box.resize(W, box.height); box.primaryAxisSizingMode = 'AUTO'; box.counterAxisSizingMode = 'FIXED';
  t.remove();
  const need = box.y + box.height + 11;
  if (need !== v.height) v.resizeWithoutConstraints(v.width, Math.max(need, 20));
  res.push([v.name, lines.length + 1 + ' строк', Math.round(box.height), Math.round(v.height)]);
}
// набор и секция — по новому низу плашек (нижний отступ набора как был, 24)
for (const set of page.findAllWithCriteria({ types: ['COMPONENT_SET'] })) {
  const bottom = Math.max(...set.children.map((c) => c.y + c.height)) + 24;
  const d = bottom - set.height;
  if (d > 0) { set.resizeWithoutConstraints(set.width, bottom); const sec = set.parent; if (sec && sec.type === 'SECTION') sec.resizeWithoutConstraints(sec.width, sec.height + d); res.push(['набор вырос на', Math.round(d)]); }
}
return res;
