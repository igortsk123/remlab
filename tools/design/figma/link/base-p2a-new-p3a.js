// design-02 П3а (T-20261103-06): копия base-p2a-new.js под книгу Desktop («Кнопки» 7:98). Исходник — П2а цикл 2 (T-20261103-03/2): НОВЫЕ базовые на странице «Кнопки» (Mobile 5:2) + новые варианты в
// существующих «Ссылка» 43:60 и «Закрыть» 43:117 (Desktop). Вид каждого варианта копируется с узла-образца в составных
// (заливки с переменными, шрифт, поля, скругление) — образцы только читаются. Существующие варианты/наборы не
// пересоздаются (id целы). Повторный запуск безопасен: набор/вариант с тем же именем пропускается.
//
// Правила текста: TEXT-свойство одно на набор (одно значение по умолчанию), поэтому в НОВЫХ наборах все RU-варианты
// показывают одну надпись и привязаны к свойству; EN — своя надпись без привязки (как в П1/П2а-1). В существующей
// «Ссылке» новые варианты к «Тексту» («Заменить») не привязываются — иначе надпись перепишется.
const PAGE_ID = '7:98';
const START_Y = 4027, GAP = 120;          // секции ниже «Кнопок поверх 3D-кадра» (3550+357), шаг как у соседних
const DARK = { r: 68 / 255, g: 64 / 255, b: 60 / 255 }; // подложка набора, где белое на тёмном (как над 3D-кадром)

