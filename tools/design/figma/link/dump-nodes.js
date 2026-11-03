// design-02 П2а (T-20261103-03/2): подробный дамп выбранных узлов (только чтение) — дерево, раскладка, заливки
// (с переменными), обводки, шрифты, метки remlab/css. Нужен, чтобы новые базовые повторяли вид мест использования.
// Одна страница на вызов: PAGE_ID + IDS.
const PAGE_ID = '17:38';
const IDS = ['85:9'];
const DEPTH = 3;

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const allVars = await figma.variables.getLocalVariablesAsync();
const vName = id => (allVars.find(v => v.id === id) || {}).name || id;
const paint = ps => (Array.isArray(ps) ? ps : []).filter(p => p.visible !== false).map(p => (p.boundVariables && p.boundVariables.color ? 'var:' + vName(p.boundVariables.color.id) + ' ' : '') + (p.type === 'SOLID' ? 'rgb(' + [p.color.r, p.color.g, p.color.b].map(c => Math.round(c * 255)).join(',') + ')' + ((p.opacity ?? 1) < 1 ? '@' + p.opacity.toFixed(2) : '') : p.type)).join('|');
function row(n, d) {
  const o = { id: n.id, t: n.type, n: n.name.slice(0, 40), x: +n.x.toFixed(1), y: +n.y.toFixed(1), w: +n.width.toFixed(2), h: +n.height.toFixed(2) };
  const css = n.getSharedPluginData('remlab', 'css'); if (css) o.css = css;
  if (!n.visible) o.hidden = 1;
  if (n.opacity !== undefined && n.opacity < 1) o.op = n.opacity;
  if ('fills' in n && n.fills !== figma.mixed) { const f = paint(n.fills); if (f) o.fill = f; }
  if ('strokes' in n) { const s = paint(n.strokes); if (s) o.stroke = s + '/' + (n.strokeWeight === figma.mixed ? 'mx' : n.strokeWeight) + (n.strokeAlign ? ',' + n.strokeAlign : ''); }
  if ('cornerRadius' in n && n.cornerRadius) o.r = n.cornerRadius === figma.mixed ? 'mixed' : n.cornerRadius;
  if ('effects' in n && n.effects.length) o.fx = n.effects.map(e => e.type + (e.radius ? ':' + e.radius : '')).join(',');
  if ('clipsContent' in n && n.clipsContent) o.clip = 1;
  if ('layoutMode' in n && n.layoutMode && n.layoutMode !== 'NONE') o.al = [n.layoutMode[0], n.paddingLeft, n.paddingRight, n.paddingTop, n.paddingBottom, n.itemSpacing, n.primaryAxisSizingMode, n.counterAxisSizingMode, n.primaryAxisAlignItems, n.counterAxisAlignItems].join(',');
  if (n.parent && 'layoutMode' in n.parent && n.parent.layoutMode !== 'NONE') o.ls = [n.layoutSizingHorizontal, n.layoutSizingVertical, n.layoutPositioning].join(',');
  if (n.type === 'TEXT') {
    o.txt = n.characters.slice(0, 40); const f = n.fontName;
    o.font = f === figma.mixed ? 'mixed' : f.family + ' ' + f.style + ' ' + (n.fontSize === figma.mixed ? 'mx' : n.fontSize);
    o.tar = n.textAutoResize; o.ta = n.textAlignHorizontal; o.lh = n.lineHeight === figma.mixed ? 'mx' : (n.lineHeight.unit === 'AUTO' ? 'auto' : n.lineHeight.value + n.lineHeight.unit[0]);
    if (n.letterSpacing !== figma.mixed && n.letterSpacing.value) o.lsp = n.letterSpacing.value + n.letterSpacing.unit[0];
    if (n.textDecoration && n.textDecoration !== 'NONE') o.deco = n.textDecoration;
  }
  if ('children' in n && d < DEPTH) o.c = n.children.map(ch => row(ch, d + 1));
  else if ('children' in n && n.children.length) o.nch = n.children.length;
  return o;
}
const out = {};
for (const id of IDS) { const n = await figma.getNodeByIdAsync(id); out[id] = n ? Object.assign(row(n, 0), { parent: n.parent.id + ' ' + n.parent.name.slice(0, 30) }) : null; }
return out;
