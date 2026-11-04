// design-02 П6в (T-20261104-04): ТОЛЬКО ЧТЕНИЕ — перечень наборов/компонентов одной страницы элементов.
// __PAGE__ — id страницы. Возвращает [id, имя, ш×в, свойства набора (имя:тип[:варианты]), варианты id=имя ш×в].
const page = await figma.getNodeByIdAsync('__PAGE__');
await figma.setCurrentPageAsync(page);
const out = [];
for (const n of page.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] })) {
  if (n.type === 'COMPONENT' && n.parent.type === 'COMPONENT_SET') continue;
  const defs = n.componentPropertyDefinitions;
  const props = Object.entries(defs).map(([k, v]) => k + ':' + v.type[0] + (v.type === 'VARIANT' ? '[' + v.variantOptions.join('|') + ']' : v.type === 'TEXT' ? '=' + String(v.defaultValue).slice(0, 20) : ''));
  const vars = n.type === 'COMPONENT_SET' ? n.children.map(c => c.id + '=' + c.name + ' ' + Math.round(c.width) + 'x' + Math.round(c.height)) : [];
  out.push([n.id, n.name, Math.round(n.width) + 'x' + Math.round(n.height), props.join('; '), vars.join(' | ')]);
}
return out;
