// design-02 П3а (T-20261103-06): копия base-p2a-props.js под книгу Desktop (id наборов Desktop). Исходник (П2а, T-20261103-03): свойства и ширина «по тексту» у СУЩЕСТВУЮЩИХ базовых наборов. Правка на месте:
// наборы и варианты не пересоздаются (id сохраняются). Повторный запуск безопасен (свойства ищутся по имени,
// уже привязанное пропускается). Одна страница на вызов: PAGE_ID + TABLE (наборы этой страницы).
//
// TABLE[setId]:
//   hug    — true: ширина варианта по тексту (primaryAxisSizingMode AUTO, текст WIDTH_AND_HEIGHT). Высота и поля — как были.
//            Только для кнопок/плашек, чья ширина на сайте задаётся текстом. Растянутые (капсулы 172, «Маленькая кнопка» 163,
//            ширина задаётся раскладкой) — false: hug дал бы −60…−100 px; в составных они будут FILL/FIXED.
//   layoutify — у варианта нет авто-раскладки (Ссылка): включить H-раскладку без полей, высота как была, текст к левому краю.
//   text   — { prop, def }: TEXT-свойство. Привязываются ТОЛЬКО тексты, равные def (свойство одно на набор, привязка
//            другого текста перепишет его — проверено в П1). Остальные варианты (EN и RU с другой надписью) — без привязки.
//   textLayer — какой текст варианта: 'first' (по умолчанию) или имя слоя.
// Цикл 2: таблицы по страницам (TABLES[PAGE_ID]); после привязки текста декор/шрифт/межстрочный возвращаются как были
// (в цикле 1 привязка сняла подчёркивание у RU «Заменить» 107:53 — восстановлено вручную 03.11).
const PAGE_ID = '7:98';
const TABLES = {
  '7:98': {                                                              // Кнопки (Desktop)
    '43:10': { hug: true },                                              // Основная кнопка (Текст — base-buttons-p3a.js)
    '43:21': { hug: true, text: { prop: 'Текст', def: 'Консультация' } },   // Капсула с заливкой — в Desktop уже по тексту (AUTO)
    '43:32': { hug: true, text: { prop: 'Текст', def: 'Ипотека' } },        // Капсула — в Desktop уже по тексту (AUTO)
    '43:60': { hug: true, layoutify: true, text: { prop: 'Текст', def: 'Заменить' } }, // Ссылка
    '43:79': { hug: false, text: { prop: 'Текст', def: 'Заменить' } },      // Маленькая кнопка — растянута (сетка 2 колонки), фикс.
    '43:98': { hug: true, text: { prop: 'Текст', def: 'Подходящие по размеру' } }, // Чип-фильтр
  },
  '7:2': {                                                               // Плашки
    '43:169': { hug: true, text: { prop: 'Текст', def: 'по размеру' } },    // Метка «по размеру»
    '43:180': { hug: true, text: { prop: 'Текст', def: 'Изменено вами' } }, // Метка состояния расстановки
  },
  '9:77': {                                                              // Образцы: кружок без текста; образец пола — ширина = плитка
    '39:43': { hug: false, text: { prop: 'Подпись', def: 'в цене' } },
  },
  '9:108': {                                                             // Вкладки стилей: вкладка по тексту
    '35:73': { hug: true, text: { prop: 'Текст', def: 'Сканди' } },
  },
  '9:122': {                                                             // Уведомление: карточка фикс.; текст «только текст»
    '36:22': { hug: false, text: { prop: 'Текст', def: 'Заменено: диван · +4 712 ₽' } },
  },
};
const TABLE = TABLES[PAGE_ID];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = { widths: [], props: {}, bound: [], unbound: [], mutated: [] };
const propKey = (set, name) => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === name);
async function loadFonts(nodes) {
  const fs = new Map();
  for (const t of nodes) for (const s of t.getStyledTextSegments(['fontName'])) fs.set(JSON.stringify(s.fontName), s.fontName);
  await Promise.all([...fs.values()].map(f => figma.loadFontAsync(f)));
}
const textOf = (v, layer) => layer && layer !== 'first' ? v.findOne(n => n.type === 'TEXT' && n.name === layer) : v.findAll(n => n.type === 'TEXT')[0];

