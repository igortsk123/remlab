#!/usr/bin/env node
// nightly-verify — ночная сверка памяти с кодом (модуль кита `_optional/nightly-verify`, v1.11; план remlab
// mem-freshness-01 п. 4, разбор Codex 05.11 § «Ночная сверка»). Банк обновляется сам: каждую ночь 1–2 дока
// сверяются с текущим кодом, правки — в отдельной ветке на утреннее ревью. Push и авто-влива НЕТ.
//
//   node tools/nightly-verify/nightly-verify.mjs [--root <проект>] [--dry-run] [--tools <папка tools кита>]
//
// Порядок прогона (один процесс на проект — flock):
//   1) `git fetch <remote> <branch>`; чистая копия ВНЕ .claude/ (по умолчанию `<root>/.nightly-verify/wt`, скрыта в
//      .git/info/exclude) на свежем `<remote>/<branch>`;
//   2) очередь — заново каждый запуск (общего изменяемого файла очереди нет):
//        а) доки, задетые кодом за последние `since_hours` (tools/memory-impact.mjs, статус «в очередь сверки»);
//        б) `--drift-report`: код изменён после сверки дока И задеты названия из текста («!»);
//        в) остальной дрейф: сперва `importance: high`, затем самый давний коммит сверки;
//        г) ротация — самый давний `last_verified` (сводки и Tier 2; кроме `_kit/no-anchor-ignore.txt`);
//   3) бюджет: не больше `max_docs` доков и `max_claims` утверждений (оценка — строки дока со ссылками в `коде`);
//      док больше бюджета пропускается с пометкой «крупный — вручную»; пустая очередь — выход 0 БЕЗ вызова модели;
//   4) ветка `memory/nightly-<ГГГГММДД>-<N>`; headless `claude -p` (первая строка запроса — метка учёта токенов),
//      агент `verify` в режиме «по списку доков» (как /memory-check, этап 1.6); правки — только в выбранных доках и
//      `changelog/verify-log.tsv` (`memory-health --log-verify`); любой другой изменённый файл → отмена;
//   5) аудит (запись реестров, затем `--check`) и `tools/memory-project-audit.mjs` (если есть) чисты → коммит в ветку
//      (`audit_gate=new`: нет проблем сверх аудита той же копии ДО модели; при `clean` грязная копия до модели —
//      отмена без платного запуска);
//   6) main уехал за время прогона → rebase и повтор аудитов; конфликт или грязный аудит → отмена
//      (ветка переименована в `…-otmena`, в main ничего не попадает).
// Отчёт прогона — stdout (journalctl) и `<git-common-dir>/memory-bank/nightly-verify/<id>/report.md`; строка
// телеметрии — `<git-common-dir>/memory-bank/nightly-verify.log`.
//
// --dry-run: без модели, без fetch, без копии и ветки — очередь и бюджет по дереву `--root` как есть (HEAD); ничего не пишет.
//
// Конфиг — `.memory_bank/_kit/nightly-verify.conf` (project-owned; `ключ=значение`, `#` — комментарий):
//   model, max_docs (2), max_claims (60), since_hours (24), remote (origin), branch (main),
//   label ([nightly-verify]), worktree (.nightly-verify/wt), claude_bin (claude), max_budget_usd (нет),
//   audit_gate (clean — оба аудита чистые; new — нет проблем сверх тех, что были в копии до сверки).
// Exit: 0 — коммит в ветке, пустая очередь или сухой прогон; 1 — отмена; 2 — ошибка запуска; 3 — занято (flock).
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync, openSync, closeSync } from "node:fs";
import { join, resolve, dirname, relative, isAbsolute, basename } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { homedir } from "node:os";

export const DEFAULTS = {
  model: "",
  max_docs: 2,
  max_claims: 60,
  since_hours: 24,
  remote: "origin",
  branch: "main",
  label: "[nightly-verify]",
  worktree: ".nightly-verify/wt",
  claude_bin: "claude",
  max_budget_usd: "",
  audit_gate: "clean",
};
const NUM = new Set(["max_docs", "max_claims", "since_hours"]);
const REASON = { impact: "code", sym: "drift", drift: "drift", rotation: "rotation" };
const CLASS_RU = { impact: "код за сутки", sym: "дрейф, задеты названия", drift: "дрейф", rotation: "ротация" };

