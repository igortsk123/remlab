// Сборщик v2 (design-01 п.5). Тело async-функции с параметром P (данные gen2.py); хранится в файле Фигмы:
// figma.root sharedPluginData remlab/builder2. P = {page, dev, maxW, only?, sections:[{sec,set,say,code,variants:[{name,cap,screen,root}]}]}
// Узлы: F — рамка (m: HORIZONTAL|VERTICAL|NONE, k — дети), T — текст, S — значок svg, I — фото (заливается upload_assets).
const out = { page: P.page, sections: [], warn: [], fit: [], images: [] };
const colls = await figma.variables.getLocalVariableCollectionsAsync();
const cname = {}; for (const c of colls) cname[c.id] = c.name;
const V = {}; for (const v of await figma.variables.getLocalVariablesAsync()) V[cname[v.variableCollectionId] + ':' + v.name] = v;
const TS = {}; for (const s of await figma.getLocalTextStylesAsync()) TS[s.name] = s;
const FX = {}; for (const s of await figma.getLocalEffectStylesAsync()) FX[s.name] = s;
const FW = { Regular: 'Regular', Medium: 'Medium', Semibold: 'Semi Bold', Bold: 'Bold' };
for (const st of Object.values(FW)) await figma.loadFontAsync({ family: 'Inter', style: st });
const hexc = (h) => { h = String(h).replace('#', ''); const n = (i) => parseInt(h.slice(i, i + 2), 16) / 255; return { c: { r: n(0), g: n(2), b: n(4) }, a: h.length >= 8 ? n(6) : 1 }; };
function paint(f) {
  if (!f) return null;
  if (f.v && V[f.v]) return figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', V[f.v]);
  if (f.v) out.warn.push('нет переменной ' + f.v);
  if (f.hex) { const k = hexc(f.hex); return { type: 'SOLID', color: k.c, opacity: k.a }; }
  return null;
}
function num(node, field, o) {
  if (o == null) return;
  if (typeof o === 'number') { node[field] = o; return; }
  if (o.px != null) node[field] = o.px;
  if (o.v && V[o.v]) { try { node.setBoundVariable(field, V[o.v]); } catch (e) { out.warn.push(field + ': ' + e.message); } }
}
async function style(n, r) {
  if (r.f) n.fills = r.f.map(paint).filter(Boolean);
  if (r.s) {
    const p = paint(r.s);
    if (p) {
      n.strokes = [p]; n.strokeAlign = 'INSIDE';
      if (r.s.sides) { n.strokeTopWeight = r.s.sides[0]; n.strokeRightWeight = r.s.sides[1]; n.strokeBottomWeight = r.s.sides[2]; n.strokeLeftWeight = r.s.sides[3]; }
      else n.strokeWeight = r.s.w || 1;
      if (r.s.d) n.dashPattern = [4, 4];
    }
  }
  if (r.r) {
    if (r.r.c) { n.topLeftRadius = r.r.c[0]; n.topRightRadius = r.r.c[1]; n.bottomRightRadius = r.r.c[2]; n.bottomLeftRadius = r.r.c[3]; }
    else {
      n.cornerRadius = r.r.px || 0;
      if (r.r.v && V[r.r.v]) for (const k of ['topLeftRadius', 'topRightRadius', 'bottomLeftRadius', 'bottomRightRadius']) { try { n.setBoundVariable(k, V[r.r.v]); } catch (e) {} }
    }
  }
  if (r.fx) for (const e of r.fx) if (FX[e]) { await n.setEffectStyleIdAsync(FX[e].id); break; }
  if (r.o != null) n.opacity = r.o;
}
function hatch(f, r) {
  const H = r.hatch, w = r.w, h = r.h, step = H.per * Math.SQRT2;
  let d = ''; for (let x = -h; x < w + h; x += step) d += 'M' + x.toFixed(2) + ' ' + h + 'L' + (x + h).toFixed(2) + ' 0';
  const v = figma.createNodeFromSvg('<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '"><path d="' + d + '" stroke="#a93b27" stroke-width="' + H.band + '" fill="none"/></svg>');
  v.name = 'Штриховка'; v.fills = [];
  const p1 = paint(H.c1); if (p1) for (const n of v.findAll((n) => n.type === 'VECTOR')) { n.strokes = [p1]; n.name = 'Полосы'; }
  const p2 = paint(H.c2); f.fills = p2 ? [p2] : [];
  f.clipsContent = true; f.appendChild(v);
  if (f.layoutMode !== 'NONE') v.layoutPositioning = 'ABSOLUTE';
  v.x = 0; v.y = 0; v.locked = true;
}
async function text(r, inAuto) {
  const t = figma.createText();
  t.fontName = { family: 'Inter', style: FW[r.st] || 'Regular' };
  t.characters = r.c || ' ';
  const sty = TS[r.ts];
  if (sty) await t.setTextStyleIdAsync(sty.id); else { t.fontName = { family: 'Inter', style: FW[r.st] || 'Regular' }; t.fontSize = r.sz || 14; }
  if (r.lh) { const L = t.lineHeight; const cur = L.unit === 'PIXELS' ? L.value : L.unit === 'PERCENT' ? L.value * t.fontSize / 100 : null; if (cur == null || Math.abs(cur - r.lh) > 0.3) t.lineHeight = { unit: 'PIXELS', value: r.lh }; }
  if (r.up) t.textCase = 'UPPER';
  if (r.ud) t.textDecoration = 'UNDERLINE';
  const p = paint(r.tc); if (p) t.fills = [p];
  const len = t.characters.length;
  for (const q of r.runs || []) {
    const s = Math.max(0, q.s), e = Math.min(len, q.e); if (e <= s) continue;
    if (q.st) t.setRangeFontName(s, e, { family: 'Inter', style: FW[q.st] || 'Regular' });
    if (q.sz) t.setRangeFontSize(s, e, q.sz);
    if (q.tc) { const pp = paint(q.tc); if (pp) t.setRangeFills(s, e, [pp]); }
  }
  t.textAlignHorizontal = r.al === 'C' ? 'CENTER' : r.al === 'R' ? 'RIGHT' : 'LEFT';
  t.textAlignVertical = 'CENTER';
  if (r.hug && inAuto) {
    t.textAutoResize = 'WIDTH_AND_HEIGHT';
    if (t.width > r.w + 1) out.fit.push(['шире сайта', (r.c || '').slice(0, 30), Math.round(t.width), r.w]);
  } else {
    t.textAutoResize = 'HEIGHT'; t.resize(Math.max(1, r.w), t.height);
    const one = r.nw || r.tr || r.ln === 1;
    if (t.height > r.h + 1) {
      if (one) out.fit.push(['не влез в строку — многоточие', (r.c || '').slice(0, 30), Math.round(t.width), r.w]);
      else out.fit.push(['выше сайта', (r.c || '').slice(0, 30), Math.round(t.height), r.h]);
    }
    if (one) { t.textTruncation = 'ENDING'; t.maxLines = 1; }
  }
  return t;
}
async function frame(r) {
  const f = figma.createFrame(); f.fills = [];
  const auto = r.m === 'HORIZONTAL' || r.m === 'VERTICAL';
  if (auto) {
    f.layoutMode = r.m;
    if (r.wrap && r.m === 'HORIZONTAL') f.layoutWrap = 'WRAP';
    if (r.p) ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].forEach((k, i) => num(f, k, r.p[i]));
    if (r.g) num(f, 'itemSpacing', r.g);
    f.primaryAxisAlignItems = { CENTER: 'CENTER', MAX: 'MAX', SPACE_BETWEEN: 'SPACE_BETWEEN' }[r.pa] || 'MIN';
    f.counterAxisAlignItems = { CENTER: 'CENTER', MAX: 'MAX', BASELINE: 'BASELINE' }[r.ca] || 'MIN';
  }
  f.resize(Math.max(0.01, r.w), Math.max(0.01, r.h));
  if (auto) { f.primaryAxisSizingMode = (r.hugH && r.m === 'VERTICAL') || (r.hugW && r.m === 'HORIZONTAL') ? 'AUTO' : 'FIXED'; f.counterAxisSizingMode = 'FIXED'; }
  f.clipsContent = !!r.clip;
  await style(f, r);
  if (r.bg) { f.setSharedPluginData('remlab', 'src', r.bg); out.images.push({ id: f.id, src: r.bg, kind: 'фон' }); }
  for (const k of r.k || []) {
    const ch = await build(k, auto);
    f.appendChild(ch);
    if (auto && k.abs) { ch.layoutPositioning = 'ABSOLUTE'; ch.x = k.x; ch.y = k.y; }
    else if (auto) {
      if (k.sp) ch.layoutGrow = 1;
      else if (r.ca === 'STRETCH') ch.layoutAlign = 'STRETCH';
      if (k.t === 'T' && k.hug) ch.layoutSizingHorizontal = 'HUG';
    } else { ch.x = k.x; ch.y = k.y; }
  }
  if (r.hatch) hatch(f, r);
  return f;
}
async function build(r, inAuto) {
  let n;
  if (r.t === 'T') n = await text(r, inAuto);
  else if (r.t === 'S') {
    try { n = figma.createNodeFromSvg(r.svg); n.fills = []; } catch (e) { out.warn.push('svg: ' + e.message); n = figma.createFrame(); n.fills = []; }
    if (Math.abs(n.width - r.w) > 0.5 || Math.abs(n.height - r.h) > 0.5) n.resize(Math.max(0.01, r.w), Math.max(0.01, r.h));
  } else if (r.t === 'I') {
    n = figma.createRectangle(); n.resize(Math.max(1, r.w), Math.max(1, r.h));
    const p = paint({ v: 'Цвета:Фон/Подложка тёмная' }); if (p) n.fills = [p];
    if (r.r) await style(n, { r: r.r });
    n.setSharedPluginData('remlab', 'src', r.src || ''); n.setSharedPluginData('remlab', 'fit', r.fit || 'cover');
    out.images.push({ id: n.id, src: r.src, kind: r.n });
  } else n = await frame(r);
  n.name = r.n || (r.t === 'T' ? (r.c || 'Текст').slice(0, 40) : 'Блок');
  if (r.css) n.setSharedPluginData('remlab', 'css', r.css);
  return n;
}
// ——— страница: секция на набор, «что это» над набором, подпись над каждым вариантом
const page = figma.root.children.find((p) => p.name === P.page);
if (!page) return { err: 'нет страницы ' + P.page };
await figma.setCurrentPageAsync(page);
const only = P.only ? new Set(P.only) : null;
const PAD = 40, SP = 24, GX = 48, GY = 40, CAP = 18, CAPG = 8;
const capPaint = paint({ v: 'Цвета:Текст/Второстепенный' }) || { type: 'SOLID', color: { r: 0.47, g: 0.44, b: 0.42 } };
const say = (s, size, st) => { const t = figma.createText(); t.fontName = { family: 'Inter', style: st || 'Regular' }; t.fontSize = size; t.characters = s; t.fills = [capPaint]; return t; };
for (const s of P.sections) {
  if (only && !only.has(s.sec)) continue;
  for (const n of page.children.filter((n) => (n.type === 'SECTION' && n.name === s.sec) || (n.type === 'COMPONENT_SET' && n.name === s.set))) n.remove();
  const comps = [], caps = [];
  for (const v of s.variants) {
    const fr = await build(v.root, false);
    page.appendChild(fr); fr.x = -5000; fr.y = 0;
    const c = figma.createComponentFromNode(fr);
    c.name = v.name;
    c.setSharedPluginData('remlab', 'screen', v.screen || '');
    comps.push(c);
    const cap = say(v.cap || v.name, 12, 'Medium'); cap.name = 'Подпись варианта'; cap.setSharedPluginData('remlab', 'variant', v.name); caps.push(cap);
  }
  const set = figma.combineAsVariants(comps, page);
  set.name = s.set; set.description = s.say || ''; set.setSharedPluginData('remlab', 'code', s.code || '');
  // элементы, которые на сайте лежат поверх фото/сцены, — на тёмной подложке набора, иначе белое на белом не видно
  if (s.setBg) { const p = paint(s.setBg); if (p) set.fills = [p]; }
  // строгая таблица: колонка = самая широкая ячейка набора (вариант или подпись), одна для всех колонок;
  // ячейка прижата к левому верхнему углу; высота строки = самая высокая в строке; каждый язык — с новой строки
  const colW = Math.max(160, Math.ceil(Math.max(...comps.map((c) => c.width))));
  caps.forEach((t) => { if (t.width > colW) { t.textAutoResize = 'HEIGHT'; t.resize(colW, t.height); } });
  const ncol = Math.max(1, Math.floor((P.maxW - 2 * SP + GX) / (colW + GX)));
  const rows = []; let cur = null, lang = null;
  s.variants.forEach((v, i) => {
    if (!cur || cur.length >= ncol || (v.lang || '') !== lang) { cur = []; rows.push(cur); lang = v.lang || ''; }
    cur.push(i);
  });
  const pos = []; let y = SP, used = 0;
  for (const r of rows) {
    const rowH = Math.max(...r.map((i) => comps[i].height));
    const capH = Math.max(CAP, ...r.map((i) => Math.ceil(caps[i].height)));
    r.forEach((i, k) => { const x = SP + k * (colW + GX); comps[i].x = x; comps[i].y = y + capH + CAPG; pos[i] = [x, y]; });
    used = Math.max(used, r.length); y += capH + CAPG + rowH + GY;
  }
  set.resizeWithoutConstraints(SP * 2 + used * colW + (used - 1) * GX, y - GY + SP);
  const sec = figma.createSection(); sec.name = s.sec; page.appendChild(sec);
  sec.setSharedPluginData('remlab', 'code', s.code || '');
  const title = say(s.say || s.sec, 14, 'Regular'); title.name = 'Что это';
  sec.appendChild(title); title.x = PAD; title.y = PAD;
  title.textAutoResize = 'WIDTH_AND_HEIGHT'; if (title.width > 900) { title.textAutoResize = 'HEIGHT'; title.resize(900, title.height); }
  sec.appendChild(set); set.x = PAD; set.y = PAD + title.height + 16;
  caps.forEach((cap, i) => { sec.appendChild(cap); cap.x = set.x + pos[i][0]; cap.y = set.y + pos[i][1]; });
  sec.resizeWithoutConstraints(Math.max(set.x + set.width, title.x + title.width) + PAD, set.y + set.height + PAD);
  out.sections.push({ sec: s.sec, id: sec.id, setId: set.id, variants: comps.length, size: [Math.round(sec.width), Math.round(sec.height)] });
}
// раскладка секций столбцом по фактическим размерам (порядок — как в данных), отступ 120
const order = P.sections.map((s) => s.sec);
const secs = page.children.filter((n) => n.type === 'SECTION').sort((a, b) => ((order.indexOf(a.name) + 1) || 999) - ((order.indexOf(b.name) + 1) || 999));
let yy = 0; for (const n of secs) { n.x = 0; n.y = yy; yy += n.height + 120; }
out.layout = secs.map((n) => [n.name, Math.round(n.y), Math.round(n.width), Math.round(n.height)]);
out.warn = [...new Set(out.warn)].slice(0, 20);
return out;
