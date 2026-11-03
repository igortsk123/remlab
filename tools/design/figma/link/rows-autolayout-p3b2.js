// design-02 П3б2 (T-20261103-09): перевод вариантов «Шторка/Строка предмета» 26:165 книги Desktop на авто-раскладку
// (id сохраняются, вид — 0 px). Образец — rows-autolayout-p2b2.js (Mobile, принят). Зачем: строки боковой панели
// (48:1082 и 48:764 на «Окне расстановки», 66 шт., ширина 373, цена 35–81) лягут на экземпляр только с авто-раскладкой —
// слои внутри экземпляра нельзя двигать и тянуть.
// Отличия от Mobile: цена стоит не вплотную к колонке — зазор колонка→цена (34 у обычной строки, 10 у «выбрано»)
// задаётся полем слева у «Цена»; b / span / span.sws шириной с колонку — «заполнить» (тянутся вместе с колонкой).
// Устройство: строка VERTICAL (поля: сверху = div.t.y, слева/справа/снизу — по старому) → «Верх» HORIZONTAL (по верху,
// шаг = зазор фото→колонка): «Фото» (поле сверху) · div.t (FILL, VERTICAL, шаг = зазор b→span) · «Цена» (поля сверху/слева)
// · span.acts (FILL). span.sws: поле сверху добирает зазор до кружков. Плюс BOOLEAN «Образцы цвета» (вкл.), «Счётчик +N»
// (выкл.), «Кружок 4», «Кружок 5» (выкл.) — 2 скрытых кружка и скрытый «+N» (92:77 RU / 92:79 EN) в span.sws.
// Скрытые в главном слои в экземпляре недоступны API (урок Mobile 03.11) — поэтому кружки 4/5 на своих BOOLEAN.
// Неровное свойство «Цвета» (было только у 2 из 6): остальным вариантам дописано «Цвета=без выбора цвета» (id те же).
// Проверка внутри: абсолютные рамки всех прежних слоёв до/после (допуск 0.01 px).
const SET = '26:165';
const ONLY = null; // первый прогон 03.11: ['26:91'], затем null
const page = await figma.getNodeByIdAsync('9:64');
await figma.setCurrentPageAsync(page);
const tag = n => n.getSharedPluginData('remlab', 'css');
const abs = n => { const t = n.absoluteTransform; return [t[0][2], t[1][2], n.width, n.height]; };
const set = await figma.getNodeByIdAsync(SET);
const key = nm => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === nm);
const kSw = key('Образцы цвета') || set.addComponentProperty('Образцы цвета', 'BOOLEAN', true);
const kN = key('Счётчик +N') || set.addComponentProperty('Счётчик +N', 'BOOLEAN', false);
const k4 = key('Кружок 4') || set.addComponentProperty('Кружок 4', 'BOOLEAN', false);
const k5 = key('Кружок 5') || set.addComponentProperty('Кружок 5', 'BOOLEAN', false);
const mk = (name, mode) => { const f = figma.createFrame(); f.name = name; f.fills = []; f.clipsContent = false; f.layoutMode = mode;
  f.primaryAxisSizingMode = 'AUTO'; f.counterAxisSizingMode = 'AUTO'; f.itemSpacing = 0; return f; };
