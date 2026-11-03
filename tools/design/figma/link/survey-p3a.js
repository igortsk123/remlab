// design-02 П3а (T-20261103-06): обзор страницы Desktop (только чтение) — секции, тексты секций, наборы и варианты
// (корень варианта: размер, раскладка, заливки, текст, привязки свойств). Одна страница на вызов: PAGE_ID.
const PAGE_ID = '7:98';
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const allVars = await figma.variables.getLocalVariablesAsync('COLOR');
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => p.boundVariables && p.boundVariables.color ? 'v:' + vName(p.boundVariables.color.id) : (p.type === 'SOLID' ? 'rgb(' + [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255)).join(',') + ')' : p.type)).join('|');
const out = { top: [] };
for (const n of page.children) {
  const o = { id: n.id, t: n.type, n: n.name, x: n.x, y: n.y, w: Math.round(n.width), h: Math.round(n.height) };
  if ('children' in n) o.c = n.children.map(ch => {
    const r = { id: ch.id, t: ch.type, n: ch.name.slice(0, 40), x: Math.round(ch.x), y: Math.round(ch.y), w: Math.round(ch.width), h: Math.round(ch.height) };
    if (ch.type === 'TEXT') r.txt = ch.characters.slice(0, 60);
    if (ch.type === 'COMPONENT_SET') {
      r.props = Object.entries(ch.componentPropertyDefinitions).map(([k, d]) => k + ':' + d.type + (d.type === 'VARIANT' ? '[' + d.variantOptions.join('/') + ']' : '=' + d.defaultValue));
      r.v = ch.children.map(v => {
        const t = v.findAll(x => x.type === 'TEXT');
        const css = v.getSharedPluginData('remlab', 'css');
        return [v.id, v.name, Math.round(v.x) + ',' + Math.round(v.y), (+v.width.toFixed(2)) + 'x' + (+v.height.toFixed(2)), v.layoutMode && v.layoutMode !== 'NONE' ? v.layoutMode[0] + ':' + [v.paddingLeft, v.paddingRight, v.paddingTop, v.paddingBottom, v.itemSpacing, v.primaryAxisSizingMode, v.counterAxisSizingMode].join(',') : 'noAL', 'f=' + paint(v.fills), 's=' + paint(v.strokes), css, 'nodes=' + v.findAll(() => true).length, t.map(x => '«' + x.characters.slice(0, 20) + '»' + (x.componentPropertyReferences && x.componentPropertyReferences.characters ? '#ref' : '') + ' ' + x.textAutoResize).join(' ')].join(' | ');
      });
    }
    return r;
  });
  out.top.push(o);
}
return out;
