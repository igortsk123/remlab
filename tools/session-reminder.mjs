#!/usr/bin/env node
// session-reminder — Stop-hook. Два режима:
//   без флага (default-пресет): мягкое напоминание в stdout — уходит ПОЛЬЗОВАТЕЛЮ (агент его
//     не видит — механика Stop-hook: stdout при exit 0 не скармливается Claude);
//   --block (пресеты important/autopilot): механический гейт — если работа была, а захват
//     пропущен/аудит грязный, отвечает {"decision":"block","reason":"..."} — Claude получает
//     reason и обязан запустить /memory-check прежде чем закончить.
// Блок УЗКИЙ (Stop срабатывает на каждом завершении ответа): только когда
//   (1) есть план in_progress (или completed, не прошедший гейт переноса) И
//   (2) есть изменения вне .memory_bank/ И
//   (3) блокнот _intake/session-scratch.md пуст ИЛИ memory-audit --check грязный.
// Цикл-защита ОБЯЗАТЕЛЬНА: stop_hook_active=true в stdin-JSON → exit 0 (блокируем максимум
// один раз на попытку завершения). Не git-репо / git недоступен → молчим (exit 0).
// Подключение — пресеты settings-presets/* (hooks.Stop) или tools/stop-hook.example.json.
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { runChecks } from "./memory-audit.mjs";

const args = process.argv.slice(2);
const blockMode = args.includes("--block");
// Пороговые флаги audit пробрасываются в runChecks (проект с нестандартными бюджетами задаёт
// их в команде хука, напр. `session-reminder.mjs . --block --tier0-max-kb 10`).
const THRESHOLD_FLAGS = {
  "--stale-days": "staleDays",
  "--ps-max-kb": "psMaxKb",
  "--tier1-max-kb": "tier1MaxKb",
  "--tier0-max-kb": "tier0MaxKb",
  "--plan-stale-days": "planStaleDays",
  "--frozen-commits": "frozenCommits",
};
// CODE-DRIFT — warning: на решение о блоке (оно по problems) не влияет, а стоит лишнего
// `git log` на КАЖДОМ завершении ответа. Здесь он не нужен: находки показывает SessionStart,
// --check и CI. Считаем только то, от чего зависит решение.
const auditOpts = { write: false, noCodeDrift: true };
if (args.includes("--no-git")) auditOpts.noGit = true;
for (const [flag, key] of Object.entries(THRESHOLD_FLAGS)) {
  const i = args.indexOf(flag);
  if (i !== -1 && i + 1 < args.length && Number.isFinite(Number(args[i + 1])))
    auditOpts[key] = Number(args[i + 1]);
}
const flagValueIdx = new Set(
  Object.keys(THRESHOLD_FLAGS)
    .map((f) => args.indexOf(f))
    .filter((i) => i !== -1)
    .map((i) => i + 1)
);
const root = resolve(
  args.find((a, i) => !a.startsWith("--") && !flagValueIdx.has(i)) ?? process.cwd()
);

// stdin-JSON хука (Stop): интересует stop_hook_active — защита от бесконечного цикла.
let hookInput = {};
if (!process.stdin.isTTY) {
  try {
    hookInput = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    /* не-JSON / пустой stdin — работаем дальше */
  }
}
if (hookInput.stop_hook_active) process.exit(0);

