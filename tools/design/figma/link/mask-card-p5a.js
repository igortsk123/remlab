// design-02 П5 (T-20261107-62) п.8, Desktop: вуаль под карточкой товара (экран 16).
// Замер (tools/design/figma/link/veil-p5a.py, снимки shots/0711-1353-p5a/before/d-ru16-*.png): на эталоне 16 вуаль НЕ светлая —
// нейтральная чёрная ~40 % (белый ряд списка 255 → 153), у сборки — тёплая 20,16,12 @ 38 % (255 → 166). На эталоне 22 (окошко имени)
// вуаль = нынешней (20,16,12 @ 38 %, сверка с эталоном 19 того же кадра, ошибка 0,3 уровня) — 22 не трогаем.
// Поэтому: переменная «Затемнение/Под карточкой» (0,0,0, 0.40) в коллекции переменной 5:29 и варианты Modal / Mask 37:116
// `state=card` (ru/en) — копии state=default с заливкой на этой переменной; экземпляры экрана 16 → state=card.
// CFG = { screens: [{ page, id: <экземпляр Modal / Mask на экране 16> }] }. Повтор безопасен.
const CFG = __CFG__;
const set = await figma.getNodeByIdAsync('37:116');
const base = await figma.variables.getVariableByIdAsync('VariableID:5:29');
const coll = await figma.variables.getVariableCollectionByIdAsync(base.variableCollectionId);
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
let v = vars.find(x => x.name === 'Затемнение/Под карточкой' && x.variableCollectionId === coll.id);
if (!v) { v = figma.variables.createVariable('Затемнение/Под карточкой', coll, 'COLOR'); v.setValueForMode(coll.defaultModeId, { r: 0, g: 0, b: 0, a: 0.4 });
  v.description = 'Вуаль под карточкой товара (Card / Product Detail), замер по эталону 16: чёрный 40 %.'; }
const out = { var: v.id, variants: [], screens: [] };
let y = Math.max(...set.children.map(c => c.y + c.height)) + 48;
for (const lang of ['ru', 'en']) {
  let c = set.children.find(n => n.name === 'lang=' + lang + ', state=card');
  if (!c) {
    const src = set.children.find(n => n.name === 'lang=' + lang + ', state=default');
    c = src.clone(); set.appendChild(c); c.name = 'lang=' + lang + ', state=card'; c.x = src.x; c.y = y; y += c.height + 48;
  }
  c.fills = [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 }, opacity: 1 }, 'color', v)];
  out.variants.push(c.id + ' ' + c.name + ' @' + Math.round(c.x) + ',' + Math.round(c.y));
}
const bottom = Math.max(...set.children.map(c => c.y + c.height));
if (set.height < bottom + 24) set.resizeWithoutConstraints(set.width, bottom + 24);
for (const S of CFG.screens) {
  await figma.setCurrentPageAsync(await figma.getNodeByIdAsync(S.page));
  const m = await figma.getNodeByIdAsync(S.id);
  m.setProperties({ state: 'card' });
  out.screens.push(S.id + ' → ' + m.mainComponent.name + ' showModal=' + Object.entries(m.componentProperties).filter(([k]) => k.startsWith('showModal')).map(([, p]) => p.value));
}
return out;
