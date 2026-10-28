// Страница «Образцы» (помощник 3, 26.10 19:20): пересборка из уже лежащих в файле данных с подписями по новому словарю
// (pages/Образцы.json: «22 px» / «34 px», «не выбрано», короткая строка «что это» у пола) — без повторной переписи частей.
// Затем заливка фото по карте imgHash, кольцо выбранного кружка (как swatch-ring.js) и проверка.
// DEV — 'phone' (Mobile, maxW 1240) или 'desktop' (Desktop, maxW 3000): подставить перед вызовом.
const DEV = typeof DEV_NAME !== 'undefined' ? DEV_NAME : 'phone';
const g = (k) => figma.root.getSharedPluginData('remlab', k);
const AF = Object.getPrototypeOf(async function () {}).constructor;
const FLOOR = 'Образец пола в окне отделки: фото материала и подпись (в цене или доплата); выбранный — с обводкой';
const fix = (s) => s.split('22 px — в шторке').join('22 px').split('34 px — в карточке товара').join('34 px').split('Обычное').join('не выбрано')
  .split('Образец покрытия пола в окне отделки: квадрат с фото материала и подпись (входит в сертификат или доплата); выбранный — с обводкой').join(FLOOR)
  // строка «что это» у кружка содержит «34 px — в карточке товара» — вернуть её целиком (найдено снимком 19:22)
  .split('в строке шторки, 34 px; выбранный').join('в строке шторки, 34 px — в карточке товара; выбранный');
const sections = [];
for (const k of ['data/' + DEV + '/Образцы/01', 'data/' + DEV + '/Образцы/02']) {
  const s = fix(g(k)); figma.root.setSharedPluginData('remlab', k, s);
  const d = JSON.parse(s); sections.push({ ...d.sec, variants: d.variants });
}
const o = await new AF('P', g('builder2'))({ page: 'Образцы', dev: DEV, maxW: DEV === 'desktop' ? 3000 : 1240, sections });
if (o.err) return o;
const page = figma.root.children.find((p) => p.name === 'Образцы');
await figma.setCurrentPageAsync(page);
const M = JSON.parse(g('imgHash') || '{}');
let filled = 0; const need = [];
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { need.push(src); continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = (n) => vars.find((v) => v.name === n);
const ring = (spread, varName, hex) => { const e = { type: 'DROP_SHADOW', color: { r: hex[0], g: hex[1], b: hex[2], a: 1 }, offset: { x: 0, y: 0 }, radius: 0, spread, visible: true, blendMode: 'NORMAL', showShadowBehindNode: false }; const v = V(varName); return v ? figma.variables.setBoundVariableForEffect(e, 'color', v) : e; };
const sec = page.children.find((n) => n.type === 'SECTION' && n.name === 'Кружок цвета');
let rings = 0;
for (const c of sec.findAllWithCriteria({ types: ['COMPONENT'] })) {
  if (!/\.on\b/.test(c.getSharedPluginData('remlab', 'css'))) continue;
  c.effects = [ring(3.5, 'Бренд/Основной', [0.69, 0.415, 0.29]), ring(2, 'Фон/Карточка', [1, 1, 1])]; rings++;
}
for (const n of page.findAll((n) => (n.type === 'FRAME' || n.type === 'COMPONENT') && (n.effects || []).some((e) => e.spread) && !n.children.length)) n.clipsContent = true;
const chk = await new AF('P', g('check'))({ page: 'Образцы' });
return { sections: o.sections, filled, need, rings, counts: chk.counts };
