// design-02 П4б (T-20261103-12): ЗАПИСЬ — переименование страниц элементов по plan-<книга>.json (pageRenames).
// Подставить RENAMES = [[id, старое, новое]]. Страница с именем не старым и не новым — стоп до записи.
// «Как пользоваться», «Счастливый путь», «Экраны RU/EN» в списке нет и не трогаются.
const RENAMES = __RENAMES__;
const pages = {};
for (const p of figma.root.children) pages[p.id] = p;
for (const [id, o, n] of RENAMES) {
  const p = pages[id];
  if (!p) throw new Error('нет страницы ' + id);
  if (p.name !== o && p.name !== n) throw new Error(id + ': имя «' + p.name + '» не старое и не новое');
}
let k = 0;
for (const [id, o, n] of RENAMES) if (pages[id].name !== n) { pages[id].name = n; k++; }
return JSON.stringify({ renamed: k, pages: figma.root.children.map(p => [p.id, p.name]) });
