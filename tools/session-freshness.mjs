#!/usr/bin/env node
// session-freshness — SessionStart-hook: одна строка о свежести памяти в начале сессии.
// Молчит, когда память свежая и audit чист (тишина = норма, баннер = сигнал).
// Сигналы: project-state старше 14 дней; проблемы аудита (счётчик по категориям).
// Подключение — пресеты settings-presets/* (hooks.SessionStart).
import { resolve } from "node:path";
import { runChecks } from "./memory-audit.mjs";

const root = resolve(process.argv[2] ?? process.cwd());
const res = runChecks(root, { write: false });
if (res.fatal) process.exit(0); // нет .memory_bank — проект без банка, молчим

const parts = [];
if (res.psAgeDays !== null && res.psAgeDays > 14)
  parts.push(`project-state обновлён ${res.psAgeDays}д назад (${res.psUpdated}) — не доверяй снимку молча`);
const byCat = (list) => {
  const counts = {};
  for (const p of list) {
    const cat = p.split(/\s+/)[0];
    counts[cat] = (counts[cat] ?? 0) + 1;
  }
  return Object.entries(counts)
    .map(([c, n]) => (n > 1 ? `${c}×${n}` : c))
    .join(", ");
};
if (!res.ok) parts.push(`audit: ${res.problems.length} пробл. (${byCat(res.problems)})`);
// Предупреждения (CODE-DRIFT и т.п.) — отдельной группой от проблем: завершить работу они не
// мешают, но разбираются там же, в /memory-check (Этап 4), поэтому в баннер попадают.
if (res.warnings?.length) parts.push(`⚠ ${res.warnings.length} предупр. (${byCat(res.warnings)})`);
if (parts.length) console.log(`🧠 memory: ${parts.join("; ")} → начни с /memory-check`);