for (const [sid, cfg] of Object.entries(TABLE)) {
  const set = await figma.getNodeByIdAsync(sid);
  if (!set || set.type !== 'COMPONENT_SET') throw new Error('нет набора ' + sid);
  const setW = set.width, setH = set.height;
  for (const v of set.children) {
    const w0 = v.width, h0 = v.height;
    const t = textOf(v, cfg.textLayer);
    if (cfg.layoutify && (!v.layoutMode || v.layoutMode === 'NONE')) {
      if (t) await loadFonts([t]);
      const tx = t ? t.x : 0, ty = t ? t.y : 0;
      v.layoutMode = 'HORIZONTAL';
      v.paddingLeft = tx; v.paddingRight = 0; v.paddingTop = ty; v.paddingBottom = 0; v.itemSpacing = 0;
      v.primaryAxisAlignItems = 'MIN'; v.counterAxisAlignItems = 'MIN';
      v.counterAxisSizingMode = 'FIXED';
      v.resize(v.width, h0);
      out.mutated.push(v.id);
    }
    if (cfg.hug && v.layoutMode === 'HORIZONTAL') {
      if (t && t.textAutoResize !== 'WIDTH_AND_HEIGHT') { await loadFonts([t]); t.textAutoResize = 'WIDTH_AND_HEIGHT'; out.mutated.push(t.id); }
      if (t && t.layoutSizingHorizontal !== 'HUG') t.layoutSizingHorizontal = 'HUG';
      if (v.primaryAxisSizingMode !== 'AUTO') { v.primaryAxisSizingMode = 'AUTO'; out.mutated.push(v.id); }
      if (Math.abs(v.height - h0) > 0.01) v.resize(v.width, h0);
      // П3а: в Desktop текст Inter уже, чем на сайте → hug сужал плашки/ссылку на 2–5 px. Чтобы вид не менялся,
      // сужение не допускаем: minWidth = прежняя ширина (рост по тексту остаётся). Расширение (+1…+11) — как в Mobile.
      if (v.width < w0 - 0.01) { v.minWidth = w0; if (cfg.layoutify) v.primaryAxisAlignItems = 'CENTER'; out.minWidth = (out.minWidth || []).concat(v.id + ' ' + w0); }
    }
    if (Math.abs(v.width - w0) > 0.01 || Math.abs(v.height - h0) > 0.01) out.widths.push({ set: sid, v: v.id, name: v.name, txt: t && t.characters, w0, w1: +v.width.toFixed(2), dw: +(v.width - w0).toFixed(2), h0, h1: v.height });
  }
  if (cfg.text) {
    let key = propKey(set, cfg.text.prop);
    if (!key) key = set.addComponentProperty(cfg.text.prop, 'TEXT', cfg.text.def);
    out.props[sid + ' ' + cfg.text.prop] = key;
    for (const v of set.children) {
      const t = textOf(v, cfg.textLayer); if (!t) continue;
      if (t.componentPropertyReferences && t.componentPropertyReferences.characters === key) { out.bound.push(v.id + ' (уже)'); continue; }
      if (t.characters !== cfg.text.def) { out.unbound.push(sid + ' ' + v.name + ' «' + t.characters + '»'); continue; }
      await loadFonts([t]);
      const st = { deco: t.textDecoration, font: t.fontName, size: t.fontSize, lh: t.lineHeight, ls: t.letterSpacing, fills: t.fills, tcase: t.textCase };
      t.componentPropertyReferences = Object.assign({}, t.componentPropertyReferences || {}, { characters: key });
      const fixed = [];
      if (t.textDecoration !== st.deco) { t.textDecoration = st.deco; fixed.push('deco'); }
      if (JSON.stringify(t.fontName) !== JSON.stringify(st.font)) { t.fontName = st.font; fixed.push('font'); }
      if (t.fontSize !== st.size) { t.fontSize = st.size; fixed.push('size'); }
      if (JSON.stringify(t.lineHeight) !== JSON.stringify(st.lh)) { t.lineHeight = st.lh; fixed.push('lh'); }
      if (JSON.stringify(t.letterSpacing) !== JSON.stringify(st.ls)) { t.letterSpacing = st.ls; fixed.push('ls'); }
      if (JSON.stringify(t.fills) !== JSON.stringify(st.fills)) { t.fills = st.fills; fixed.push('fills'); }
      if (t.textCase !== st.tcase) { t.textCase = st.tcase; fixed.push('case'); }
      if (fixed.length) out.restoredStyle = (out.restoredStyle || []).concat(t.id + ':' + fixed.join(','));
      out.bound.push(v.id); out.mutated.push(t.id);
    }
  }
  if (set.width !== setW || set.height !== setH) out.mutated.push(set.id + ' size ' + setW + 'x' + setH + '→' + set.width + 'x' + set.height);
}
return out;
