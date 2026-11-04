// design-02 П6д (T-20261104-07, Desktop) (T-20261104-04): ТОЛЬКО ЧТЕНИЕ — компактное дерево узлов (__IDS__): отступ·тип·имя·ш×в·текст; глубина __DEPTH__.
const out = {};
const T = { FRAME: 'F', TEXT: 'T', INSTANCE: 'I', RECTANGLE: 'R', VECTOR: 'V', ELLIPSE: 'E', COMPONENT: 'C', GROUP: 'G', BOOLEAN_OPERATION: 'B' };
const walk = (n, d, acc) => {
  let s = '.'.repeat(d) + (T[n.type] || n.type) + ' ' + n.name.slice(0, 24) + ' ' + Math.round(n.width) + 'x' + Math.round(n.height) + (n.visible ? '' : ' !hid');
  if (n.type === 'TEXT') s += ' "' + n.characters.slice(0, 60) + '"';
  if (n.type === 'INSTANCE' && n.mainComponent) s += ' →' + n.mainComponent.id;
  if (n.layoutMode && n.layoutMode !== 'NONE') s += ' AL' + n.layoutMode[0] + n.itemSpacing;
  acc.push(s);
  if (d < __DEPTH__ && 'children' in n && !(n.type === 'INSTANCE' && d > 0 && __STOPINST__)) for (const c of n.children) walk(c, d + 1, acc);
};
for (const id of __IDS__) { const n = await figma.getNodeByIdAsync(id); const acc = []; if (n) walk(n, 0, acc); out[id] = acc.join('\n'); }
return out;
