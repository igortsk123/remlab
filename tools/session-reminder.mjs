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
import { runChecks, THRESHOLD_KEYS } from "./memory-audit.mjs";
import {
  readOwnEdits, mayHoldRules, onlyOwn, porcelainPath, isOwn, ownRulesEdits, parseStrazh, strazhVerdict,
  runStrazh, strazhAnswer, strazhNotFound, STRAZH_REL, defaultStrazhCmd, dropForeignProblems, DEFAULT_BLOCK_FIELDS,
} from "./stop-gate-own.mjs";

const args = process.argv.slice(2);
const blockMode = args.includes("--block");
// T-20261127-175/5 (Fable 27 § 2–3), оба флага выключены по умолчанию — без них хук работает как раньше:
//   --own-edits   гейт судит ТОЛЬКО по файлам, которые ЭТА сессия правила Edit/Write (из стенограммы stdin.transcript_path); чужая
//                 незакоммиченная правка в общей копии и чужие находки аудита сессию не блокируют; стенограммы нет → не блокируем;
//   --strazh      у директора (REMLAB_ROLE=директор) и только если он правил файлы правил и они не закоммичены: запускает страж
//                 (tools/ops/rules_guard.py --check или --strazh-cmd "<команда>") и блокирует при «просрочено»/«вне реестра» > 0
//                 (--strazh-fields «просрочено,вне реестра,без разбора,на удаление» — чем блокировать). Стража нет в дереве — блок «страж не найден: путь»;
//                 страж упал/пустой вывод/нет счётчиков — блок «страж не ответил: код N»; страж сказал «реестр не читается» — блок с причиной
//                 (молчать нельзя — так проверка тихо отваливается).
const ownMode = args.includes("--own-edits");
const strazhMode = args.includes("--strazh");
const argVal = (flag) => {
  const i = args.indexOf(flag);
  return i !== -1 && i + 1 < args.length ? args[i + 1] : null;
};
const strazhCmdArg = argVal("--strazh-cmd");
const strazhFields = (argVal("--strazh-fields") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
// Пороговые флаги audit пробрасываются в runChecks (все 11 — тот же словарь, что у CLI). Проекту
// с нестандартными бюджетами флаги в команде хука больше не нужны: runChecks сам читает
// project-owned `.memory_bank/_kit/audit-flags.txt` (v1.8); флаг в команде — точечное переопределение.
const THRESHOLD_FLAGS = THRESHOLD_KEYS;
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
  [...Object.keys(THRESHOLD_FLAGS), "--strazh-cmd", "--strazh-fields", "--scratch-fresh-days"]
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
// Рабочий (вкладка «рабочие:рабочий N») /memory-check не запускает — свод делает директор (P-037, T-20261123-23 п.4):
// гейт и напоминание ему не нужны, иначе Stop-хук требует то, что правило запрещает. Переменную ставит запуск вкладки рабочего.
if (process.env.REMLAB_ROLE === "рабочий") process.exit(0);

let changed = [];
let dirtyAll = [];
try {
  const out = execFileSync("git", ["-C", root, "status", "--porcelain"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  dirtyAll = out.split("\n").filter(Boolean);
  changed = dirtyAll.filter((l) => !l.slice(3).startsWith(".memory_bank/"));
} catch {
  process.exit(0);
}
// Свои правки сессии (из стенограммы) — только если включён один из флагов T-175/5.
const transcriptRead = ownMode || strazhMode ? readOwnEdits(hookInput.transcript_path, root) : null;
const own = transcriptRead ? transcriptRead.own : null;
const dirtyPaths = dirtyAll.map(porcelainPath);
// Строки стенограммы длиннее предела пропущены (свои правки в них не учтены) — число видно В СТРОКЕ гейта (в причине блока и в напоминании), а не только в stderr (Fable 27, ❓4 → правка).
const skipNote = transcriptRead?.skipped ? `пропущено строк: ${transcriptRead.skipped} (длиннее предела, свои правки в них не учтены)` : "";
const withSkip = (reason) => (skipNote ? `${reason} [стенограмма: ${skipNote}]` : reason);

// Стенограмма не прочиталась (длинная/битая/нет) — «свои правки» неизвестны; это НЕ «правок нет» (27.11: у директора 1,29 ГБ → гейт и страж молчали).
// Директору — блок, если есть что проверять (незакоммиченные файлы правил при --strazh; чужие/свои несохранённые при --own-edits); остальным — предупреждение в stderr.
if (transcriptRead && !own) {
  const rulesDirty = dirtyPaths.filter(mayHoldRules);
  const need = (strazhMode && rulesDirty.length > 0) || (ownMode && changed.length > 0);
  if (blockMode && process.env.REMLAB_ROLE === "директор" && need) {
    console.log(
      JSON.stringify({
        decision: "block",
        reason: withSkip(
          `Гейт: стенограмма не читается: ${transcriptRead.why}. Что правила именно эта сессия, не определить, а в дереве есть несохранённое ` +
            `(${(strazhMode && rulesDirty.length ? rulesDirty : changed.map(porcelainPath)).slice(0, 3).join(", ")}) — проверка «своих правок» и стража молчать не может: ` +
            `почини чтение (tools/stop-gate-own.mjs, readOwnEdits) или закоммить/верни эти файлы, затем завершай.`
        ),
      })
    );
    process.exit(0);
  }
  console.error(`session-reminder: стенограмма не читается: ${transcriptRead.why} — гейт «только свои правки» и строка стража в этом ответе не работают`);
} else if (transcriptRead?.skipped) {
  console.error(`session-reminder: в стенограмме пропущено слишком длинных строк: ${transcriptRead.skipped} (свои правки в них не учтены)`);
}

// Строка стража — только у директора и только по его правкам файлов правил, ещё не закоммиченных (чужие сессии и рабочие не трогаем).
if (strazhMode && process.env.REMLAB_ROLE === "директор" && blockMode) {
  const myRules = ownRulesEdits(own).filter((p) => dirtyPaths.some((d) => d === p || (d.endsWith("/") && p.startsWith(d))));
  if (myRules.length) {
    const cmd = strazhCmdArg ? strazhCmdArg.split(/\s+/).filter(Boolean) : defaultStrazhCmd(root);
    // нет файла стража (команды по умолчанию) — НЕ молчим: «страж не найден: путь» (Fable 27 (в)); есть команда, а ответа нет — «не ответил»; реестр не читается — свой блок
    const answer = cmd ? strazhAnswer(runStrazh(cmd, root)) : strazhNotFound(join(root, STRAZH_REL));
    const line = answer.line ?? null;
    if (!answer.ok) {
      const tail =
        answer.kind === "registry"
          ? `починить tools/scout/rules/rule-registry.json (валидный JSON с rules и groups; git diff покажет, что сломалось) и завершать — пока реестр не читается, сроки и выключатели не проверены.`
          : answer.kind === "switches"
            ? `починить настройки/порог сторожа выключателей (tools/scout/rules/switch-settings.json, switch-guard-threshold.json; python3 tools/ops/rule_switch_guard.py покажет, чего нет) и завершать — пока он не работает, «вне реестра» не измерено.`
            :`а проверить их нечем — почини страж (python3 tools/ops/rules_guard.py --check) и завершай; молча пропускать нельзя.`;
      console.log(
        JSON.stringify({
          decision: "block",
          reason: withSkip(`Гейт стража правил: ${answer.silent}. Ты правил файлы правил (${myRules.slice(0, 3).join(", ")}${myRules.length > 3 ? ", …" : ""}), ` + tail),
        })
      );
      process.exit(0);
    }
    const verdict = strazhVerdict(answer.parsed, strazhFields.length ? strazhFields : DEFAULT_BLOCK_FIELDS);
    if (verdict.block) {
      console.log(
        JSON.stringify({
          decision: "block",
          reason: withSkip(
            `Гейт стража правил: ${line.trim()} → ${verdict.bad.join(", ")}. Ты правил файлы правил (${myRules.slice(0, 3).join(", ")}${myRules.length > 3 ? ", …" : ""}) — ` +
              `доведи реестр и сроки до нуля (правило в реестр, решение или один перенос срока с причиной), затем завершай.`
          ),
        })
      );
      process.exit(0);
    }
  }
}

if (ownMode) changed = onlyOwn(changed, own); // чужие и неизвестные (нет стенограммы) правки гейт не считает
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
if (ownMode && audit && !audit.fatal && !audit.ok)
  audit = { ...audit, problems: dropForeignProblems(audit.problems, dirtyPaths, own) }; // находки, названные только про чужие незакоммиченные файлы, сессию не держат
const auditDirty = !!(audit && !audit.fatal && (ownMode ? audit.problems.length > 0 : !audit.ok));
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
      reason: withSkip(
        `Гейт памяти (план ${plan.file}: ${plan.status}; изменено файлов вне .memory_bank/: ${changed.length}). ` +
          `Запусти /memory-check и доведи audit до «чисто», затем завершай. Причина: ${why.join("; ")}`
      ),
    })
  );
  process.exit(0);
}

// Мягкое напоминание (default-режим или узкое условие блока не выполнено) — видит пользователь.
console.log(
  `⚠ Похоже, в сессии была содержательная работа (изменено файлов вне .memory_bank/: ${changed.length}).`
);
if (skipNote) console.log(`  Стенограмма: ${skipNote}.`);
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
