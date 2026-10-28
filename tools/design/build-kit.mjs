// СТРАНИЦА UI-КИТА (план design-01-figma-export, п.1): образцы компонентов, снятые capture.mjs с живого демо, на CSS демо ДОСЛОВНО.
// Каждый образец — в элементе с `data-figma="Категория/Имя"` и `data-variant="ключ=значение,…"` (для html.to.design и коннектора).
// Стили демо зависят от ширины окна (@media 700/900/1600), поэтому кит — две страницы: phone.html (смотреть/импортировать при 375×812)
// и desktop.html (1440×900); index.html — оглавление с обеими во фреймах. Скриптов нет; картинки — абсолютными адресами прода.
//   node tools/design/build-kit.mjs <OUT>
import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { allCss, parseRules, selectorLines, SRC_REL } from "./lib-css.mjs";
import { REGISTRY } from "./registry.mjs";

const OUT = process.argv[2]; const KIT = join(OUT, "kit"); mkdirSync(KIT, { recursive: true });
const CSS = allCss(); const rules = parseRules();
const cap = join(OUT, "capture");
const samples = readdirSync(cap).filter((f) => /^samples-.*\.json$/.test(f)).sort().flatMap((f) => JSON.parse(readFileSync(join(cap, f), "utf8")));
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const vstr = (v) => Object.entries(v).filter(([, x]) => x !== undefined).map(([k, x]) => `${k}=${String(x).replace(/[,=]/g, " ")}`).join(",");
const order = new Map(REGISTRY.map((c, i) => [c.figma, i]));

// ancestors: те же теги/id/классы (селекторы демо завязаны на предков), но без раскладки — позиция, размеры, фон, тени сняты
const NEUTRAL = "position:relative;inset:auto;top:auto;left:auto;right:auto;bottom:auto;transform:none;margin:0;padding:0;width:100%;height:auto;min-height:0;max-height:none;" +
  "overflow:visible;background:transparent;box-shadow:none;border:0;border-radius:0;z-index:auto;opacity:1;visibility:visible;backdrop-filter:none;-webkit-backdrop-filter:none;animation:none";
