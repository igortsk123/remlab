// ТОКЕНЫ ДИЗАЙНА ДЕМО → W3C Design Tokens (DTCG: `$type`/`$value`) — план design-01-figma-export, п.1.
// Источник — CSS страницы `tools/scout/flat215-demo/index.html` (все три блока <style>): переменные `:root` + литералы,
// встреченные ≥ 3 раз (кандидаты в токены, `$extensions.remlab.source = "literal"`, `count`). Текстовые стили (typography) —
// из замера живой страницы (`capture/computed-*.json` от capture.mjs), если он уже есть. Продукт не меняет.
//   node tools/design/tokens.mjs <OUT>        → <OUT>/tokens.json, <OUT>/tokens.md
import { writeFileSync, readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { parseRules, rootVars, readSrc, SRC_REL } from "./lib-css.mjs";

const OUT = process.argv[2]; if (!OUT) { console.error("нужна папка вывода"); process.exit(2); }
const html = readSrc(); const rules = parseRules(html);
const css = rules.filter((r) => !r.keyframes);
const allDecls = css.flatMap((r) => r.decls.map((d) => ({ ...d, selector: r.selector, media: r.media })));
const vars = rootVars(rules);
const MIN = 3;

// ——— цвета ———
const hx = (n) => Math.round(Math.max(0, Math.min(255, n))).toString(16).padStart(2, "0");
export function toHex(r, g, b, a = 1) { return "#" + hx(r) + hx(g) + hx(b) + (a < 1 ? hx(a * 255) : ""); }
function parseColor(s, resolve) {
  s = s.trim();
  let m;
  if ((m = s.match(/^#([0-9a-f]{3,8})$/i))) {
    let h = m[1]; if (h.length <= 4) h = [...h].map((c) => c + c).join("");
    const n = (i) => parseInt(h.slice(i, i + 2), 16); return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
  }
  if ((m = s.match(/^rgba?\(([^)]*)\)$/i))) {
    const p = m[1].replace(/\//, " ").split(/[\s,]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  if (s === "white" || s === "#fff") return { r: 255, g: 255, b: 255, a: 1 };
  if (s === "black") return { r: 0, g: 0, b: 0, a: 1 };
  if ((m = s.match(/^color-mix\(in srgb,\s*(.+?)\s+(\d+(?:\.\d+)?)%\s*,\s*transparent\s*\)$/i))) {
    const c = resolve ? resolve(m[1]) : parseColor(m[1]); if (!c) return null; return { ...c, a: c.a * Number(m[2]) / 100 };
  }
  if ((m = s.match(/^var\(--([\w-]+)\)$/)) && resolve) return resolve(s);
  return null;
}
const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|color-mix\([^()]*(?:\([^)]*\)[^()]*)*\)|\bwhite\b/g;

// ——— :root → токены ———
const rootMap = new Map(); for (const v of vars) if (!v.media.length && !rootMap.has(v.name)) rootMap.set(v.name, v);
const varUse = (name) => (html.match(new RegExp(`var\\(--${name.replace(/[-]/g, "\\-")}[,)]`, "g")) || []).length;
const resolveColor = (expr, seen = new Set()) => {
  const m = expr.trim().match(/^var\(--([\w-]+)(?:,\s*(.+))?\)$/);
  if (m) { if (seen.has(m[1])) return null; seen.add(m[1]); const v = rootMap.get(m[1]); if (!v) return m[2] ? resolveColor(m[2], seen) : null; return resolveColor(v.value, seen); }
  return parseColor(expr, (e) => resolveColor(e, seen));
};
const COLOR_GROUP = { bg: "page", surface: "surface", ink: "text", muted: "text", faint: "text", "ink-strong": "text", line: "border", grip: "border",
  accent: "brand", "accent-dark": "brand", "accent-soft": "brand", wash: "surface", "wash-2": "surface", "wash-3": "surface",
  "ok-bg": "status", "ok-ink": "status", "warn-bg": "status", "warn-ink": "status", "warn-line": "status", "bad-bg": "status", "bad-ink": "status",
  warn: "status", ok: "status", up: "budget", "up-soft": "budget", "fu-soft": "budget", scrim: "overlay", "scrim-soft": "overlay", veil: "overlay" };
const comment = (line) => { const L = html.split("\n")[line - 1] || ""; const m = L.match(/\/\*\s*(.*?)\s*\*\//); return m ? m[1] : undefined; };

const T = { $description: `Токены демо-страницы remont-lab /demo (как есть, ${new Date().toISOString().slice(0, 10)}). Источник: ${SRC_REL}. ` +
  "Значения :root — source=root; повторяющиеся литералы CSS (≥3) — source=literal с числом вхождений. Цвета — hex (#rrggbb[aa]).",
  color: {}, shadow: {}, radius: {}, zIndex: {}, dimension: {}, breakpoint: {}, fontFamily: {}, fontSize: {}, fontWeight: {}, lineHeight: {},
  space: {}, size: {}, opacity: {}, duration: {}, gradient: {}, typography: {} };
const ext = (o) => ({ remlab: o });
const md = []; // строки таблицы для tokens.md: [группа, имя, значение, источник, css]
const add = (group, name, tok, src, cssv, count) => { T[group][name] = tok; md.push([group, name, typeof tok.$value === "object" ? JSON.stringify(tok.$value) : String(tok.$value), src, cssv, count ?? ""]); };

// цвета :root
for (const [name, v] of rootMap) {
  const isColorName = COLOR_GROUP[name];
  if (!isColorName) continue;
  const alias = v.value.match(/^var\(--([\w-]+)\)$/);
  if (alias) {
    const cyc = alias[1] === name;
    add("color", name, { $type: "color", $value: cyc ? "#00000000" : `{color.${alias[1]}}`, $description: comment(v.line),
      $extensions: ext({ source: "root", css: `--${name}:${v.value}`, line: v.line, uses: varUse(name), ...(cyc ? { invalid: "ссылается сама на себя — в браузере значение не определено; в CSS используется" } : {}) }) },
    "root", v.value, varUse(name));
    continue;
  }
  const c = resolveColor(v.value); if (!c) continue;
  add("color", name, { $type: "color", $value: toHex(c.r, c.g, c.b, c.a), $description: comment(v.line),
    $extensions: ext({ source: "root", group: COLOR_GROUP[name], css: v.value, line: v.line, uses: varUse(name) }) }, "root", v.value, varUse(name));
}
// --danger используется с запасным значением, но в :root не объявлен
if (/var\(--danger,/.test(html)) {
  const m = html.match(/var\(--danger,\s*([^)]+)\)/); const c = parseColor(m[1]);
  add("color", "danger", { $type: "color", $value: toHex(c.r, c.g, c.b, c.a), $extensions: ext({ source: "fallback", css: m[0], note: "в :root не объявлен — работает запасное значение" }) }, "fallback", m[0], varUse("danger"));
}
// литеральные цвета
const litColors = new Map();
for (const d of allDecls) {
  if (d.prop.startsWith("--")) continue;
  for (const m of d.value.matchAll(COLOR_RE)) {
    const raw = m[0]; const c = parseColor(raw, (e) => resolveColor(e)); if (!c) continue;
    const hex = toHex(c.r, c.g, c.b, c.a); const e = litColors.get(hex) || { hex, raws: new Set(), count: 0, lines: [] };
    e.raws.add(raw); e.count++; if (e.lines.length < 6) e.lines.push(d.line); litColors.set(hex, e);
  }
}
const rootHex = new Map(Object.entries(T.color).filter(([, t]) => !String(t.$value).startsWith("{")).map(([k, t]) => [t.$value, k]));
for (const e of [...litColors.values()].sort((a, b) => b.count - a.count)) {
  if (e.count < MIN) continue;
  const same = rootHex.get(e.hex);
  const nm = "literal-" + e.hex.slice(1);
  add("color", nm, { $type: "color", $value: same ? `{color.${same}}` : e.hex,
    $extensions: ext({ source: "literal", count: e.count, css: [...e.raws].join(" | "), lines: e.lines, ...(same ? { equals: `--${same}` } : {}) }) }, "literal", [...e.raws].join(" | "), e.count);
}

// ——— тени (:root) ———
function splitTop(s, sep = ",") { const out = []; let d = 0, st = 0; for (let i = 0; i < s.length; i++) { if (s[i] === "(") d++; else if (s[i] === ")") d--; else if (s[i] === sep && d === 0) { out.push(s.slice(st, i).trim()); st = i + 1; } } out.push(s.slice(st).trim()); return out; }
function colorRef(expr) {
  const m = expr.match(/^var\(--([\w-]+)\)$/); if (m && T.color[m[1]]) return `{color.${m[1]}}`;
  const mm = expr.match(/^color-mix\(in srgb,\s*var\(--([\w-]+)\)\s+(\d+)%\s*,\s*transparent\)$/);
  const c = resolveColor(expr) || parseColor(expr, (e) => resolveColor(e)); return c ? toHex(c.r, c.g, c.b, c.a) : expr;
}
function parseShadow(v) {
  const layers = [];
  for (const part of splitTop(v)) {
    const ref = part.match(/^var\(--([\w-]+)\)$/); if (ref) { layers.push({ ref: ref[1] }); continue; }
    const inset = /\binset\b/.test(part); let s = part.replace(/\binset\b/, "").trim();
    const cm = s.match(COLOR_RE) || s.match(/var\(--[\w-]+\)/); const colorExpr = cm ? cm[0] : "#000";
    s = s.replace(colorExpr, "").trim(); const nums = s.split(/\s+/).filter(Boolean);
    const px = (x) => (x === undefined ? "0px" : /px$/.test(x) ? x : x + "px");
    layers.push({ color: colorRef(colorExpr), offsetX: px(nums[0]), offsetY: px(nums[1]), blur: px(nums[2]), spread: px(nums[3]), ...(inset ? { inset: true } : {}) });
  }
  return layers;
}
const SHADOWS = ["e1", "e2", "e3", "e4", "e4-up", "e4-side", "e5", "ring", "ring-sel", "ring-in", "ring-line", "ring-cut", "glow", "shadow"];
for (const n of SHADOWS) {
  const v = rootMap.get(n); if (!v) continue;
  let layers = parseShadow(v.value);
  if (layers.length === 1 && layers[0].ref) { add("shadow", n, { $type: "shadow", $value: `{shadow.${layers[0].ref}}`, $extensions: ext({ source: "root", css: v.value, line: v.line, uses: varUse(n) }) }, "root", v.value, varUse(n)); continue; }
  add("shadow", n, { $type: "shadow", $value: layers.length === 1 ? layers[0] : layers, $description: comment(v.line),
    $extensions: ext({ source: "root", css: v.value, line: v.line, uses: varUse(n), level: /^e\d/.test(n) ? n : undefined }) }, "root", v.value, varUse(n));
}
// литеральные тени (не var)
const litSh = new Map();
for (const d of allDecls) if (d.prop === "box-shadow" && !/^var\(--[\w-]+\)$/.test(d.value) && d.value !== "none") { const e = litSh.get(d.value) || { count: 0, lines: [] }; e.count++; e.lines.push(d.line); litSh.set(d.value, e); }
for (const [v, e] of litSh) if (e.count >= MIN) add("shadow", "literal-" + (Object.keys(T.shadow).length + 1), { $type: "shadow", $value: parseShadow(v), $extensions: ext({ source: "literal", count: e.count, css: v, lines: e.lines.slice(0, 6) }) }, "literal", v, e.count);

// ——— градиент штриховки ———
const hatch = rootMap.get("hatch");
if (hatch) add("gradient", "hatch", { $type: "gradient", $value: [{ color: "{color.bad-ink}", position: 0 }, { color: "{color.bad-ink}", position: 0.476 }, { color: "{color.surface}", position: 0.476 }, { color: "{color.surface}", position: 1 }],
  $description: "штриховка «сверх лимита»: repeating-linear-gradient −45°, шаг 4.2px (2px терракота-красный / 2.2px белый)", $extensions: ext({ source: "root", css: hatch.value, line: hatch.line, repeat: { angle: -45, periodPx: 4.2 }, uses: varUse("hatch") }) }, "root", hatch.value, varUse("hatch"));

// ——— радиусы, z, размеры (:root) ———
for (const [n, v] of rootMap) {
  if (/^(radius|radius-sm|r-xs|r-lg)$/.test(n)) add("radius", n, { $type: "dimension", $value: v.value, $extensions: ext({ source: "root", css: v.value, line: v.line, uses: varUse(n) }) }, "root", v.value, varUse(n));
  if (/^z-|^zl-/.test(n)) add("zIndex", n, { $type: "number", $value: Number(v.value), $description: n.startsWith("zl-") ? "слой внутри окна варианта (#shot)" : "слой страницы",
    $extensions: ext({ source: "root", css: v.value, line: v.line, uses: varUse(n) }) }, "root", v.value, varUse(n));
}
// размеры с режимами телефона/компьютера (--hm-hd, --hm-gut)
for (const n of ["hm-hd", "hm-gut"]) {
  const all = vars.filter((v) => v.name === n); if (!all.length) continue;
  const base = all.find((v) => !v.media.length); const modes = Object.fromEntries(all.map((v) => [v.media.join(" ") || "default", v.value]));
  add("dimension", n, { $type: "dimension", $value: base.value, $description: n === "hm-hd" ? "высота строки квартиры (липкой)" : "поле колонки страницы",
    $extensions: ext({ source: "root", modes, line: base.line, uses: varUse(n) }) }, "root", JSON.stringify(modes), varUse(n));
}
T.radius.pill = { $type: "dimension", $value: "999px", $extensions: ext({ source: "literal", count: allDecls.filter((d) => /border-radius/.test(d.prop) && /999px/.test(d.value)).length, note: "капсула (ступень шкалы радиусов 8·12·16·20·999)" }) };
md.push(["radius", "pill", "999px", "literal", "999px", T.radius.pill.$extensions.remlab.count]);

// ——— литералы по свойствам ———
function countVals(filter, pick) {
  const m = new Map();
  for (const d of allDecls) { if (!filter(d)) continue; for (const v of pick(d)) { if (!v) continue; const e = m.get(v) || { count: 0, lines: [] }; e.count++; if (e.lines.length < 6) e.lines.push(d.line); m.set(v, e); } }
  return [...m.entries()].filter(([, e]) => e.count >= MIN).sort((a, b) => b[1].count - a[1].count);
}
const fontShort = (v) => { const m = v.match(/^(?:(\d{3}|bold|normal)\s+)?([\d.]+px)(?:\/([\d.]+(?:px)?))?\s+(.+)$/); return m ? { weight: m[1], size: m[2], lh: m[3], family: m[4] } : null; };
// семейство
const fam = (html.match(/font:clamp\(17px,1\.25vw,20px\)\/1\.5 ([^;}]+)/) || [])[1] || "system-ui,-apple-system,Segoe UI,Roboto";
add("fontFamily", "base", { $type: "fontFamily", $value: fam.split(",").map((s) => s.trim()), $description: "системный шрифт (SF на iPhone/Mac, Segoe UI на Windows, Roboto на Android)", $extensions: ext({ source: "body", css: fam }) }, "body", fam);
add("fontFamily", "ui-compact", { $type: "fontFamily", $value: ["system-ui", "sans-serif"], $description: "переключатели ракурсов и мелкие плашки (`font:600 13px/1.1 system-ui,sans-serif`)", $extensions: ext({ source: "literal", count: (html.match(/system-ui,sans-serif/g) || []).length }) }, "literal", "system-ui,sans-serif");
// кегль
const clampAt = (v, W) => { const m = v.match(/^clamp\(([\d.]+)px,\s*([\d.]+)vw,\s*([\d.]+)px\)$/); if (!m) return null; return Math.round(Math.min(+m[3], Math.max(+m[1], +m[2] * W / 100)) * 100) / 100; };
for (const [v, e] of countVals((d) => d.prop === "font-size" || d.prop === "font", (d) => [d.prop === "font" ? (fontShort(d.value) || {}).size : d.value])) {
  if (/em$|%$|inherit/.test(v)) { add("fontSize", "rel-" + v.replace(/\./g, "_"), { $type: "dimension", $value: v, $extensions: ext({ source: "literal", count: e.count, lines: e.lines, note: "относительный" }) }, "literal", v, e.count); continue; }
  const cl = clampAt(v, 375);
  const name = cl != null ? `fluid-${v.match(/clamp\(([\d.]+)px/)[1]}-${v.match(/,\s*([\d.]+)px\)$/)[1]}`.replace(/\./g, "_") : v.replace("px", "").replace(".", "_");
  add("fontSize", name, { $type: "dimension", $value: cl != null ? `${cl}px` : v,
    $extensions: ext({ source: "literal", count: e.count, lines: e.lines, ...(cl != null ? { css: v, fluid: true, modes: { phone375: `${clampAt(v, 375)}px`, desktop1440: `${clampAt(v, 1440)}px`, wide1920: `${clampAt(v, 1920)}px` } } : {}) }) }, "literal", v, e.count);
}
// базовый кегль тела (одно вхождение, но это корень всей шкалы)
if (!T.fontSize["fluid-17-20"]) add("fontSize", "fluid-17-20", { $type: "dimension", $value: "17px", $description: "кегль тела страницы", $extensions: ext({ source: "body", css: "clamp(17px,1.25vw,20px)", fluid: true, modes: { phone375: "17px", desktop1440: "18px", wide1920: "20px" } }) }, "body", "clamp(17px,1.25vw,20px)");
// вес
for (const [v, e] of countVals((d) => d.prop === "font-weight" || d.prop === "font", (d) => [d.prop === "font" ? (fontShort(d.value) || {}).weight : d.value]))
  add("fontWeight", v, { $type: "fontWeight", $value: Number(v) || v, $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
if (!T.fontWeight["400"]) add("fontWeight", "400", { $type: "fontWeight", $value: 400, $extensions: ext({ source: "default" }) }, "default", "400");
// межстрочный
for (const [v, e] of countVals((d) => d.prop === "line-height" || d.prop === "font", (d) => [d.prop === "font" ? (fontShort(d.value) || {}).lh : d.value]))
  add("lineHeight", v.replace(/\./g, "_"), { $type: "number", $value: /px$/.test(v) ? v : Number(v), ...( /px$/.test(v) ? { $type: "dimension" } : {}), $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
if (!T.lineHeight["1_5"]) add("lineHeight", "1_5", { $type: "number", $value: 1.5, $description: "межстрочный тела", $extensions: ext({ source: "body" }) }, "body", "1.5");
// отступы (padding/margin/gap) — числа px
const pxList = (v) => (v.match(/-?\d+(?:\.\d+)?px/g) || []).map((x) => x.replace(/^-/, "")).filter((x) => x !== "0px");
for (const [v, e] of countVals((d) => /^(padding|margin|gap|row-gap|column-gap)(-|$)/.test(d.prop), (d) => [...new Set(pxList(d.value))]))
  add("space", v.replace("px", "").replace(".", "_"), { $type: "dimension", $value: v, $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
// радиусы-литералы
for (const [v, e] of countVals((d) => d.prop === "border-radius", (d) => [...new Set(d.value.split(/\s+/).filter((x) => !/var\(/.test(x)))]))
  if (v !== "999px") add("radius", "literal-" + v.replace(/[^\w]/g, "_"), { $type: "dimension", $value: v, $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
// размеры элементов управления
for (const [v, e] of countVals((d) => /^(width|height|min-height|min-width|flex-basis)$/.test(d.prop) || d.prop === "flex", (d) => [...new Set(pxList(d.value))]))
  add("size", v.replace("px", "").replace(".", "_"), { $type: "dimension", $value: v, $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
// z-index литералы
for (const [v, e] of countVals((d) => d.prop === "z-index", (d) => [/^-?\d+$/.test(d.value) ? d.value : null]))
  add("zIndex", "literal-" + v, { $type: "number", $value: Number(v), $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
// прозрачность
for (const [v, e] of countVals((d) => d.prop === "opacity", (d) => [d.value]))
  add("opacity", v.replace(".", "_"), { $type: "number", $value: Number(v), $extensions: ext({ source: "literal", count: e.count, lines: e.lines }) }, "literal", v, e.count);
// длительности
for (const [v, e] of countVals((d) => /^(transition|animation)/.test(d.prop), (d) => [...new Set(d.value.match(/\b\d*\.?\d+m?s\b/g) || [])]))
  add("duration", v.replace(".", "_"), { $type: "duration", $value: /ms$/.test(v) ? v : `${Math.round(parseFloat(v) * 1000)}ms`, $extensions: ext({ source: "literal", count: e.count, lines: e.lines, css: v }) }, "literal", v, e.count);
// брейкпоинты (@media / @container)
const bp = new Map();
for (const r of css) for (const m of r.media) for (const mm of m.matchAll(/\((max|min)-width:\s*(\d+)px\)/g)) {
  const kind = m.startsWith("@container") ? "container" : "media"; const k = `${kind}-${mm[1]}-${mm[2]}`;
  const e = bp.get(k) || { kind, cmp: mm[1], px: mm[2], rules: 0, lines: new Set() }; e.rules++; e.lines.add(r.line); bp.set(k, e);
}
for (const [k, e] of [...bp.entries()].sort((a, b) => +a[1].px - +b[1].px))
  add("breakpoint", k, { $type: "dimension", $value: e.px + "px", $description: `${e.kind === "container" ? "@container" : "@media"} (${e.cmp}-width:${e.px}px)`,
    $extensions: ext({ source: e.kind, rules: e.rules, firstLines: [...e.lines].slice(0, 6) }) }, e.kind, `${e.cmp}-width:${e.px}px`, e.rules);

// ——— текстовые стили из замера живой страницы ———
const capDir = join(OUT, "capture");
if (existsSync(capDir)) {
  const combos = new Map();
  for (const f of readdirSync(capDir).filter((f) => /^computed-.*\.json$/.test(f))) {
    const j = JSON.parse(readFileSync(join(capDir, f), "utf8")); const dev = /-375/.test(f) ? "phone" : "desktop";
    for (const t of j.texts || []) { const k = `${dev}|${t.fs}|${t.fw}|${t.lh}`; const e = combos.get(k) || { dev, fs: t.fs, fw: t.fw, lh: t.lh, count: 0, ex: new Set() }; e.count++; if (e.ex.size < 4) e.ex.add(t.sel); combos.set(k, e); }
  }
  const pxNum = (x) => parseFloat(x);
  for (const e of [...combos.values()].filter((e) => e.count >= MIN).sort((a, b) => a.dev.localeCompare(b.dev) || pxNum(b.fs) - pxNum(a.fs) || b.fw - a.fw)) {
    const lhRatio = e.lh === "normal" ? "normal" : Math.round(pxNum(e.lh) / pxNum(e.fs) * 100) / 100;
    const name = `${e.dev}/${String(pxNum(e.fs)).replace(".", "_")}-${e.fw}`;
    if (T.typography[name] && T.typography[name].$extensions.remlab.count >= e.count) continue;
    add("typography", name, { $type: "typography", $value: { fontFamily: "{fontFamily.base}", fontSize: e.fs, fontWeight: Number(e.fw), lineHeight: lhRatio, letterSpacing: "0px" },
      $extensions: ext({ source: "computed", count: e.count, lineHeightPx: e.lh, examples: [...e.ex] }) }, "computed", `${e.fs}/${e.lh} ${e.fw}`, e.count);
  }
}

// чистка пустых групп
for (const k of Object.keys(T)) if (!k.startsWith("$") && !Object.keys(T[k]).length) delete T[k];
writeFileSync(join(OUT, "tokens.json"), JSON.stringify(T, null, 2));
const n = md.length, byGroup = {}; for (const r of md) byGroup[r[0]] = (byGroup[r[0]] || 0) + 1;
const esc = (s) => String(s).replace(/\|/g, "\\|").replace(/\n/g, " ");
const head = `# Токены демо /demo — как есть\n\nИсточник: \`${SRC_REL}\` (3 блока <style>). Формат файла рядом — W3C Design Tokens (\`tokens.json\`, \`$type\`/\`$value\`).\n` +
  `**source**: root — переменная \`:root\`; literal — повторяющееся значение в CSS (≥${MIN} раз, кандидат в токен); computed — замер живой страницы (текстовые стили); body/fallback — особые случаи.\n\n` +
  `Всего: **${n}** · ` + Object.entries(byGroup).map(([g, c]) => `${g} ${c}`).join(" · ") + "\n";
const tbl = Object.keys(byGroup).map((g) => `\n## ${g}\n\n| имя | значение | источник | CSS | раз |\n|---|---|---|---|---|\n` +
  md.filter((r) => r[0] === g).map((r) => `| \`${r[1]}\` | ${r[0] === "color" && /^#/.test(r[2]) ? `<span style="display:inline-block;width:12px;height:12px;background:${r[2]};border:1px solid #ccc"></span> ` : ""}\`${esc(r[2]).slice(0, 120)}\` | ${r[3]} | \`${esc(r[4]).slice(0, 90)}\` | ${r[5]} |`).join("\n")).join("\n");
const notes = `\n\n## Замечания по исходнику (для дизайнера, продукт не меняли)\n` +
  `- \`--warn:var(--warn)\` в \`:root\` ссылается сам на себя — значение не определено (стили \`.issue b\` и \`#tip.warn\` фактически без цвета); рядом есть \`--warn-ink\`.\n` +
  `- \`--danger\` не объявлен — работает запасное \`#b4442f\` (кнопка «Удалить» в окошке избранного).\n` +
  `- Класс \`.sw\` объявлен дважды: квадрат 10×10 легенды бюджета (стр. ~205) и кружок цвета 22×22 (стр. ~873, demo-28) — второе правило переопределяет размер и у легенды.\n` +
  `- Литералы цвета вне \`:root\` (\`#B3261E\`, \`#fff\`, \`rgba(255,255,255,.9x)\`, \`rgba(24,20,17,.55)\`, \`#1A1F1C/#3B76A2/#EAF2F8\` у \`.fh-3d\`) — кандидаты в токены, см. \`literal-*\`.\n`;
writeFileSync(join(OUT, "tokens.md"), head + tbl + notes);
console.log(`tokens: ${n} (` + Object.entries(byGroup).map(([g, c]) => `${g} ${c}`).join(", ") + ")");
