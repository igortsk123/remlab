// design-02 П5 (T-20261107-62): ТОЛЬКО ЧТЕНИЕ — компактное дерево узлов (__IDS__): отступ·тип·имя·ш×в·текст; глубина __DEPTH__.
// AL<направление><gap> p<поля> — авто-раскладка; clip — обрезка; x,y — для абсолютных.
const out = {};
const T = { FRAME: 'F', TEXT: 'T', INSTANCE: 'I', RECTANGLE: 'R', VECTOR: 'V', ELLIPSE: 'E', COMPONENT: 'C', GROUP: 'G', BOOLEAN_OPERATION: 'B' };
const walk = (n, d, acc) => {
  let s = '.'.repeat(d) + (T[n.type] || n.type) + ' ' + n.id + ' ' + n.name.slice(0, 22) + ' ' + Math.round(n.width) + 'x' + Math.round(n.height) + '@' + Math.round(n.x) + ',' + Math.round(n.y) + (n.visible ? '' : ' !hid');
  if (n.type === 'TEXT') s += ' "' + n.characters.slice(0, 40) + '" ' + (typeof n.fontSize === 'number' ? n.fontSize : 'mix') + '/' + (typeof n.fontName === 'object' && n.fontName.style ? n.fontName.style : 'mix') + ' ' + n.textAutoResize;
  if (n.type === 'INSTANCE' && n.mainComponent) s += ' →' + n.mainComponent.id;
  if (n.layoutMode && n.layoutMode !== 'NONE') s += ' AL' + n.layoutMode[0] + n.itemSpacing + ' p' + [n.paddingTop, n.paddingRight, n.paddingBottom, n.paddingLeft].join('/') + ' ' + n.primaryAxisAlignItems[0] + n.counterAxisAlignItems[0];
  if (n.clipsContent) s += ' clip';
  if (n.layoutPositioning === 'ABSOLUTE') s += ' ABS';
  acc.push(s);
  if (d < __DEPTH__ && 'children' in n && !(n.type === 'INSTANCE' && d > 0 && __STOPINST__)) for (const c of n.children) walk(c, d + 1, acc);
};
for (const id of __IDS__) { const n = await figma.getNodeByIdAsync(id); const acc = []; if (n) walk(n, 0, acc); out[id] = acc.join('\n'); }
return out;
