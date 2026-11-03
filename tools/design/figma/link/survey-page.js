// design-02 (T-20261103-03): обзор страницы элементов (только чтение) — наборы, варианты, дерево слоёв с метками
// remlab/css, размерами, авто-раскладкой, заливками (переменные), шрифтами и привязками свойств.
// Одна страница на вызов: PAGE_ID. Вывод ограничен глубиной DEPTH.
const PAGE_ID = '5:2';
const DEPTH = 4;

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const allVars = await figma.variables.getLocalVariablesAsync('COLOR');
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => p.boundVariables && p.boundVariables.color ? 'var:' + vName(p.boundVariables.color.id) : (p.type === 'SOLID' ? 'rgb(' + [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255)).join(',') + ')' + (p.opacity < 1 ? '@' + p.opacity.toFixed(2) : '') : p.type)).join('|');
function row(n, d) {
  const o = { id: n.id, t: n.type, n: n.name, x: Math.round(n.x), y: Math.round(n.y), w: +n.width.toFixed(2), h: +n.height.toFixed(2) };
  const css = n.getSharedPluginData('remlab', 'css'); if (css) o.css = css;
  if (!n.visible) o.hidden = 1;
  if ('fills' in n && n.fills !== figma.mixed) { const f = paint(n.fills); if (f) o.fill = f; }
  if ('strokes' in n) { const s = paint(n.strokes); if (s) o.stroke = s + '/' + n.strokeWeight; }
  if ('cornerRadius' in n && n.cornerRadius) o.r = n.cornerRadius === figma.mixed ? 'mixed' : n.cornerRadius;
  if ('layoutMode' in n && n.layoutMode && n.layoutMode !== 'NONE') o.al = [n.layoutMode[0], n.paddingLeft, n.paddingRight, n.paddingTop, n.paddingBottom, n.itemSpacing, n.primaryAxisSizingMode, n.counterAxisSizingMode, n.primaryAxisAlignItems, n.counterAxisAlignItems].join(',');
  if (n.parent && 'layoutMode' in n.parent && n.parent.layoutMode !== 'NONE') o.ls = [n.layoutSizingHorizontal, n.layoutSizingVertical, n.layoutPositioning].join(',');
  if (n.type === 'TEXT') { o.txt = n.characters.slice(0, 40); const f = n.fontName; o.font = f === figma.mixed ? 'mixed' : f.family + ' ' + f.style + ' ' + (n.fontSize === figma.mixed ? 'mx' : n.fontSize); o.tar = n.textAutoResize; }
  if (n.componentPropertyReferences && Object.keys(n.componentPropertyReferences).length) o.ref = n.componentPropertyReferences;
  if ('children' in n && d < DEPTH) o.c = n.children.map(ch => row(ch, d + 1));
  else if ('children' in n && n.children.length) o.nch = n.children.length;
  return o;
}
const sets = page.findAllWithCriteria({ types: ['COMPONENT_SET'] });
const out = { page: page.name, sets: [] };
for (const s of sets) {
  out.sets.push({ id: s.id, name: s.name, x: s.x, y: s.y, w: s.width, h: s.height, parent: s.parent.id + ' ' + s.parent.type + ' ' + s.parent.name,
    props: s.componentPropertyDefinitions, variants: s.children.map(v => row(v, 0)) });
}
out.top = page.children.map(n => ({ id: n.id, t: n.type, n: n.name, x: n.x, y: n.y, w: n.width, h: n.height }));
return out;
