// ОГЛАВЛЕНИЕ ЭКРАНОВ → screens/index.html (план design-01-figma-export, п.1): по набору (язык × ширина) — превью PNG,
// ссылки на PNG и статичный HTML (для html.to.design: вставить адрес .html — импортирует вёрстку без скриптов).
//   node tools/design/build-screens.mjs <OUT>
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const OUT = process.argv[2]; const cap = join(OUT, "capture");
const sets = readdirSync(cap).filter((f) => /^screens-.*\.json$/.test(f)).map((f) => ({ key: f.slice(8, -5), list: JSON.parse(readFileSync(join(cap, f), "utf8")) }))
  .sort((a, b) => (a.key.startsWith("ru") === b.key.startsWith("ru") ? parseInt(a.key.split("-")[1]) - parseInt(b.key.split("-")[1]) : a.key.startsWith("ru") ? -1 : 1));
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
let total = 0;
const sec = sets.map(({ key, list }) => {
  total += list.length;
  const [lang, w] = key.split("-"); const phone = +w <= 700;
  return `<section id="${key}"><h2>${lang.toUpperCase()} · ${phone ? "телефон 375×812" : "компьютер 1440×900"} <small>${list.length} экранов</small></h2><div class="grid ${phone ? "ph" : "dt"}">` +
    list.map((s) => `<figure data-state="${esc(s.id)}"><a href="${key}/${s.png}" target="_blank"><img loading="lazy" src="${key}/${s.png}" alt=""></a>` +
      `<figcaption><b>${esc(s.id)}</b><span>${esc(s.title)}</span><span class="l"><a href="${key}/${s.png}">PNG</a>${s.full ? ` · <a href="${key}/${s.full}">PNG во всю длину</a>` : ""} · <a href="${key}/${s.html}">HTML</a></span></figcaption></figure>`).join("") + `</div></section>`;
}).join("\n");
const html = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Экраны демо</title>
<style>:root{--bg:#f6f4f0;--card:#fff;--ink:#1f1d1a;--muted:#6f6a63;--line:#e4dfd6;--acc:#b0694a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1b1a18;--card:#262421;--ink:#efebe5;--muted:#a49d93;--line:#3a3733;--acc:#d48a69}}
:root[data-theme="dark"]{--bg:#1b1a18;--card:#262421;--ink:#efebe5;--muted:#a49d93;--line:#3a3733;--acc:#d48a69}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px 16px}
h1{font-size:24px;margin:0 0 6px}p{color:var(--muted);max-width:820px}h2{font-size:18px;margin:32px 0 12px;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:1}h2 small{color:var(--muted);font-weight:400}
nav a,figcaption a{color:var(--acc)}nav{display:flex;gap:14px;flex-wrap:wrap}
.grid{display:grid;gap:14px}.grid.ph{grid-template-columns:repeat(auto-fill,minmax(170px,1fr))}.grid.dt{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
figure img{display:block;width:100%;height:auto;aspect-ratio:auto;border-bottom:1px solid var(--line)}
.ph figure img{aspect-ratio:375/812;object-fit:cover;object-position:top}.dt figure img{aspect-ratio:1440/900;object-fit:cover;object-position:top}
figcaption{padding:8px 10px;display:flex;flex-direction:column;gap:2px;font-size:13px}figcaption span{color:var(--muted)}figcaption .l{color:var(--muted)}
</style></head><body><h1>Экраны демо для застройщика — как есть</h1>
<p>Снято ${new Date().toISOString().slice(0, 10)} с <a href="https://remont-lab.online/demo/">remont-lab.online/demo/</a>, всего ${total} экранов. У каждого — PNG и статичный HTML без скриптов
(вставить адрес .html в html.to.design). Шрифт на снимках — DejaVu (сервер Linux); в Фигме — системный (SF Pro / Inter). 3D — снимок как есть. Компоненты — <a href="../kit/">кит</a>.</p>
<nav>${sets.map((s) => `<a href="#${s.key}">${s.key}</a>`).join("")}</nav>
${sec}
</body></html>`;
writeFileSync(join(OUT, "screens", "index.html"), html);
console.log(`screens/index.html: наборов ${sets.length}, экранов ${total}`);
