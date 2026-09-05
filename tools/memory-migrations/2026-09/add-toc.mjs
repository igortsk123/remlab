// add-toc.mjs — вставляет «## Содержание» (список H2) после первого H1 в доках, где его нет
import { readFileSync, writeFileSync } from "node:fs";
const files = process.argv.slice(2);
for (const f of files) {
  let t = readFileSync(f, "utf8");
  if (/^## Содержание/m.test(t)) { console.log("есть:", f); continue; }
  const lines = t.split("\n");
  const h1 = lines.findIndex((l) => /^# /.test(l));
  if (h1 < 0) { console.log("нет H1:", f); continue; }
  const h2 = lines.filter((l) => /^## /.test(l)).map((l) => l.replace(/^## /, "").trim());
  if (h2.length < 4) { console.log("мало H2:", f); continue; }
  const toc = ["", "## Содержание", ...h2.map((h, i) => `${i + 1}. ${h}`), ""];
  // вставить после H1 и следующего за ним блока цитаты/пустой строки
  let ins = h1 + 1;
  while (ins < lines.length && (lines[ins].startsWith(">") || lines[ins].trim() === "")) ins++;
  lines.splice(ins, 0, ...toc);
  writeFileSync(f, lines.join("\n"));
  console.log(`TOC ${h2.length} разделов: ${f}`);
}