export function readConfig(root) {
  const cfg = { ...DEFAULTS };
  const warnings = [];
  const f = join(root, ".memory_bank", "_kit", "nightly-verify.conf");
  if (!existsSync(f)) return { cfg, warnings };
  for (const raw of readFileSync(f, "utf8").split(/\r?\n/)) {
    const l = raw.replace(/(^|\s)#.*$/, "").trim();
    if (!l) continue;
    const m = l.match(/^([a-z_]+)\s*=\s*(.*)$/);
    if (!m || !(m[1] in DEFAULTS)) {
      warnings.push(`конфиг: строка «${l}» не понята — пропущена`);
      continue;
    }
    if (NUM.has(m[1])) {
      const n = Number(m[2]);
      if (!Number.isInteger(n) || n <= 0) warnings.push(`конфиг: ${m[1]} — не целое > 0 («${m[2]}»), оставлено ${cfg[m[1]]}`);
      else cfg[m[1]] = n;
    } else if (m[1] === "audit_gate" && !["clean", "new"].includes(m[2])) warnings.push(`конфиг: audit_gate — clean или new («${m[2]}»), оставлено ${cfg.audit_gate}`);
    else cfg[m[1]] = m[2];
  }
  return { cfg, warnings };
}

function git(cwd, args, { ok = false, input } = {}) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8", input, maxBuffer: 256 * 1024 * 1024, stdio: [input ? "pipe" : "ignore", "pipe", "pipe"] });
  if (ok) return r;
  if (r.error || r.status !== 0) throw new Error(`git ${args.join(" ")}: ${(r.stderr || String(r.error || "")).trim()}`);
  return r.stdout.trim();
}

