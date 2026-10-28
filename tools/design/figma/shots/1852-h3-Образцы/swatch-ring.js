// Страница «Образцы» (помощник 3, 26.10): после build-all — обводка выбранного кружка цвета.
// Зачем: на сайте выбранный кружок обведён (index.html:876 `.sw.on{box-shadow:0 0 0 2px var(--surface),0 0 0 3.5px var(--accent)}`),
// выгрузка эту тень не переносит (не токен тени) — «выбрано» и «обычное» выходили одинаковыми.
// Делаем те же два кольца тенями без размытия (белое 2 px, бренд 3.5 px), цвета привязаны к переменным Фон/Карточка и Бренд/Основной.
const page = figma.root.children.find((p) => p.name === 'Образцы');
await figma.setCurrentPageAsync(page);
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = (n) => vars.find((v) => v.name === n);
const ring = (spread, varName, hex) => {
  const e = { type: 'DROP_SHADOW', color: { r: hex[0], g: hex[1], b: hex[2], a: 1 }, offset: { x: 0, y: 0 }, radius: 0, spread, visible: true, blendMode: 'NORMAL', showShadowBehindNode: false };
  const v = V(varName); return v ? figma.variables.setBoundVariableForEffect(e, 'color', v) : e;
};
const sec = page.children.find((n) => n.type === 'SECTION' && n.name === 'Кружок цвета');
const done = [];
for (const c of sec.findAllWithCriteria({ types: ['COMPONENT'] })) {
  if (!/\.on\b/.test(c.getSharedPluginData('remlab', 'css'))) continue;
  // порядок проверен снимком: последняя тень в списке рисуется сверху — белое кольцо поверх кольца бренда
  c.effects = [ring(3.5, 'Бренд/Основной', [0.69, 0.415, 0.29]), ring(2, 'Фон/Карточка', [1, 1, 1])];
  done.push(c.name);
}
// тень с «растяжкой» (spread) Фигма рисует у рамки только при «обрезать содержимое» — включаем у пустых рамок с такой тенью
// (кружки цвета и квадраты образцов пола с «Тень/ring-sel»; детей у них нет, обрезать нечего)
for (const n of page.findAll((n) => (n.type === 'FRAME' || n.type === 'COMPONENT') && (n.effects || []).some((e) => e.spread) && !n.children.length)) n.clipsContent = true;
return { done };
