// записать новые адреса в карту remlab/imgHash и залить фото страницы «Окно расстановки»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"asset:ru-375-s31-cv1.jpg": "0d8d79048c8a78070a368caf82232ea3392fa83e", "https://remont-lab.online/test/share/frames/improve-132712-C1.jpg": "88516a6056a832ae95ae364112d120ffd4195095", "asset:en-375-s31-cv1.jpg": "190dc887b6073a62f216ff13c817e37cd9a6b23d", "https://remont-lab.online/demo/img/833aa090526a8096-l.jpg": "03b3bf6e5cae4e01c7062236878ad9459580b5e4"});
figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));
const page = figma.root.children.find((p) => p.name === "Окно расстановки");
await figma.setCurrentPageAsync(page);
const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
let filled = 0; const need = {};
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { if (!need[src]) need[src] = n.id; continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
return { filled, stillMissing: Object.keys(need) };
