// design-02 П2б2 (T-20261103-05/2): перевод вариантов «Шторка/Строка предмета» 76:187 на авто-раскладку (id сохраняются,
// вид — 0 px). Решение ведущего: вариант А. Зачем: строки шторки 77:965 (347 шир., высоты 125/126/148/158, цена шириной 33–78)
// не ложатся на экземпляр с абсолютной раскладкой — слои внутри экземпляра нельзя двигать и тянуть.
// Новое устройство варианта: строка VERTICAL (поля сверху 8, снизу по старому, слева/справа = отступ img/acts) →
//   «Верх» HORIZONTAL (шаг 10, по верху): «Фото» (поле сверху = смещение img) · div.t (FILL) · «Цена» (поле сверху = смещение цены)
//   · span.acts (FILL). div.t (кроме hl) — VERTICAL «по содержимому», шаг = зазор b→span (2.2), у span.sws поле сверху добирает
//   старый зазор до кружков. В экземпляре смещения задаются полями «Фото»/«Цена» и шагами — их переопределять можно.
// Плюс: BOOLEAN «Образцы цвета» (вкл.) на span.sws; в span.sws 2 скрытых лишних кружка (108:6/108:15) и скрытый «+N»
// (221:89/221:91) с BOOLEAN «Счётчик +N» (выкл.). Проверка внутри: абсолютные рамки всех прежних слоёв до/после.
const SET = '76:187';
const page = await figma.getNodeByIdAsync('15:46');
await figma.setCurrentPageAsync(page);
const tag = n => n.getSharedPluginData('remlab', 'css');
const abs = n => { const t = n.absoluteTransform; return [t[0][2], t[1][2], n.width, n.height]; };
const set = await figma.getNodeByIdAsync(SET);
const key = nm => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === nm);
const kSw = key('Образцы цвета') || set.addComponentProperty('Образцы цвета', 'BOOLEAN', true);
const kN = key('Счётчик +N') || set.addComponentProperty('Счётчик +N', 'BOOLEAN', false);
const mk = (name, mode) => { const f = figma.createFrame(); f.name = name; f.fills = []; f.clipsContent = false; f.layoutMode = mode;
  f.primaryAxisSizingMode = 'AUTO'; f.counterAxisSizingMode = 'AUTO'; f.itemSpacing = 0; return f; };
const res = {};
for (const v of set.children) {
  if (v.layoutMode !== 'NONE') { res[v.id] = 'уже авто'; continue; }
  const before = new Map([[v.id, abs(v)]]); v.findAll(() => true).forEach(n => before.set(n.id, abs(n)));
  const [img, dt, dp, acts] = v.children;
  if (!/^img/.test(tag(img)) || tag(dt) !== 'div.t' || tag(dp) !== 'div.p' || tag(acts) !== 'span.acts') { res[v.id] = 'не та структура'; continue; }
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  const g = { top: dt.y, l: img.x, r: v.width - (acts.x + acts.width), b: v.height - (acts.y + acts.height), gap: acts.y - (dt.y + dt.height),
    ip: img.y - dt.y, pp: dp.y - dt.y, hs: dt.x - (img.x + img.width), H: v.height };
  // div.t: вертикальная раскладка «по содержимому»
  const sws = dt.children.find(c => tag(c) === 'span.sws');
  if (dt.layoutMode === 'NONE') {
    const [b, sp] = dt.children;
    const s1 = sp.y - (b.y + b.height);
    const s2 = sws ? sws.y - (sp.y + sp.height) : 0;
    dt.layoutMode = 'VERTICAL'; dt.itemSpacing = s1; dt.primaryAxisSizingMode = 'AUTO'; dt.counterAxisSizingMode = 'FIXED';
    if (sws) { const h = sws.height; sws.paddingTop = s2 - s1; sws.resize(sws.width, h + sws.paddingTop); }
  }
  const top = mk('Верх', 'HORIZONTAL'); top.itemSpacing = g.hs; top.counterAxisAlignItems = 'MIN';
  const fb = mk('Фото', 'VERTICAL'); fb.paddingTop = g.ip;
  const pb = mk('Цена', 'VERTICAL'); pb.paddingTop = g.pp;
  v.insertChild(0, top);
  top.appendChild(fb); fb.appendChild(img);
  top.appendChild(dt);
  top.appendChild(pb); pb.appendChild(dp);
  v.layoutMode = 'VERTICAL'; v.primaryAxisSizingMode = 'AUTO'; v.counterAxisSizingMode = 'FIXED';
  v.strokesIncludedInLayout = false; // верхняя линия строки (1 px) не должна сдвигать содержимое
  v.paddingTop = g.top; v.paddingLeft = g.l; v.paddingRight = g.r; v.paddingBottom = g.b; v.itemSpacing = g.gap;
  top.layoutSizingHorizontal = 'FILL'; acts.layoutSizingHorizontal = 'FILL'; dt.layoutSizingHorizontal = 'FILL';
  // образцы: BOOLEAN, лишние кружки и «+N» (скрыты)
  if (sws) {
    sws.componentPropertyReferences = { visible: kSw };
    for (let i = 0; i < 2; i++) { const c = (await figma.getNodeByIdAsync(lang === 'EN' ? '108:15' : '108:6')).createInstance();
      sws.appendChild(c); c.name = 'Кружок цвета'; c.setSharedPluginData('remlab', 'css', 'button.sw'); c.visible = false; }
    const n = (await figma.getNodeByIdAsync(lang === 'EN' ? '221:91' : '221:89')).createInstance();
    sws.appendChild(n); n.name = 'Счётчик +N'; n.setSharedPluginData('remlab', 'css', 'button.swn'); n.visible = false;
    n.componentPropertyReferences = { visible: kN };
  }
  // сверка рамок
  const bad = [];
  for (const [id, a] of before) { const n = await figma.getNodeByIdAsync(id); const b = abs(n);
    const d = Math.max(...a.map((x, i) => Math.abs(x - b[i]))); if (d > 0.01) bad.push(id + ' ' + (tag(n) || n.type) + ' ' + a.map(x => +x.toFixed(2)) + '→' + b.map(x => +x.toFixed(2))); }
  res[v.id] = { g, bad: bad.slice(0, 12), nBad: bad.length };
}
// Добавлено после пробы (03.11): слои, скрытые в главном компоненте, в экземпляре недоступны API → 4-й и 5-й кружки
// привязаны к своим BOOLEAN «Кружок 4» / «Кружок 5» (выкл.).
const k4 = key('Кружок 4') || set.addComponentProperty('Кружок 4', 'BOOLEAN', false);
const k5 = key('Кружок 5') || set.addComponentProperty('Кружок 5', 'BOOLEAN', false);
for (const v of set.children) {
  const sws = v.findOne(n => tag(n) === 'span.sws'); if (!sws) continue;
  sws.children[3].componentPropertyReferences = { visible: k4 };
  sws.children[4].componentPropertyReferences = { visible: k5 };
}
res.props = Object.keys(set.componentPropertyDefinitions);
return res;
