// Проверка страницы деталей (design-01 п.5, только чтение). Подставить PAGE.
// 1) наложения секций; 2) в каждом варианте: текст за границами родителя, текст на соседе (сосед — любой видимый слой варианта,
//    кроме предков и намеренно абсолютных значков/штриховки); 3) пустые «Фото»/«Иконка (заглушка)»/пустые рамки без смысла.
const PAGE = (typeof P !== 'undefined' && P.page) || '__PAGE__';
const page = figma.root.children.find((p) => p.name === PAGE);
await figma.setCurrentPageAsync(page);
const bb = (n) => n.absoluteBoundingBox;
const inter = (a, b, tol = 0.5) => Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > tol && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > tol;
const inside = (a, b, tol = 0.5) => a.x >= b.x - tol && a.y >= b.y - tol && a.x + a.width <= b.x + b.width + tol && a.y + a.height <= b.y + b.height + tol;
const res = { page: PAGE, sections: 0, sectionOverlaps: [], variants: 0, texts: 0, textOut: [], textHit: [], emptyPhoto: [], stubs: [], emptyFrames: [], capHit: [], outOfVariant: [] };
const secs = page.children.filter((n) => n.type === 'SECTION');
res.sections = secs.length;
for (let i = 0; i < page.children.length; i++) for (let j = i + 1; j < page.children.length; j++) {
  const a = page.children[i], b = page.children[j];
  if (inter(bb(a), bb(b), 0)) res.sectionOverlaps.push([a.name, b.name]);
}
const isDeco = (n) => n.name === 'Штриховка' || n.name === 'Полосы' || n.name === 'Отступ';
for (const sec of secs) {
  // подписи вариантов и «что это» не налезают на варианты/друг на друга
  const loose = sec.children.filter((n) => n.type === 'TEXT');
  const set = sec.children.find((n) => n.type === 'COMPONENT_SET');
  if (set) for (const t of loose) {
    for (const c of set.children) if (inter(bb(t), bb(c))) res.capHit.push([sec.name, t.characters.slice(0, 20), c.name]);
    for (const u of loose) if (u !== t && inter(bb(t), bb(u))) res.capHit.push([sec.name, t.characters.slice(0, 20), u.characters.slice(0, 20)]);
  }
  for (const v of sec.findAllWithCriteria({ types: ['COMPONENT'] })) {
    res.variants++;
    const all = v.findAll((n) => n.visible !== false);
    const leaves = all.filter((n) => !isDeco(n) && (n.type === 'TEXT' || n.type === 'RECTANGLE' || n.type === 'VECTOR' || (n.type === 'FRAME' && (n.fills.length || n.strokes.length) )));
    // видимая часть слоя: рамка, урезанная всеми обрезающими предками до варианта (26.10, находка помощника 4: прокрученный
    // список лежит на y<0 под обрезкой — скрытые строки не «наезжают»). null — слой целиком скрыт.
    const vis = (n) => {
      let b = bb(n); if (!b) return null; b = { x: b.x, y: b.y, width: b.width, height: b.height };
      for (let a = n.parent; a && a !== v.parent; a = a.parent) if (a.clipsContent && bb(a)) {
        const c = bb(a), x0 = Math.max(b.x, c.x), y0 = Math.max(b.y, c.y), x1 = Math.min(b.x + b.width, c.x + c.width), y1 = Math.min(b.y + b.height, c.y + c.height);
        if (x1 - x0 <= 0.5 || y1 - y0 <= 0.5) return null; b = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
      }
      return b;
    };
    for (const t of all.filter((n) => n.type === 'TEXT')) {
      res.texts++;
      const p = t.parent; const tv = vis(t);
      if (!tv) continue;
      if (!inside(bb(t), bb(p))) res.textOut.push([sec.name, v.name, t.characters.slice(0, 24), Math.round(bb(t).width) + 'x' + Math.round(bb(t).height), p.name]);
      const tb = tv;
      for (const o of leaves) {
        if (o === t) continue;
        const ov = vis(o); if (!ov) continue;
        let anc = false; for (let a = t.parent; a; a = a.parent) if (a === o) { anc = true; break; }
        if (anc) continue;
        if (o.type !== 'TEXT' && o.layoutPositioning === 'ABSOLUTE') continue;
        // надпись поверх фото (фото лежит ниже по порядку слоёв) — так задумано на сайте
        if (o.type !== 'TEXT' && /Фото|кадр/.test(o.name) && all.indexOf(o) < all.indexOf(t)) continue;
        if (inter(tb, ov, 1)) res.textHit.push([sec.name, v.name, t.characters.slice(0, 24), o.name]);
      }
    }
    const vb = bb(v);
    for (const n of all) if (!isDeco(n) && n.absoluteBoundingBox && !inside(bb(n), vb, 1)) {
      let clipped = false; for (let a = n.parent; a; a = a.parent) { if (a.clipsContent) { clipped = true; break; } if (a === v) break; }
      if (!clipped) res.outOfVariant.push([sec.name, v.name, n.name]);
    }
    for (const n of all) {
      if (n.type === 'RECTANGLE' && /Фото|кадр/.test(n.name) && !n.fills.some((f) => f.type === 'IMAGE')) res.emptyPhoto.push([sec.name, v.name, n.name]);
      if (n.type === 'FRAME' && n.getSharedPluginData('remlab', 'src') && !n.fills.some((f) => f.type === 'IMAGE')) res.emptyPhoto.push([sec.name, v.name, n.name + ' (фон)']);
      if (/заглушка/i.test(n.name)) res.stubs.push([sec.name, v.name, n.name]);
      if (n.type === 'FRAME' && !isDeco(n) && !n.children.length && !n.fills.length && !n.strokes.length && !n.effects.length) res.emptyFrames.push([sec.name, v.name, n.name]);
    }
  }
}
const cnt = {}; for (const k of Object.keys(res)) if (Array.isArray(res[k])) { cnt[k] = res[k].length; res[k] = res[k].slice(0, 15); }
return { counts: cnt, ...res };
