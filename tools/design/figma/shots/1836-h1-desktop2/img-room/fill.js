// записать новые адреса в карту remlab/imgHash и залить фото страницы «Комната»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"https://remont-lab.online/test/share/frames/improve-132712-C1.t.jpg": "a55b6fa502d386cf435fcb33febb33700f72713f", "https://remont-lab.online/test/share/frames/improve-133024-C1.t.jpg": "8ad8298cb793f1bed4e11be4febfd2151b99d028"});
figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));
const page = figma.root.children.find((p) => p.name === "Комната");
await figma.setCurrentPageAsync(page);
const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
let filled = 0; const need = {};
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { if (!need[src]) need[src] = n.id; continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
return { filled, stillMissing: Object.keys(need) };