// ---------- очередь ----------
function frontmatter(text) {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  const fm = {};
  if (m) for (const l of m[1].split(/\r?\n/)) {
    const kv = l.match(/^([A-Za-z_]+):\s*(.*)$/);
    if (kv) fm[kv[1]] = kv[2].replace(/^["']|["']$/g, "").trim();
  }
  return { fm, body: m ? text.slice(m[0].length) : text };
}
/** Оценка числа проверяемых утверждений: строки тела со ссылкой в `коде` (кроме блоков ```), минимум 1. */
export function estimateClaims(text) {
  let fence = false;
  let n = 0;
  for (const l of frontmatter(text).body.split(/\r?\n/)) {
    if (/^\s*```/.test(l)) fence = !fence;
    else if (!fence && /`[^`\n]+`/.test(l)) n++;
  }
  return Math.max(1, n);
}

/**
 * Очередь сверки по дереву `dir` (рабочая копия или ночная копия): → {items:[{doc, cls, why, claims, importance}], notes}
 * `tools` — папка с memory-audit.mjs / memory-impact.mjs / code-touch-hint.mjs; `now` — Date (тесты).
 */
export async function buildQueue(dir, { tools, sinceHours = 24, head = "HEAD", now = new Date() } = {}) {
  const imp = (f) => import(pathToFileURL(join(tools, f)).href);
  const [{ runChecks }, { memoryImpact }, { isDescribingDoc }] = await Promise.all([
    imp("memory-audit.mjs"),
    imp("memory-impact.mjs"),
    imp("code-touch-hint.mjs"),
  ]);
  const mb = join(dir, ".memory_bank");
  const notes = [];
  const seen = new Map();
  const docInfo = (rel) => {
    const f = join(mb, rel);
    if (!existsSync(f)) return null;
    const text = readFileSync(f, "utf8");
    const { fm } = frontmatter(text);
    return { claims: estimateClaims(text), importance: fm.importance || "", lastVerified: /^\d{4}-\d{2}-\d{2}$/.test(fm.last_verified || "") ? fm.last_verified : "" };
  };
  const add = (rel, cls, why) => {
    rel = rel.replace(/^\.memory_bank\//, "");
    if (seen.has(rel)) return;
    const info = docInfo(rel);
    if (!info) return;
    seen.set(rel, { doc: rel, cls, why, ...info });
  };

  // Дрейф по коммиту сверки (только чтение: телеметрию пишет CLI аудита, не runChecks) — нужен и для порядка в а).
  const audit = runChecks(dir, { write: false, driftReport: true, noCodeDrift: false });
  const dr = audit.driftReport;
  const drift = !dr || dr.error ? null : dr.items.filter((x) => isDescribingDoc(`.memory_bank/${x.doc}`));
  const symDocs = new Set((drift || []).filter((x) => x.symHit).map((x) => x.doc));
  const high = (rel) => (docInfo(rel)?.importance || "") === "high";

  // а) код за последние sinceHours: base — последний коммит head до окна (по первой линии родителей). Внутри класса:
  //    importance high → задеты названия (дрейф «!») → больше изменённых файлов → по имени.
  const before = new Date(now.getTime() - sinceHours * 3600e3).toISOString();
  const base = git(dir, ["rev-list", "-1", "--first-parent", `--before=${before}`, head], { ok: true }).stdout?.trim();
  if (!base) notes.push(`код за ${sinceHours} ч: нет коммита старше окна — пропущено`);
  else {
    const res = memoryImpact(dir, base, head);
    const rows = res.rows
      .filter((r) => r.status === "в очередь сверки")
      .map((r) => ({ r, rel: r.doc.replace(/^\.memory_bank\//, "") }))
      .sort((a, b) => Number(high(b.rel)) - Number(high(a.rel)) || Number(symDocs.has(b.rel)) - Number(symDocs.has(a.rel)) ||
        b.r.files.length - a.r.files.length || a.rel.localeCompare(b.rel));
    for (const { r } of rows) add(r.doc, "impact", r.files.map((f) => f.path).join(", "));
    notes.push(`код за ${sinceHours} ч (${base.slice(0, 7)}..${git(dir, ["rev-parse", "--short", head])}): файлов кода ${res.codeFiles}, доков в очередь ${rows.length}`);
  }

  // б, в) дрейф: сперва задеты названия из текста («!»), затем остальной — importance high, затем самый давний коммит сверки
  if (!drift) notes.push(`дрейф: ${dr?.error || "отчёт не построен"}`);
  else {
    for (const x of drift.filter((y) => y.symHit))
      add(x.doc, "sym", x.hits.filter((h) => h.syms.length).map((h) => `${h.file} [${h.syms.join(", ")}]`).join("; "));
    const age = (x) => (x.base.sha === "WORKTREE" ? "9999-99-99" : x.base.date);
    const rest = drift.filter((y) => !y.symHit);
    rest.sort((a, b) => Number(high(b.doc)) - Number(high(a.doc)) || age(a).localeCompare(age(b)));
    for (const x of rest) add(x.doc, "drift", `сверка ${age(x)}; ${x.hits.map((h) => h.file).join(", ")}`);
    notes.push(`дрейф: доков ${drift.length}, из них задеты названия ${symDocs.size}`);
  }

  // г) ротация: самый давний last_verified среди доков-описаний (Tier 1 и Tier 2), кроме no-anchor-ignore
  const ign = new Set();
  const ignFile = join(mb, "_kit", "no-anchor-ignore.txt");
  if (existsSync(ignFile)) for (const l of readFileSync(ignFile, "utf8").split(/\r?\n/)) {
    const t = l.replace(/#.*/, "").trim().split(/\s+/)[0];
    if (t) ign.add(t);
  }
  const all = git(dir, ["ls-files", "-z", "--", ".memory_bank"]).split("\0").filter((p) => p && isDescribingDoc(p));
  const rot = all
    .map((p) => p.replace(/^\.memory_bank\//, ""))
    .filter((rel) => !ign.has(rel))
    .map((rel) => ({ rel, info: docInfo(rel) }))
    .filter((r) => r.info?.lastVerified)
    .sort((a, b) => a.info.lastVerified.localeCompare(b.info.lastVerified) || a.rel.localeCompare(b.rel));
  for (const r of rot) add(r.rel, "rotation", `last_verified ${r.info.lastVerified}`);
  return { items: [...seen.values()], notes };
}

/** Бюджет: по порядку очереди, пока доков < maxDocs и утверждений ≤ maxClaims; крупный док — пропуск с пометкой. */
export function pickBudget(items, { maxDocs, maxClaims }) {
  const picked = [];
  const tooBig = [];
  let claims = 0;
  for (const it of items) {
    if (picked.length >= maxDocs) break;
    if (it.claims > maxClaims) {
      if (it.cls !== "rotation") tooBig.push(it); // ротация крупных — не сигнал, просто следующий
      continue;
    }
    if (claims + it.claims > maxClaims) continue;
    picked.push(it);
    claims += it.claims;
  }
  return { picked, claims, tooBig };
}

function renderQueue(q, pick, cfg) {
  const out = [`Очередь сверки: ${q.items.length} док(ов); бюджет — ${cfg.max_docs} док(а), ≤ ${cfg.max_claims} утверждений (оценка)`];
  for (const n of q.notes) out.push(`  · ${n}`);
  const chosen = new Set(pick.picked.map((p) => p.doc));
  q.items.slice(0, 15).forEach((it, i) =>
    out.push(`  ${chosen.has(it.doc) ? "→" : " "} ${String(i + 1).padStart(2)}. ${it.doc} — ${CLASS_RU[it.cls]}, ~${it.claims} утв.${it.importance ? `, importance ${it.importance}` : ""} (${it.why.length > 90 ? it.why.slice(0, 89) + "…" : it.why})`)
  );
  if (q.items.length > 15) out.push(`     … и ещё ${q.items.length - 15}`);
  out.push(
    pick.picked.length
      ? `Сегодня: ${pick.picked.map((p) => p.doc).join(", ")} — ~${pick.claims} утверждений`
      : "Сегодня: нечего сверять в пределах бюджета — модель не вызывается"
  );
  if (pick.tooBig.length) out.push(`Крупные — вручную (больше ${cfg.max_claims} утверждений): ${pick.tooBig.map((p) => `${p.doc} (~${p.claims})`).join(", ")}`);
  return out.join("\n");
}

// ---------- прогон ----------
/**
 * Бюджеты размера выбранных доков — из аудита копии (`sizeBudget` + пороги `_kit/audit-flags.txt`), не хардкодом.
 * Аудит старше v1.11 (нет `sizeBudget`) — бюджетов в запросе нет, ловит только аудит после прогона.
 */
export async function docBudgets(dir, tools, docs) {
  let mod;
  try {
    mod = await import(pathToFileURL(join(tools, "memory-audit.mjs")).href);
  } catch {
    return {};
  }
  if (typeof mod.sizeBudget !== "function" || typeof mod.projectThresholds !== "function") return {};
  const o = mod.projectThresholds(dir);
  const out = {};
  for (const d of docs) {
    const f = join(dir, ".memory_bank", d);
    if (!existsSync(f)) continue;
    const text = readFileSync(f, "utf8");
    const b = mod.sizeBudget(d, (mod.parseFrontmatter ? mod.parseFrontmatter(text).fm : frontmatter(text).fm) || {}, text, o);
    if (b) out[d] = b;
  }
  return out;
}

const budgetText = (b) =>
  `бюджет ${b.check}: ${b.what} ≤ ${b.limitKb} KB (${Math.floor(b.limitKb * 1024)} байт), сейчас ${b.bytes} байт` +
  (b.bytes > b.limitKb * 1024 ? " — УЖЕ БОЛЬШЕ, сократи" : `, запас ${Math.floor(b.limitKb * 1024) - b.bytes}`);

export function buildPrompt(cfg, picked, today, budgets = {}) {
  const list = picked
    .map((p) => `- .memory_bank/${p.doc} — причина: ${CLASS_RU[p.cls]} (--reason ${REASON[p.cls]})${budgets[p.doc] ? `; ${budgetText(budgets[p.doc])}` : ""}`)
    .join("\n");
  const anyBudget = picked.some((p) => budgets[p.doc]);
  return `${cfg.label}
Ночная сверка памяти с кодом (без человека). Это не задача на код: код НЕ меняй, ничего не коммить, ничего не запускай,
кроме команд ниже.

Доки на сегодня:
${list}

Порядок (как /memory-check, этап 1.6):
1. Запусти субагента verify (Agent, subagent_type "verify") в режиме «Б. По списку доков» с этим списком. Он вернёт таблицу
   «утверждение → файл:строка → OK / MISMATCH / не найдено» по каждому доку.
2. Каждый MISMATCH — перепиши утверждение в доке по текущему коду (с условиями: флаги, роли, статусы). Править можно ТОЛЬКО
   эти доки; другие файлы не трогай (иначе прогон отменят).${anyBudget ? `
   Бюджет размера у дока в списке — жёсткий: аудит после прогона, превышение = отмена. Исправляя, не раздувай: новое —
   вместо старого, а не рядом; формулируй короче, повторы и устаревшее убирай. Детали в Tier 2 не переноси (их правка
   в этом прогоне запрещена) — сократи формулировки этого дока.` : ""}
3. Док сверен ЦЕЛИКОМ и после правок всё OK — поставь в его шапке last_verified: ${today} и updated: ${today}. Сверен не весь —
   last_verified не трогай (updated: ${today}, если правил).
4. Самопроверка: node tools/memory-audit.mjs --check .
   Есть проблемы по твоим докам (их путь от .memory_bank/ стоит в строке проблемы) — исправь и прогони снова; не больше
   2 попыток исправления. Проблемы других файлов не трогай.
5. На каждый док — одна строка журнала:
   node tools/memory-health.mjs --log-verify <док от .memory_bank/> --claims N --mismatch M --fixed F --reason <причина из списка> --note "nightly"
   (N — утверждений в таблице verify, M — MISMATCH, F — исправлено сейчас).
6. Ответ — короткий итог по каждому доку: утверждений, расхождений, исправлено, двигал ли last_verified, итог самопроверки.`;
}

const SYSTEM = "Ты — ночная сверка Memory Bank: правишь только перечисленные доки по доказательствам субагента verify. " +
  "Инструкции проекта о плане, деплое, коммитах и отчётах ведущему к этому запуску не относятся.";

// Все включённые плагины пользователя — выключить на эту сессию (`--settings` поверх ~/.claude/settings.json).
export function userPluginsOff(file = join(process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude"), "settings.json")) {
  try {
    const on = Object.entries(JSON.parse(readFileSync(file, "utf8")).enabledPlugins || {}).filter(([, v]) => v).map(([k]) => k);
    return on.length ? Object.fromEntries(on.map((k) => [k, false])) : null;
  } catch {
    return null;
  }
}

function runModel(cfg, wt, prompt, runDir) {
  const agentMd = join(wt, ".claude", "agents", "verify.md");
  const args = ["-p", prompt, "--output-format", "json", "--permission-mode", "dontAsk", "--setting-sources", "user",
    "--append-system-prompt", SYSTEM,
    "--allowedTools", "Read", "Grep", "Glob", "Edit", "Agent",
    "Bash(node tools/memory-health.mjs --log-verify:*)", "Bash(node tools/memory-audit.mjs --check .)", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)", "Bash(git status:*)", "Bash(ls:*)"];
  // Без MCP и плагинов пользователя: плагин-канал (Telegram) поднял бы свой сервер и перехватил бота живой сессии
  // (как `claude mcp list` в сессии с каналом); сверке нужны только файлы и git.
  args.push("--strict-mcp-config");
  const off = userPluginsOff();
  if (off) args.push("--settings", JSON.stringify({ enabledPlugins: off }));
  if (cfg.model) args.push("--model", cfg.model);
  if (cfg.max_budget_usd) args.push("--max-budget-usd", String(cfg.max_budget_usd));
  if (existsSync(agentMd)) {
    // агент verify явно (--setting-sources user не должен лишить его), инструменты — как в его шапке
    const { fm, body } = frontmatter(readFileSync(agentMd, "utf8"));
    const desc = (fm.description && fm.description !== ">" ? fm.description : "Read-only сверка доков памяти с кодом").slice(0, 300);
    const tools = (fm.tools || "Read, Grep, Glob, Bash").split(/,\s*/);
    writeFileSync(join(runDir, "agents.json"), JSON.stringify({ verify: { description: desc, prompt: body.trim(), tools } }));
    args.push("--agents", join(runDir, "agents.json"));
  }
  const r = spawnSync(cfg.claude_bin, args, { cwd: wt, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 3 * 3600e3, env: { ...process.env, NIGHTLY_VERIFY: "1" } });
  writeFileSync(join(runDir, "claude.json"), r.stdout || "");
  if (r.stderr) writeFileSync(join(runDir, "claude.stderr.txt"), r.stderr);
  let res = {};
  try {
    res = JSON.parse(r.stdout || "{}");
  } catch {
    /* не JSON — итог берём как текст */
  }
  return { ok: !r.error && r.status === 0, status: r.status, error: r.error?.message, result: res.result ?? r.stdout ?? "", cost: res.total_cost_usd, session: res.session_id };
}

// Строки проблем аудита («  - …»): по ним гейт `audit_gate=new` сравнивает «до» и «после» сверки.
export const problemLines = (text) => String(text || "").split("\n").filter((l) => /^\s+- /.test(l)).map((l) => l.trim().slice(2));

function audits(wt, { write = true } = {}) {
  const out = [];
  const problems = [];
  let clean = true;
  const node = (a) => spawnSync(process.execPath, a, { cwd: wt, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (write) node(["tools/memory-audit.mjs", "."]); // запись реестров (GENERATED-блоки), если док сменил шапку
  const a = node(["tools/memory-audit.mjs", "--check", "."]);
  out.push(`memory-audit --check: exit ${a.status}`);
  if (a.status !== 0) {
    clean = false;
    const pl = problemLines(a.stdout);
    problems.push(...pl.map((l) => `audit: ${l}`));
    out.push((pl.length ? pl.map((l) => `  - ${l}`) : (a.stdout || a.stderr || "").trim().split("\n").slice(-5)).slice(0, 10).join("\n"));
  }
  if (existsSync(join(wt, "tools", "memory-project-audit.mjs"))) {
    const p = node(["tools/memory-project-audit.mjs", "."]);
    out.push(`memory-project-audit: exit ${p.status}`);
    if (p.status !== 0) {
      clean = false;
      problems.push(...problemLines(p.stdout).map((l) => `project: ${l}`));
      out.push((p.stdout || p.stderr || "").trim().split("\n").slice(-10).join("\n"));
    }
  }
  return { clean, problems, text: out.filter(Boolean).join("\n") };
}

// Гейт аудитов: `clean` — оба чистые (по умолчанию); `new` — нет проблем, которых не было в копии ДО сверки
// (для проектов, где чистая копия из git не чиста сама: ссылки на файлы вне git, `ROADMAP` #15 п. 5).
function auditPass(a, base, gate) {
  if (a.clean) return { ok: true, fresh: [] };
  // упал без разборчивых строк (ошибка запуска и т. п.) — сравнить нечего, отмена
  if (!a.problems.length) return { ok: false, fresh: [], why: "аудит не чист (проблемы не разобраны по строкам)" };
  const old = new Set(gate === "new" ? base.problems : []);
  const fresh = a.problems.filter((x) => !old.has(x));
  if (!fresh.length) return { ok: true, fresh };
  return { ok: false, fresh, why: `${gate === "new" ? "новые проблемы аудита" : "аудит не чист"}: ${fresh.slice(0, 3).join("; ")}` };
}

// Проблема «своя» — про один из выбранных доков: строка аудита `<ПРОВЕРКА> <док от .memory_bank/> — …`
// (с префиксом источника `audit: ` / `project: `). Все новые проблемы свои → работа модели сохраняется в ветке `…-otmena`.
export function ownProblems(problems, docs) {
  const set = new Set(docs);
  const own = [];
  const other = [];
  for (const x of problems) {
    const t = x.replace(/^(audit|project): /, "").split(/\s+/);
    (set.has(t[1]) ? own : other).push(x);
  }
  return { own, other };
}

function changedPaths(wt) {
  // без trim: первая запись « M путь» начинается с пробела, обрезка съела бы первый символ пути
  return (git(wt, ["status", "--porcelain", "-z", "--untracked-files=all", "--no-renames"], { ok: true }).stdout || "")
    .split("\0")
    .filter(Boolean)
    .map((l) => l.slice(3));
}

function lock(common, argv) {
  if (process.env.NIGHTLY_VERIFY_LOCKED === "1") return null; // уже под flock
  const dir = join(common, "memory-bank");
  mkdirSync(dir, { recursive: true });
  const lf = join(dir, "nightly-verify.lock");
  closeSync(openSync(lf, "a"));
  const r = spawnSync("flock", ["-n", "-E", "3", lf, process.execPath, fileURLToPath(import.meta.url), ...argv], {
    stdio: "inherit",
    env: { ...process.env, NIGHTLY_VERIFY_LOCKED: "1" },
  });
  if (r.error) throw new Error(`flock недоступен: ${r.error.message}`);
  if (r.status === 3) console.error("nightly-verify: уже идёт прогон этого проекта (flock) — выход");
  return r.status ?? 2;
}

function excludeWorktree(common, wtRel) {
  const f = join(common, "info", "exclude");
  const line = `/${wtRel.split("/")[0]}/`;
  const cur = existsSync(f) ? readFileSync(f, "utf8") : "";
  if (!cur.split(/\r?\n/).includes(line)) {
    mkdirSync(dirname(f), { recursive: true });
    appendFileSync(f, `${cur && !cur.endsWith("\n") ? "\n" : ""}# nightly-verify: копия ночной сверки\n${line}\n`);
  }
}

export async function main(argv = process.argv.slice(2)) {
  const arg = (k) => {
    const i = argv.indexOf(k);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const root = resolve(arg("--root") || process.cwd());
  const dry = argv.includes("--dry-run");
  if (!existsSync(join(root, ".memory_bank"))) {
    console.error(`nightly-verify: нет .memory_bank в ${root}`);
    return 2;
  }
  const { cfg, warnings } = readConfig(root);
  for (const w of warnings) console.error(`nightly-verify: ${w}`);
  const now = process.env.NIGHTLY_VERIFY_NOW ? new Date(process.env.NIGHTLY_VERIFY_NOW) : new Date();
  const today = now.toISOString().slice(0, 10);

  if (dry) {
    const tools = resolve(arg("--tools") || join(root, "tools"));
    const q = await buildQueue(root, { tools, sinceHours: cfg.since_hours, now });
    const pick = pickBudget(q.items, { maxDocs: cfg.max_docs, maxClaims: cfg.max_claims });
    console.log(`[сухой прогон] дерево ${root} как есть (HEAD ${git(root, ["rev-parse", "--short", "HEAD"])}), без модели, без fetch, без копии и ветки; ничего не пишется`);
    console.log(`модель: ${cfg.model || "по умолчанию claude"}; метка: ${cfg.label}`);
    console.log(renderQueue(q, pick, cfg));
    const bud = await docBudgets(root, tools, pick.picked.map((p) => p.doc));
    for (const p of pick.picked) if (bud[p.doc]) console.log(`  ${p.doc}: ${budgetText(bud[p.doc])}`);
    return 0;
  }

  const common = resolve(root, git(root, ["rev-parse", "--git-common-dir"]));
  const locked = lock(common, argv);
  if (locked !== null) return locked;

  const upstream = `${cfg.remote}/${cfg.branch}`;
  const wt = isAbsolute(cfg.worktree) ? cfg.worktree : join(root, cfg.worktree);
  if (relative(root, wt).split("/").includes(".claude")) {
    console.error("nightly-verify: копия внутри .claude/ запрещена (хуки и аудит считают такие пути не кодом)");
    return 2;
  }
  git(root, ["fetch", "-q", cfg.remote, cfg.branch]);
  if (!isAbsolute(cfg.worktree)) excludeWorktree(common, cfg.worktree);
  if (!existsSync(join(wt, ".git"))) git(root, ["worktree", "add", "-q", "--detach", wt, upstream]);
  else {
    git(wt, ["checkout", "-q", "--force", "--detach", upstream]);
    git(wt, ["clean", "-q", "-fd"]); // остатки прерванного прогона — только в своей копии
  }
  const baseSha = git(wt, ["rev-parse", "HEAD"]);
  const tools = resolve(arg("--tools") || join(wt, "tools"));
  const q = await buildQueue(wt, { tools, sinceHours: cfg.since_hours, now });
  const pick = pickBudget(q.items, { maxDocs: cfg.max_docs, maxClaims: cfg.max_claims });
  const report = [`# Ночная сверка ${today}`, "", `База: ${upstream} ${baseSha.slice(0, 7)}`, "", "```", renderQueue(q, pick, cfg), "```"];
  const tele = (status, extra = "") =>
    appendFileSync(join(common, "memory-bank", "nightly-verify.log"), `${now.toISOString()}\t${status}\t${pick.picked.map((p) => p.doc).join(",") || "-"}\t${pick.claims}\t${extra}\n`);
  if (!pick.picked.length) {
    console.log(report.join("\n"));
    tele("empty");
    return 0;
  }
  // аудит копии ДО модели (без записи): при строгом гейте грязная копия — отмена без платного запуска
  const base = audits(wt, { write: false });
  report.push("", `Аудит копии до сверки: ${base.clean ? "чисто" : `проблем ${base.problems.length} (гейт ${cfg.audit_gate})`}`);
  if (!base.clean) report.push("```", base.text, "```");
  if (!base.clean && cfg.audit_gate !== "new") {
    report.push("", "**Итог: отмена до модели** — чистая копия из git уже не проходит аудит; поправить банк или `audit_gate=new`");
    console.log(report.join("\n"));
    tele("audit-dirty", `${base.problems.length} проблем до сверки`);
    return 1;
  }

  const stamp = today.replace(/-/g, "");
  const existing = git(root, ["branch", "--list", `memory/nightly-${stamp}-*`]).split("\n").filter(Boolean).length;
  const id = `${stamp}-${existing + 1}`;
  const branchName = `memory/nightly-${id}`;
  const runDir = join(common, "memory-bank", "nightly-verify", id);
  mkdirSync(runDir, { recursive: true });
  git(wt, ["switch", "-q", "-c", branchName]);
  const budgets = await docBudgets(wt, tools, pick.picked.map((p) => p.doc));
  const prompt = buildPrompt(cfg, pick.picked, today, budgets);
  writeFileSync(join(runDir, "prompt.txt"), prompt);
  const m = runModel(cfg, wt, prompt, runDir);
  report.push("", `Модель: ${m.ok ? "ok" : `ошибка (exit ${m.status}${m.error ? `, ${m.error}` : ""})`}${m.cost !== undefined ? ` · $${m.cost}` : ""}${m.session ? ` · сессия ${m.session}` : ""}`, "", String(m.result).trim());

  const finish = (status, why) => {
    report.push("", `**Итог: ${status}**${why ? ` — ${why}` : ""}`, `Отчёт: ${join(runDir, "report.md")}`);
    writeFileSync(join(runDir, "report.md"), report.join("\n") + "\n");
    console.log(report.join("\n"));
    tele(status, why || "");
  };
  const cancel = (why) => {
    git(wt, ["checkout", "-q", "--force", "--detach", baseSha]);
    git(wt, ["clean", "-q", "-fd"]);
    git(root, ["branch", "-m", branchName, `${branchName}-otmena`]);
    finish("отмена", why);
    return 1;
  };
  // Аудит не пропустил только из-за выбранных доков (раздулась сводка и т. п.) — сверка сделана, терять её жалко:
  // коммит в ветку `…-otmena` + patch в каталоге прогона, утром ведущий доводит руками. Main и origin не трогаются.
  const committed = () => git(wt, ["rev-parse", "HEAD"]) !== baseSha;
  const commitWork = (subject) =>
    git(wt, ["-c", "user.name=nightly-verify", "-c", "user.email=nightly-verify@localhost", "commit", "-q", "-m",
      `${subject} ${pick.picked.map((p) => basename(p.doc, ".md")).join(", ")} ${cfg.label}\n\nОчередь: ${pick.picked.map((p) => `${p.doc} (${CLASS_RU[p.cls]})`).join("; ")}.`]);
  const failGate = (g, suffix = "") => {
    const { own, other } = ownProblems(g.fresh, pick.picked.map((p) => p.doc));
    if (!own.length || other.length) return cancel(`${g.why}${suffix}`);
    if (!committed()) {
      git(wt, ["add", "-A", "--", ".memory_bank"]);
      commitWork("memory(nightly, НЕ ПРОШЛО АУДИТ): сверка");
    }
    const sha = git(wt, ["rev-parse", "--short", "HEAD"]);
    const patch = join(runDir, "sverka.patch");
    writeFileSync(patch, git(wt, ["format-patch", "-1", "--stdout", "HEAD"]) + "\n");
    git(wt, ["checkout", "-q", "--force", "--detach", baseSha]);
    git(wt, ["clean", "-q", "-fd"]);
    git(root, ["branch", "-m", branchName, `${branchName}-otmena`]);
    finish("отмена, работа сохранена", `${g.why}${suffix}. Правки — ветка ${branchName}-otmena (${sha}) и ${patch}; довести руками: ` +
      `\`git cherry-pick ${sha}\`, сократить, аудит`);
    return 1;
  };
  if (!m.ok) return cancel("модель завершилась с ошибкой");

  const allowed = new Set([...pick.picked.map((p) => `.memory_bank/${p.doc}`), ".memory_bank/changelog/verify-log.tsv"]);
  const changed = changedPaths(wt);
  const foreign = changed.filter((p) => !allowed.has(p));
  if (foreign.length) return cancel(`изменены файлы вне выбранных доков: ${foreign.slice(0, 5).join(", ")}`);
  if (!changed.length) {
    finish("без изменений", "модель ничего не записала (нет даже строки verify-log)");
    git(wt, ["checkout", "-q", "--detach", baseSha]);
    git(root, ["branch", "-m", branchName, `${branchName}-pusto`]);
    return 1;
  }
  let a = audits(wt);
  report.push("", "Аудиты:", "```", a.text, "```");
  let gate = auditPass(a, base, cfg.audit_gate);
  if (!gate.ok) return failGate(gate);
  git(wt, ["add", "-A", "--", ".memory_bank"]);
  commitWork("memory(nightly): сверка");

  // main уехал за время прогона → rebase и повтор аудитов
  git(root, ["fetch", "-q", cfg.remote, cfg.branch]);
  const fresh = git(root, ["rev-parse", upstream]);
  if (fresh !== baseSha) {
    const rb = git(wt, ["-c", "user.name=nightly-verify", "-c", "user.email=nightly-verify@localhost", "rebase", "-q", upstream], { ok: true });
    if (rb.status !== 0) {
      git(wt, ["rebase", "--abort"], { ok: true });
      return cancel(`${upstream} уехал (${fresh.slice(0, 7)}), rebase с конфликтом`);
    }
    a = audits(wt);
    report.push("", `После rebase на ${fresh.slice(0, 7)}:`, "```", a.text, "```");
    gate = auditPass(a, base, cfg.audit_gate);
    if (!gate.ok) return failGate(gate, " (после rebase)");
  }
  finish("ветка готова к ревью", `${branchName} (${git(wt, ["rev-parse", "--short", "HEAD"])}); push и влив — утром, руками`);
  return 0;
}

const isMain = (() => {
  try {
    return !!process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
})();
if (isMain) {
  main().then(
    (code) => process.exit(code),
    (e) => {
      console.error(`nightly-verify: ${e.message}`);
      process.exit(2);
    }
  );
}