// Образцы — места использования в Desktop (размеры Desktop, не Mobile): «Диалог» 37:9/37:11, «Конструктор» 32:4,
// «Окно расстановки» 48:20/48:22 (31 px), 48:1143/48:1145 (30 px; «Во весь экран» 37:128/37:130 — тот же вид, растянут),
// 48:1160/48:1162, 48:119; «Во весь экран» 37:121/37:123/37:125; «Шторка» 26:63; «Уведомление» 36:8; «Шапка» 55:39.
// minFromSrc: hug не уже образца (minWidth = ширина образца): Inter в Figma уже шрифта сайта, без этого −2…−15 px.
const NEW_SETS = [
  { name: 'Кнопки/Кнопка', section: 'Кнопка', hug: true,
    what: 'Обычная кнопка сайта: 16,5 px, поля 20/12, высота 46, ширина по тексту (в диалоге растянута на половину ряда). Основная — «Сохранить», «Подтвердить», «Заменить»; обычная — «Готово», «В магазин», «Открыть» в избранном; тихая — «Отмена», «Изменить расстановку». Надпись — свойство «Текст».',
    text: { prop: 'Текст', ru: 'Сохранить', en: 'Save', bindEN: false },
    cols: [ { props: 'Вид=Основная', label: 'Основная', from: '37:9' }, { props: 'Вид=Обычная', label: 'Обычная', from: '32:4' }, { props: 'Вид=Тихая', label: 'Тихая', from: '37:11' } ] },
  { name: 'Кнопки/Переключатель', section: 'Переключатель', hug: true, dark: true,
    what: 'Сегменты на тёмной подложке: 31 px — «Фото / 3D / План» в окне расстановки; 30 px — ракурс камеры в окне и «Во весь экран» (там сегменты растянуты на равную ширину). Выбранный — белый, остальные — белый текст без заливки. Надпись — свойство «Текст».',
    text: { prop: 'Текст', ru: 'Со стороны двери', en: 'From the door', bindEN: false },
    cols: [ { props: 'Размер=31 px, Состояние=выбрано', label: '31 · выбрано', from: '48:22' }, { props: 'Размер=31 px, Состояние=не выбрано', label: '31 · не выбрано', from: '48:20' },
            { props: 'Размер=30 px, Состояние=выбрано', label: '30 · выбрано', from: '48:1143' }, { props: 'Размер=30 px, Состояние=не выбрано', label: '30 · не выбрано', from: '48:1145' } ] },
  { name: 'Кнопки/Отменить и повторить', section: 'Отменить и повторить', hug: false, dark: true,
    what: 'Круглые кнопки ↶ ↷ (34 px) над 3D-кадром окна расстановки. «Недоступно» — полупрозрачная: отменять или повторять нечего.',
    cols: [ { props: 'Действие=Отменить, Состояние=доступно', label: '↶ · доступно', from: '48:1160', opacity: 1 }, { props: 'Действие=Отменить, Состояние=недоступно', label: '↶ · недоступно', from: '48:1160', opacity: 0.35 },
            { props: 'Действие=Повторить, Состояние=доступно', label: '↷ · доступно', from: '48:1162', opacity: 1 }, { props: 'Действие=Повторить, Состояние=недоступно', label: '↷ · недоступно', from: '48:1162', opacity: 0.35 } ] },
  { name: 'Кнопки/Счётчик +N', section: 'Счётчик +N', hug: true, minFromSrc: true,
    what: 'Сколько ещё цветов у товара — «+4» рядом с кружками цвета в боковой панели и окне расстановки. Число — свойство «Число».',
    text: { prop: 'Число', ru: '+4', en: '+4', bindEN: true },
    cols: [ { props: 'Состояние=Обычное', label: 'Обычное', from: '48:119' } ] },
  { name: 'Кнопки/Стрелка листания', section: 'Стрелка листания', hug: false,
    what: 'Белые круглые стрелки ‹ › (44 px) по бокам кадра в режиме «Во весь экран».',
    cols: [ { props: 'Направление=влево', label: '‹ влево', from: '37:123' }, { props: 'Направление=вправо', label: '› вправо', from: '37:125' } ] },
];
// Новые варианты в существующих наборах: RU/EN-надписи — как в образце и его EN-близнеце (26:69, 36:18, 55:57, 37:138).
// 36:18 после связывания «Уведомления» удалён (стал экземпляром) — его ширина записана здесь.
const minSrcW = { '36:18': 62 };
const ADD_VARIANTS = [
  { set: '43:60', section: '43:61', hug: true, minFromSrc: true,
    whatAdd: ' Полужирная — «← Назад» в шторке; жирная — «Перейти →» в уведомлении; мелкая со стрелкой — «Подробнее ⌄» в шапке (стрелка — свойство «Стрелка»).',
    bool: { prop: 'Стрелка', layer: 1 },
    cols: [ { state: 'Полужирная', label: 'полужирная', from: '26:63', en: ['← Back'], enFrom: '26:69' },
            { state: 'Жирная', label: 'жирная', from: '36:8', en: ['Open →'], enFrom: '36:18' },
            { state: 'Мелкая со стрелкой', label: 'мелкая со стрелкой', from: '55:39', en: ['Details', '⌄'], enFrom: '55:57', bool: true } ] },
  { set: '43:117', section: '43:118', hug: false,
    whatAdd: ' Во весь экран — белая 42 px без рамки.',
    cols: [ { state: 'во весь экран', label: 'во весь экран', from: '37:121', en: ['×'] } ] },
];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = name => vars.find(v => v.name === name);
const out = { created: [], sets: {}, added: {}, props: {}, skipped: [], mutated: [] };
const loaded = new Set();
async function font(f) { const k = JSON.stringify(f); if (!loaded.has(k)) { await figma.loadFontAsync(f); loaded.add(k); } }
async function paints(ps) {
  const res = [];
  for (const p of ps) {
    const c = JSON.parse(JSON.stringify(p)); delete c.boundVariables;
    if (p.boundVariables && p.boundVariables.color) { const v = await figma.variables.getVariableByIdAsync(p.boundVariables.color.id); res.push(figma.variables.setBoundVariableForPaint(c, 'color', v)); }
    else res.push(c);
  }
  return res;
}
function copyPD(dst, src) { for (const k of src.getSharedPluginDataKeys('remlab')) dst.setSharedPluginData('remlab', k, src.getSharedPluginData('remlab', k)); }
async function copyText(src, chars) {
  const t = figma.createText();
  await font(src.fontName);
  t.fontName = src.fontName; t.characters = chars; t.fontSize = src.fontSize;
  t.lineHeight = src.lineHeight; t.letterSpacing = src.letterSpacing; t.textCase = src.textCase; t.textDecoration = src.textDecoration;
  t.textAlignHorizontal = src.textAlignHorizontal; t.textAlignVertical = src.textAlignVertical;
  t.fills = await paints(src.fills); t.opacity = src.opacity; t.name = src.name === src.characters ? chars : src.name;
  t.textAutoResize = 'WIDTH_AND_HEIGHT';
  copyPD(t, src);
  return t;
}
// Компонент по образцу-рамке: одна ступень детей (тексты). texts — надписи по порядку текстов образца.
async function makeVariant(srcId, name, texts, hug, opacity, minFromSrc, minSrcId) {
  const src = await figma.getNodeByIdAsync(srcId);
  if (!src || src.type !== 'FRAME') throw new Error('образец не рамка: ' + srcId);
  const c = figma.createComponent();
  c.name = name;
  c.layoutMode = src.layoutMode;
  c.paddingLeft = src.paddingLeft; c.paddingRight = src.paddingRight; c.paddingTop = src.paddingTop; c.paddingBottom = src.paddingBottom;
  c.itemSpacing = src.itemSpacing; c.primaryAxisAlignItems = src.primaryAxisAlignItems; c.counterAxisAlignItems = src.counterAxisAlignItems;
  c.fills = await paints(src.fills); c.strokes = await paints(src.strokes); c.strokeWeight = src.strokeWeight; c.strokeAlign = src.strokeAlign;
  if (src.cornerRadius === figma.mixed) { c.topLeftRadius = src.topLeftRadius; c.topRightRadius = src.topRightRadius; c.bottomLeftRadius = src.bottomLeftRadius; c.bottomRightRadius = src.bottomRightRadius; }
  else c.cornerRadius = src.cornerRadius;
  c.effects = JSON.parse(JSON.stringify(src.effects)); c.clipsContent = src.clipsContent;
  c.opacity = opacity !== undefined ? opacity : src.opacity;
  c.resize(src.width, src.height);
  const srcTexts = src.children.filter(n => n.type === 'TEXT');
  if (srcTexts.length !== src.children.length) throw new Error('у образца не только тексты: ' + srcId);
  const made = [];
  for (let i = 0; i < srcTexts.length; i++) { const t = await copyText(srcTexts[i], texts[i] !== undefined ? texts[i] : srcTexts[i].characters); c.appendChild(t); t.layoutSizingHorizontal = 'HUG'; t.layoutSizingVertical = 'HUG'; made.push(t); }
  if (hug) { c.primaryAxisSizingMode = 'AUTO'; c.counterAxisSizingMode = 'FIXED'; c.resize(c.width, src.height); c.primaryAxisSizingMode = 'AUTO'; }
  else { c.primaryAxisSizingMode = 'FIXED'; c.counterAxisSizingMode = 'FIXED'; c.resize(src.width, src.height); }
  // minWidth — ширина места использования; для EN — ширина EN-близнеца (minSrcId), не RU-образца (иначе EN «Open →» 62 стал 91)
  const minW = minSrcId ? ((await figma.getNodeByIdAsync(minSrcId)) || {}).width || minSrcW[minSrcId] : src.width;
  if (hug && minFromSrc && minW && c.width < minW - 0.01) c.minWidth = minW;
  copyPD(c, src);
  return { c, texts: made, src };
}
async function label(parent, x, y, txt, dark) {
  await font({ family: 'Inter', style: 'Medium' });
  const t = figma.createText();
  t.fontName = { family: 'Inter', style: 'Medium' }; t.fontSize = 12; t.characters = txt; t.name = 'Подпись варианта';
  t.fills = [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', V(dark ? 'Фон/Карточка' : 'Текст/Второстепенный'))];
  parent.appendChild(t); t.x = x; t.y = y;
  if (t.width > 180) { t.textAutoResize = 'HEIGHT'; t.resize(180, t.height); }
  out.created.push(t.id);
  return t;
}
async function whatText(parent, txt, w) {
  await font({ family: 'Inter', style: 'Regular' });
  const t = figma.createText();
  t.fontName = { family: 'Inter', style: 'Regular' }; t.fontSize = 14; t.characters = txt; t.name = 'Что это';
  t.fills = [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', V('Текст/Второстепенный'))];
  parent.appendChild(t); t.x = 40; t.y = 40;
  t.textAutoResize = 'HEIGHT'; t.resize(w, t.height);
  out.created.push(t.id);
  return t;
}
function fitSection(sec, set, what) {
  const w = Math.max(set.x + set.width, what.x + what.width) + 40, h = set.y + set.height + 40;
  sec.resizeWithoutConstraints(w, h);
}

// ---- новые наборы ----
let y = START_Y;
const existing = page.findAllWithCriteria({ types: ['COMPONENT_SET'] });
for (const spec of NEW_SETS) {
  const have = existing.find(s => s.name === spec.name);
  if (have) { out.skipped.push(spec.name + ' есть: ' + have.id); y = have.parent.y + have.parent.height + GAP; continue; }
  const comps = [], grid = [];
  for (const [li, lang] of ['RU', 'EN'].entries()) {
    for (const [ci, col] of spec.cols.entries()) {
      const src = await figma.getNodeByIdAsync(col.from);
      const nT = src.children.filter(n => n.type === 'TEXT').length;
      const texts = spec.text ? [lang === 'RU' ? spec.text.ru : spec.text.en] : Array(nT).fill(undefined);
      const m = await makeVariant(col.from, 'Язык=' + lang + ', ' + col.props, texts, spec.hug, col.opacity, spec.minFromSrc);
      comps.push(m.c); grid.push({ c: m.c, li, ci, lang, col, t: m.texts[0] });
    }
  }
  const sec = figma.createSection();
  page.appendChild(sec);
  sec.name = spec.section; sec.x = 0; sec.y = y;
  sec.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
  const set = figma.combineAsVariants(comps, sec);
  set.name = spec.name; set.description = spec.what; set.cornerRadius = 5; set.clipsContent = true;
  if (spec.dark) set.fills = [{ type: 'SOLID', color: DARK }];
  const maxW = Math.max(...comps.map(c => c.width)), maxH = Math.max(...comps.map(c => c.height));
  const colStep = Math.max(208, Math.ceil(maxW) + 48), rowStep = Math.ceil(maxH) + 66;
  for (const g of grid) { g.c.x = 24 + g.ci * colStep; g.c.y = 50 + g.li * rowStep; }
  set.resizeWithoutConstraints(spec.cols.length * colStep, 50 + rowStep + Math.ceil(maxH) + 24);
  const what = await whatText(sec, spec.what, Math.max(set.width, 640));
  set.x = 40; set.y = Math.round(what.y + what.height + 16);
  for (const g of grid) await label(sec, set.x + g.c.x, set.y + g.c.y - 26, g.lang + ' · ' + g.col.label, !!spec.dark);
  // свойство текста
  if (spec.text) {
    const key = set.addComponentProperty(spec.text.prop, 'TEXT', spec.text.ru);
    out.props[spec.name] = key;
    for (const g of grid) if (g.lang === 'RU' || spec.text.bindEN) { g.t.componentPropertyReferences = { characters: key }; }
  }
  fitSection(sec, set, what);
  out.sets[spec.name] = { section: sec.id, set: set.id, variants: grid.map(g => g.c.id + ' ' + g.c.name + ' ' + Math.round(g.c.width) + 'x' + Math.round(g.c.height)) };
  y = sec.y + sec.height + GAP;
}

// ---- новые варианты в существующих наборах ----
for (const spec of ADD_VARIANTS) {
  const set = await figma.getNodeByIdAsync(spec.set), sec = await figma.getNodeByIdAsync(spec.section);
  const what = sec.children.find(n => n.type === 'TEXT' && n.name === 'Что это');
  const rows = { RU: set.children.find(v => /Язык=RU/.test(v.name)).y, EN: set.children.find(v => /Язык=EN/.test(v.name)).y };
  const colStep = 208;
  let col0 = Math.max(...set.children.map(v => Math.round((v.x - 24) / colStep))) + 1;
  const done = [];
  let boolKey = null;
  if (spec.bool) { boolKey = Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === spec.bool.prop) || set.addComponentProperty(spec.bool.prop, 'BOOLEAN', true); out.props[set.name + ' ' + spec.bool.prop] = boolKey; }
  for (const col of spec.cols) {
    for (const lang of ['RU', 'EN']) {
      const name = 'Язык=' + lang + ', Состояние=' + col.state;
      if (set.children.find(v => v.name === name)) { out.skipped.push(set.name + ' ' + name + ' есть'); continue; }
      const m = await makeVariant(col.from, name, lang === 'EN' ? col.en : [], spec.hug, undefined, spec.minFromSrc, lang === 'EN' ? col.enFrom : undefined);
      set.appendChild(m.c);
      m.c.x = 24 + col0 * colStep; m.c.y = rows[lang];
      if (col.bool && boolKey) m.texts[spec.bool.layer].componentPropertyReferences = { visible: boolKey };
      await label(sec, set.x + m.c.x, set.y + m.c.y - 26, lang + ' · ' + col.label, false);
      done.push(m.c.id + ' ' + name + ' ' + Math.round(m.c.width) + 'x' + Math.round(m.c.height));
    }
    col0++;
  }
  if (done.length) {
    set.resizeWithoutConstraints(Math.max(set.width, col0 * colStep), set.height);
    if (what && !what.characters.includes(spec.whatAdd.trim().slice(0, 12))) {
      await font(what.fontName); what.characters = what.characters + spec.whatAdd; out.mutated.push(what.id);
      set.description = (set.description || '') + spec.whatAdd;
    }
    fitSection(sec, set, what);
    out.mutated.push(set.id, sec.id);
  }
  out.added[spec.set] = done;
}
out.props43_60 = Object.keys((await figma.getNodeByIdAsync('43:60')).componentPropertyDefinitions);
return out;