let changed = [];
try {
  const out = execFileSync("git", ["-C", root, "status", "--porcelain"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  changed = out
    .split("\n")
    .filter(Boolean)
    .filter((l) => !l.slice(3).startsWith(".memory_bank/"));
} catch {
  process.exit(0);
}
if (!changed.length) process.exit(0);

// Блокнот захвата на ходу: пуст (нет строк после метки SCRATCH START) ИЛИ — при --scratch-fresh-days N
// (opt-in, v1.7.0) — протух: все датированные записи `- YYYY-MM-DD …` старше N дней. Одна непустота
// гейт не держит: старый текст в блокноте гасил проверку навсегда (remlab: 120 строк за 2 дня, свод не
// запускался). Эвристика по датам не доказывает захват ИМЕННО этой сессии (критика Codex: недатированный
// текст = вечный false negative, строка «свод выполнен» открывает окно в N дней) — поэтому по умолчанию
// ВЫКЛЮЧЕНА (0), обкатывается на remlab флагом в команде хука; PreCompact пока проверяет непустоту.
// Возвращает null (ок) или причину.
const SCRATCH_FRESH_DAYS = (() => {
  const i = args.indexOf("--scratch-fresh-days");
  return i !== -1 && Number.isFinite(Number(args[i + 1])) ? Number(args[i + 1]) : 0;
})();
function scratchProblem() {
  const f = join(root, ".memory_bank", "_intake", "session-scratch.md");
  if (!existsSync(f)) return "блокнот _intake/session-scratch.md ПУСТ (файла нет) — захват сессии не сделан";
  try {
    const txt = readFileSync(f, "utf8");
    const i = txt.indexOf("SCRATCH START");
    const tail = (i === -1 ? txt : txt.slice(txt.indexOf("\n", i) + 1)).replace(/<!--[\s\S]*?-->/g, "");
    if (tail.trim().length === 0) return "блокнот _intake/session-scratch.md ПУСТ — захват сессии не сделан";
    if (!SCRATCH_FRESH_DAYS) return null; // проверка свежести не включена — достаточно непустоты
    const dates = [...tail.matchAll(/^- (\d{4}-\d{2}-\d{2})/gm)].map((m) => m[1]);
    if (!dates.length) return null; // недатированные записи — считаем свежими
    const newest = dates.sort().pop();
    const ageDays = Math.round((Date.now() - Date.parse(newest)) / 86400000);
    if (ageDays > SCRATCH_FRESH_DAYS)
      return `в блокноте нет записи свежее ${SCRATCH_FRESH_DAYS}д (последняя ${newest}) — захват этой сессии не сделан, старые строки гейт не держат`;
    return null;
  } catch {
    return "блокнот _intake/session-scratch.md не читается";
  }
}

// Активный план: in_progress, либо completed, но всё ещё в plans/ (гейт переноса не пройден).
function activePlan() {
  const dir = join(root, ".memory_bank", "plans");
  if (!existsSync(dir)) return null;
  for (const n of readdirSync(dir).sort()) {
    if (!n.endsWith(".md") || n === "README.md" || n === "_template.md") continue;
    try {
      const st = (readFileSync(join(dir, n), "utf8").match(/^status:\s*(\S+)/m) || [])[1];
      if (st === "in_progress" || st === "completed") return { file: n, status: st };
    } catch {
      /* нечитаемый план — пропускаем */
    }
  }
  return null;
}

// Структурная проверка банка тем же кодом, что audit --check (без спавна второго node).
let audit = null;
try {
  audit = runChecks(root, auditOpts);
} catch {
  /* нет .memory_bank / сбой — не считаем грязным */
}
const auditDirty = !!(audit && !audit.fatal && !audit.ok);
const scratchWhy = scratchProblem();
const empty = !!scratchWhy;
const plan = activePlan();

if (blockMode && plan && (empty || auditDirty)) {
  const why = [];
  if (empty) why.push(scratchWhy);
  if (auditDirty)
    why.push(
      `memory-audit: ${audit.problems.length} наход(ок): ${audit.problems.slice(0, 3).join(" · ")}${audit.problems.length > 3 ? " · …" : ""}`
    );
  // ЕДИНСТВЕННЫЙ stdout в этом режиме — JSON решения (иначе харнесс не распарсит).
  console.log(
    JSON.stringify({
      decision: "block",
      reason:
        `Гейт памяти (план ${plan.file}: ${plan.status}; изменено файлов вне .memory_bank/: ${changed.length}). ` +
        `Запусти /memory-check и доведи audit до «чисто», затем завершай. Причина: ${why.join("; ")}`,
    })
  );
  process.exit(0);
}

// Мягкое напоминание (default-режим или узкое условие блока не выполнено) — видит пользователь.
console.log(
  `⚠ Похоже, в сессии была содержательная работа (изменено файлов вне .memory_bank/: ${changed.length}).`
);
if (empty) {
  console.log(`  ${scratchWhy}.`);
  console.log("  Запусти /memory-check (разнесёт решения по .memory_bank/) — иначе факты сессии потеряются.");
} else {
  console.log("  Перед /clear запусти /memory-check — консолидировать блокнот и захват сессии в .memory_bank/.");
}
if (auditDirty) {
  console.log(`  memory-audit --check: ${audit.problems.length} наход(ок):`);
  for (const p of audit.problems.slice(0, 10)) console.log("    - " + p);
  if (audit.problems.length > 10) console.log(`    … и ещё ${audit.problems.length - 10}`);
}
