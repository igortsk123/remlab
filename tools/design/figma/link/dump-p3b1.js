// design-02 П2б (T-20261103-04, p2b1): сжатый дамп узлов для сравнения «рамка ↔ база» (только чтение).
// Строка на узел: тип, размер, раскладка, заливка/обводка/радиус, текст/шрифт; дети до DEPTH. Страница не переключается:
// getNodeByIdAsync грузит узлы любых страниц (IDS — через запятую в коде вызова).
const IDS = ['83:85', '221:2'];
const DEPTH = 2;
const allVars = await figma.variables.getLocalVariablesAsync();
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => (p.boundVariables && p.boundVariables.color ? vName(p.boundVariables.color.id) : (p.type === 'SOLID' ? '#' + [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255).toString(16).padStart(2, '0')).join('') : p.type)) + ((p.opacity ?? 1) < 1 ? '@' + p.opacity.toFixed(2) : '')).join('|');
function row(n, d) {
  let s = n.id + ' ' + n.type[0] + ' ' + (+n.width.toFixed(1)) + 'x' + (+n.height.toFixed(1)) + ' @' + (+n.x.toFixed(1)) + ',' + (+n.y.toFixed(1));
  const css = n.getSharedPluginData('remlab', 'css'); if (css) s += ' {' + css + '}';
  if (!n.visible) s += ' HIDDEN';
  if ('fills' in n && n.fills !== figma.mixed) { const f = paint(n.fills); if (f) s += ' f:' + f; }
  if ('strokes' in n) { const f = paint(n.strokes); if (f) s += ' s:' + f + '/' + (n.strokeWeight === figma.mixed ? 'mx' : n.strokeWeight); }
  if ('cornerRadius' in n && n.cornerRadius) s += ' r:' + (n.cornerRadius === figma.mixed ? 'mx' : n.cornerRadius);
  if ('layoutMode' in n && n.layoutMode !== 'NONE') s += ' al:' + [n.layoutMode[0], n.paddingLeft, n.paddingRight, n.paddingTop, n.paddingBottom, n.itemSpacing, n.primaryAxisAlignItems[0], n.counterAxisAlignItems[0]].join(',');
  if (n.parent && 'layoutMode' in n.parent && n.parent.layoutMode !== 'NONE') s += ' ls:' + n.layoutSizingHorizontal[0] + n.layoutSizingVertical[0] + (n.layoutPositioning === 'ABSOLUTE' ? 'A' : '');
  if (n.type === 'TEXT') { const f = n.fontName; s += ' «' + n.characters.slice(0, 30) + '» ' + (f === figma.mixed ? 'mx' : f.family + ' ' + f.style) + ' ' + (n.fontSize === figma.mixed ? 'mx' : n.fontSize) + ' ' + n.textAutoResize[0] + n.textAlignHorizontal[0]; }
  const r = [s];
  if ('children' in n && d < DEPTH) for (const c of n.children) r.push(...row(c, d + 1).map(x => '  ' + x));
  return r;
}
const out = {};
for (const id of IDS) { const n = await figma.getNodeByIdAsync(id); out[id] = n ? row(n, 0).join('\n') + '\n  parent: ' + n.parent.id + ' ' + n.parent.type : null; }
return out;
