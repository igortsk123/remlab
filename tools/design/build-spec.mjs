// СПЕЦИФИКАЦИЯ ДЛЯ ПЕРЕНОСА В ФИГМУ КОННЕКТОРОМ (план design-01-figma-export, п.1): на компонент — JSON ≤ 18 КБ.
// Из замера живой страницы (capture.mjs → tree): размеры, auto-layout (направление, padding, gap, выравнивание), заливки/обводки/тени/
// радиусы ССЫЛКАМИ на токены (tokens.json), текстовые стили ссылками (typography.*), варианты, вложенные компоненты.
// + order.json — порядок сборки: сначала атомы (уровень 1), потом составные (уровень = 1 + максимум вложенных).
//   node tools/design/build-spec.mjs <OUT>
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { REGISTRY } from "./registry.mjs";
import { parseRules, selectorLines, SRC_REL } from "./lib-css.mjs";

const OUT = process.argv[2]; const SPEC = join(OUT, "figma-spec"); mkdirSync(SPEC, { recursive: true });
const LIMIT = process.env.SPEC_LIMIT === "0" ? Infinity : 18 * 1024;   // п.5: SPEC_LIMIT=0 — без лимита и без обрезки (данные идут сжатыми группами)
const cap = join(OUT, "capture");
const samples = readdirSync(cap).filter((f) => /^samples-.*\.json$/.test(f)).sort().flatMap((f) => JSON.parse(readFileSync(join(cap, f), "utf8")));
const probes = Object.fromEntries(readdirSync(cap).filter((f) => /^probe-.*\.json$/.test(f)).map((f) => [f.slice(6, -5), JSON.parse(readFileSync(join(cap, f), "utf8"))]));
const T = JSON.parse(readFileSync(join(OUT, "tokens.json"), "utf8"));
const rules = parseRules();