const res = {};
for (const v of set.children) {
  if (ONLY && !ONLY.includes(v.id)) continue;
  if (v.layoutMode !== 'NONE') { res[v.id] = 'уже авто'; continue; }
  const before = new Map([[v.id, abs(v)]]); v.findAll(() => true).forEach(n => before.set(n.id, abs(n)));
  const [img, dt, dp, acts] = v.children;
  if (!/^img/.test(tag(img)) || tag(dt) !== 'div.t' || tag(dp) !== 'div.p' || tag(acts) !== 'span.acts') { res[v.id] = 'не та структура'; continue; }
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  const hs = dt.x - (img.x + img.width);
  const g = { top: dt.y, l: img.x, r: v.width - (acts.x + acts.width), b: v.height - (acts.y + acts.height), gap: acts.y - (dt.y + dt.height),
    ip: img.y - dt.y, pp: dp.y - dt.y, hs, pl: dp.x - (dt.x + dt.width) - hs };
  if (Math.max(img.y + img.height, dp.y + dp.height) > dt.y + dt.height + 0.01) { res[v.id] = 'колонка не самая высокая'; continue; }
  const sws = dt.children.find(c => tag(c) === 'span.sws');
  if (dt.layoutMode === 'NONE') {
    const [b, sp] = dt.children;
    const s1 = sp.y - (b.y + b.height);
    const s2 = sws ? sws.y - (sp.y + sp.height) : 0;
    dt.layoutMode = 'VERTICAL'; dt.itemSpacing = s1; dt.primaryAxisSizingMode = 'AUTO'; dt.counterAxisSizingMode = 'FIXED';
    if (sws) { const h = sws.height; sws.paddingTop = sws.paddingTop + (s2 - s1); sws.resize(sws.width, h + (s2 - s1)); }
  }
  const top = mk('Верх', 'HORIZONTAL'); top.itemSpacing = g.hs; top.counterAxisAlignItems = 'MIN';
  const fb = mk('Фото', 'VERTICAL'); fb.paddingTop = g.ip;
  const pb = mk('Цена', 'VERTICAL'); pb.paddingTop = g.pp; pb.paddingLeft = g.pl;
  v.insertChild(0, top);
  top.appendChild(fb); fb.appendChild(img);
  top.appendChild(dt);
  top.appendChild(pb); pb.appendChild(dp);
  v.layoutMode = 'VERTICAL'; v.primaryAxisSizingMode = 'AUTO'; v.counterAxisSizingMode = 'FIXED';
  v.strokesIncludedInLayout = false;
  v.paddingTop = g.top; v.paddingLeft = g.l; v.paddingRight = g.r; v.paddingBottom = g.b; v.itemSpacing = g.gap;
  top.layoutSizingHorizontal = 'FILL'; acts.layoutSizingHorizontal = 'FILL'; dt.layoutSizingHorizontal = 'FILL';
  for (const c of dt.children) if (Math.abs(c.width - dt.width) < 0.01 && c.layoutPositioning !== 'ABSOLUTE') c.layoutSizingHorizontal = 'FILL';
  if (sws) {
    sws.componentPropertyReferences = { visible: kSw };
    const swId = lang === 'EN' ? '39:15' : '39:6';
    for (const k of [k4, k5]) { const c = (await figma.getNodeByIdAsync(swId)).createInstance();
      sws.appendChild(c); c.name = 'Кружок цвета'; c.setSharedPluginData('remlab', 'css', 'button.sw'); c.visible = false;
      c.componentPropertyReferences = { visible: k }; }
    const n = (await figma.getNodeByIdAsync(lang === 'EN' ? '92:79' : '92:77')).createInstance();
    sws.appendChild(n); n.name = 'Счётчик +N'; n.setSharedPluginData('remlab', 'css', 'button.swn'); n.visible = false;
    n.componentPropertyReferences = { visible: kN };
  }
  const bad = [];
  for (const [id, a] of before) { const n = await figma.getNodeByIdAsync(id); const b = abs(n);
    const d = Math.max(...a.map((x, i) => Math.abs(x - b[i]))); if (d > 0.01) bad.push(id + ' ' + (tag(n) || n.type) + ' ' + a.map(x => +x.toFixed(2)) + '→' + b.map(x => +x.toFixed(2))); }
  res[v.id] = { g, bad: bad.slice(0, 12), nBad: bad.length };
}
// неровное свойство «Цвета»
if (!ONLY) for (const v of set.children) if (!/Цвета=/.test(v.name)) v.name = v.name + ', Цвета=без выбора цвета';
res.names = set.children.map(v => v.id + ' ' + v.name);
res.props = Object.keys(set.componentPropertyDefinitions);
return res;
