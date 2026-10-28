// записать новые адреса в карту remlab/imgHash и залить фото страницы «Окно расстановки»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"asset:ru-1440-s31-cv1.jpg": "373039cc44e76f7c81d1b368137859b891a5d78a", "asset:en-1440-s31-cv1.jpg": "373039cc44e76f7c81d1b368137859b891a5d78a", "https://remont-lab.online/test/share/frames/improve-132712-C1.jpg": "88516a6056a832ae95ae364112d120ffd4195095", "https://remont-lab.online/demo/img/833aa090526a8096-l.jpg": "03b3bf6e5cae4e01c7062236878ad9459580b5e4", "https://remont-lab.online/demo/img/2ea3213754af04d2.jpg": "867c73434d88603d279ddaaf6d872b5c95d1f902", "https://remont-lab.online/demo/img/3e31b1ca95b25cf1.jpg": "68105a9a23580b162d7ad8578cc84786e1db9c4f", "https://remont-lab.online/demo/img/c43a87629e11081f.jpg": "9bf57bdf6a1a475fbd5a782512b9bff1a9a6a83c", "https://remont-lab.online/demo/img/5e4d8a99bd94a9aa.jpg": "ee9ac9dcae63bc7507a91675bc82424076f9ff39", "https://remont-lab.online/demo/img/584de9f1d6e6b381.jpg": "ee6623b53d02b953b5c7ef3a5ee5723f11c7e601", "https://remont-lab.online/demo/img/52695e7158c1dcd2.jpg": "1d025e77ca47e8813aafd7e97be07aa9795edb78", "https://remont-lab.online/demo/img/92945fbfd9df6b9a.jpg": "38543c4a1d18672983226637bdae9342521e3f50", "https://remont-lab.online/demo/img/a243befc7aae237a.jpg": "3e8ad1cf8573a759221a26c2491c1ab532d623a7", "https://remont-lab.online/demo/img/be2cdd11610a2659.jpg": "0b0a3840414f754b473a4f32369f18cde09cc0ce"});
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
