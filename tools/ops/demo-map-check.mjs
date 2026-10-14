#!/usr/bin/env node
// КАРТА СЦЕНАРИЕВ ↔ ЖИВЫЕ ПРОВЕРКИ (план demo-03 п.3). Каждая строка карты `domain/demo-scenario-map.md` (номер 1.1, 2.7…)
// должна быть покрыта живой проверкой: номер — в начале названия теста в e2e/live/*.live.ts («2.1–2.3 …» покрывает
// 2.1, 2.2, 2.3). Непокрытая строка — WARN для дайджеста (жёлтый, не красный): сценарий есть, а проверки нет.
// Строки, ушедшие в другой план (колонка «Факт» начинается с «→»), не считаются.
import { readFileSync, readdirSync } from "node:fs";
const root = new URL("../..", import.meta.url).pathname;
const map = readFileSync(root + ".memory_bank/domain/demo-scenario-map.md", "utf8");
const rows = [...map.matchAll(/^\| (\d+\.\d+) \|[^\n]*\| ([^|\n]*) \|\s*$/gm)].filter((m) => !/^\s*→/.test(m[2])).map((m) => m[1]);
const covered = new Set();
for (const f of readdirSync(root + "e2e/live").filter((f) => f.endsWith(".live.ts"))) {
  const src = readFileSync(root + "e2e/live/" + f, "utf8");
  for (const m of src.matchAll(/test\("((?:\d+\.\d+(?:–\d+\.\d+)?,?\s*)+)/g))
    for (const part of m[1].split(",")) {
      const [a, b] = part.trim().split("–");
      if (!a) continue;
      const [ma, na] = a.split(".").map(Number); const nb = b ? Number(b.split(".")[1]) : na;
      for (let n = na; n <= nb; n++) covered.add(`${ma}.${n}`);
    }
}
const miss = rows.filter((r) => !covered.has(r));
console.log(`карта сценариев: строк ${rows.length}, под живой проверкой ${rows.length - miss.length}`);
if (miss.length) console.log(`WARN:demo_map_uncovered: строки карты без живой проверки: ${miss.join(", ")}`);
