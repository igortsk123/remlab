// Самопроверка: computed-стиль и рамка элемента в файле.  node tools/design/probe-el.mjs <файл> <селектор> [W] [H]
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
const [src, sel, W = "375", H = "812"] = process.argv.slice(2);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: +W, height: +H } });
await p.goto(pathToFileURL(src).href, { waitUntil: "networkidle" });
console.log(JSON.stringify(await p.evaluate((s) => [...document.querySelectorAll(s)].slice(0, 3).map((e) => { const c = getComputedStyle(e), r = e.getBoundingClientRect();
  const chain = []; for (let x = e; x; x = x.parentElement) { const cs = getComputedStyle(x); chain.push(`${x.tagName}#${x.id}.${[...x.classList].join(".")} op=${cs.opacity} vis=${cs.visibility} disp=${cs.display} z=${cs.zIndex} pos=${cs.position}`); }
  return { r: [r.x, r.y, r.width, r.height], op: c.opacity, disp: c.display, vis: c.visibility, z: c.zIndex, complete: e.complete, nw: e.naturalWidth, chain: chain.slice(0, 8) }; }), sel), null, 1));
await b.close();
