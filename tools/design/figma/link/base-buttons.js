// design-02 (T-20261103-02): базовые кнопки — свойства и новые варианты. Правка НА МЕСТЕ, существующие варианты
// не удаляются и не переименовываются (их id сохраняются). Повторный запуск безопасен (идемпотентно: свойства и
// варианты ищутся по имени, второй раз не создаются).
// Страница одна на вызов: PAGE_ID. Книга Mobile: «Кнопки» = 5:2.
//
// ТАБЛИЦА (правится под книгу/страницу):
//   text   — набор, свойство TEXT «Текст» → надпись. Привязываются ТОЛЬКО варианты, где надпись = default
//            (TEXT-свойство одно на весь набор: привязка варианта с другой надписью перепишет её — проверено 03.11
//            на временном наборе; поэтому EN-варианты «Open» остаются со своей надписью, без привязки).
//   bool   — набор, свойство BOOLEAN → видимость слоя по имени (во всех вариантах, где слой есть).
//   addVariants — новые варианты-клоны: from → имя, заливки по переменным (имя переменной), подпись под вариантом.
const PAGE_ID = '5:2';
const TABLE = {
  text: [{ set: '107:10', prop: 'Текст', def: 'Открыть' }],
  bool: [{ set: '107:49', prop: 'Значок', layer: 'Значок', def: true }],
  addVariants: [
    { set: '107:10', from: '107:4', name: 'Язык=RU, Состояние=Контурная', x: 232, y: 50,
      frameFill: 'Бренд/Мягкий фон', textFill: 'Бренд/Основной', caption: { from: '107:5' } },
    { set: '107:10', from: '107:8', name: 'Язык=EN, Состояние=Контурная', x: 232, y: 156,
      frameFill: 'Бренд/Мягкий фон', textFill: 'Бренд/Основной', caption: { from: '107:9' } },
  ],
};

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const log = { created: [], mutated: [], props: {}, skipped: [] };
const allVars = await figma.variables.getLocalVariablesAsync('COLOR');
const varByName = n => { const v = allVars.find(x => x.name === n); if (!v) throw new Error('нет переменной ' + n); return v; };
const boundPaint = (n) => figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', varByName(n));
const propKey = (set, name) => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === name);
const firstText = n => n.findAll(t => t.type === 'TEXT')[0];
async function loadFonts(nodes) {
  const fs = new Map();
  for (const t of nodes) for (const s of t.getStyledTextSegments(['fontName'])) fs.set(JSON.stringify(s.fontName), s.fontName);
  await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f)));
}

// 1) новые варианты (до TEXT-привязки, чтобы клон RU тоже привязался)
for (const a of TABLE.addVariants) {
  const set = await figma.getNodeByIdAsync(a.set);
  let v = set.children.find(c => c.name === a.name);
  if (v) { log.skipped.push('variant exists ' + a.name + ' ' + v.id); continue; }
  const src = await figma.getNodeByIdAsync(a.from);
  await loadFonts(src.findAll(t => t.type === 'TEXT'));
  v = src.clone();
  set.appendChild(v);
  v.name = a.name; v.x = a.x; v.y = a.y;
  v.fills = [boundPaint(a.frameFill)];
  const t = firstText(v); if (t) t.fills = [boundPaint(a.textFill)];
  log.created.push(v.id);
  if (a.caption) {
    const c0 = await figma.getNodeByIdAsync(a.caption.from);
    await loadFonts([c0]);
    const c = c0.clone(); c0.parent.appendChild(c);
    c.characters = c0.characters.replace(/Обычное/g, 'Контурная');
    c.x = c0.x + (a.x - src.x); c.y = c0.y + (a.y - src.y);
    log.created.push(c.id);
  }
  // растянуть набор по детям (+24 справа/снизу, как у сборщика)
  let mx = 0, my = 0; for (const ch of set.children) { mx = Math.max(mx, ch.x + ch.width); my = Math.max(my, ch.y + ch.height); }
  set.resizeWithoutConstraints(Math.max(set.width, mx + 24), Math.max(set.height, my + 24));
  log.mutated.push(set.id);
}

// 2) TEXT-свойства
for (const r of TABLE.text) {
  const set = await figma.getNodeByIdAsync(r.set);
  let key = propKey(set, r.prop);
  if (!key) { key = set.addComponentProperty(r.prop, 'TEXT', r.def); }
  log.props[r.set + ' ' + r.prop] = key;
  for (const v of set.children) {
    const t = firstText(v); if (!t) continue;
    if (t.componentPropertyReferences && t.componentPropertyReferences.characters === key) continue;
    if (t.characters !== r.def) { log.skipped.push('text not linked (другая надпись) ' + v.name + ' «' + t.characters + '»'); continue; }
    await loadFonts([t]);
    t.componentPropertyReferences = Object.assign({}, t.componentPropertyReferences || {}, { characters: key });
    log.mutated.push(t.id);
  }
}

// 3) BOOLEAN-свойства
for (const r of TABLE.bool) {
  const set = await figma.getNodeByIdAsync(r.set);
  let key = propKey(set, r.prop);
  if (!key) key = set.addComponentProperty(r.prop, 'BOOLEAN', r.def);
  log.props[r.set + ' ' + r.prop] = key;
  for (const v of set.children) {
    const l = v.findOne(n => n.name === r.layer); if (!l) { log.skipped.push('no layer ' + r.layer + ' in ' + v.name); continue; }
    l.componentPropertyReferences = Object.assign({}, l.componentPropertyReferences || {}, { visible: key });
    log.mutated.push(l.id);
  }
}

// итог
const sum = {};
for (const id of [...new Set([...TABLE.text.map(r => r.set), ...TABLE.bool.map(r => r.set)])]) {
  const s = await figma.getNodeByIdAsync(id);
  sum[id] = { name: s.name, w: s.width, h: s.height, props: Object.keys(s.componentPropertyDefinitions),
    variants: s.children.map(v => ({ id: v.id, name: v.name, x: v.x, y: v.y, w: v.width, h: v.height, txt: (firstText(v) || {}).characters })) };
}
return { log, sum };
