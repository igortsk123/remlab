// design-02 П2б2 (T-20261103-05): восстановление правки дизайнера в её 6 экземплярах «Диалог/Затемнение» (главный 85:100)
// на «Счастливый путь» 123:2. До правки у всех было одно переопределение: скрыт слой 85:89 (окно ввода имени, div.favbox)
// — снимок shots/0311-1438-p2b2/before/designer-85-100.json. Слой заменён экземпляром «Ввод имени» с BOOLEAN «Окно»
// на наборе 85:116 → восстанавливаем свойством «Окно» = false (её узлы иначе не трогаются). Повторный запуск безопасен.
const PAGE_ID = '123:2';
const INSTS = ['157:114', '158:138', '158:199', '158:242', '158:302', '158:397'];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = {};
for (const id of INSTS) {
  const inst = await figma.getNodeByIdAsync(id);
  const key = Object.keys(inst.componentProperties).find(k => k.replace(/#[^#]*$/, '') === 'Окно');
  if (!key) throw new Error(id + ': нет свойства Окно');
  if (inst.componentProperties[key].value !== false) inst.setProperties({ [key]: false });
  const mc = await inst.getMainComponentAsync();
  out[id] = { main: mc && mc.id, okno: inst.componentProperties[key].value, overrides: inst.overrides.map(o => o.id + ':' + o.overriddenFields.join(',')) };
}
return out;
