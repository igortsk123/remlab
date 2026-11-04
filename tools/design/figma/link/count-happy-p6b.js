// design-02 П6б: ТОЛЬКО ЧТЕНИЕ — «Счастливый путь» (123:2): число узлов, экземпляров, отпечаток (id+тип+размер+видимость+текст).
const page = await figma.getNodeByIdAsync('123:2');
await figma.setCurrentPageAsync(page);
const all = page.findAll(() => true);
const h = s => { let x = 5381; for (let i = 0; i < s.length; i++) x = ((x * 33) ^ s.charCodeAt(i)) >>> 0; return x.toString(36); };
const sig = all.map(n => n.id + n.type[0] + Math.round(n.width) + 'x' + Math.round(n.height) + '@' + Math.round(n.x) + ',' + Math.round(n.y) + (n.visible ? '' : '!') + ('characters' in n ? '=' + n.characters : '')).join('|');
const ov = all.filter(n => n.type === 'INSTANCE').map(n => n.id + ':' + (n.overrides || []).map(o => o.id + o.overriddenFields.join(',')).join(';')).join('|');
return { nodes: all.length, instances: all.filter(n => n.type === 'INSTANCE').length, top: page.children.length, sig: h(sig), ov: h(ov) };
