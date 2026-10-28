// Страница «Образцы» (помощник 3, 26.10): подписи состояний и строка «что это» — как в pages/Образцы.json после правки 19:15.
// Зачем: «Обычное» рядом с «выбрано» читается странно — «не выбрано»; строка «что это» у образца пола переносилась на 2-ю строку.
// Нужна только для уже собранных страниц; при новой сборке словарь даёт то же сам.
const FLOOR = 'Образец пола в окне отделки: фото материала и подпись (в цене или доплата); выбранный — с обводкой';
const page = figma.root.children.find((p) => p.name === 'Образцы');
await page.loadAsync();
const out = [];
for (const sec of page.children.filter((n) => n.type === 'SECTION')) {
  for (const c of sec.findAllWithCriteria({ types: ['COMPONENT'] })) if (/Обычное/.test(c.name)) { c.name = c.name.replace('Обычное', 'не выбрано'); out.push(c.name); }
  for (const t of sec.findAllWithCriteria({ types: ['TEXT'] })) {
    if (t.parent && t.parent.type === 'COMPONENT') continue;
    if (/· Обычное$/.test(t.characters)) { await figma.loadFontAsync(t.fontName); t.characters = t.characters.replace('Обычное', 'не выбрано'); out.push(t.characters); }
    if (sec.name === 'Образец пола' && /^Образец покрытия пола/.test(t.characters)) { await figma.loadFontAsync(t.fontName); t.characters = FLOOR; out.push('cap ' + Math.round(t.width) + 'x' + Math.round(t.height)); }
  }
  const set = sec.findOne((n) => n.type === 'COMPONENT_SET');
  if (sec.name === 'Образец пола' && set && /^Образец покрытия пола/.test(set.description)) set.description = FLOOR;
}
const g = (k) => figma.root.getSharedPluginData('remlab', k);
const AF = Object.getPrototypeOf(async function () {}).constructor;
const chk = await new AF('P', g('check'))({ page: 'Образцы' });
return { out, counts: chk.counts };
