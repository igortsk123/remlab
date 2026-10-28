// записать новые адреса в карту remlab/imgHash и залить фото страницы «Шторка»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"https://remont-lab.online/flat3d/materials/laminate-oak-light-preview.webp": "c066d0b94e26c5b0af05d4452905a047d2dc2f32", "https://remont-lab.online/flat3d/materials/oak-grey-preview.webp": "ea52c2869f94227b64dc2c1ad788f1b67c1f7c22", "https://remont-lab.online/flat3d/materials/board-oak-natural-preview.webp": "c7ff4783f55ed3867e19450c64ad4fefbbbef3ec", "https://remont-lab.online/flat3d/materials/parquet-herringbone-preview.webp": "bc07d9eff19313dbb4f1f7e84a179b1eb5ddf2f9", "https://remont-lab.online/flat3d/materials/vinyl-stone-grey-preview.webp": "83b9f7cf6e7983bcca39d7b91f565b5ca1e8d201", "https://remont-lab.online/demo/img/833aa090526a8096.jpg": "2c6baa042b0d92124be8b7f1b457dfac4dd473e7", "https://remont-lab.online/demo/img/e9c6ca120e5913c4.jpg": "32286dc3bc62fe42335afce550b88f5fef8ca31e"});
figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));
const page = figma.root.children.find((p) => p.name === "Шторка");
await figma.setCurrentPageAsync(page);
const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
let filled = 0; const need = {};
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { if (!need[src]) need[src] = n.id; continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
return { filled, stillMissing: Object.keys(need) };
