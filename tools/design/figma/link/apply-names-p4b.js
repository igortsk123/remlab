// design-02 П4б (T-20261103-12): ЗАПИСЬ — переименование наборов одной страницы по плану plan-p4b.py.
// Генерируется gen-apply-p4b.py: подставляются PAGE_ID и OPS. Повторный запуск безопасен (уже переименованное пропускается).
// OPS: [{id, o: старое имя, n: новое, j: строка JSX, p: [[ключ TEXT/BOOLEAN, новое имя]], v: [[id варианта, новое имя]]}]
// Описание = JSX + '\n' + текущее описание, где «свойство «X»» → «свойство <новое>» (DESC_MAP).
const PAGE_ID = '__PAGE__';
const OPS = __OPS__;
const DESC_MAP = __DESC_MAP__;
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
// 1) проверка до записи — ничего не меняем, если что-то не сходится
const nodes = {};
for (const o of OPS) {
  const s = await figma.getNodeByIdAsync(o.id);
  if (!s || s.type !== 'COMPONENT_SET') throw new Error('нет набора ' + o.id);
  if (s.name !== o.o && s.name !== o.n) throw new Error(o.id + ': имя «' + s.name + '» не старое и не новое');
  for (const [cid] of o.v) {
    const c = await figma.getNodeByIdAsync(cid);
    if (!c || !c.parent || c.parent.id !== o.id) throw new Error(o.id + ': вариант ' + cid + ' не в наборе');
  }
  nodes[o.id] = s;
}
// 2) запись
const res = [];
for (const o of OPS) {
  const s = nodes[o.id];
  const defs = s.componentPropertyDefinitions;
  let np = 0;
  for (const [k, nn] of o.p) {
    if (k in defs) { s.editComponentProperty(k, { name: nn }); np++; }
    else if (!Object.keys(defs).some(x => x === nn + '#' + k.split('#')[1])) throw new Error(o.id + ': нет свойства ' + k);
  }
  let nv = 0;
  for (const [cid, nn] of o.v) {
    const c = await figma.getNodeByIdAsync(cid);
    if (c.name !== nn) { c.name = nn; nv++; }
  }
  s.name = o.n;
  // Фигма отдаёт описание экранированным (&lt; &gt; &quot; &#39;) — сравниваем оба вида, чтобы не дописать JSX дважды
  const esc = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  if (!s.description.startsWith(o.j + '\n') && !s.description.startsWith(esc(o.j) + '\n')) {
    s.description = o.j + '\n' + s.description.replace(/свойство «([^»]+)»/g, (m, x) => DESC_MAP[x] ? 'свойство ' + DESC_MAP[x] : m);
  }
  // 3) сверка по месту
  const d2 = s.componentPropertyDefinitions;
  const keys = Object.keys(d2).map(k => k.split('#')[0]);
  const bad = o.v.filter(([cid, nn]) => !s.children.some(c => c.id === cid && c.name === nn)).length;
  res.push([o.id, np, nv, bad, keys.join(',')]);
}
return JSON.stringify({ page: page.id, done: res, mutatedNodeIds: OPS.map(o => o.id) });
