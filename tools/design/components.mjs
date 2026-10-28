// ПЕРЕЧЕНЬ КОМПОНЕНТОВ → components.json + components.md (план design-01-figma-export, п.1).
// Имя `Категория/Имя` и состояния — `registry.mjs`; file:line — по CSS (`lib-css.mjs`); снятые варианты и экраны — по образцам capture.mjs.
//   node tools/design/components.mjs <OUT>
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { parseRules, selectorLines, SRC_REL } from "./lib-css.mjs";
import { REGISTRY } from "./registry.mjs";

const OUT = process.argv[2];
const rules = parseRules();
const cap = join(OUT, "capture");
const samples = existsSync(cap) ? readdirSync(cap).filter((f) => /^samples-.*\.json$/.test(f)).flatMap((f) => JSON.parse(readFileSync(join(cap, f), "utf8"))) : [];
export const vkey = (v) => Object.entries(v).filter(([k]) => !["lang"].includes(k)).map(([k, x]) => `${k}=${x}`).join(",");
const comps = REGISTRY.map((c) => {
  const lines = [...new Set(c.css.flatMap((s) => selectorLines(rules, s)))].sort((a, b) => a - b);
  const mine = samples.filter((s) => s.figma === c.figma);
  const variants = {};
  for (const s of mine) { const k = vkey(s.variant); const e = variants[k] || (variants[k] = { key: k, variant: { ...s.variant, lang: undefined }, langs: [], screens: [], size: [s.w, s.h] }); if (!e.langs.includes(s.variant.lang)) e.langs.push(s.variant.lang); if (s.screen) e.screens.push(`${s.variant.lang}-${s.variant.device === "phone" ? 375 : 1440}/${s.screen}`); }
  const [cat, name] = c.figma.split("/");
  return { figma: c.figma, category: cat, name, description: c.desc, selector: c.sel, cssSelectors: c.css, source: lines.map((l) => `${SRC_REL}:${l}`),
    statesInCode: c.states, where: c.where, captured: Object.values(variants).map((v) => ({ key: v.key, langs: v.langs, size: v.size, screens: [...new Set(v.screens)] })),
    capturedCount: Object.keys(variants).length };
});
const total = comps.reduce((a, c) => a + c.capturedCount, 0);
writeFileSync(join(OUT, "components.json"), JSON.stringify({ $description: `Компоненты демо /demo (как есть). Источник ${SRC_REL}. Имя = будущее имя компонента в Фигме.`, count: comps.length, capturedVariants: total, components: comps }, null, 1));
const md = [`# Компоненты демо /demo — как есть\n`, `Источник: \`${SRC_REL}\`. Имя \`Категория/Имя\` = имя компонента в Фигме; варианты в Фигме — свойства \`state\`, \`device\` (phone/desktop) и др. из столбца «снято».`,
  `Всего компонентов **${comps.length}**, снятых вариантов **${total}** (RU и EN считаются одним вариантом). «Состояния в коде» — что есть в CSS/JS; не всё снимается живым обходом (hover, платное).\n`];
let cat = "";
for (const c of comps) {
  if (c.category !== cat) { cat = c.category; md.push(`\n## ${cat}\n\n| компонент | селектор | файл:строка | состояния в коде | снято (варианты) | где |\n|---|---|---|---|---|---|`); }
  const src = c.source.length ? c.source.slice(0, 6).map((s) => s.split(":").pop()).join(", ") + (c.source.length > 6 ? ` …(+${c.source.length - 6})` : "") : "—";
  md.push(`| **${c.figma}**<br>${c.description} | \`${c.selector.replace(/\|/g, "\\|")}\` | index.html:${src} | ${c.statesInCode.join("; ")} | ${c.captured.map((v) => `\`${v.key}\``).join("<br>") || "— не снято"} | ${c.where.join("; ")} |`);
}
writeFileSync(join(OUT, "components.md"), md.join("\n") + "\n");
console.log(`components: ${comps.length}, вариантов снято ${total}, без образца: ${comps.filter((c) => !c.capturedCount).map((c) => c.figma).join(", ")}`);
