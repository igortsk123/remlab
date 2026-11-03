// design-02 (T-20261103-02): восстановление правок дизайнера в её экземплярах после связывания.
// Правки на заменённых слоях слетают (слой удалён) — возвращаем их через свойства, без прямой правки слоёв.
// Узлы дизайнера НЕ правятся иначе как через setProperties своих экземпляров. Повторный запуск безопасен.
// RESTORE: inst — её экземпляр; props — свойства набора по имени (без #ключа); nested — свойства вложенного
// экземпляра (по имени слоя-экземпляра в компоненте) — через exposedInstances.
const PAGE_ID = '123:2';            // Mobile → «Счастливый путь»
const RESTORE = [
  { inst: '158:771', props: { 'Поделиться': false, 'Сердечко': false }, nested: { 'Кнопка «Открыть»': { 'Состояние': 'Контурная' } } },
  { inst: '158:806', props: { 'Сердечко': false }, nested: {} },
];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = {};
for (const r of RESTORE) {
  const inst = await figma.getNodeByIdAsync(r.inst);
  const cp = inst.componentProperties;
  const byName = n => Object.keys(cp).find(k => k.replace(/#[^#]*$/, '') === n);
  const set = {};
  for (const [n, val] of Object.entries(r.props)) { const k = byName(n); if (!k) throw new Error(r.inst + ': нет свойства ' + n); set[k] = val; }
  if (Object.keys(set).length) inst.setProperties(set);
  const nestedDone = {};
  for (const [layer, props] of Object.entries(r.nested)) {
    const ex = inst.exposedInstances.find(e => e.name === layer);
    if (!ex) throw new Error(r.inst + ': нет вложенного ' + layer);
    ex.setProperties(props);
    nestedDone[layer] = { id: ex.id, props: ex.componentProperties };
  }
  const mc = await inst.getMainComponentAsync();
  out[r.inst] = { main: mc && mc.id, props: inst.componentProperties, nested: nestedDone, overrides: inst.overrides };
}
return out;
