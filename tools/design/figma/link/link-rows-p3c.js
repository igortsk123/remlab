// design-02 П3в (T-20261103-10, Desktop): связывание строк боковой панели (рамки div.row) на странице «Окно расстановки» 9:134
// с «Шторка/Строка предмета» 26:165 (переведена на авто-раскладку в П3б2). Копия link-rows-p2b2.js (Mobile, принят) с отличиями:
//  - строки лежат в авто-раскладке (div.pinlist): ширина/высота экземпляра — по старой строке (ширина FIXED, высота — по
//    содержимому; сверка требует ту же высоту);
//  - вариант: есть кружки (span.sws) → «с выбором цвета» 26:107 RU / 26:151 EN, нет → «без выбора цвета» 26:91 / 26:135
//    + BOOLEAN «Образцы цвета» = выкл.;
//  - «Цена»: зазор колонка→цена у старых строк 10 (в базе 34 = шаг 10 + поле слева 24) → поле слева «Цены» = 0;
//    цена прижата влево (LEFT) → текст «по ширине» + поле справа «Цены» до старой ширины (как в Mobile).
// Проверка: каждая пара слоёв (положение от строки и размер) ≤ TOL px, иначе экземпляр удаляется, строка остаётся рамкой
// («лучше честно оставить, чем сдвинуть»). Старая рамка удаляется только после проверки. Повторный запуск безопасен.
// Запуск: CFG = { owner: '48:1082' | '48:764', dry: true|false, only?: [id строки] }; одна страница (9:134).
const CFG = { owner: '48:1082', dry: true };
const TOL = 1.5;
const page = await figma.getNodeByIdAsync('9:134');
await figma.setCurrentPageAsync(page);
const J = x => JSON.stringify(x);
const tag = n => n.getSharedPluginData('remlab', 'css');
const set = await figma.getNodeByIdAsync('26:165');
const key = nm => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === nm);
const kSw = key('Образцы цвета'), kN = key('Счётчик +N'), k4 = key('Кружок 4'), k5 = key('Кружок 5');
const VAR = { RU: { sw: '26:107', no: '26:91' }, EN: { sw: '26:151', no: '26:135' } };
const SW = { RU: { on: '39:9', off: '39:6' }, EN: { on: '39:18', off: '39:15' } };
const VIS = ['fills', 'strokes', 'effects', 'opacity', 'cornerRadius', 'strokeWeight', 'strokeAlign', 'dashPattern'];
const TXT = ['fontSize', 'fontName', 'textDecoration', 'letterSpacing', 'lineHeight', 'textAlignHorizontal', 'textCase'];
const rep = { linked: 0, kept: [], ovr: {}, maxD: 0, err: [], list: [], ids: [] };
const cnt = k => { rep.ovr[k] = (rep.ovr[k] || 0) + 1; };
const get = id => figma.getNodeByIdAsync(id);
async function fonts(t) { const m = new Map(); for (const g of t.getStyledTextSegments(['fontName'])) m.set(J(g.fontName), g.fontName); await Promise.all([...m.values()].map(f => figma.loadFontAsync(f))); }
function vis(o, n, label) { for (const f of VIS) { if (!(f in o) || !(f in n) || o[f] === figma.mixed) continue; if (J(o[f]) !== J(n[f])) { n[f] = o[f]; cnt(label + ':' + f); } } }
async function text(o, n, label) {
  if (TXT.some(f => o[f] !== figma.mixed && J(o[f]) !== J(n[f]))) { await fonts(n); if (o.fontName !== figma.mixed) await figma.loadFontAsync(o.fontName);
    for (const f of TXT) if (o[f] !== figma.mixed && J(o[f]) !== J(n[f])) { n[f] = o[f]; cnt(label + ':' + f); } }
  if (o.characters !== n.characters) { await fonts(n); n.characters = o.characters; cnt(label + ':text'); }
  vis(o, n, label);
}
const rel = (n, root) => { const a = n.absoluteTransform, r = root.absoluteTransform; return [a[0][2] - r[0][2], a[1][2] - r[1][2], n.width, n.height]; };