const OVERLAY = /^(Window\/Frame|Picker\/Sheet|Zoom\/Fullscreen|Dialog\/Overlay|Sheet\/Panel|Window\/Side panel|ItemCard\/Sheet)$/;
function wrapChain(s, inner) {
  let html = inner;
  const ch = s.chain || [];
  for (let i = ch.length - 1; i >= 0; i--) {
    const a = ch[i]; const tag = /^(div|section|header|nav|article|aside|main|span|ul|li|label|figure)$/.test(a.tag) ? a.tag : "div";
    const last = i === ch.length - 1;
    // непосредственный родитель держит свой display (flex/grid решают ширину образца); остальные — блок
    const disp = last ? (/^(flex|grid|inline-flex|inline-grid)$/.test(s.parentDisplay) ? `display:${s.parentDisplay.replace("inline-", "")};flex-direction:${s.parentFlexDir || "row"};` : "display:block;") : "display:block;";
    const attrs = (a.attrs || []).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
    html = `<${tag}${a.id ? ` id="${esc(a.id)}"` : ""}${a.cls ? ` class="${esc(a.cls)}"` : ""}${attrs} style="${NEUTRAL};${disp}">${html}</${tag}>`;
  }
  return html;
}
let radN = 0;
function sampleHtml(s, assetPrefix) {
  let h = s.html.replace(/data-asset="([^"]+)"/g, (m, f) => `src="${assetPrefix}${f}"`).replace(/\sdata-fxcv(-src)?="[^"]*"/g, "");
  // радио-кнопки разных образцов на одной странице — одна группа по name: отмеченной осталась бы только последняя
  radN++; h = h.replace(/<input\b[^>]*>/g, (tag) => /type="(radio|checkbox)"/.test(tag) ? tag.replace(/\sname="([^"]*)"/, (m, n) => ` name="${n}--kit${radN}"`) : tag);
  // корень образца: ширина как на странице; плавающее/фиксированное — в поток
  const tag = h.match(/^<([a-zA-Z0-9-]+)/)[1];
  const st = h.match(/^<[^>]*?\sstyle="([^"]*)"/);
  const fix = (s.fixed || /absolute|fixed/.test((s.tree && s.tree.st && s.tree.st.position) || "")) ? "position:relative;inset:auto;top:auto;left:auto;right:auto;bottom:auto;transform:none;margin:0;" : "";
  const size = `width:${s.w}px;max-width:none;box-sizing:border-box;` + (OVERLAY.test(s.figma) || s.fixed ? `height:${s.h}px;min-height:0;max-height:none;` : "");
  const add = fix + size;
  if (st) h = h.replace(/^(<[^>]*?\sstyle=")([^"]*)"/, (m, a, b) => `${a}${b};${add}"`); else h = h.replace(/^<([a-zA-Z0-9-]+)/, `<$1 style="${add}"`);
  // показать то, что живая страница держит скрытым до события (сообщение уже погасло к моменту клона — нет; hidden у корня снимаем)
  h = h.replace(/^(<[^>]*?)\shidden(="")?(?=[\s>])/, "$1");
  return wrapChain(s, h);
}
const KIT_CSS = `
/* ——— оформление кита: только классы kit-*, стили демо выше не тронуты ——— */
.kit-page{--kit-gut:16px;padding:20px var(--kit-gut) 60px;max-width:none}
.kit-h{font:700 26px/1.2 system-ui;margin:0 0 6px}.kit-p{font:14px/1.5 system-ui;color:rgb(120 113 108);margin:0 0 6px;max-width:900px}
.kit-cat{margin:34px 0 0;padding-top:12px;border-top:2px solid rgb(41 37 36)}
.kit-cat-t{font:700 22px/1.2 system-ui;margin:0 0 4px}
.kit-comp{margin:22px 0 0}
.kit-comp-t{font:700 16px/1.3 system-ui;margin:0 0 2px}.kit-comp-t small{font:12px/1.4 ui-monospace,monospace;color:rgb(120 113 108);margin-left:8px;font-weight:400}
.kit-comp-d{font:13px/1.4 system-ui;color:rgb(120 113 108);margin:0 0 8px}
.kit-row{display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start}
.kit-item{margin:0;display:flex;flex-direction:column;gap:6px}
.kit-item>figcaption{font:12px/1.35 ui-monospace,monospace;color:rgb(87 83 78);max-width:420px;word-break:break-word}
.kit-stage{position:relative;transform:translateZ(0);outline:1px dashed rgb(214 211 209);outline-offset:4px;background:rgb(251 248 243)}
.kit-stage.ovl{overflow:hidden}
.kit-item.bleed{margin-left:calc(-1 * var(--kit-gut))}.kit-item.bleed>figcaption{margin-left:var(--kit-gut)}
.kit-tok{display:flex;flex-wrap:wrap;gap:10px}
.kit-sw{width:120px;font:11px/1.3 ui-monospace,monospace;color:rgb(87 83 78)}.kit-sw i{display:block;height:44px;border-radius:8px;border:1px solid rgb(231 229 228);margin-bottom:4px}
.kit-sh{width:150px;height:80px;border-radius:12px;background:#fff;display:grid;place-items:center;font:12px ui-monospace,monospace;margin:10px 18px 18px 0}
.kit-ty{margin:4px 0;font-family:system-ui,-apple-system,Segoe UI,Roboto}
.kit-nav{display:flex;flex-wrap:wrap;gap:6px 14px;font:13px/1.5 system-ui;margin:10px 0 0}.kit-nav a{color:rgb(176 106 74)}
`;
function tokensSection() {
  const t = JSON.parse(readFileSync(join(OUT, "tokens.json"), "utf8"));
  const col = Object.entries(t.color || {}).filter(([, v]) => /^#/.test(v.$value));
  const sh = Object.entries(t.shadow || {}).filter(([k]) => /^e\d|^ring|^glow/.test(k));
  const ty = Object.entries(t.typography || {});
  return `<section class="kit-cat" id="tokens"><div class="kit-cat-t">Tokens</div><p class="kit-p">Переменные — в tokens.json (W3C DTCG). Здесь — образцы для глаза.</p>
  <div class="kit-comp"><div class="kit-comp-t">Colors</div><div class="kit-tok">${col.map(([k, v]) => `<div class="kit-sw" data-token="color.${k}"><i style="background:${v.$value}"></i>${k}<br>${v.$value}</div>`).join("")}</div></div>
  <div class="kit-comp"><div class="kit-comp-t">Shadows</div><div class="kit-tok">${sh.map(([k]) => `<div class="kit-sh" data-token="shadow.${k}" style="box-shadow:var(--${k})">--${k}</div>`).join("")}</div></div>
  <div class="kit-comp"><div class="kit-comp-t">Radii</div><div class="kit-tok">${["r-xs", "radius-sm", "radius", "r-lg"].map((k) => `<div class="kit-sh" data-token="radius.${k}" style="border:1px solid var(--line);border-radius:var(--${k})">--${k}</div>`).join("")}<div class="kit-sh" style="border:1px solid var(--line);border-radius:999px">999px</div></div></div>
  ${ty.length ? `<div class="kit-comp"><div class="kit-comp-t">Typography (замер)</div>${ty.map(([k, v]) => `<div class="kit-ty" data-token="typography.${k}" style="font-size:${v.$value.fontSize};font-weight:${v.$value.fontWeight};line-height:${v.$value.lineHeight}">${k} — Квартира · Living room 245 000 ₽</div>`).join("")}</div>` : ""}
  </section>`;
}
function page(device) {
  const mine = samples.filter((s) => s.variant.device === device);
  // дубли (тот же компонент, вариант и язык) — первый
  const seen = new Set(); const list = [];
  for (const s of mine) { const k = s.figma + "|" + vstr(s.variant); if (seen.has(k)) continue; seen.add(k); list.push(s); }
  list.sort((a, b) => (order.get(a.figma) ?? 999) - (order.get(b.figma) ?? 999) || a.variant.lang.localeCompare(b.variant.lang) * -1);
  const byComp = new Map(); for (const s of list) { if (!byComp.has(s.figma)) byComp.set(s.figma, []); byComp.get(s.figma).push(s); }
  const cats = [...new Set(REGISTRY.map((c) => c.figma.split("/")[0]))];
  let body = "";
  for (const cat of cats) {
    const comps = REGISTRY.filter((c) => c.figma.startsWith(cat + "/") && byComp.has(c.figma)); if (!comps.length) continue;
    body += `<section class="kit-cat" id="cat-${cat}"><div class="kit-cat-t">${cat}</div>`;
    for (const c of comps) {
      const lines = [...new Set(c.css.flatMap((s) => selectorLines(rules, s)))].sort((a, b) => a - b).slice(0, 5);
      body += `<div class="kit-comp" data-component="${esc(c.figma)}"><div class="kit-comp-t">${esc(c.figma)}<small>${esc(c.sel)} · index.html:${lines.join(",")}</small></div><div class="kit-comp-d">${esc(c.desc)}</div><div class="kit-row">`;
      for (const s of byComp.get(c.figma)) {
        const v = { ...s.variant }; const vs = vstr(v);
        const bleed = device === "phone" && s.w > 375 - 32;
        body += `<figure class="kit-item${bleed ? " bleed" : ""}"><figcaption>${esc(vs)}${s.screen ? ` · экран ${esc(s.screen)}` : ""}</figcaption>` +
          `<div class="kit-stage${OVERLAY.test(s.figma) || s.fixed ? " ovl" : ""}" data-figma="${esc(s.figma)}" data-variant="${esc(vs)}" style="width:${Math.max(s.w, 1)}px;${OVERLAY.test(s.figma) || s.fixed ? `height:${s.h}px;` : ""}">${sampleHtml(s, "../assets/")}</div></figure>`;
      }
      body += `</div></div>`;
    }
    body += `</section>`;
  }
  const W = device === "phone" ? 375 : 1440;
  const nav = cats.filter((c) => [...byComp.keys()].some((k) => k.startsWith(c + "/"))).map((c) => `<a href="#cat-${c}">${c}</a>`).join("");
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UI-кит демо — ${device === "phone" ? "телефон 375" : "компьютер 1440"}</title>
<meta name="description" content="UI-кит /demo как есть: каждый компонент в каждом снятом состоянии; CSS — дословно из ${SRC_REL}">
<style>
${CSS}
</style>
<style>${KIT_CSS}</style></head><body><div class="kit-page">
<div class="kit-h">UI-кит демо /demo — ${device === "phone" ? "телефон (375)" : "компьютер (1440)"}</div>
<p class="kit-p">Как есть на ${new Date().toISOString().slice(0, 10)}. CSS — дословно из <code>${SRC_REL}</code> (все три блока &lt;style&gt; подряд). Каждый образец снят с живой страницы
(<a href="https://remont-lab.online/demo/">RU</a> / <a href="https://remont-lab.online/demo/?lang=en">EN</a>) и лежит в элементе с <code>data-figma</code> (имя компонента) и <code>data-variant</code>.
Импорт в Фигму (html.to.design) — при ширине окна <b>${W}</b>${device === "phone" ? " и высоте 812" : " и высоте 900"}: стили демо зависят от ширины экрана.
Образцов: ${list.length}, компонентов: ${byComp.size}.</p>
<div class="kit-nav"><a href="#tokens">Tokens</a>${nav}<a href="./">← оглавление</a></div>
${tokensSection()}
${body}
</div></body></html>`;
}
const stats = {};
for (const d of ["phone", "desktop"]) { const h = page(d); writeFileSync(join(KIT, `${d}.html`), h); stats[d] = { bytes: h.length, samples: (h.match(/class="kit-stage/g) || []).length }; }
const index = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>UI-кит демо — оглавление</title>
<style>${CSS}</style><style>${KIT_CSS}
.kit-frames{display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-top:18px}
.kit-fr{display:flex;flex-direction:column;gap:6px;font:13px system-ui}
.kit-fr iframe{border:1px solid rgb(214 211 209);border-radius:12px;background:#fff}
.kit-dk{width:min(100%,1440px);overflow:hidden}.kit-dk iframe{width:1440px;height:1800px;transform-origin:0 0}
</style></head><body><div class="kit-page">
<div class="kit-h">UI-кит демо /demo — как есть</div>
<p class="kit-p">Заготовка для Фигмы (план design-01-figma-export). Стили демо меняются по ширине экрана, поэтому кит — две страницы:</p>
<div class="kit-nav"><a href="phone.html">phone.html — телефон, импорт при 375×812</a><a href="desktop.html">desktop.html — компьютер, импорт при 1440×900</a>
<a href="../screens/">экраны (PNG + HTML)</a><a href="../tokens.json">tokens.json</a><a href="../tokens.md">tokens.md</a><a href="../components.md">components.md</a><a href="../components.json">components.json</a><a href="../figma-spec/order.json">figma-spec/order.json</a></div>
<p class="kit-p">Образцов: телефон ${stats.phone.samples}, компьютер ${stats.desktop.samples}. Каждый — в элементе <code>data-figma="Категория/Имя"</code> с <code>data-variant</code>.</p>
<div class="kit-frames"><div class="kit-fr">Телефон 375<iframe src="phone.html" width="375" height="1800" title="телефон"></iframe></div>
<div class="kit-fr kit-dk">Компьютер 1440 (уменьшено)<iframe src="desktop.html" title="компьютер" style="transform:scale(.6);height:3000px;margin-bottom:-1200px"></iframe></div></div>
</div></body></html>`;
writeFileSync(join(KIT, "index.html"), index);
console.log("kit:", JSON.stringify(stats));
