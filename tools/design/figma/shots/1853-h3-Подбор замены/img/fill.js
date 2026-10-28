// записать новые адреса в карту remlab/imgHash и залить фото страницы «Подбор замены»
const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
Object.assign(M0, {"https://remont-lab.online/demo/img/65bbd97438b2895d.jpg": "c804697d32359aa4dfcae0adfdcd9066d80b1019", "https://remont-lab.online/demo/img/543e377f6fd018a2.jpg": "e6836a2b4ef928818900c72d15d1e582066e2a9d", "https://remont-lab.online/demo/img/8e801b061b7d71ca.jpg": "c76b69e50ab910c5e6256993cbecdba806b5d590", "https://remont-lab.online/demo/img/2dea3c03190da3db.jpg": "ffedcb26c472b6a778fac80e0c3691ea49b5a63a", "https://remont-lab.online/demo/img/666f32dd0ac4b5e9.jpg": "7b210070e2845b11570916bbb7c87ac61f1a7461", "https://remont-lab.online/demo/img/c921edceb36c1ca4.jpg": "e1446f110c14e1cf025a10378250cc78b622cd97", "https://remont-lab.online/demo/img/0f9655750bf943f0.jpg": "54b576f96e23405cbda0703c743f95d9334a5d8a", "https://remont-lab.online/demo/img/1d576ae5e567941f.jpg": "d9b29fcdd9afb71f64a919fc608e25f7e29b4513", "https://remont-lab.online/demo/img/a862806f0ec05b2a.jpg": "056b6edfb6314d389d866ea6310876d3f86f0bbf", "https://remont-lab.online/demo/img/c8d382fdd1df4087.jpg": "5d6ec7d7748c95f9d506afe05d4c332fb64508fe", "https://remont-lab.online/demo/img/025b2f55c0216641.jpg": "4471e6469ad60f8cfb6091fd606c60cea1e3f93b", "https://remont-lab.online/demo/img/9b33713a232f281b.jpg": "a84575c826a990323a4242795c66f1a64134a789", "https://remont-lab.online/demo/img/0f205e75414749d3.jpg": "bf40905d69505dbfa9475908ca92c24c09d0988d", "https://remont-lab.online/demo/img/cc3f9de5b43324a4.jpg": "222f2f7089f238eab3194a50e7423224fcf4c040", "https://remont-lab.online/demo/img/d7626ebd947e609a.jpg": "52ff6abf921e228239596450ac3146585507eb2d"});
figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));
const page = figma.root.children.find((p) => p.name === "Подбор замены");
await figma.setCurrentPageAsync(page);
const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');
let filled = 0; const need = {};
for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {
  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];
  if (!h) { if (!need[src]) need[src] = n.id; continue; }
  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;
}
return { filled, stillMissing: Object.keys(need) };
