// design-02 П5 (T-20261107-62) п.7: 3D-кадр «после замены» (бежевый диван) как компонент-картинка + слот в окне 3D.
// CFG = { page, at:[x,y], winSet, frame:[W,H], ref:[RW,RH], desc,
//         langs:[{ lang, win, renderCol, tagsCol, refId, crop:{x,y,w,h}, tags:[{ x, y, text }], patches:[{ x, y, w, h, sx, sy }] }] }
//  · набор «Image / 3D Render» (варианты lang=…, scene=afterReplace): рамка W×H без заливки, внутри «Кадр» crop.w×crop.h —
//    вырезка из рамки-эталона (CROP по её imageHash; crop — в координатах эталона RW×RH, кладётся в 0,0);
//  · «Заплатка N» — та же картинка со сдвигом (sx,sy — откуда брать, в координатах кадра) поверх запечённых полупрозрачных
//    плашек эталона (иначе плашки окна ложатся вторым слоем: двойное затемнение, «призрак» текста);
//  · в набор окна (winSet) — BOOLEAN showAfterReplace (по умолчанию выкл.); в 3D-варианты окна — экземпляр кадра поверх
//    прежнего «3D-кадр» и слой «Ценники после замены» (Ценник на местах эталона, поверх запечённых — непрозрачные белые),
//    оба видны только при showAfterReplace. Прежние слои и их переопределения в сборках не трогаются.
// Прогоны 07.11: Mobile (page 16:2, winSet 95:972, frame 375×812, ref 375×812, crop 0,0,375×680 ru / ×630 en) — первым вариантом
// скрипта (заплатки — patch-render-p5a.js); Desktop (page 9:134, winSet 48:764, frame 910×828, ref 1440×900, crop 60,36,910×828).
// Повтор безопасен: набор ищется по имени, слои — по имени, заплатки пересоздаются.
const CFG = __CFG__;
const page = await figma.getNodeByIdAsync(CFG.page); await figma.setCurrentPageAsync(page);
const [W, H] = CFG.frame, [RW, RH] = CFG.ref;
const out = { set: null, prop: null, win: [] };
let set = page.children.find(n => n.type === 'COMPONENT_SET' && n.name === 'Image / 3D Render');
if (!set) {
  const comps = [];
  for (const L of CFG.langs) {
    const c = figma.createComponent(); c.name = 'lang=' + L.lang + ', scene=afterReplace'; c.resize(W, H); c.fills = []; c.clipsContent = true;
    const r = figma.createRectangle(); r.name = 'Кадр'; r.resize(L.crop.w, L.crop.h);
    const ref = await figma.getNodeByIdAsync(L.refId);
    r.fills = [{ type: 'IMAGE', imageHash: ref.fills.find(f => f.type === 'IMAGE').imageHash, scaleMode: 'CROP',
      imageTransform: [[L.crop.w / RW, 0, L.crop.x / RW], [0, L.crop.h / RH, L.crop.y / RH]] }];
    c.appendChild(r); r.x = 0; r.y = 0; comps.push(c);
  }
  set = figma.combineAsVariants(comps, page);
  set.name = 'Image / 3D Render'; set.x = CFG.at[0]; set.y = CFG.at[1];
  set.layoutMode = 'HORIZONTAL'; set.itemSpacing = 40; set.paddingTop = set.paddingBottom = set.paddingLeft = set.paddingRight = 40;
  set.primaryAxisSizingMode = 'AUTO'; set.counterAxisSizingMode = 'AUTO';
  set.description = '<Image src="…" preview={false} />\n' + CFG.desc;
}
out.set = set.id + ' ' + set.children.map(c => c.id + ' ' + c.name).join(', ');
for (const L of CFG.langs) { // заплатки
  const c = set.children.find(v => v.name === 'lang=' + L.lang + ', scene=afterReplace'), img = c.findOne(n => n.name === 'Кадр');
  const hash = img.fills[0].imageHash, cx = L.crop.x, cy = L.crop.y;
  for (const o of c.children.filter(n => n.name.startsWith('Заплатка'))) o.remove();
  for (const [i, p] of (L.patches || []).entries()) {
    const r = figma.createRectangle(); r.name = 'Заплатка ' + (i + 1); r.resize(p.w, p.h);
    r.fills = [{ type: 'IMAGE', imageHash: hash, scaleMode: 'CROP', imageTransform: [[p.w / RW, 0, (cx + p.sx) / RW], [0, p.h / RH, (cy + p.sy) / RH]] }];
    c.appendChild(r); r.x = p.x; r.y = p.y;
  }
}
const winSet = await figma.getNodeByIdAsync(CFG.winSet);
let key = Object.keys(winSet.componentPropertyDefinitions).find(k => k.startsWith('showAfterReplace#'));
if (!key) key = winSet.addComponentProperty('showAfterReplace', 'BOOLEAN', false);
out.prop = key;
for (const L of CFG.langs) {
  const w = await figma.getNodeByIdAsync(L.win);
  const v = set.children.find(c => c.name === 'lang=' + L.lang + ', scene=afterReplace');
  const col = await figma.getNodeByIdAsync(L.renderCol);
  let ri = col.children.find(n => n.name === '3D-кадр после замены');
  if (!ri) { ri = v.createInstance(); ri.name = '3D-кадр после замены'; col.insertChild(1, ri); ri.layoutPositioning = 'ABSOLUTE'; ri.x = 0; ri.y = 0; }
  ri.componentPropertyReferences = { visible: key };
  const tc = await figma.getNodeByIdAsync(L.tagsCol), host = tc.parent;
  let tg = host.children.find(n => n.name === 'Ценники после замены');
  if (!tg) {
    tg = figma.createFrame(); tg.name = 'Ценники после замены'; tg.fills = []; tg.clipsContent = false; tg.resize(W, H);
    host.insertChild(host.children.indexOf(tc) + 1, tg); tg.layoutPositioning = 'ABSOLUTE'; tg.x = 0; tg.y = 0;
    const main = await tc.children[0].getMainComponentAsync();
    for (const T of L.tags) {
      const t = main.createInstance(); tg.appendChild(t); t.x = T.x; t.y = T.y;
      const tx = t.findOne(n => n.type === 'TEXT'); for (const s of tx.getStyledTextSegments(['fontName'])) await figma.loadFontAsync(s.fontName);
      tx.characters = T.text;
    }
  }
  tg.componentPropertyReferences = { visible: key };
  out.win.push(w.id + ': render ' + ri.id + ' ' + Math.round(ri.width) + 'x' + Math.round(ri.height) + ' · tags ' + tg.id + ' ' +
    tg.children.map(t => Math.round(t.x) + ',' + Math.round(t.y) + ' ' + Math.round(t.width) + 'x' + Math.round(t.height) + '=' + t.findOne(n => n.type === 'TEXT').characters).join(' | '));
}
return out;