// ——— сопоставление значений с токенами ———
const hx = (n) => Math.round(n).toString(16).padStart(2, "0");
function rgbHex(s) {
  let m = s && s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
  if (m) { const a = m[4] === undefined ? 1 : +m[4]; return "#" + hx(+m[1]) + hx(+m[2]) + hx(+m[3]) + (a < 1 ? hx(a * 255) : ""); }
  m = s && s.match(/color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/);
  if (m) { const a = m[4] === undefined ? 1 : +m[4]; return "#" + hx(m[1] * 255) + hx(m[2] * 255) + hx(m[3] * 255) + (a < 1 ? hx(a * 255) : ""); }
  return null;
}
const colorByHex = new Map();
for (const [k, v] of Object.entries(T.color || {})) { const val = String(v.$value); if (/^#/.test(val) && !colorByHex.has(val)) colorByHex.set(val, `color.${k}`); }
const near = (a, b) => { const p = (h) => [1, 3, 5, 7].map((i) => parseInt(h.slice(i, i + 2) || "ff", 16)); const x = p(a), y = p(b); return x.every((v, i) => Math.abs(v - y[i]) <= 2); };
function colorRef(css) {
  const h = rgbHex(css); if (!h) return css ? { css } : null; if (h.length === 9 && h.endsWith("00")) return null;
  if (colorByHex.has(h)) return { token: colorByHex.get(h) };
  for (const [hex, tok] of colorByHex) if (hex.length === h.length && near(hex, h)) return { token: tok, approx: h };
  return { hex: h };
}
const shadowByCss = new Map(); for (const p of Object.values(probes)) for (const [k, v] of Object.entries(p.shadow || {})) if (!shadowByCss.has(v)) shadowByCss.set(v, `shadow.${k.slice(2)}`);
const shadowRef = (css) => (!css || css === "none" ? null : shadowByCss.has(css) ? { token: shadowByCss.get(css) } : { css });
const RAD = { "8px": "radius.r-xs", "12px": "radius.radius-sm", "16px": "radius.radius", "20px": "radius.r-lg", "999px": "radius.pill" };
function radiusRef(st, w, h) {
  const c = [st.borderTopLeftRadius, st.borderTopRightRadius, st.borderBottomRightRadius, st.borderBottomLeftRadius].map((x) => x || "0px");
  if (c.every((x) => x === "0px")) return null;
  const one = (x) => { if (/%$/.test(x)) return parseFloat(x) >= 50 ? { circle: true } : { css: x }; const px = parseFloat(x); if (px >= Math.min(w, h) / 2 && px >= 30) return { token: "radius.pill", px }; return RAD[x] ? { token: RAD[x] } : { px }; };
  if (c.every((x) => x === c[0])) return one(c[0]);
  return { corners: c.map(one) };
}
const typoBy = new Map(); for (const [k, v] of Object.entries(T.typography || {})) typoBy.set(`${k.split("/")[0]}|${v.$value.fontSize}|${v.$value.fontWeight}`, `typography.${k}`);
const fsTok = new Map(); for (const [k, v] of Object.entries(T.fontSize || {})) if (/px$/.test(v.$value) && !fsTok.has(v.$value)) fsTok.set(v.$value, `fontSize.${k}`);
const spaceTok = new Map(); for (const [k, v] of Object.entries(T.space || {})) spaceTok.set(v.$value, `space.${k}`);
const sp = (px) => { if (!px || px === "0px" || px === "normal") return 0; return spaceTok.has(px) ? { px: parseFloat(px), token: spaceTok.get(px) } : parseFloat(px); };
const ALIGN = { "flex-start": "MIN", start: "MIN", normal: "MIN", left: "MIN", center: "CENTER", "flex-end": "MAX", end: "MAX", right: "MAX", "space-between": "SPACE_BETWEEN", "space-around": "SPACE_BETWEEN", "space-evenly": "SPACE_BETWEEN", baseline: "BASELINE", stretch: "STRETCH" };

// наследуемое оформление текста (замер пишет у потомка только отличия от родителя)
const INH = ["color", "fontSize", "fontWeight", "lineHeight", "textAlign", "whiteSpace", "textTransform", "textOverflow"];
function nodeSpec(n, dev, depth = 0, inh = {}, files = {}) {
  const st0 = n.st || {}; const st = { ...st0 }; for (const k of INH) if (st[k] === undefined && inh[k] !== undefined && (n.text || k === "textAlign" || k === "whiteSpace")) st[k] = inh[k];
  const inhK = { ...inh }; for (const k of INH) if (st0[k] !== undefined) inhK[k] = st0[k];
  const o = { name: n.el };
  const leaf = !!n.text && !(n.children && n.children.length);
  // текст «в коробке» (кнопка, плашка: заливка/рамка/отступы) — в Фигме это фрейм с auto-layout и текстовым слоем внутри
  const boxy = leaf && (!!colorRef(st.backgroundColor) || ["borderTopWidth", "borderBottomWidth", "borderLeftWidth"].some((k) => parseFloat(st[k] || "0") > 0) || ["paddingTop", "paddingLeft"].some((k) => parseFloat(st[k] || "0") > 0) || (st.backgroundImage && st.backgroundImage !== "none"));
  const isText = leaf && !boxy;
  o.type = n.img ? "IMAGE" : n.svg ? "SVG" : n.canvas ? "IMAGE" : isText ? "TEXT" : "FRAME";
  o.size = { w: n.w, h: n.h }; if (depth) o.pos = { x: n.x, y: n.y };
  const disp = st.display || "block";
  if (o.type === "FRAME") {
    const lay = {};
    if (/flex/.test(disp)) { lay.mode = (st.flexDirection || "row").startsWith("column") ? "VERTICAL" : "HORIZONTAL"; if (st.flexWrap === "wrap") lay.wrap = true; }
    else if (/grid/.test(disp)) { lay.mode = "GRID"; if (st.gridTemplateColumns) lay.columns = st.gridTemplateColumns; }
    else if (boxy) { lay.mode = "HORIZONTAL"; lay.approx = "текст в коробке"; lay.primaryAlign = st.textAlign === "center" ? "CENTER" : /right|end/.test(st.textAlign || "") ? "MAX" : "MIN"; lay.counterAlign = "CENTER"; }
    else if (n.children && n.children.length) { lay.mode = "VERTICAL"; lay.approx = "block flow"; }
    else lay.mode = "NONE";
    const pad = [st.paddingTop, st.paddingRight, st.paddingBottom, st.paddingLeft].map(sp); if (pad.some((x) => x)) lay.padding = { t: pad[0], r: pad[1], b: pad[2], l: pad[3] };
    const gap = lay.mode === "VERTICAL" ? st.rowGap : st.columnGap; if (gap && gap !== "normal" && gap !== "0px") lay.gap = sp(gap);
    if (lay.mode === "GRID" && st.rowGap && st.rowGap !== "normal") lay.rowGap = sp(st.rowGap);
    if (st.justifyContent && /flex|grid/.test(disp)) lay.primaryAlign = ALIGN[st.justifyContent] || st.justifyContent;
    if (st.alignItems && /flex|grid/.test(disp)) lay.counterAlign = ALIGN[st.alignItems] || st.alignItems;
    if (/absolute|fixed/.test(st.position || "")) lay.positioning = st.position === "fixed" ? "ABSOLUTE (fixed к экрану)" : "ABSOLUTE";
    if (st.position === "sticky") lay.sticky = true;
    if (/hidden|clip|auto|scroll/.test(st.overflowX || st.overflowY || "")) lay.clip = true;
    if (/auto|scroll/.test(st.overflowY || "")) lay.scroll = "VERTICAL"; else if (/auto|scroll/.test(st.overflowX || "")) lay.scroll = "HORIZONTAL";
    o.layout = lay;
  }
  if (/absolute|fixed/.test(st.position || "") && o.type !== "FRAME") o.positioning = "ABSOLUTE";
  const fill = colorRef(st.backgroundColor); const fills = []; if (fill) fills.push(fill);
  if (st.backgroundImage && st.backgroundImage !== "none") fills.push(/hatch|repeating-linear-gradient\(-45deg/.test(st.backgroundImage) ? { token: "gradient.hatch" } : { css: st.backgroundImage.slice(0, 200) });
  if (fills.length) o.fills = fills;
  const bw = [st.borderTopWidth, st.borderRightWidth, st.borderBottomWidth, st.borderLeftWidth].map((x) => parseFloat(x || "0"));
  if (bw.some((x) => x > 0)) { const c = colorRef(st.borderTopColor || st.borderBottomColor || st.borderLeftColor || st.borderRightColor); o.stroke = { ...(c || {}), weight: bw.every((x) => x === bw[0]) ? bw[0] : { t: bw[0], r: bw[1], b: bw[2], l: bw[3] }, style: st.borderTopStyle || "solid", align: "INSIDE" }; }
  const r = radiusRef(st, n.w, n.h); if (r) o.radius = r;
  const sh = shadowRef(st.boxShadow); if (sh) o.effects = [sh];
  if (st.backdropFilter && st.backdropFilter !== "none") (o.effects || (o.effects = [])).push({ backgroundBlur: st.backdropFilter });
  if (st.opacity) o.opacity = +st.opacity;
  if (n.text) {
    const key = `${dev}|${st.fontSize || ""}|${st.fontWeight || ""}`;
    o.text = { content: n.text };
    if (st.fontSize || st.fontWeight || st.lineHeight) o.text.style = typoBy.get(key) ? { token: typoBy.get(key) } : { size: st.fontSize, sizeToken: fsTok.get(st.fontSize), weight: st.fontWeight, lineHeight: st.lineHeight };
    if (st.color) o.text.color = colorRef(st.color);
    if (st.textAlign && st.textAlign !== "start") o.text.align = st.textAlign;
    if (st.textTransform && st.textTransform !== "none") o.text.transform = st.textTransform;
    if (st.textDecorationLine) o.text.decoration = st.textDecorationLine;
    if (st.whiteSpace === "nowrap") o.text.wrap = false;
    if (st.textOverflow === "ellipsis") o.text.truncate = true;
  } else if (st.color && depth === 0) o.textColor = colorRef(st.color);
  if (depth === 0 && st.fontFamily) o.fontFamily = { token: "fontFamily.base", computed: st.fontFamily };
  if (n.img) o.image = { src: n.img.startsWith("shot:") ? "asset:" + (files[n.img] || "") : n.img, fit: st.objectFit || "fill" };
  if (n.canvas) o.image = { src: files["cv:" + n.cv] ? "asset:" + files["cv:" + n.cv] : "", fit: "cover", canvas: true };
  if (n.bgimg) o.bgImage = n.bgimg;
  if (n.svg) o.svg = n.svg;
  if (n.text && n.tb) { o.textBox = n.tb; o.lines = n.lines; }
  if (n.runs) o.runs = n.runs.map((r) => ({ s: r.s, e: r.e, fw: r.fw, size: r.fs, color: colorRef(r.color) }));
  if (n.pseudo) o.pseudo = n.pseudo.map((p) => ({ part: p.p, size: [p.w, p.h], fill: colorRef(p.bg), radius: p.radius }));
  if (n.truncated) o.truncated = true;
  if (n.children && n.children.length) o.children = n.children.map((c) => nodeSpec(c, dev, depth + 1, inhK, files));
  if (boxy && o.text) { o.children = [{ name: "label", type: "TEXT", sizing: "HUG", text: o.text, ...(o.textBox ? { size: { w: o.textBox.w, h: o.textBox.h }, pos: { x: o.textBox.x, y: o.textBox.y }, lines: o.lines } : {}), ...(o.runs ? { runs: o.runs } : {}) }]; delete o.text; delete o.textBox; delete o.runs; }
  return o;
}
// ——— вложенные компоненты: класс/ид из `sel` другого компонента встречается в дереве ———
const sig = (sel) => sel.split(",")[0].trim().split(/\s+/).pop().replace(/:[\w-]+(\([^)]*\))?/g, "");
const sigParts = (s) => (s.match(/[.#][\w-]+/g) || []);
const elHas = (el, parts) => parts.every((p) => (p[0] === "#" ? el.includes("#" + p.slice(1) + ".") || el.endsWith("#" + p.slice(1)) || el.includes("#" + p.slice(1)) : el.split(".").slice(1).includes(p.slice(1))));
function nestedOf(figma, trees) {
  const out = new Set();
  for (const c of REGISTRY) { if (c.figma === figma) continue; const parts = sigParts(sig(c.sel)); if (!parts.length) continue;
    const hit = (n, d) => d > 0 && elHas(n.el, parts) || (n.children || []).some((k) => hit(k, d + 1));
    if (trees.some((t) => hit(t, 0))) out.add(c.figma); }
  return [...out];
}
// ——— сборка ———
const byComp = new Map(); for (const s of samples) { if (!byComp.has(s.figma)) byComp.set(s.figma, []); byComp.get(s.figma).push(s); }
const vk = (v) => Object.entries(v).filter(([, x]) => x !== undefined).map(([k, x]) => `${k}=${x}`).join(",");
const fileOf = (figma) => figma.replace(/\//g, "__").replace(/[^\w.-]+/g, "-") + ".json";
function prune(node, maxDepth, d = 0) { const o = { ...node }; if (o.children) { if (d >= maxDepth) { o.children = undefined; o.truncated = `глубже ${maxDepth} — см. HTML образца в kit/`; } else o.children = o.children.map((c) => prune(c, maxDepth, d + 1)); } return o; }
const levels = {}; const nestedMap = {}; const parts = [];
for (const c of REGISTRY) {
  const list = byComp.get(c.figma) || [];
  const seen = new Set(); const vars = [];
  for (const s of list) { const k = vk(s.variant); if (seen.has(k)) continue; seen.add(k); vars.push(s); }
  nestedMap[c.figma] = nestedOf(c.figma, vars.map((s) => s.tree).filter(Boolean));
  const props = {}; for (const s of vars) for (const [k, v] of Object.entries(s.variant)) { (props[k] = props[k] || new Set()).add(String(v)); }
  const head = { component: c.figma, description: c.desc, selector: c.sel, source: [...new Set(c.css.flatMap((x) => selectorLines(rules, x)))].sort((a, b) => a - b).map((l) => `${SRC_REL}:${l}`),
    statesInCode: c.states, properties: Object.fromEntries(Object.entries(props).map(([k, v]) => [k, [...v]])), nested: nestedMap[c.figma],
    notes: ["Значения — замер Chromium на Linux: system-ui = DejaVu Sans; в Фигме — fontFamily.base (на iPhone это SF Pro). Размеры — px при 375×812 (phone) и 1440×900 (desktop).",
      "fills/stroke/effects/radius — {token: …} ссылается на tokens.json; {hex|px|css} — значения вне токенов (кандидаты)."] };
  if (!vars.length) { head.variants = []; head.captured = false; head.why = "живым обходом не снято — см. statesInCode и components.md"; }
  // варианты: полный кадр; если не влезает — глубина меньше; если всё равно — части
  let depth = LIMIT === Infinity ? 99 : 6; let body;
  const build = (d) => vars.map((s) => ({ key: vk(s.variant), props: s.variant, size: { w: s.w, h: s.h }, screen: s.screen, frame: prune(nodeSpec(s.tree, s.variant.device, 0, {}, s.files || {}), d) }));
  for (;;) { body = build(depth); const one = JSON.stringify({ ...head, variants: body }); if (one.length <= LIMIT || depth <= 2) break; depth--; }
  const out = []; let cur = []; const baseLen = JSON.stringify({ ...head, part: "1/1", variants: [] }).length;
  for (const v of body) { const L = JSON.stringify(v).length; const curLen = JSON.stringify(cur).length; if (cur.length && baseLen + curLen + L + 2 > LIMIT) { out.push(cur); cur = []; } cur.push(v); }
  if (cur.length || !out.length) out.push(cur);
  const fn = fileOf(c.figma);
  out.forEach((vs, i) => {
    const name = i === 0 ? fn : fn.replace(/\.json$/, `--${i + 1}.json`);
    let obj = { ...head, part: `${i + 1}/${out.length}`, ...(depth < 6 && LIMIT !== Infinity ? { prunedDepth: depth } : {}), variants: vs };
    let txt = JSON.stringify(obj);
    if (txt.length > LIMIT) { // последний рубеж: один вариант — урезать дерево до 1 уровня
      obj.variants = vs.map((v) => ({ ...v, frame: prune(v.frame, 1) })); obj.prunedDepth = 1; txt = JSON.stringify(obj); }
    writeFileSync(join(SPEC, name), txt);
    parts.push({ file: name, bytes: txt.length, component: c.figma, variants: vs.length });
  });
}
// уровни сборки
const lv = (f, stack = []) => { if (levels[f]) return levels[f]; if (stack.includes(f)) return 1; const n = nestedMap[f] || []; const l = n.length ? 1 + Math.max(...n.map((x) => lv(x, [...stack, f]))) : 1; levels[f] = l; return l; };
REGISTRY.forEach((c) => lv(c.figma));
const order = { $description: "Порядок сборки в Фигме коннектором: 0 — переменные из tokens.json; затем уровни: 1 — атомы (без вложенных), далее — составные (1 + максимум вложенных). Внутри уровня — по категориям.",
  steps: [{ level: 0, what: "variables", file: "../tokens.json", collections: Object.keys(T).filter((k) => !k.startsWith("$")) }],
  components: REGISTRY.map((c) => ({ component: c.figma, level: levels[c.figma], nested: nestedMap[c.figma], files: parts.filter((p) => p.component === c.figma).map((p) => p.file), captured: (byComp.get(c.figma) || []).length > 0 }))
    .sort((a, b) => a.level - b.level || a.component.localeCompare(b.component)) };
writeFileSync(join(SPEC, "order.json"), JSON.stringify(order, null, 1));
const maxB = Math.max(...parts.map((p) => p.bytes));
console.log(`figma-spec: файлов ${parts.length} (компонентов ${REGISTRY.length}), макс ${maxB} байт, > 18 КБ: ${parts.filter((p) => p.bytes > LIMIT).length}; уровни: ${JSON.stringify(Object.values(levels).reduce((a, l) => (a[l] = (a[l] || 0) + 1, a), {}))}`);
