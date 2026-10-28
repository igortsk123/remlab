// Страница «Подбор замены» (помощник 3, 26.10): после сборки — кнопка «×» у правого края заголовка, как на сайте.
// Зачем: на сайте заголовок в обёртке `.h{flex:1}` (index.html:421) растягивается и толкает «×» вправо; выгрузка схлопывает
// обёртку в сам текст, и текст «по содержимому» — «×» прилипает к заголовку. Делаем текст заголовка «заполнить по ширине».
// Работает в обоих файлах (Mobile и Desktop): страница ищется по имени.
const page = figma.root.children.find((p) => p.name === 'Подбор замены');
await page.loadAsync();
const done = [];
for (const t of page.findAllWithCriteria({ types: ['TEXT'] })) {
  if (!/sh-title/.test(t.getSharedPluginData('remlab', 'css'))) continue;
  const p = t.parent;
  if (!p || p.layoutMode !== 'HORIZONTAL') continue;
  t.layoutSizingHorizontal = 'FILL';
  done.push([t.id, Math.round(t.width)]);
}
return { done };