const owner = await get(CFG.owner);
const rows = owner.findAll(n => n.type === 'FRAME' && tag(n) === 'div.row' && !n.id.startsWith('I'));
for (const R of rows) {
  if (CFG.only && !CFG.only.includes(R.id)) continue;
  let v = R; while (v.parent.id !== owner.id) v = v.parent;
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  const [oImg, oT, oP, oA] = R.children;
  const [oB, oS] = oT.children; const oSws = oT.children.find(c => tag(c) === 'span.sws');
  if (!/^img/.test(tag(oImg)) || tag(oT) !== 'div.t' || tag(oP) !== 'div.p' || tag(oA) !== 'span.acts') { rep.err.push(R.id + ' не та структура'); continue; }
  const parent = R.parent, idx = parent.children.indexOf(R);
  const auto = parent.layoutMode && parent.layoutMode !== 'NONE';
  let inst = (await get(VAR[lang][oSws ? 'sw' : 'no'])).createInstance();
  parent.insertChild(idx, inst);
  const iid = inst.id;
  try {
    inst.name = R.name; inst.constraints = R.constraints; inst.visible = R.visible;
    if (!auto) { inst.x = R.x; inst.y = R.y; }
    for (const k of R.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, R.getSharedPluginData('remlab', k));
    inst.resize(R.width, inst.height); inst.primaryAxisSizingMode = 'AUTO';
    if (auto) { inst.layoutAlign = R.layoutAlign; inst.layoutGrow = R.layoutGrow; inst.layoutSizingHorizontal = R.layoutSizingHorizontal === 'FILL' ? 'FILL' : 'FIXED'; inst.layoutSizingVertical = 'HUG'; }
    const props = {};
    if (!oSws) props[kSw] = false;
    const oc = oSws ? oSws.children : [];
    if (oc.some(c => tag(c) === 'button.swn')) props[kN] = true;
    // скрытые в главном слои в экземпляре недоступны (урок Mobile 03.11) → 4-й и 5-й кружки включаются свойствами
    const nSw = oc.filter(c => tag(c) !== 'button.swn').length;
    if (nSw >= 4) props[k4] = true;
    if (nSw >= 5) props[k5] = true;
    if (Object.keys(props).length) { inst.setProperties(props); cnt('bool'); }
    inst = await get(iid);
    vis(R, inst, 'row');
    const [iTop, iA] = inst.children;
    const [iFb, iT, iPb] = iTop.children;
    const iImg = iFb.children[0], iP = iPb.children[0];
    const [iB, iS] = iT.children;
    vis(oImg, iImg, 'img');
    await text(oB, iB, 'b'); await text(oS, iS, 'span'); await text(oP, iP, 'p');
    for (let i = 0; i < oA.children.length; i++) { const o = oA.children[i], n = iA.children[i]; if (n && o.type === 'TEXT' && n.type === 'TEXT') await text(o, n, 'acts'); else rep.err.push(R.id + ' acts ' + i); }
    if (oA.children.length !== iA.children.length) rep.err.push(R.id + ' acts len ' + oA.children.length + '/' + iA.children.length);
    // кружки
    if (oSws) {
      const swsNow = (await get(iid)).children[0].children[1].children[2];
      const swIds = swsNow.children.filter(c => c.name !== 'Счётчик +N').map(c => c.id); let k = 0;
      const swnNode = swsNow.children.find(c => c.name === 'Счётчик +N');
      for (const o of oc) {
        if (tag(o) === 'button.swn') { const n = swnNode && await get(swnNode.id); if (!n) { rep.err.push(R.id + ' нет +N'); break; }
          for (let j = 0; j < o.children.length; j++) { const oo = o.children[j], nn = n.children[j]; if (oo && nn && oo.type === 'TEXT' && nn.type === 'TEXT') await text(oo, nn, 'swn'); }
          vis(o, n, 'swn');
          const m = await get(n.id), ex = (o.width - m.width) / 2;
          if (Math.abs(ex) > 0.01 && m.layoutMode === 'HORIZONTAL') { m.paddingLeft += ex; m.paddingRight += ex; cnt('swn:pad'); }
          continue; }
        if (k >= 5) { rep.err.push(R.id + ' >5 кружков'); break; }
        let n = swIds[k] ? await get(swIds[k]) : null; k++;
        if (!n) { rep.err.push(R.id + ' нет кружка ' + (k - 1)); break; }
        const want = SW[lang][tag(o) === 'button.sw.on' ? 'on' : 'off'];
        if ((await n.getMainComponentAsync()).id !== want) { n.swapComponent(await get(want)); cnt('sw:swap'); n = await get(n.id); }
        if (!n.visible) { n.visible = true; cnt('sw:show'); }
        vis(o, n, 'sw');
      }
      for (; k < swIds.length; k++) { const n = await get(swIds[k]); if (n && n.visible) { n.visible = false; cnt('sw:hide'); } }
    }
    // размеры и смещения
    const T = await get(iT.id), B = await get(iB.id), S = await get(iS.id), P = await get(iP.id);
    if (B.layoutSizingHorizontal !== 'FILL') B.layoutSizingHorizontal = 'FILL';
    // textAutoResize = «по ширине» у слоя с FILL оставляет layoutAlign STRETCH, и Фигма центрует текст (проба 03.11: x 43.5
    // вместо 0) → сразу «по содержимому» (HUG)
    if (oS.textAutoResize === 'WIDTH_AND_HEIGHT') { await fonts(S); S.textAutoResize = 'WIDTH_AND_HEIGHT'; S.layoutSizingHorizontal = 'HUG'; cnt('span:hug'); } else if (S.layoutSizingHorizontal !== 'FILL') S.layoutSizingHorizontal = 'FILL';
    // цена прижата влево: текст по ширине + поле справа «Цены» до старой ширины
    if (Math.abs(oP.width - P.width) > 0.01) { await fonts(P); P.textAutoResize = 'WIDTH_AND_HEIGHT'; P.layoutSizingHorizontal = 'HUG'; cnt('p:hug');
      const pr = oP.width - (await get(P.id)).width; if (pr > 0) { (await get(iPb.id)).paddingRight = pr; cnt('p:padR'); } }
    const s1 = oS.y - (oB.y + oB.height);
    if (Math.abs(T.itemSpacing - s1) > 0.01) { T.itemSpacing = s1; cnt('t:gap'); }
    const last = oT.children[oT.children.length - 1];
    const tpt = Math.max(0, oB.y), tpb = Math.max(0, oT.height - (last.y + last.height));
    if (Math.abs(T.paddingTop - tpt) > 0.01) { T.paddingTop = tpt; cnt('t:padT'); }
    if (Math.abs(T.paddingBottom - tpb) > 0.01) { T.paddingBottom = tpb; cnt('t:padB'); }
    // span.sws в базе фиксированной высоты 29.6 (поле 5.6 + 24); resize() слоя в экземпляре не действует (проба 03.11) →
    // при другом зазоре: «по содержимому» и поля сверху/снизу так, чтобы кружки (22) стояли по центру старых 24
    if (oSws) { const sw = (await get(iid)).children[0].children[1].children[2]; const pt = oSws.y - (oS.y + oS.height) - s1;
      if (Math.abs(sw.paddingTop - pt) > 0.01) { const ex = (oSws.height - Math.max(...oc.map(c => c.height))) / 2;
        sw.paddingTop = pt + ex; sw.paddingBottom = ex; sw.layoutSizingVertical = 'HUG'; cnt('sws:pad'); } }
    const fb = await get(iFb.id), pb = await get(iPb.id), top0 = await get(iTop.id);
    if (Math.abs(fb.paddingTop - (oImg.y - oT.y)) > 0.01) { fb.paddingTop = oImg.y - oT.y; cnt('img:pad'); }
    if (Math.abs(pb.paddingTop - (oP.y - oT.y)) > 0.01) { pb.paddingTop = oP.y - oT.y; cnt('p:pad'); }
    const hs = oT.x - (oImg.x + oImg.width);
    if (Math.abs(top0.itemSpacing - hs) > 0.01) { top0.itemSpacing = hs; cnt('top:gap'); }
    const pl = oP.x - (oT.x + oT.width) - hs;
    if (Math.abs(pb.paddingLeft - pl) > 0.01) { pb.paddingLeft = pl; cnt('p:padL'); }
    inst = await get(iid);
    const pads = { paddingTop: oT.y, paddingLeft: oImg.x, paddingRight: R.width - (oA.x + oA.width) };
    for (const [f, val] of Object.entries(pads)) if (Math.abs(inst[f] - val) > 0.01) { inst[f] = val; cnt('row:' + f); }
    const top = await get(iTop.id);
    const gap = oA.y - (oT.y + top.height), pbt = R.height - (oA.y + oA.height);
    if (Math.abs(inst.itemSpacing - gap) > 0.01) { inst.itemSpacing = gap; cnt('row:gap'); }
    if (Math.abs(inst.paddingBottom - pbt) > 0.01) { inst.paddingBottom = pbt; cnt('row:padB'); }
    // сверка
    inst = await get(iid);
    const pairs = [[R, inst], [oImg, iImg], [oT, iT], [oB, iB], [oS, iS], [oP, iP], [oA, iA], ...oA.children.map((c, i) => [c, iA.children[i]])];
    if (oSws) { const ids = (await get(iid)).children[0].children[1].children[2].children.filter(c => c.visible).map(c => c.id); oc.forEach((c, i) => pairs.push([c, { id: ids[i] }])); }
    let worst = 0, wn = '';
    for (const [o, nn] of pairs) {
      const n = nn && nn.id ? await get(nn.id) : null; if (!n) { worst = 99; wn = 'нет пары ' + (tag(o) || o.type); break; }
      const a = o.id === R.id ? [0, 0, R.width, R.height] : rel(o, R), b = n.id === iid ? [0, 0, n.width, n.height] : rel(n, inst);
      const d = Math.max(...a.map((x, i) => (o.id === oP.id && i === 2) ? 0 : Math.abs(x - b[i])));
      if (d > worst) { worst = d; wn = (tag(o) || o.type) + ' ' + a.map(x => +x.toFixed(1)) + '→' + b.map(x => +x.toFixed(1)); }
    }
    rep.maxD = Math.max(rep.maxD, worst);
    if (worst > TOL) { rep.kept.push(R.id + ' ' + worst.toFixed(1) + ' ' + wn); (await get(iid)).remove(); continue; }
    if (worst > 0.6 && rep.list.length < 30) rep.list.push(R.id + ' ' + worst.toFixed(1) + ' ' + wn);
  } catch (e) { rep.err.push(R.id + ': ' + e.message); const live = await get(iid); if (live) live.remove(); continue; }
  rep.linked++;
  if (CFG.dry) (await get(iid)).remove(); else { rep.ids.push(R.id + '→' + iid); R.remove(); }
}
return rep;
