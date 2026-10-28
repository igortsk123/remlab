// записать новые адреса в карту remlab/imgHash и залить фото страницы «Избранное»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"https://remont-lab.online/test/share/frames/improve-133336-C1.jpg": "bc9e9cba47114c77bc6e7b31290502f30660ec98"});
figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));
const page = figma.root.children.find((p) => p.name === "Избранное");
await figma.setCurrentPageAsync(page);
const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
let filled = 0; const need = {};
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { if (!need[src]) need[src] = n.id; continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
return { filled, stillMissing: Object.keys(need) };
