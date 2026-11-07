// design-02 П5 (T-20261107-62), Mobile: пересверка экранов со шторкой после drawer-p5a.js.
// CFG = { page: '280:2'|'293:2', items: [{ id: <сборка>, S: <прокрутка px>, finishes: true|false }] }.
// В сборке берётся экземпляр «Drawer / Sheet» (верхний уровень экрана), showFinishes = finishes (по умолчанию да),
// затем «прокрутка» клип-колонки списка на S px. Приём build-p6d.js (CENTER + поле, поле < высоты) у EN-шторки до малых S
// не достаёт (клип 606 при списке 1608), а размер вложенного слоя в экземпляре не переопределяется (resize молча не действует).
// Поэтому: CENTER, поле сверху pt = H/2 − S, снизу 1700 — рамка растёт до pt + 1700 (ниже края шторки/экрана, всё равно обрезано),
// место под содержимое = 0, его середина на pt → верх содержимого = pt − H/2 = −S. Повтор даёт то же.
const CFG = __CFG__;
await figma.setCurrentPageAsync(await figma.getNodeByIdAsync(CFG.page));
const out = {};
for (const it of CFG.items) {
  const s = await figma.getNodeByIdAsync(it.id);
  const d = s.children.find(n => n.type === 'INSTANCE' && n.name === 'Drawer / Sheet');
  if (!d) { out[it.id] = 'нет Drawer / Sheet'; continue; }
  const k = Object.keys(d.componentProperties).find(x => x.startsWith('showFinishes#'));
  d.setProperties({ [k]: it.finishes !== false });
  const c = d.findOne(n => n.type === 'FRAME' && n.clipsContent && n.layoutMode === 'VERTICAL' && n.height > 400);
  if (!c) { out[it.id] = 'нет клип-колонки'; continue; }
  const kids = c.children.filter(n => n.visible && n.layoutPositioning !== 'ABSOLUTE');
  const H = kids.reduce((a, n) => a + n.height, 0) + c.itemSpacing * Math.max(0, kids.length - 1);
  // рамка не сжимается обратно после прошлого прогона → поле снизу добирает до её текущей высоты (место под содержимое = 0)
  c.primaryAxisAlignItems = 'CENTER'; c.paddingTop = H / 2 - it.S; c.paddingBottom = Math.max(1700, c.height - c.paddingTop);
  out[it.id] = { sheet: d.id, clip: c.id, H: Math.round(H), h: Math.round(c.height), pt: Math.round(c.paddingTop), firstY: Math.round(c.children[0].y) };
}
return out;
