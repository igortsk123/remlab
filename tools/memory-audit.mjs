#!/usr/bin/env node
// memory-audit — детерминированная проверка консистентности Memory Bank.
// Без внешних зависимостей (Node >= 18, ESM). Тесты: tests/audit.test.mjs (фикстуры tests/fixtures/).
//
// Регенерирует (в write-режиме) из frontmatter:
//   - INDEX.md: блок GENERATED:decision-tree (Tier 1 доки, сорт high→med→low, затем topic);
//   - core/README.md: блок GENERATED:core-registry;
//   - plans/README.md: блок GENERATED:plans-registry;
//   - completed_plans/README.md: блок GENERATED:completed-plans-registry.
//   В --check режиме файлы не пишутся; расхождение → REGISTRY-STALE.
//
// Находки делятся на два класса:
//   problems  — влияют на exit code и на Stop-гейт (`session-reminder --block`);
//   warnings  — печатаются и считаются в метриках, но НЕ делают прогон «грязным». Фаза сбора
//               эмпирики для новой категории: сперва меряем частоту находок по флоту, потом
//               осознанно повышаем до problems (тот же путь warn→block, что у CI-гейта).
//
// Категории проверок (exit 1 при любой находке класса problems):
//   ORPHAN          content-док без frontmatter `topic` (невидим в навигации)
//   STALE           Tier 1 сводка, чей tier2-док новее (Tier2.updated > Tier1.updated)
//   BROKEN          указатели tier1/tier2 и [[ссылки]], которые не резолвятся; нет маркеров GENERATED
//   LAGGING         (v1.9: свежесть = более поздняя из updated и last_verified) Tier 1 док отстаёт от project-state.updated более чем на --stale-days (дрейф слоя)
//   REVIEW          review_after в прошлом — пересмотреть актуальность
//   UNVERIFIED      source_of_truth: canonical без last_verified
//   LAST-VERIFIED-OLD (warning) last_verified старше --verified-max-days и review_after не задан
//                   (UNVERIFIED проверяет только ФАКТ наличия даты, значение — никто)
//   BLOATED         project-state.md больше --ps-max-kb (снимок превратился в журнал)
//   NO-TIER1        domain/-док без парной Tier 1 сводки (не попадёт в decision tree)
//   PLACEHOLDER     незаполненные {{...}} в живых доках / INDEX.md / корневом CLAUDE.md
//   DUP-TOPIC       два content-дока с одинаковым topic
//   TIER1-BLOAT     Tier 1 сводка больше --tier1-max-kb (детали должны уйти в Tier 2)
//   TIER0-BLOAT     CLAUDE.md (корень) + INDEX.md суммарно больше --tier0-max-kb
//   TIER0-RULES     (warning, v1.9) правила .claude/rules/*.md БЕЗ `paths:` грузятся в каждую сессию — их сумма больше
//                   --tier0-rules-max-kb (20): реальный Tier 0 = CLAUDE.md + INDEX + эти правила (аудит 1.8 видел только первые два)
//   PLAN-STUCK      план in_progress без движения дольше --plan-stale-days (мастер-план `plan_kind: portfolio_master|
//                   track_master` с будущей review_after — не застрявший, v1.9)
//   PLAN-MISPLACED  completed-план в plans/ или не-completed в completed_plans/
//   BAD-FM          YAML-массив/вложенность в frontmatter (схема требует плоские строки)
//   INDEX-REF       путь в ручной части INDEX.md указывает на несуществующий файл
//   REGISTRY-STALE  GENERATED-блок устарел (в --check режиме)
//   DIVERGENCE      найдена вторая .memory_bank (в предках до git-root или внутри проекта)
//   SECRET          _secrets/ без .gitignore при git-репо; похожее на значение секрета вне _secrets/
//   CODE-REF        backtick-путь к файлу кода в памяти не найден в дереве репозитория (память отстала от кода)
//   CODE-DRIFT      (warning) код, на который док ссылается, изменён после last_verified/updated дока
//                   более чем на --code-drift-days — утверждение про этот код никто не пересверял
//                   (доки банка и правила .claude/rules/*; якоря `путь`, `путь:символ`, уникальное голое имя файла)
//   NO-ANCHOR       (warning) сводка Tier 1 без единой ссылки на код — CODE-DRIFT её не видит
//                   (исключения — `_kit/no-anchor-ignore.txt`: путь от корня банка или topic)
//   FROZEN-MEMORY   код менялся в >N коммитах с момента последнего коммита в .memory_bank/ (замерзание памяти)
//   RULES-FM        frontmatter правил .claude/rules/: Cursor-поля (alwaysApply/globs), inline-массив
//                   или некавыченный глоб в paths — правило может МОЛЧА не загружаться
//   MEM-INJECT      док с source: external:* содержит императивы к агенту / exec-паттерны —
//                   ручное ревью (память как канал persistent prompt injection, OWASP ASI06)
//   ADR-DUP         один номер решения в двух H2-записях (decisions.md + тома decisions/*.md) —
//                   ссылки на решение неоднозначны (remlab: 7 дублей на 187 записей). Префикс номера —
//                   `_kit/adr-prefix.txt` (по умолчанию `ADR-`; sup2/sib — `D`), сравнение численное
//   ADR-AMBIGUOUS   (warning) в заголовке записи несколько номеров вне скобок — id не определён
//                   (sup2: `## [дата] D60: … отменяет D2`); начни заголовок с номера, ссылки — в скобки
//   ADR-IN-INDEX    (warning) есть тома decisions/<stem>-*.md, а в decisions.md (индексе) появилась запись `## <prefix>`
//   ADR-NOT-INDEXED (warning) запись тома без строки с её номером в decisions.md
//   ADR-INDEX-ORPHAN (warning) строка индекса есть, записи в томах нет
//   ADR-RANGE       (warning) запись вне диапазона своего тома <stem>-NNNN-MMMM.md
//   DECISIONS-BLOAT (warning) decisions.md больше --decisions-max-kb — пора на индекс + тома
//   DOC-FM          (warning) у content-дока нет обязательного базового поля схемы (tier/scope/updated/
//                   importance/source) или оно пустое; `topic` ловит ORPHAN
//   DOC-VOCAB       (warning) значение tier/importance/status/source_of_truth вне словаря METADATA_SCHEMA
//                   (флот: `medium` ×13, `high|med|low` из шаблона ×12 — молча уходили в хвост дерева)
//   DOC-DATE        (warning) дата (updated/last_verified/review_after; у планов created/updated/completed)
//                   не в формате YYYY-MM-DD — невалидная дата молча выключает STALE/LAGGING/CODE-DRIFT
//   PLAN-DRAFT-STALE (warning) draft без движения дольше --draft-stale-days и без будущего review_after
//   PLAN-PARTIAL-NO-REASON (warning) partial без pause_reason — кладбище планов невидимо
//   PLAN-STATUS     (warning) статус плана вне словаря (draft/in_progress/partial/completed/cancelled)
//   PLAN-REVIEW-DUE (warning) review_after плана в прошлом (REVIEW кита планы не смотрит)
//   PLAN-COMPLETED-NO-DATE (warning) completed-план без даты `completed:` (флот: 33 из 444)
//   PLAN-CANCELLED-IN-PLANS (warning) cancelled лежит в plans/ — после уроков его место в archive/plans/
//   CANON-INTAKE-REF (warning) canonical-док ссылается в теле на _intake/ — истина опирается на сырьё,
//                   которое аудит не проверяет. Allowlist — `_kit/intake-ref-ignore.txt`
//   INTAKE-BLOAT    (warning) _intake/ больше --intake-max-mb — вход, не хранилище (remlab: 22 МБ логов)
//   INTAKE-LOGS     (warning) *.log внутри _intake/ — логи прогонов не память
//   KIT-NEW-PENDING (warning) в проекте лежит <файл>.kit-new — несведённый апгрейд кита (kit-owned конфликт
//                   или изменённый эталон project-owned файла); сигнал живёт, пока файл не сведён
//   KIT-CONFIG      (warning) project-owned конфиг `_kit/*.txt` не разобран (неизвестный флаг, не число,
//                   плохой префикс) — строка пропущена, работают дефолты
//
// Использование:
//   node tools/memory-audit.mjs [projectRoot]           (default: cwd; write-режим — регенерит блоки)
//   node tools/memory-audit.mjs --check [root]          (не писать, только проверка; для CI/hook)
//   Флаги порогов: --stale-days N (30) · --ps-max-kb N (12) · --tier1-max-kb N (3)
//                  --tier0-max-kb N (8) · --plan-stale-days N (14) · --frozen-commits N (12)
//                  --code-drift-days N (7) · --verified-max-days N (90)
//                  --decisions-max-kb N (40) · --draft-stale-days N (30) · --intake-max-mb N (10)
//   Те же флаги можно задать ОДИН раз для всех входов (CLI, CI, Stop, SessionStart) в project-owned
//   файле `.memory_bank/_kit/audit-flags.txt` (одна строка в CLI-синтаксисе, `#` — комментарий);
//   приоритет: дефолты < файл < флаги командной строки. Бюджеты размеров — в UTF-8-байтах: грубый
//   переносимый прокси стоимости контекста (кириллица весит вдвое — так и задумано, не артефакт).
//   --no-git: отключить git-проверки FROZEN-MEMORY и CODE-DRIFT (иначе включаются при наличии
//             .git и git в PATH). --no-code-drift: отключить только CODE-DRIFT.
//   --drift-report: ЭКСПЕРИМЕНТ (v1.9) — дрейф по предковости коммитов (коммит сверки дока → HEAD), отчёт и
//             строка телеметрии в .memory_bank/changelog/drift-report.log; находки не добавляет.
//   --metrics: доп. строка `METRICS ...` (footprint Tier0/корпус + счётчик находок по категориям) —
//              для пассивного сбора эмпирики (tools/metrics-append.sh, CI-summary).
//
// Exit code: 0 — чисто; 1 — найдены проблемы; 2 — ошибка запуска (нет .memory_bank).

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join, dirname, relative, resolve, basename, sep } from "node:path";
import { fileURLToPath } from "node:url";

const SKIP_DIRS = new Set(["_intake", "completed_plans", "archive", "changelog", "_secrets"]);
const SKIP_FILES = new Set([
  "README.md",
  "_template.md",
  "INDEX.md",
  // инфраструктура банка (policy/schema), не память проекта — как README
  "METADATA_SCHEMA.md",
  "CLEANUP_POLICY.md",
]);
// always-on мета-доки: у них своя секция в INDEX, в авто-таблицу decision tree не дублируем
const ALWAYS_ON_TOPICS = new Set(["source-of-truth", "project-state", "decisions"]);
// каталоги, в которые не спускаемся при поиске вложенных .memory_bank (DIVERGENCE)
const HEAVY_DIRS = new Set([
  "node_modules", ".git", ".next", "dist", "build", "out", "vendor",
  ".venv", "venv", "__pycache__", "target", "coverage",
]);
const GEN_NOTE =
  "\n<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->\n";
const PH_RE = /\{\{[^}]*\}\}/;

const stripBom = (s) => (s.charCodeAt(0) === 0xfeff ? s.slice(1) : s);
const readDoc = (f) => stripBom(readFileSync(f, "utf8"));
const isPlaceholder = (v) => !v || PH_RE.test(v) || /^<.*>$/.test(v.trim()) || v === "";
const isDate = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || "");
/** Все правила `.claude/rules/**\/*.md` (с подпапками — Claude Code грузит и их) → [{rel, full}], по алфавиту. */
const listRuleFiles = (root) => {
  const rulesDir = join(root, ".claude", "rules");
  const out = [];
  if (!existsSync(rulesDir)) return out;
  (function walk(dir) {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".md")) out.push({ full, rel: ".claude/rules/" + relative(rulesDir, full).split(sep).join("/") });
    }
  })(rulesDir);
  return out;
};
/** Текст без блоков ``` / ~~~: в правилах там примеры команд и путей, а не утверждения о коде. */
const stripFences = (s) => {
  let fence = null;
  return s
    .split("\n")
    .map((l) => {
      const m = l.match(/^\s*(```|~~~)/);
      if (m && (!fence || m[1] === fence)) {
        fence = fence ? null : m[1];
        return "";
      }
      return fence ? "" : l;
    })
    .join("\n");
};

export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function daysBetween(aISO, bISO) {
  return Math.round((Date.parse(bISO) - Date.parse(aISO)) / 86400000);
}

// Минимальный парсер frontmatter (key: value между --- ---). Значения — плоские строки.
// badKeys — поля, похожие на YAML-массив/вложенность (BAD-FM): их значения парсер НЕ видит.
export function parseFrontmatter(text) {
  text = stripBom(text);
  const out = { fm: {}, badKeys: [] };
  if (!text.startsWith("---")) return out;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return out;
  const block = text.slice(3, end);
  let lastKey = null;
  for (const raw of block.split(/\r?\n/)) {
    const line = raw.replace(/\r$/, ""); // CRLF: хвостовой \r у строки перед "\n---"
    const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (m) {
      out.fm[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
      lastKey = m[1];
      continue;
    }
    // элемент массива (`- x`) или вложенный ключ (`  key: v`) → плоская схема нарушена
    if (/^\s*-\s+\S/.test(line) || /^\s{2,}[A-Za-z0-9_-]+:\s*/.test(line)) {
      if (lastKey && !out.badKeys.includes(lastKey)) out.badKeys.push(lastKey);
    }
  }
  return out;
}

function stripCode(text) {
  return text
    .replace(/^---[\s\S]*?\n---/, "") // frontmatter
    .replace(/```[\s\S]*?```/g, "") // fenced code blocks
    .replace(/`[^`]*`/g, ""); // inline code
}

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir).sort()) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (SKIP_DIRS.has(name)) continue;
      out.push(...walk(full));
    } else if (name.endsWith(".md")) {
      out.push(full);
    }
  }
  return out;
}

function findNestedBanks(dir, depth, out, canon) {
  if (depth < 0) return;
  let entries;
  try {
    entries = readdirSync(dir).sort();
  } catch {
    return;
  }
  for (const name of entries) {
    if (HEAVY_DIRS.has(name)) continue;
    const full = join(dir, name);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (!st.isDirectory()) continue;
    if (name === ".memory_bank") {
      if (full !== canon) out.push(full);
      continue;
    }
    if (name.startsWith(".") && name !== ".memory_bank") continue;
    findNestedBanks(full, depth - 1, out, canon);
  }
}

// ---------- пороги: один источник для всех входов (v1.8) ----------
// CLI-флаг → ключ opts. Экспорт — для session-reminder (Stop) и любого другого входа: до v1.8 Stop знал
// 6 порогов из 11, SessionStart и CI — ни одного, и проект с нестандартным бюджетом правил три
// kit-owned файла (sup2: конфликт CI-флагов на каждом апгрейде).
export const THRESHOLD_KEYS = {
  "--stale-days": "staleDays",
  "--ps-max-kb": "psMaxKb",
  "--tier1-max-kb": "tier1MaxKb",
  "--tier0-max-kb": "tier0MaxKb",
  "--tier0-rules-max-kb": "tier0RulesMaxKb",
  "--plan-stale-days": "planStaleDays",
  "--frozen-commits": "frozenCommits",
  "--code-drift-days": "codeDriftDays",
  "--verified-max-days": "verifiedMaxDays",
  "--decisions-max-kb": "decisionsMaxKb",
  "--draft-stale-days": "draftStaleDays",
  "--intake-max-mb": "intakeMaxMb",
};
export const DEFAULT_THRESHOLDS = {
  staleDays: 30,
  psMaxKb: 12,
  tier1MaxKb: 3,
  tier0MaxKb: 8,
  tier0RulesMaxKb: 20,
  planStaleDays: 14,
  frozenCommits: 12,
  codeDriftDays: 7,
  verifiedMaxDays: 90,
  decisionsMaxKb: 40,
  draftStaleDays: 30,
  intakeMaxMb: 10,
};
// .memory_bank/_kit/audit-flags.txt (project-owned): флаги в CLI-синтаксисе (`--tier1-max-kb 4
// --stale-days 45`), `#` до конца строки — комментарий. Разрешены ТОЛЬКО числовые пороги: write/noGit/
// today — поведение запуска, не бюджет проекта. Ошибка → KIT-CONFIG (warning), строка пропущена.
export function readAuditFlags(mbDir) {
  const res = { opts: {}, warnings: [] };
  const f = join(mbDir, "_kit", "audit-flags.txt");
  if (!existsSync(f)) return res;
  const rel = "_kit/audit-flags.txt";
  const toks = readDoc(f)
    .split(/\r?\n/)
    .map((l) => l.replace(/#.*$/, "").trim())
    .filter(Boolean)
    .join(" ")
    .split(/\s+/)
    .filter(Boolean); // файл из одних комментариев → нет токенов, не пустой «флаг»
  for (let i = 0; i < toks.length; i++) {
    const flag = toks[i];
    const key = THRESHOLD_KEYS[flag];
    const raw = toks[i + 1];
    const hasValue = raw !== undefined && !raw.startsWith("--");
    if (!key) {
      res.warnings.push(`KIT-CONFIG ${rel} — '${flag}' не порог аудита (список — шапка tools/memory-audit.mjs) — пропущен`);
      if (hasValue) i++;
      continue;
    }
    const n = Number(raw);
    if (!hasValue || !Number.isFinite(n) || n <= 0) {
      res.warnings.push(`KIT-CONFIG ${rel} — у '${flag}' нет положительного числа (${hasValue ? raw : "—"}) — пропущен`);
      if (hasValue) i++;
      continue;
    }
    if (key in res.opts) res.warnings.push(`KIT-CONFIG ${rel} — '${flag}' задан дважды — берётся последний (${n})`);
    res.opts[key] = n;
    i++;
  }
  return res;
}

// ЭКСПЕРИМЕНТ `--drift-report` (v1.9, пилот sup2 27.09; НЕ гейт — решение о гейте по телеметрии флота).
// Дрейф по предковости коммитов: «коммит сверки» дока = последний коммит, где в доке менялась строка
// `last_verified:`; дрейф = файл-якорь (не папка) изменён между этим коммитом и рабочим деревом. Пометка
// «символы задеты» — в +/- строках диффа файла есть идентификатор из текста дока (эвристика: есть пропуски, если
// правка внутри функции, и ложные срабатывания на общих именах). Хрупкость (разбор Codex): дата сверки с точностью
// до дня, массовый сдвиг дат «отмывает» старые ошибки, squash склеивает код и сверку. Правила не участвуют.
const DRIFT_STOP = new Set(["true", "false", "null", "undefined", "json", "text", "name", "type", "data", "list", "page", "user", "item", "value", "string", "number"]);
function buildDriftReport(root, mbDir, eligible) {
  const git = (args) => {
    const r = spawnSync("git", ["-C", root, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 256 * 1024 * 1024 });
    return !r.error && r.status === 0 ? r.stdout || "" : null;
  };
  const shallow = (git(["rev-parse", "--is-shallow-repository"]) || "").trim() === "true";
  const mbRel = relative(root, mbDir).split(sep).join("/");
  const lv = new Map(); // путь дока от корня репо -> { sha, date } последнего коммита, менявшего last_verified
  const log = git(["log", "--relative", "-p", "-U0", "--no-renames", "--format=@@%H %cs", "--", mbRel]);
  if (log === null) return { error: "git log недоступен" };
  let sha = null, date = null, file = null;
  for (const line of log.split("\n")) {
    if (line.startsWith("@@") && !line.startsWith("@@ ")) {
      [sha, date] = line.slice(2).split(" ");
      file = null;
    } else if (line.startsWith("diff --git ")) {
      const m = line.match(/ b\/(.+)$/);
      file = m ? m[1] : null;
    } else if (file && line.startsWith("+last_verified:") && !lv.has(file)) lv.set(file, { sha, date });
  }
  const wtVerified = new Set();
  let f2 = null;
  for (const line of (git(["diff", "--relative", "-U0", "HEAD", "--", mbRel]) || "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const m = line.match(/ b\/(.+)$/);
      f2 = m ? m[1] : null;
    } else if (f2 && line.startsWith("+last_verified:")) wtVerified.add(f2);
  }
  const uncommitted = new Set((git(["diff", "--relative", "--name-only", "HEAD"]) || "").split("\n").filter(Boolean));
  const changedCache = new Map();
  const changedSince = (s) => {
    if (!changedCache.has(s)) {
      const out = git(["diff", "--relative", "--name-only", s, "HEAD"]);
      changedCache.set(s, out === null ? null : new Set(out.split("\n").filter(Boolean)));
    }
    return changedCache.get(s);
  };
  const isAncestor = (s) => spawnSync("git", ["-C", root, "merge-base", "--is-ancestor", s, "HEAD"], { stdio: "ignore" }).status === 0;
  const byDoc = new Map();
  for (const c of eligible) {
    if (c.isDir || c.d.isRule) continue;
    if (!byDoc.has(c.d.rel)) byDoc.set(c.d.rel, { d: c.d, files: new Set() });
    byDoc.get(c.d.rel).files.add(c.bare);
  }
  const items = [];
  const unverifiable = [];
  for (const [docRel, { d, files }] of byDoc) {
    const repoRel = `${mbRel}/${docRel}`;
    let base, changed;
    if (wtVerified.has(repoRel)) {
      base = { sha: "WORKTREE", date: "не закоммичено" };
      changed = uncommitted;
    } else {
      base = lv.get(repoRel);
      const c1 = base && isAncestor(base.sha) ? changedSince(base.sha) : null;
      if (!c1) {
        unverifiable.push(docRel);
        continue;
      }
      changed = new Set([...c1, ...uncommitted]);
    }
    const drifted = [...files].filter((f) => changed.has(f));
    if (!drifted.length) continue;
    const ids = new Set();
    for (const m of d.text.matchAll(/`([A-Za-z_][\w]{3,})`/g)) if (!DRIFT_STOP.has(m[1].toLowerCase())) ids.add(m[1]);
    for (const m of d.text.matchAll(/`[^`\s]+\.[A-Za-z0-9]+[:#]([A-Za-z_]\w{2,})`/g)) ids.add(m[1]);
    const hits = drifted.map((f) => {
      const diff = base.sha === "WORKTREE" ? git(["diff", "-U0", "HEAD", "--", f]) : git(["diff", "-U0", base.sha, "--", f]);
      const body = (diff || "").split("\n").filter((l) => /^[+-]/.test(l) && !/^(\+\+\+|---)/.test(l)).join("\n");
      const syms = [...ids].filter((id) => new RegExp(`(^|[^\\w])${id.replace(/[.$]/g, "\\$&")}([^\\w]|$)`, "m").test(body)).slice(0, 5);
      return { file: f, syms };
    });
    items.push({ doc: docRel, base, hits, symHit: hits.some((h) => h.syms.length) });
  }
  return { items, unverifiable, docs: byDoc.size, shallow };
}

// ---------- основной прогон ----------
// opts: { write, staleDays, psMaxKb, tier1MaxKb, tier0MaxKb, planStaleDays, codeDriftDays, today }
// Возвращает { ok, fatal?, problems, warnings, notes, docCount, psUpdated, psAgeDays }.
// ok считается ТОЛЬКО по problems: warnings информируют, но не блокируют (см. шапку файла).
export function runChecks(root, opts = {}) {
  root = resolve(root);
  const mbDir = join(root, ".memory_bank");
  if (!existsSync(mbDir)) {
    return { ok: false, fatal: `не найдено .memory_bank в ${root}`, problems: [], warnings: [], notes: [] };
  }
  // Пороги: дефолты < _kit/audit-flags.txt < явные opts. Вызывающий передаёт ТОЛЬКО заданное явно
  // (CLI — см. низ файла): если бы CLI слал дефолт за каждый флаг, файл никогда бы не победил.
  const flagsFile = readAuditFlags(mbDir);
  const o = {
    write: false,
    ...DEFAULT_THRESHOLDS,
    noGit: false,
    noCodeDrift: false,
    driftReport: false,
    today: todayISO(),
    ...flagsFile.opts,
    ...opts,
  };

  const problems = [];
  const warnings = [...flagsFile.warnings];
  const notes = [];

  // Собрать все доки (кроме SKIP_DIRS)
  const files = walk(mbDir);
  const docs = files.map((f) => {
    const text = readDoc(f);
    const { fm, badKeys } = parseFrontmatter(text);
    return { file: f, rel: relative(mbDir, f).split(sep).join("/"), fm, badKeys, text };
  });

  const isScaffold = (d) =>
    SKIP_FILES.has(basename(d.file)) || d.rel.startsWith("plans/") || d.rel.startsWith("_intake/");
  const contentDocs = docs.filter((d) => !isScaffold(d));
  const planDocs = docs.filter(
    (d) => d.rel.startsWith("plans/") && !["README.md", "_template.md"].includes(basename(d.file))
  );
  const cpDir = join(mbDir, "completed_plans");
  const completedDocs = !existsSync(cpDir)
    ? []
    : readdirSync(cpDir)
        .sort()
        .filter((n) => n.endsWith(".md") && n !== "README.md")
        .map((n) => {
          const f = join(cpDir, n);
          const text = readDoc(f);
          const { fm, badKeys } = parseFrontmatter(text);
          return { file: f, rel: `completed_plans/${n}`, fm, badKeys, text };
        });

  const byName = new Map(); // basename(no ext) -> doc
  const byTopic = new Map(); // topic -> [docs]
  for (const d of docs) {
    byName.set(basename(d.file, ".md"), d);
    if (d.fm.topic) {
      if (!byTopic.has(d.fm.topic)) byTopic.set(d.fm.topic, []);
      byTopic.get(d.fm.topic).push(d);
    }
  }
  const ps = contentDocs.find((d) => d.fm.topic === "project-state");

  // 1) ORPHAN — content-док без topic
  for (const d of contentDocs) {
    if (!d.fm.topic) problems.push(`ORPHAN  ${d.rel} — нет frontmatter 'topic' (невидим в decision tree)`);
  }

  // 2) DUP-TOPIC — один topic у нескольких content-доков
  for (const [topic, list] of byTopic) {
    const content = list.filter((d) => !isScaffold(d));
    if (content.length > 1)
      problems.push(
        `DUP-TOPIC '${topic}': ${content.map((d) => d.rel).join(", ")} — сведи в один док или переименуй topic`
      );
  }

  // 3) BAD-FM — массив/вложенность в frontmatter
  for (const d of [...contentDocs, ...planDocs]) {
    if (d.badKeys.length)
      problems.push(
        `BAD-FM  ${d.rel} — поле '${d.badKeys.join("', '")}' похоже на YAML-массив/вложенность; схема требует плоскую строку (METADATA_SCHEMA.md)`
      );
  }

  // 3b) DOC-FM / DOC-VOCAB / DOC-DATE (warnings, v1.8) — схема METADATA_SCHEMA проверялась только на
  //     topic (ORPHAN) и массивы (BAD-FM). Замер по 14 банкам: 28 значений importance вне словаря
  //     (`medium`, плейсхолдер `high|med|low` из шаблона) молча падали в хвост decision tree
  //     (impRank ?? 3), `tier: plan` ×13; невалидная дата updated выключала STALE/LAGGING/CODE-DRIFT
  //     через isDate-guard. Скоуп — content-доки; отсутствие НЕобязательных lifecycle-полей не флагаем.
  const VOCAB = {
    tier: ["0", "1", "2"],
    importance: ["high", "med", "low"],
    status: ["draft", "working", "stable", "stale", "deprecated", "archived"],
    source_of_truth: ["canonical", "supporting", "derived", "historical"],
  };
  const REQUIRED_FM = ["tier", "scope", "updated", "importance", "source"]; // topic — ORPHAN
  const isSet = (v) => v !== undefined && v !== "" && !PH_RE.test(String(v)); // плейсхолдер — PLACEHOLDER
  const badDates = (d, fields) => fields.filter((k) => isSet(d.fm[k]) && !isDate(d.fm[k]));
  for (const d of contentDocs) {
    if (!d.fm.topic) continue; // ORPHAN уже сказал главное — одна причина, одна диагностика
    const missing = REQUIRED_FM.filter((k) => d.fm[k] === undefined || d.fm[k] === "");
    if (missing.length)
      warnings.push(
        `DOC-FM ${d.rel} — нет обязательного поля: ${missing.map((k) => `'${k}'`).join(", ")} (METADATA_SCHEMA: tier/topic/scope/updated/importance/source)`
      );
    const bad = Object.entries(VOCAB)
      .filter(([k, vals]) => isSet(d.fm[k]) && !vals.includes(String(d.fm[k])))
      .map(([k, vals]) => `${k} '${d.fm[k]}' (${vals.join("|")})`);
    if (bad.length)
      warnings.push(`DOC-VOCAB ${d.rel} — вне словаря: ${bad.join("; ")} — реестры и сортировка дерева такое значение не понимают`);
    const dates = badDates(d, ["updated", "last_verified", "review_after"]);
    if (dates.length)
      warnings.push(
        `DOC-DATE ${d.rel} — не дата YYYY-MM-DD: ${dates.map((k) => `${k} '${d.fm[k]}'`).join(", ")} — проверки свежести по доку молчат`
      );
  }
  for (const p of [...planDocs, ...completedDocs]) {
    const dates = badDates(p, ["created", "updated", "completed", "review_after"]);
    if (dates.length)
      warnings.push(`DOC-DATE ${p.rel} — не дата YYYY-MM-DD: ${dates.map((k) => `${k} '${p.fm[k]}'`).join(", ")}`);
  }

  // 4) STALE + BROKEN(tier2) — Tier1 старше своего Tier2
  function resolvePointer(d, ptr) {
    if (isPlaceholder(ptr)) return null;
    const p = resolve(dirname(d.file), ptr);
    return existsSync(p) ? p : { missing: p };
  }
  for (const d of contentDocs) {
    const t2 = d.fm.tier2;
    if (isPlaceholder(t2)) continue;
    const target = resolvePointer(d, t2);
    if (target && target.missing) {
      problems.push(`BROKEN  ${d.rel} — tier2 указывает на несуществующий '${t2}'`);
      continue;
    }
    if (typeof target === "string") {
      const tdoc = docs.find((x) => x.file === target);
      if (tdoc && isDate(d.fm.updated) && isDate(tdoc.fm.updated) && tdoc.fm.updated > d.fm.updated) {
        problems.push(
          `STALE   ${d.rel} (updated ${d.fm.updated}) старше Tier2 ${tdoc.rel} (updated ${tdoc.fm.updated}) — сверь сводку`
        );
      }
    }
  }

  // 5) BROKEN — tier1-указатель и [[ссылки]]
  for (const d of contentDocs) {
    const t1 = d.fm.tier1;
    if (!isPlaceholder(t1)) {
      const target = resolvePointer(d, t1);
      if (target && target.missing) problems.push(`BROKEN  ${d.rel} — tier1 указывает на несуществующий '${t1}'`);
    }
    const body = stripCode(d.text);
    for (const m of body.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const name = m[1].trim();
      if (!byName.has(name) && !byTopic.has(name)) {
        problems.push(`BROKEN  ${d.rel} — [[${name}]] не резолвится (нет файла/topic)`);
      }
    }
  }

  // 6) LAGGING — Tier 1 отстаёт от project-state сильнее порога (частый провал:
  //    core/ и domain/ замёрзли вместе, попарный STALE молчал, банк отставал на недели)
  if (ps && isDate(ps.fm.updated)) {
    for (const d of contentDocs) {
      if (String(d.fm.tier) !== "1") continue;
      if (ALWAYS_ON_TOPICS.has(d.fm.topic)) continue;
      // v1.9: свежесть сводки — более поздняя из `updated` и `last_verified`. Сводку, сверенную с кодом без правки
      // текста (дата сверки двигается только по `verify`, `updated` — нет), обновление project-state больше не
      // помечает «отстающей» (remlab 28.09: 4 ложных LAGGING после честного обновления снимка).
      const fresh = [d.fm.updated, d.fm.last_verified].filter(isDate).sort().pop();
      if (fresh && daysBetween(fresh, ps.fm.updated) > o.staleDays) {
        problems.push(
          `LAGGING ${d.rel} (updated ${d.fm.updated || "—"}, сверка ${isDate(d.fm.last_verified) ? d.fm.last_verified : "—"}) отстаёт от project-state (${ps.fm.updated}) на >${o.staleDays}д — сверь с реальностью (verify)`
        );
      }
    }
  }

  // 7) REVIEW / UNVERIFIED — lifecycle-поля
  for (const d of contentDocs) {
    if (isDate(d.fm.review_after) && d.fm.review_after < o.today)
      problems.push(`REVIEW  ${d.rel} — review_after ${d.fm.review_after} в прошлом — перепроверить актуальность`);
    // {{DATE}} в last_verified — это PLACEHOLDER (init не завершён), не дублируем UNVERIFIED
    if (
      d.fm.source_of_truth === "canonical" &&
      !isDate(d.fm.last_verified) &&
      !PH_RE.test(String(d.fm.last_verified || ""))
    )
      problems.push(`UNVERIFIED ${d.rel} — canonical без last_verified`);
    // 7b) LAST-VERIFIED-OLD (warning) — дата есть, но древняя. UNVERIFIED проверяет только ФАКТ
    //     наличия даты: док с last_verified 2019 года проходил как проверенный. Не дублируем
    //     REVIEW: если у дока задан review_after, хозяин этого дока — он, одна находка на док.
    if (isDate(d.fm.last_verified) && !isDate(d.fm.review_after)) {
      const age = daysBetween(d.fm.last_verified, o.today);
      if (age > o.verifiedMaxDays)
        warnings.push(
          `LAST-VERIFIED-OLD ${d.rel} — сверялся ${age}д назад (${d.fm.last_verified}), review_after не задан — перепроверить и обновить дату`
        );
    }
  }

  // 8) BLOATED / TIER1-BLOAT / TIER0-BLOAT — бюджеты размеров
  if (ps) {
    const size = Buffer.byteLength(ps.text, "utf8");
    if (size > o.psMaxKb * 1024)
      problems.push(
        `BLOATED project-state.md — ${(size / 1024).toFixed(0)}KB > ${o.psMaxKb}KB. Это снимок, не журнал: вынеси хронологию в changelog/project-history.md`
      );
  }
  for (const d of contentDocs) {
    if (String(d.fm.tier) !== "1" || ALWAYS_ON_TOPICS.has(d.fm.topic)) continue;
    // v1.9: меряем тело без шапки — поля жизненного цикла (status, source_of_truth, last_verified, review_after,
    // tier1/tier2) растут и съедали ~350 байт бюджета содержания (remlab/sup2: сводки стояли на 97–100 %).
    const fmEnd = d.text.startsWith("---") ? d.text.indexOf("\n---", 3) : -1;
    const body = fmEnd > 0 ? d.text.slice(d.text.indexOf("\n", fmEnd + 1) + 1) : d.text;
    const size = Buffer.byteLength(body, "utf8");
    if (size > o.tier1MaxKb * 1024)
      problems.push(
        `TIER1-BLOAT ${d.rel} — ${(size / 1024).toFixed(1)}KB (тело без шапки) > ${o.tier1MaxKb}KB. Сводка = вход в тему; детали унеси в Tier 2`
      );
  }
  {
    const indexPath0 = join(mbDir, "INDEX.md");
    let t0 = 0;
    for (const f of [join(root, "CLAUDE.md"), join(mbDir, "INDEX.md")]) {
      if (existsSync(f)) t0 += Buffer.byteLength(readDoc(f), "utf8");
    }
    if (t0 > o.tier0MaxKb * 1024) {
      // Decision tree в INDEX генерируется из scope: сводок — длинные scope съедают бюджет Tier 0
      // незаметно для того, кто правит CLAUDE.md. Подсказываем, что именно ужимать.
      const longScopes = contentDocs
        .filter((d) => String(d.fm.tier) === "1" && d.fm.topic && !ALWAYS_ON_TOPICS.has(d.fm.topic) && d.fm.scope)
        .map((d) => ({ rel: d.rel, len: d.fm.scope.length }))
        .sort((a, b) => b.len - a.len)
        .slice(0, 3)
        .map((x) => `${x.rel} (scope ${x.len} симв.)`);
      const hint = longScopes.length ? `; самые длинные scope в дереве: ${longScopes.join(", ")}` : "";
      // Разбивка: что именно весит — CLAUDE.md, ручная часть INDEX или сгенерированное дерево.
      const claudeB = existsSync(join(root, "CLAUDE.md")) ? Buffer.byteLength(readDoc(join(root, "CLAUDE.md")), "utf8") : 0;
      const idxTxt = existsSync(indexPath0) ? readDoc(indexPath0) : "";
      const genB = (idxTxt.match(/<!-- GENERATED:[\s\S]*?END -->/g) || []).reduce((s, m) => s + Buffer.byteLength(m, "utf8"), 0);
      const manualB = Buffer.byteLength(idxTxt, "utf8") - genB;
      const kb = (b) => (b / 1024).toFixed(1);
      problems.push(
        `TIER0-BLOAT CLAUDE.md+INDEX.md — ${(t0 / 1024).toFixed(1)}KB > ${o.tier0MaxKb}KB (CLAUDE.md ${kb(claudeB)} · INDEX ручная часть ${kb(manualB)} · GENERATED ${kb(genB)}). Tier 0 всегда в контексте — ужми, детали в Tier 1/2${hint}`
      );
    }
  }

  // 8b) TIER0-RULES (v1.9) — правила без `paths:` грузятся в каждую сессию наравне с CLAUDE.md и INDEX, но бюджет
  //     Tier 0 их не считал: у проектов флота «8 KB Tier 0» на деле было 24–37 KB (замер 28.09).
  let rulesAlwaysBytes = 0;
  const rulesAlwaysList = [];
  {
    for (const { full, rel } of listRuleFiles(root)) {
      const f = rel.slice(".claude/rules/".length);
      const text = readDoc(full);
      const head = text.startsWith("---") ? text.slice(0, text.indexOf("\n---", 3) + 1) : "";
      if (/^paths:/m.test(head)) continue;
      const b = Buffer.byteLength(text, "utf8");
      rulesAlwaysBytes += b;
      rulesAlwaysList.push({ f, b });
    }
    if (rulesAlwaysBytes > o.tier0RulesMaxKb * 1024) {
      const top = rulesAlwaysList.sort((a, b) => b.b - a.b).slice(0, 4).map((x) => `${x.f} ${(x.b / 1024).toFixed(1)}`).join(", ");
      warnings.push(
        `TIER0-RULES .claude/rules — правила без paths: грузятся в каждую сессию: ${(rulesAlwaysBytes / 1024).toFixed(1)}KB > ${o.tier0RulesMaxKb}KB (${top}) — детали в guides/, узким правилам дай paths:`
      );
    }
  }

  // 9) NO-TIER1 — domain-док без парной Tier 1 сводки
  for (const d of contentDocs) {
    if (!d.rel.startsWith("domain/") || !d.fm.topic) continue;
    const hasTier1 = docs.some(
      (x) =>
        String(x.fm.tier) === "1" &&
        !isPlaceholder(x.fm.tier2) &&
        resolve(dirname(x.file), x.fm.tier2) === d.file
    );
    if (!hasTier1)
      problems.push(`NO-TIER1 ${d.rel} — Tier2 без парной Tier1 сводки (не попадёт в decision tree)`);
  }

  // 10) PLACEHOLDER — незаполненные {{...}} (init не завершён / док скопирован без заполнения)
  for (const d of contentDocs) {
    const fmHit = Object.entries(d.fm).find(([, v]) => PH_RE.test(String(v)));
    const bodyHit = PH_RE.test(stripCode(d.text));
    if (fmHit || bodyHit) {
      const where = fmHit ? `frontmatter '${fmHit[0]}'` : "тексте";
      problems.push(`PLACEHOLDER ${d.rel} — незаполненный {{...}} в ${where} — заполни или убери`);
    }
  }
  for (const [f, label] of [
    [join(mbDir, "INDEX.md"), "INDEX.md"],
    [join(root, "CLAUDE.md"), "CLAUDE.md (корень)"],
  ]) {
    if (existsSync(f) && PH_RE.test(stripCode(readDoc(f))))
      problems.push(`PLACEHOLDER ${label} — незаполненные {{...}} — заполни (/memory-init) или убери`);
  }

  // 11) Планы: PLAN-STUCK / PLAN-MISPLACED (problems) + кладбище планов (warnings):
  //     PLAN-STUCK видит только in_progress, а лежат и гниют draft/partial (remlab: 61 открытый план,
  //     из них 33 partial без причины и 18 draft старше месяца; по флоту partial без причины ~90 %).
  //     Базовая частота высокая → warning, не блок: чинит триаж по манифесту (HEAL.md), не галочка.
  const PLAN_STATUSES = new Set(["draft", "in_progress", "partial", "completed", "cancelled"]);
  for (const p of planDocs) {
    const st = p.fm.status || "";
    if (st === "completed")
      problems.push(`PLAN-MISPLACED ${p.rel} — status completed, но лежит в plans/ (перенеси в completed_plans/)`);
    const refDate = isDate(p.fm.updated) ? p.fm.updated : isDate(p.fm.created) ? p.fm.created : null;
    // v1.9: мастер-план (портфель/трек, `plan_kind: portfolio_master|track_master`) живёт долго по природе —
    // PLAN-STUCK на нём ложный (remlab MASTER-cost-first), НО только при будущей дате пересмотра `review_after`.
    const isMaster = /^(portfolio_master|track_master)$/.test(String(p.fm.plan_kind || ""));
    const masterOk = isMaster && isDate(p.fm.review_after) && p.fm.review_after > o.today;
    if (st === "in_progress" && refDate && daysBetween(refDate, o.today) > o.planStaleDays && !masterOk)
      problems.push(
        `PLAN-STUCK ${p.rel} — in_progress без движения с ${refDate} (> ${o.planStaleDays}д) — доведи, переведи в partial или отмени` +
          (isMaster ? " (мастер-план: поставь будущую дату пересмотра review_after — тогда не застрявший)" : "")
      );
    if (!PLAN_STATUSES.has(st))
      warnings.push(
        `PLAN-STATUS ${p.rel} — status '${st || "—"}' вне словаря (draft/in_progress/partial/completed/cancelled) — реестр и PLAN-STUCK его не видят`
      );
    const futureReview = isDate(p.fm.review_after) && p.fm.review_after > o.today;
    if (st === "draft" && refDate && daysBetween(refDate, o.today) > o.draftStaleDays && !futureReview)
      warnings.push(
        `PLAN-DRAFT-STALE ${p.rel} — draft без движения с ${refDate} (> ${o.draftStaleDays}д) — деплой, review_after или archive/plans/ с archive_reason`
      );
    if (st === "partial" && isPlaceholder(p.fm.pause_reason))
      warnings.push(
        `PLAN-PARTIAL-NO-REASON ${p.rel} — partial без pause_reason (почему пауза / resume_trigger когда вернуться) — иначе план невидимо гниёт`
      );
    // review_after у планов: REVIEW кита смотрит только content-доки, а дата возврата у partial/draft
    // без этой проверки — мёртвое поле.
    if (isDate(p.fm.review_after) && p.fm.review_after < o.today && st !== "completed")
      warnings.push(`PLAN-REVIEW-DUE ${p.rel} — review_after ${p.fm.review_after} прошёл (status ${st || "—"}) — верни в работу, продли дату или архивируй`);
    // v1.8: cancelled — после записи уроков в archive/plans/ (plans/README.md). Правило v1.7 в
    // .claude/rules/agent-workflow.md держало его в plans/ — файл project-owned, апгрейд его не меняет
    // (ручной шаг в CHANGELOG v1.8.0). Флот: julia 2, wt-speed 2.
    if (st === "cancelled")
      warnings.push(
        `PLAN-CANCELLED-IN-PLANS ${p.rel} — cancelled лежит в plans/ — запиши уроки и перенеси в archive/plans/ (archived, archive_reason); правило — plans/README.md`
      );
  }
  for (const p of completedDocs) {
    if ((p.fm.status || "") !== "completed")
      problems.push(`PLAN-MISPLACED ${p.rel} — status '${p.fm.status || "—"}' ≠ completed, но лежит в completed_plans/`);
    // completed в plans/ получает только PLAN-MISPLACED; дата есть, но кривая — DOC-DATE (одна причина —
    // одна диагностика). Флот: 33 из 444.
    else if (!isSet(p.fm.completed))
      warnings.push(
        `PLAN-COMPLETED-NO-DATE ${p.rel} — completed без даты completed: YYYY-MM-DD — реестр сортирует по ней, «когда сделано» неизвестно`
      );
  }

  // 11b) ADR-лог: decisions.md — единственный tier-1 без бюджета (ALWAYS_ON исключён из TIER1-BLOAT),
  //      на флоте он растёт в журнал (remlab 474 КБ, sup2 233, sib 115). Конвенция v1.7: при росте —
  //      decisions.md остаётся ИНДЕКСОМ (строка на решение), полные тексты — тома decisions/<stem>-NNNN-MMMM.md.
  //      v1.8: префикс номера — `_kit/adr-prefix.txt` (нет файла → `ADR-`; sup2/sib нумеруют `D127`).
  //      Автодетекта нет: смешанные журналы (sup2, sib, wt-speed) сделали бы его недетерминированным.
  //      Id записи: (1) якорь `^## <prefix>N`; иначе (2) токены `<prefix>N` вне скобок: ровно один → он,
  //      ноль → запись безномерная (fallback в скобки убран: `## [дата] … (см. ADR-0042)` считался
  //      записью 0042), два и больше → ADR-AMBIGUOUS (sup2: `## [дата] D60: … отменяет D2` — правило
  //      «последний токен» давало ложный дубль D2). Номера сравниваются численно (D1/D01/D001 — один id),
  //      в выводе — как в заголовке.
  {
    const decIndex = docs.find((d) => d.rel === "decisions.md");
    let adrPrefix = "ADR-";
    {
      const pf = join(mbDir, "_kit", "adr-prefix.txt");
      if (existsSync(pf)) {
        const raw = readDoc(pf).split(/\r?\n/).map((l) => l.replace(/#.*$/, "").trim()).find(Boolean) || "";
        if (/^[A-Za-z][A-Za-z0-9-]{0,7}$/.test(raw)) adrPrefix = raw;
        else
          warnings.push(
            `KIT-CONFIG _kit/adr-prefix.txt — '${raw || "—"}' не префикс (буква, затем до 7 букв/цифр/дефисов) — используется ADR-`
          );
      }
    }
    const stem = adrPrefix.toLowerCase().replace(/-+$/, ""); // имя тома: adr-0001-0050.md, d-001-050.md
    const escPrefix = adrPrefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // Граница слева — не буква/цифра/дефис: иначе `ID12` ловилось бы как D12.
    const tokenRe = new RegExp(`(?<![\\p{L}\\p{N}-])${escPrefix}(\\d+)`, "gu");
    const anchorRe = new RegExp(`^## ${escPrefix}(\\d+)`);
    const volumes = docs.filter((d) => /^decisions\/(?!README\.md$).+\.md$/.test(d.rel));
    // Заголовки внутри ```-блоков (пример формата в шаблоне) — не записи.
    const noFences = (t) => t.replace(/```[\s\S]*?```/g, (m) => m.replace(/[^\n]/g, " "));
    const label = (digits) => `${adrPrefix}${digits}`;
    const adrId = (heading) => {
      const b = heading.match(anchorRe);
      if (b) return { id: String(Number(b[1])), label: label(b[1]) };
      const noParens = heading.replace(/\([^)]*\)/g, "");
      const toks = [...noParens.matchAll(tokenRe)].map((m) => m[1]);
      if (toks.length === 1) return { id: String(Number(toks[0])), label: label(toks[0]) };
      if (toks.length > 1) return { ambiguous: toks.map(label) };
      return null;
    };
    const records = []; // {id, label, rel, line, inIndex}
    for (const d of [decIndex, ...volumes].filter(Boolean)) {
      noFences(d.text).split(/\r?\n/).forEach((line, i) => {
        if (!/^## /.test(line)) return;
        const r = adrId(line);
        if (!r) return;
        if (r.ambiguous)
          warnings.push(
            `ADR-AMBIGUOUS ${d.rel}:${i + 1} — в заголовке несколько номеров вне скобок (${r.ambiguous.join(", ")}) — id записи не определён: начни заголовок с номера, ссылки на другие решения — в скобки`
          );
        else records.push({ id: r.id, label: r.label, rel: d.rel, line: i + 1, inIndex: d === decIndex });
      });
    }
    const withVolumes = volumes.length > 0 && !!decIndex;
    // При томах записи в индексе уже флагает ADR-IN-INDEX — в подсчёт дублей их не берём
    // (одна причина — одна диагностика).
    const dupPool = withVolumes ? records.filter((r) => !r.inIndex) : records;
    const byId = new Map();
    for (const r of dupPool) (byId.get(r.id) || byId.set(r.id, []).get(r.id)).push(r);
    for (const [, list] of [...byId].sort((a, b) => Number(a[0]) - Number(b[0]))) {
      if (list.length > 1)
        problems.push(
          `ADR-DUP ${list[0].label} — ${list.length} записи под одним номером: ${list.map((r) => `${r.rel}:${r.line}`).join(", ")} — поздней дай следующий свободный номер (max+1, пометка Legacy), ссылки поправь`
        );
    }
    if (withVolumes) {
      const inIndex = records.filter((r) => r.inIndex);
      if (inIndex.length)
        warnings.push(
          `ADR-IN-INDEX decisions.md:${inIndex[0].line} — ${inIndex.length} запис(ей) \`## ${adrPrefix}…\` в индексе при наличии томов decisions/ — текст решения пиши в текущий том, в индекс — строку`
        );
      // Строка индекса — структурная (список/таблица с номером), а не любое упоминание в тексте.
      const indexLineRe = new RegExp(`^\\s*(?:[-*|]|\\d+\\.)[^\\n]*?(?<![\\p{L}\\p{N}-])${escPrefix}(\\d+)`, "gmu");
      const indexed = new Map(); // численный id → метка как в индексе
      for (const m of noFences(decIndex.text).matchAll(indexLineRe)) {
        if (!indexed.has(String(Number(m[1])))) indexed.set(String(Number(m[1])), label(m[1]));
      }
      const volIds = new Set(records.filter((r) => !r.inIndex).map((r) => r.id));
      for (const r of records.filter((r) => !r.inIndex)) {
        if (!indexed.has(r.id))
          warnings.push(`ADR-NOT-INDEXED ${r.rel}:${r.line} — ${r.label} есть в томе, но строки с ним нет в decisions.md (индекс)`);
      }
      for (const [id, lbl] of [...indexed].sort((a, b) => Number(a[0]) - Number(b[0]))) {
        if (!volIds.has(id))
          warnings.push(`ADR-INDEX-ORPHAN decisions.md — строка **${lbl}** есть в индексе, а записи в томах decisions/ нет`);
      }
      // Диапазон тома по имени файла <stem>-NNNN-MMMM.md: запись вне диапазона — в чужом томе (0 допустим в первом).
      const volNameRe = new RegExp(`^${stem}-(\\d+)-(\\d+)\\.md$`);
      const ranged = volumes
        .map((v) => ({ v, m: basename(v.file).match(volNameRe) }))
        .filter((x) => x.m)
        .map((x) => ({ rel: x.v.rel, lo: Number(x.m[1]), hi: Number(x.m[2]), loS: x.m[1], hiS: x.m[2] }));
      const firstLo = ranged.length ? Math.min(...ranged.map((x) => x.lo)) : null;
      for (const r of records.filter((r) => !r.inIndex)) {
        const vol = ranged.find((x) => x.rel === r.rel);
        if (!vol) continue;
        const n = Number(r.id);
        if ((n === 0 && vol.lo === firstLo) || (n >= vol.lo && n <= vol.hi)) continue;
        warnings.push(`ADR-RANGE ${r.rel}:${r.line} — ${r.label} вне диапазона тома ${vol.loS}…${vol.hiS} — перенеси в свой том`);
      }
    }
    if (decIndex) {
      const size = Buffer.byteLength(decIndex.text, "utf8");
      if (size > o.decisionsMaxKb * 1024)
        warnings.push(
          `DECISIONS-BLOAT decisions.md — ${(size / 1024).toFixed(0)}KB > ${o.decisionsMaxKb}KB — журнал не читается целиком: оставь здесь индекс (строка на решение, «по темам»), тексты — в тома decisions/${stem}-NNNN-MMMM.md`
        );
    }
  }

  // 12) INDEX-REF — пути в ручной части INDEX указывают на несуществующее
  const indexPath = join(mbDir, "INDEX.md");
  if (existsSync(indexPath)) {
    let manual = readDoc(indexPath).replace(
      /<!-- GENERATED:[\s\S]*?END -->/g,
      ""
    );
    manual = manual.replace(/```[\s\S]*?```/g, "");
    for (const m of manual.matchAll(/`([^`\n]+\.md)`/g)) {
      const p = m[1];
      if (/[*<>{}]/.test(p)) continue; // глоб/плейсхолдер/пример
      if (!existsSync(join(mbDir, p)) && !existsSync(join(root, p)))
        problems.push(`INDEX-REF INDEX.md — \`${p}\` не существует (ни в .memory_bank/, ни в корне)`);
    }
  }

  // 13) Регенерация GENERATED-блоков (write) / REGISTRY-STALE (--check)
  function regenBlock(filePath, marker, table) {
    if (!existsSync(filePath)) return;
    const relName = relative(mbDir, filePath).split(sep).join("/");
    const txt = readDoc(filePath);
    const START = `<!-- GENERATED:${marker} START -->`;
    const END = `<!-- GENERATED:${marker} END -->`;
    const s = txt.indexOf(START);
    const e = txt.indexOf(END);
    if (s === -1 || e === -1 || e < s) {
      problems.push(`BROKEN  ${relName} — нет маркеров GENERATED:${marker} START/END`);
      return;
    }
    const rebuilt = txt.slice(0, s + START.length) + GEN_NOTE + table + txt.slice(e);
    if (rebuilt === txt) return;
    if (o.write) {
      writeFileSync(filePath, rebuilt, "utf8");
      notes.push(`${relName}: ${marker} регенерирован`);
    } else {
      problems.push(`REGISTRY-STALE ${relName} — блок ${marker} устарел (запусти audit без --check или /memory-check)`);
    }
  }
  const impRank = { high: 0, med: 1, low: 2 };
  const bySort = (a, b) =>
    (impRank[a.fm.importance] ?? 3) - (impRank[b.fm.importance] ?? 3) ||
    (String(a.fm.topic) < String(b.fm.topic) ? -1 : 1);
  function mdTable(header, rows, emptyRow) {
    return ["", header, header.replace(/[^|]/g, "-"), ...(rows.length ? rows : [emptyRow]), ""].join("\n");
  }
  // 13a) decision tree в INDEX.md
  {
    const tier1 = contentDocs
      .filter((d) => String(d.fm.tier) === "1" && d.fm.topic && !ALWAYS_ON_TOPICS.has(d.fm.topic))
      .sort(bySort);
    // Путь Tier 2 печатаем относительно .memory_bank/ (читатель INDEX стоит в корне банка), а не
    // копируем tier2: verbatim — тот относителен к папке сводки (`../domain/x.md` из core/ сбивал).
    const t2Display = (d) => {
      if (isPlaceholder(d.fm.tier2)) return "—";
      const abs = resolve(dirname(d.file), d.fm.tier2);
      return `\`${relative(mbDir, abs).split(sep).join("/")}\``;
    };
    const rows = tier1.map((d) => `| ${d.fm.scope || d.fm.topic} | \`${d.rel}\` | ${t2Display(d)} |`);
    regenBlock(
      indexPath,
      "decision-tree",
      mdTable("| Задача (scope) | Tier 1 | Tier 2 |", rows, "| _(нет Tier 1 доков с topic)_ | — | — |")
    );
  }
  // 13b) core-registry в core/README.md
  {
    const coreDocs = contentDocs.filter((d) => d.rel.startsWith("core/")).sort(bySort);
    const rows = coreDocs.map((d) => {
      const t2 = isPlaceholder(d.fm.tier2) ? "—" : `\`${d.fm.tier2}\``;
      return `| \`${basename(d.file)}\` | ${d.fm.topic || "—"} | ${d.fm.scope || "—"} | ${t2} | ${d.fm.updated || "—"} |`;
    });
    regenBlock(
      join(mbDir, "core", "README.md"),
      "core-registry",
      mdTable("| Файл | topic | Когда читать (scope) | Tier 2 | updated |", rows, "| _(пусто — сводки добавляются по мере роста)_ | | | | |")
    );
  }
  // 13c) plans-registry в plans/README.md
  {
    const rows = planDocs
      .slice()
      .sort((a, b) => (String(a.fm.created) < String(b.fm.created) ? 1 : -1))
      .map(
        (p) =>
          `| ${p.fm.slug || basename(p.file, ".md")} | ${p.fm.title || "—"} | ${p.fm.status || "—"} | ${p.fm.created || "—"} | ${p.fm.updated || "—"} |`
      );
    regenBlock(
      join(mbDir, "plans", "README.md"),
      "plans-registry",
      mdTable("| slug | Название | status | created | updated |", rows, "| _(нет активных планов)_ | | | | |")
    );
  }
  // 13d) completed-plans-registry в completed_plans/README.md
  {
    const rows = completedDocs
      .slice()
      .sort((a, b) => (String(a.fm.completed) < String(b.fm.completed) ? 1 : -1))
      .map((p) => `| ${p.fm.slug || basename(p.file, ".md")} | ${p.fm.title || "—"} | ${p.fm.completed || "—"} |`);
    regenBlock(
      join(mbDir, "completed_plans", "README.md"),
      "completed-plans-registry",
      mdTable("| slug | Название | Завершён |", rows, "| _(пусто)_ | | |")
    );
  }

  // 14) DIVERGENCE — вторая .memory_bank: в предках (до git-root, ≤3 уровней) или внутри проекта
  {
    const others = [];
    let cur = dirname(root);
    for (let i = 0; i < 3 && cur !== dirname(cur); i++) {
      if (existsSync(join(cur, ".memory_bank"))) others.push(join(cur, ".memory_bank"));
      if (existsSync(join(cur, ".git"))) break;
      cur = dirname(cur);
    }
    findNestedBanks(root, 3, others, mbDir);
    if (others.length)
      problems.push(
        `DIVERGENCE найдено >1 .memory_bank: ${mbDir}, ${others.join(", ")} — сведи к одному канону (DEPLOY.md «Каноничное расположение»)`
      );
  }

  // 15) SECRET — _secrets/ вне .gitignore; значения секретов в памяти вне _secrets/
  {
    const secretsDir = join(mbDir, "_secrets");
    if (existsSync(secretsDir) && existsSync(join(root, ".git"))) {
      const giPath = join(root, ".gitignore");
      const gi = existsSync(giPath) ? readDoc(giPath) : "";
      // negation-строки (!...) НЕ считаются игнором — только реальные ignore-паттерны
      const ignoresSecrets = gi.split(/\r?\n/).some((l) => {
        const t = l.trim();
        return t && !t.startsWith("#") && !t.startsWith("!") && t.includes("_secrets");
      });
      if (!ignoresSecrets)
        problems.push(`SECRET  .memory_bank/_secrets/ не исключён в .gitignore — секреты уедут в git`);
    }
    const SECRET_RE =
      /(password|passwd|secret|api[_-]?key|token)["']?\s*[:=]\s*["']?([A-Za-z0-9_\-.+=]{16,})["']?/i;
    for (const d of contentDocs) {
      const lines = d.text.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.includes("_secrets") || PH_RE.test(line)) continue;
        const m = line.match(SECRET_RE);
        if (m && /\d/.test(m[2])) {
          problems.push(`SECRET  ${d.rel}:${i + 1} — похоже на значение секрета в памяти — перенеси в _secrets/ (вне git)`);
          break; // одна находка на файл
        }
      }
    }
  }

  let driftCoverage = null; // {docsWithRefs, docsCovered} — заполняется в блоке 16, см. там
  let driftReport = null; // --drift-report (эксперимент B5) — блок 16c

  // 16) CODE-REF — backtick-путь к файлу кода в памяти не найден в дереве репо (память ↔ код разъехались).
  //     Консервативно: под-флаг важнее пере-флага. Флагаем ТОЛЬКО inline-code-токены, похожие на
  //     репо-относительный путь файла (есть `/` и известное код-расширение) или на вложенную папку (после
  //     снятия хвостового `/` внутри всё ещё есть `/`). НЕ флагаем: абсолютные (`/opt/…`, `/go/`-роут,
  //     `/home/…`) — это серверные пути/роуты/внешнее, не репо-код; одиночные `lib/`, `services/` —
  //     grep-подсказки. notes-проект (нет кода) — проверку не гоним. Allowlist `_kit/code-ref-ignore.txt`:
  //     точный токен ИЛИ префикс (строка с хвостовым `/` гасит всё под ней, напр. `mltest/`).
  {
    const projTypeFile = join(mbDir, "_intake", "brief", "_project-type.txt");
    const projType = existsSync(projTypeFile) ? readDoc(projTypeFile).trim() : "dev";
    if (projType !== "notes") {
      const CODE_EXT = new Set([
        "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "go", "rs", "rb", "php", "java",
        "sql", "sh", "css", "scss", "html", "vue", "svelte", "yml", "yaml", "json", "toml",
      ]);
      const ignoreFile = join(mbDir, "_kit", "code-ref-ignore.txt");
      const ignoreExact = new Set();
      const ignorePrefix = [];
      for (const l of (existsSync(ignoreFile) ? readDoc(ignoreFile) : "").split(/\r?\n/)) {
        const t = l.trim();
        if (!t || t.startsWith("#")) continue;
        if (t.endsWith("/")) ignorePrefix.push(t);
        else ignoreExact.add(t);
      }
      const looksLikePath = (tok) => {
        if (!tok.includes("/") || /\s/.test(tok) || /[*<>{}()|]/.test(tok)) return false;
        if (tok.includes("://") || tok.startsWith("http")) return false; // URL
        if (tok.startsWith("/") || tok.startsWith("~")) return false; // абсолютный/серверный путь/роут — не репо-код
        return true;
      };
      // Якоря `путь:символ` / `путь#символ` / `путь:123` и голые имена файлов (v1.9; пилот sup2 27.09): раньше
      // расширение превращалось в `ts:символ`, а `sup2-deploy.sh` без `/` не считался ссылкой — такие утверждения
      // CODE-DRIFT не видел. Голое имя — ссылка, только если файл с таким именем в репо ровно один.
      const hasGit = !o.noGit && existsSync(join(root, ".git"));
      const byBase = new Map();
      if (hasGit) {
        try {
          const r = spawnSync("git", ["-C", root, "ls-files"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 64 * 1024 * 1024 });
          if (!r.error && r.status === 0)
            for (const f of (r.stdout || "").split("\n")) {
              if (!f) continue;
              const b = f.slice(f.lastIndexOf("/") + 1);
              if (!byBase.has(b)) byBase.set(b, []);
              byBase.get(b).push(f);
            }
        } catch {
          /* нет git — голые имена не резолвим */
        }
      }
      const normTok = (raw) => {
        let tok = raw.trim().replace(/^\.\//, "");
        const sfx = tok.match(/^([^\s:#]+\.([A-Za-z0-9]+))[:#]\S*$/);
        if (sfx && CODE_EXT.has(sfx[2].toLowerCase())) tok = sfx[1];
        if (!tok.includes("/")) {
          // Без «/» — только имя файла, уникальное в репо; прочие слова (`sql`, `*-topbar.tsx`) — не ссылки.
          if (!/^[\w.\-]+\.[A-Za-z0-9]+$/.test(tok)) return null;
          const hits = CODE_EXT.has(tok.split(".").pop().toLowerCase()) ? byBase.get(tok) : null;
          if (!hits) return null;
          if (hits.includes(tok)) return tok; // файл в корне репо (`package.json` при десятке вложенных) — он и имелся в виду
          return hits.length === 1 ? hits[0] : null;
        }
        return tok;
      };
      // Правила `.claude/rules/*.md` тоже описывают поведение кода (объяснение автодеплоя в server-access.md
      // устарело 17.08, и никто не заметил) — сканируем их наравне с доками банка. Дата-якорь правила:
      // last_verified/updated в шапке, иначе дата последнего коммита файла правила.
      // Блоки ``` в правилах — примеры команд и путей, не утверждения: из скана якорей вырезаются.
      const ruleDocs = [];
      for (const { full, rel } of listRuleFiles(root)) {
        const raw = readDoc(full);
        const fm = parseFrontmatter(raw).fm || {};
        let gitDate = null;
        if (hasGit) {
          const r = spawnSync("git", ["-C", root, "log", "-1", "--format=%cs", "--", rel], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
          const s = (r.stdout || "").trim();
          if (!r.error && r.status === 0 && isDate(s)) gitDate = s;
        }
        ruleDocs.push({ rel, text: stripFences(raw), fm, gitDate, isRule: true });
      }
      const seen = new Set(); // одна находка на (doc, path)
      const codeClaims = []; // живые ссылки на код в репо — вход для CODE-DRIFT (16b)
      for (const d of contentDocs.concat(ruleDocs)) {
        for (const m of d.text.matchAll(/`([^`\n]+)`/g)) {
          const tok = normTok(m[1]);
          // Без «/» normTok отдаёт только уникальный в репо файл (в т.ч. в корне: `instrumentation.ts`) — это якорь.
          if (!tok || (tok.includes("/") && !looksLikePath(tok))) continue;
          const isDir = tok.endsWith("/");
          const bare = isDir ? tok.slice(0, -1) : tok;
          if (isDir) {
            if (!bare.includes("/")) continue; // одиночная папка (grep-подсказка) — не claim
          } else {
            const ext = (bare.split(".").pop() || "").toLowerCase();
            if (!CODE_EXT.has(ext)) continue; // не файл кода (в т.ч. .md — это [[ссылки]]/INDEX-REF)
          }
          if (ignoreExact.has(tok) || ignoreExact.has(bare)) continue;
          if (ignorePrefix.some((p) => tok.startsWith(p) || bare.startsWith(p))) continue;
          if (bare.startsWith(".memory_bank") || bare.startsWith("node_modules")) continue;
          const key = `${d.rel}::${tok}`;
          if (seen.has(key)) continue;
          seen.add(key);
          // Резолвим и от корня репо (код), и от .memory_bank (memory-относительные пути вроде
          // `_intake/brief/`, `core/…`) — как INDEX-REF. Найдено в любом → не claim о коде.
          const inRepo = existsSync(join(root, bare));
          const resolved = inRepo ? join(root, bare) : existsSync(join(mbDir, bare)) ? join(mbDir, bare) : null;
          const ok = resolved && (isDir ? statSync(resolved).isDirectory() : true);
          // Правила кита содержат иллюстративные пути (`lib/auth/jwt.ts` как пример якоря) — для них
          // несуществующий путь не ошибка: правила идут только в CODE-DRIFT по реальным ссылкам.
          if (!ok && !d.isRule)
            problems.push(
              `CODE-REF ${d.rel} — \`${tok}\` не найден в дереве репозитория (память отстала от кода? обнови ссылку или добавь в _kit/code-ref-ignore.txt)`
            );
          // Живая ссылка на код в репо — кандидат для CODE-DRIFT (16b).
          else if (inRepo) codeClaims.push({ d, tok, bare, isDir });
        }
      }

      // 16b) CODE-DRIFT (warning) — путь на месте, но код за ним уехал. CODE-REF ловит только
      //      удаление/переименование: если файл переписали, а путь остался, память молча врёт.
      //      Якорь свежести дока — last_verified (когда утверждения сверяли), иначе updated.
      //      Даты кода берём ОДНИМ проходом git log (процесс на токен — недопустимо дорого).
      //      Исключения: always-on мета-доки (decisions/project-state/source-of-truth — журналы
      //      решений, они и должны быть старше кода) и source_of_truth: historical.
      const anchorOf = (d) =>
        isDate(d.fm.last_verified) ? d.fm.last_verified : isDate(d.fm.updated) ? d.fm.updated : d.gitDate || null;
      // Исключённые по политике (журналы решений, historical) — НЕ «непокрытые»: их не проверяют
      // намеренно. Поэтому они уходят и из числителя, и из знаменателя покрытия.
      const eligible = codeClaims.filter(
        (c) =>
          !ALWAYS_ON_TOPICS.has(c.d.fm.topic) &&
          !/^decisions(-|$)/.test(String(c.d.fm.topic || "")) && // тома ADR — журнал, как и decisions.md
          c.d.fm.source_of_truth !== "historical"
      );
      const tracked = eligible.filter((c) => anchorOf(c.d));
      // Покрытие: сколько доков со ссылками на код проверка вообще ВИДИТ. Без даты-якоря во
      // frontmatter CODE-DRIFT по доку молчит — а у докитовых банков якорей нет ни у одного дока,
      // и тогда «0 находок» читается как здоровье. Молчание проверки ≠ здоровье, поэтому цифра
      // покрытия идёт в вывод и в METRICS рядом с находками.
      // Честный знаменатель (27.09): «покрытие 100%» считалось только среди доков, где ссылки уже распознаны, —
      // сводка без единого якоря в него не попадала и выглядела здоровой. Теперь считаем от всех сводок Tier 1;
      // сводка без якорей — NO-ANCHOR (warning). Сводки не о коде — в `_kit/no-anchor-ignore.txt` (путь или topic).
      const naFile = join(mbDir, "_kit", "no-anchor-ignore.txt");
      const naIgnore = new Set(
        (existsSync(naFile) ? readDoc(naFile) : "").split(/\r?\n/).map((l) => l.replace(/#.*/, "").trim()).filter(Boolean)
      );
      const anchoredRel = new Set(eligible.map((c) => c.d.rel));
      const tier1 = contentDocs.filter((d) => String(d.fm.tier) === "1" && d.fm.topic && !ALWAYS_ON_TOPICS.has(d.fm.topic));
      const exempt = tier1.filter((d) => naIgnore.has(d.rel) || naIgnore.has(d.fm.topic));
      const noAnchor = tier1.filter((d) => !anchoredRel.has(d.rel) && !exempt.includes(d));
      for (const d of noAnchor)
        warnings.push(
          `NO-ANCHOR ${d.rel} — в сводке нет ни одной ссылки на код (\`путь\` или \`путь:символ\`), CODE-DRIFT её не видит — добавь якоря к утверждениям о поведении или впиши в _kit/no-anchor-ignore.txt, если сводка не о коде`
        );
      driftCoverage = {
        docsWithRefs: new Set(eligible.map((c) => c.d.rel)).size,
        docsCovered: new Set(tracked.map((c) => c.d.rel)).size,
        tier1Total: tier1.length,
        tier1Anchored: tier1.filter((d) => anchoredRel.has(d.rel)).length,
        tier1Exempt: exempt.length,
        rulesAnchored: ruleDocs.filter((d) => anchoredRel.has(d.rel)).length,
        rulesTotal: ruleDocs.length,
      };

      const gitOk = !o.noGit && !o.noCodeDrift && existsSync(join(root, ".git"));
      if (gitOk && codeClaims.length) {
        const since = tracked.map((c) => anchorOf(c.d)).sort()[0];
        if (since) {
          // path -> дата последнего коммита (git log идёт от новых к старым → первая победа).
          const lastTouch = new Map();
          try {
            const r = spawnSync(
              "git",
              // -n: потолок на случай древнего якоря в большом репо. Лог идёт от новых к старым,
              // так что срезаются только СТАРЫЕ касания — а такой банк уже ловит FROZEN-MEMORY.
              ["-C", root, "log", "--relative", `--since=${since}`, "-n", "4000", "--format=%cs", "--name-only", "--no-renames"], // --relative: пути от корня проекта, не репо (монорепо)
              { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 64 * 1024 * 1024 }
            );
            if (!r.error && r.status === 0) {
              let cur = null;
              for (const line of (r.stdout || "").split("\n")) {
                const s = line.trim();
                if (!s) continue;
                if (isDate(s)) cur = s;
                else if (cur && !lastTouch.has(s)) lastTouch.set(s, cur);
              }
            }
          } catch {
            /* git недоступен — CODE-DRIFT просто не сработает, это не ошибка банка */
          }
          // Дата последнего касания пути: файл — точное совпадение, папка — максимум по префиксу.
          const touchedAt = (bare, isDir) => {
            if (!isDir) return lastTouch.get(bare) || null;
            const pref = bare.endsWith("/") ? bare : bare + "/";
            let best = null;
            for (const [p, dt] of lastTouch) if (p.startsWith(pref) && (!best || dt > best)) best = dt;
            return best;
          };
          const perDoc = new Map(); // rel -> { d, anchor, hits: [{tok, date, days}] }
          for (const c of tracked) {
            const at = touchedAt(c.bare, c.isDir);
            if (!at) continue;
            const anchor = anchorOf(c.d);
            const gap = daysBetween(anchor, at);
            if (gap < o.codeDriftDays) continue;
            if (!perDoc.has(c.d.rel)) perDoc.set(c.d.rel, { anchor, hits: [] });
            perDoc.get(c.d.rel).hits.push({ tok: c.tok, date: at, days: gap });
          }
          for (const [rel, { anchor, hits }] of [...perDoc].sort((a, b) => a[0].localeCompare(b[0]))) {
            const top = hits.sort((a, b) => b.days - a.days)[0];
            const more = hits.length > 1 ? `, всего ссылок разошлось: ${hits.length}` : "";
            warnings.push(
              `CODE-DRIFT ${rel} — код изменился после ${anchor} (\`${top.tok}\` → ${top.date}, +${top.days}д${more}) — сверь утверждения и обнови last_verified`
            );
          }
        }
      }
      // 16c) --drift-report — эксперимент B5 (см. buildDriftReport): только отчёт и телеметрия, не находки.
      if (o.driftReport && hasGit) driftReport = buildDriftReport(root, mbDir, eligible);
    }
  }

  // 17) FROZEN-MEMORY — код менялся во множестве коммитов, а память замёрзла (механический сигнал
  //     согласованного замерзания — тот же класс провала, но пойманный по git-активности, а не по датам).
  //     Считаем коммиты, тронувшие код, ПОСЛЕ последнего коммита, тронувшего .memory_bank/.
  //     Гварды: только при наличии .git и доступного git; иначе тихо пропускаем (фикстуры/оффлайн).
  if (!o.noGit && existsSync(join(root, ".git"))) {
    const git = (args) =>
      spawnSync("git", ["-C", root, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    try {
      const lastMemRes = git(["log", "-1", "--format=%H", "--", ".memory_bank"]);
      const lastMem = lastMemRes.error || lastMemRes.status !== 0 ? "" : (lastMemRes.stdout || "").trim();
      if (lastMem) {
        const cntRes = git(["rev-list", "--count", `${lastMem}..HEAD`, "--", ".", ":(exclude).memory_bank"]);
        const n = cntRes.error || cntRes.status !== 0 ? NaN : parseInt((cntRes.stdout || "").trim(), 10);
        if (Number.isFinite(n) && n > o.frozenCommits)
          problems.push(
            `FROZEN-MEMORY ${n} коммит(ов) тронули код после последнего изменения .memory_bank/ (порог ${o.frozenCommits}) — сверь память с кодом (/memory-check)`
          );
      }
    } catch {
      /* git недоступен — тихо пропускаем, это не ошибка банка */
    }
  }

  // 18) RULES-FM — линт frontmatter правил .claude/rules/*.md. Claude Code игнорирует Cursor-поля
  //     (alwaysApply/globs), а paths вне документированного формата (YAML-список, паттерны в кавычках)
  //     в ряде версий приводил к тому, что правило МОЛЧА не загружалось. Always-on = правило БЕЗ paths.
  {
    const rulesDir = join(root, ".claude", "rules");
    if (existsSync(rulesDir)) {
      for (const { full: f, rel } of listRuleFiles(root)) {
        const text = readDoc(f);
        if (!text.startsWith("---")) continue; // без frontmatter — легальное always-on правило (v1.7: warning отклонён критикой — механического эффекта нет)
        const end = text.indexOf("\n---", 3);
        if (end === -1) {
          problems.push(`RULES-FM ${rel} — frontmatter не закрыт (нет парного ---)`);
          continue;
        }
        let inPaths = false;
        for (const raw of text.slice(3, end).split(/\r?\n/)) {
          const line = raw.replace(/\r$/, "");
          const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
          if (m) {
            inPaths = m[1] === "paths";
            if (m[1] === "alwaysApply" || m[1] === "globs")
              problems.push(
                `RULES-FM ${rel} — поле '${m[1]}' — формат Cursor, Claude Code его не читает (always-on = правило БЕЗ paths; см. guides/how-to-write-rules.md)`
              );
            if (m[1] === "paths" && m[2].trim().startsWith("["))
              problems.push(
                `RULES-FM ${rel} — inline-массив в 'paths' — используй YAML-список: каждый паттерн с новой строки, в кавычках`
              );
            continue;
          }
          const li = line.match(/^\s*-\s+(.+)$/);
          if (li && inPaths) {
            const v = li[1].trim();
            if (!/^(["']).*\1$/.test(v))
              problems.push(`RULES-FM ${rel} — глоб в 'paths' без кавычек: ${v} — глоб с * без кавычек ломает YAML`);
          }
        }
      }
    }
  }

  // 19) MEM-INJECT — защита от отравления памяти (OWASP ASI06): док с провенансом external:*
  //     содержит императивы к агенту или exec-паттерны. Консервативная эвристика — сигналит на
  //     ручное ревью, не цензурирует текст: тот же контент с source: manual не флагается.
  //     Сканируем сырое тело (НЕ stripCode): инъекции часто живут именно в код-примерах.
  {
    const IMPERATIVE_RES = [
      /\b(always|never)\s+(run|use|execute|exec|install|skip|ignore|disable)\b/i,
      /\bignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions?|rules?)\b/i,
      /\b(do\s+not|don'?t)\s+ask\b/i,
      /\b(всегда|никогда\s+не)\s+(запускай|выполняй|используй|устанавливай|спрашивай)\b/i,
      /\bигнорируй\s+(предыдущие|прошлые|все)\s+(инструкции|правила)\b/i,
      /\bне\s+спрашивая\b|\bбез\s+подтверждения\b/i,
      /curl[^\n]{0,200}\|\s*(ba|z)?sh\b/i,
      /wget[^\n]{0,200}\|\s*(ba|z)?sh\b/i,
    ];
    for (const d of contentDocs) {
      if (!/^external:/.test(String(d.fm.source || ""))) continue;
      const body = d.text.replace(/^---[\s\S]*?\n---/, "");
      const bodyOffset = d.text.length - body.length;
      let hit = null;
      for (const re of IMPERATIVE_RES) {
        const m = body.match(re);
        if (m) {
          hit = { idx: bodyOffset + m.index, frag: m[0] };
          break;
        }
      }
      if (hit) {
        const lineNo = d.text.slice(0, hit.idx).split("\n").length;
        problems.push(
          `MEM-INJECT ${d.rel}:${lineNo} — императив/exec-паттерн («${hit.frag}») в доке с source: ${d.fm.source} — проверь вручную: инструкции из внешних источников в память не переносятся (memory-discipline)`
        );
      }
    }
  }

  // 20) Слепые зоны — честно назвать, что аудит НЕ смотрит. SKIP_DIRS исключены намеренно, но
  //     «✓ чисто» читалось как «всё проверено»: remlab держал в _intake/ 22 МБ логов, а canonical-доки
  //     ссылались туда как на истину. Размер исключённого — в вывод; сырьё в каноне и логи — warnings.
  const excluded = [];
  {
    for (const name of ["_intake", "archive", "completed_plans", "changelog"]) {
      const dir = join(mbDir, name);
      if (!existsSync(dir)) continue;
      let files = 0, bytes = 0, logs = 0;
      const biggest = []; // top-3 по размеру — для INTAKE-BLOAT
      (function walkAll(d) {
        for (const n of readdirSync(d)) {
          const full = join(d, n);
          let st;
          try { st = statSync(full); } catch { continue; }
          if (st.isDirectory()) walkAll(full);
          else {
            files++; bytes += st.size; if (n.endsWith(".log")) logs++;
            biggest.push({ rel: relative(mbDir, full).split(sep).join("/"), size: st.size });
          }
        }
      })(dir);
      excluded.push({ name, files, bytes, logs });
      if (name === "_intake") {
        if (bytes > o.intakeMaxMb * 1048576) {
          const top = biggest.sort((a, b) => b.size - a.size).slice(0, 3).map((x) => `${x.rel} (${(x.size / 1048576).toFixed(1)} МБ)`);
          warnings.push(`INTAKE-BLOAT _intake/ — ${(bytes / 1048576).toFixed(1)} МБ > ${o.intakeMaxMb} МБ — это вход, не хранилище: крупнейшие ${top.join(", ")}`);
        }
        if (logs)
          warnings.push(`INTAKE-LOGS _intake/ — ${logs} файл(ов) *.log внутри банка — логи прогонов не память: держи вне .memory_bank/ (например ~/<проект>-logs/)`);
      }
    }
    // Allowlist _kit/intake-ref-ignore.txt (v1.8): `<док от корня банка> [<путь или префикс/ в _intake/>]  # причина`.
    // Без второго столбца гасятся ВСЕ ссылки дока — широко, и это осознанно (бриф как канон по решению
    // владельца); с ним — только эта ссылка (или всё под префиксом с хвостовым `/`).
    const intakeIgnore = []; // {doc, ref|null}
    {
      const f = join(mbDir, "_kit", "intake-ref-ignore.txt");
      for (const l of (existsSync(f) ? readDoc(f) : "").split(/\r?\n/)) {
        const t = l.replace(/#.*$/, "").trim();
        if (!t) continue;
        const [doc, ref] = t.split(/\s+/).map((s) => s.replace(/\\/g, "/").replace(/^\.\//, ""));
        if ([doc, ref].some((s) => s && s.split("/").includes(".."))) {
          warnings.push(`KIT-CONFIG _kit/intake-ref-ignore.txt — '${t}' содержит '..' — строка пропущена`);
          continue;
        }
        intakeIgnore.push({ doc, ref: ref || null });
      }
    }
    const intakeAllowed = (rel, hitRaw) => {
      const hit = hitRaw.replace(/[.,;:]+$/, ""); // точка в конце предложения — не часть пути
      return intakeIgnore.some(
        (e) => e.doc === rel && (!e.ref || hit === e.ref || (e.ref.endsWith("/") && hit.startsWith(e.ref)))
      );
    };
    for (const d of contentDocs) {
      if (d.fm.source_of_truth !== "canonical") continue;
      const body = d.text.replace(/^---[\s\S]*?\n---/, "");
      const hits = [...body.matchAll(/_intake\/(?!session-scratch\.md)[A-Za-z0-9_./-]+/g)]
        .map((m) => m[0])
        .filter((h) => !intakeAllowed(d.rel, h));
      if (hits.length)
        warnings.push(
          `CANON-INTAKE-REF ${d.rel} — canonical ссылается на ${[...new Set(hits)].slice(0, 2).join(", ")}${hits.length > 2 ? " …" : ""} — сырьё вне аудита; факт перенеси в док, провенанс оставь в source:`
        );
    }
  }

  // 21) KIT-NEW-PENDING (v1.8) — upgrade.sh кладёт новую версию рядом как <файл>.kit-new (kit-owned
  //     конфликт или изменённый эталон project-owned файла) и никогда не перезаписывает. Без проверки
  //     .kit-new лежит незамеченным (sup2: гайд и правила отстали на 3 версии молча). Пути — из
  //     _kit/manifest.txt (строки `<hash> <rel>` kit-owned и `owned <hash> <rel>` эталонов).
  {
    const mf = join(mbDir, "_kit", "manifest.txt");
    if (existsSync(mf)) {
      for (const l of readDoc(mf).split(/\r?\n/)) {
        const parts = l.trim().split(/\s+/);
        const rel = parts[0] === "owned" ? parts[2] : parts[1];
        if (!rel) continue;
        if (existsSync(join(root, `${rel}.kit-new`)))
          warnings.push(`KIT-NEW-PENDING ${rel}.kit-new — несведённый апгрейд кита: сравни с ${rel}, перенеси нужное и удали .kit-new`);
      }
    }
  }

  const psAgeDays = ps && isDate(ps.fm.updated) ? daysBetween(ps.fm.updated, o.today) : null;

  // Метрики (пассивный сбор — эмпирика вместо заявлений):
  //  - footprint: доля «всегда в контексте» (Tier 0 = CLAUDE.md + INDEX.md) в активном корпусе
  //    (Tier 0 + все доки банка). Структурная экономия токенов — измеримо, детерминированно.
  //  - byCategory: сколько находок каждой категории (частота дрейфа — эффект гейта в фазе warn).
  const claudeBytes = existsSync(join(root, "CLAUDE.md"))
    ? Buffer.byteLength(readDoc(join(root, "CLAUDE.md")), "utf8")
    : 0;
  const indexBytes = existsSync(join(mbDir, "INDEX.md"))
    ? Buffer.byteLength(readDoc(join(mbDir, "INDEX.md")), "utf8")
    : 0;
  const docsBytes = docs.reduce((s, d) => s + Buffer.byteLength(d.text, "utf8"), 0); // includes INDEX.md
  const corpusBytes = claudeBytes + docsBytes; // всё, что агент может прочитать (CLAUDE + весь банк)
  const alwaysOnBytes = claudeBytes + indexBytes; // всегда в контексте
  const footprintPct = corpusBytes > 0 ? Math.round((alwaysOnBytes / corpusBytes) * 1000) / 10 : null;
  // Аннотация «читался N×» по changelog/reads.log (PostToolUse-логгер, локальный, в .gitignore).
  // Отвечает на вопрос, который у находки про свежесть возникает первым: это живой док или мёртвый
  // вес? Сортировать находки по частоте НЕ стали — замер 2026-08-04 показал, что сортировать
  // нечего: топ-читаемые доки сверены 1–4 дня назад, а у 8 из 9 находок CODE-DRIFT ноль чтений
  // (дрейфует ровно то, чего никто не открывает). Порядок вывода остаётся детерминированным.
  {
    const readsFile = join(mbDir, "changelog", "reads.log");
    if (existsSync(readsFile)) {
      const counts = new Map();
      let firstDay = null;
      for (const line of readDoc(readsFile).split(/\r?\n/)) {
        const [day, p] = line.trim().split(/\s+/);
        if (!p) continue;
        counts.set(p, (counts.get(p) || 0) + 1);
        if (isDate(day) && (!firstDay || day < firstDay)) firstDay = day;
      }
      if (counts.size) {
        // Окно лога обязательно в тексте: «не открывался» за 5 дней и за полгода — разные факты.
        const windowDays = firstDay ? Math.max(1, daysBetween(firstDay, o.today)) : null;
        const ANNOTATED = /^(CODE-DRIFT|LAST-VERIFIED-OLD|REVIEW|UNVERIFIED)\b/;
        const annotate = (list) => {
          for (let i = 0; i < list.length; i++) {
            if (!ANNOTATED.test(list[i])) continue;
            const rel = list[i].split(/\s+/)[1];
            const n = counts.get(rel) || 0;
            list[i] += n
              ? ` (читался ${n}×)`
              : windowDays
                ? ` (не открывался за ${windowDays}д лога чтений)`
                : " (не открывался по логу чтений)";
          }
        };
        annotate(problems);
        annotate(warnings);
      }
    }
  }

  // Счётчик — по обоим классам: warn-категории в фазе сбора эмпирики нужны в метриках именно
  // затем, чтобы понять их частоту до повышения в problems.
  const byCategory = {};
  for (const p of [...problems, ...warnings]) {
    const cat = p.split(/\s+/)[0];
    byCategory[cat] = (byCategory[cat] || 0) + 1;
  }

  return {
    ok: problems.length === 0,
    problems,
    warnings,
    notes,
    docCount: docs.length,
    psUpdated: ps && isDate(ps.fm.updated) ? ps.fm.updated : null,
    psAgeDays,
    alwaysOnBytes,
    rulesAlwaysBytes,
    corpusBytes,
    footprintPct,
    byCategory,
    driftCoverage,
    driftReport,
    excluded,
  };
}

// ---------- CLI ----------
const isMain =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  // Передаём ТОЛЬКО явно заданные пороги: дефолты и _kit/audit-flags.txt применяет runChecks
  // (дефолт за каждый отсутствующий флаг перекрывал бы файл проекта).
  const explicit = {};
  for (const [flag, key] of Object.entries(THRESHOLD_KEYS)) {
    const i = args.indexOf(flag);
    if (i === -1 || i + 1 >= args.length) continue;
    const n = Number(args[i + 1]);
    if (Number.isFinite(n)) explicit[key] = n;
  }
  const BOOL_FLAGS = new Set(["--check", "--no-git", "--no-code-drift", "--metrics", "--drift-report"]); // не забирают значение → не съедают позиционный root
  const positional = args.filter(
    (a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--") && !BOOL_FLAGS.has(args[i - 1]))
  );
  const root = resolve(positional[0] ?? process.cwd());
  const res = runChecks(root, {
    write: !args.includes("--check"),
    ...explicit,
    noGit: args.includes("--no-git"),
    noCodeDrift: args.includes("--no-code-drift"),
    driftReport: args.includes("--drift-report"),
  });
  if (res.fatal) {
    console.error(`[memory-audit] ${res.fatal}`);
    process.exit(2);
  }
  console.log(`[memory-audit] root=${root}`);
  const regen = res.notes.length ? res.notes.join("; ") : args.includes("--check") ? "GENERATED-блоки (--check: не переписаны)" : "GENERATED-блоки актуальны";
  console.log(`[memory-audit] доков: ${res.docCount}; ${regen}`);
  if (res.excluded && res.excluded.length) {
    const fmt = (x) => `${x.name} (${x.files} ф., ${(x.bytes / 1048576).toFixed(1)} МБ${x.logs ? `, .log: ${x.logs}` : ""})`;
    console.log(`[memory-audit] вне content-scan (намеренно): ${res.excluded.map(fmt).join(" · ")} — «чисто» их не касается (completed_plans — только PLAN-MISPLACED, _secrets — своя проверка)`);
  }
  if (res.footprintPct !== null)
    console.log(
      `[memory-audit] Tier 0 (всегда в контексте): ${(res.alwaysOnBytes / 1024).toFixed(1)}KB — ${res.footprintPct}% активного корпуса (${(res.corpusBytes / 1024).toFixed(1)}KB)` +
        (res.rulesAlwaysBytes ? `; с правилами без paths: — ${((res.alwaysOnBytes + res.rulesAlwaysBytes) / 1024).toFixed(1)}KB` : "")
    );
  if (res.psAgeDays !== null && res.psAgeDays > 14)
    console.log(`[memory-audit] ⚠ project-state обновлялся ${res.psAgeDays}д назад (${res.psUpdated}) — возможно, снимок отстал`);
  // Покрытие CODE-DRIFT: без даты-якоря во frontmatter проверка по доку молчит. У докитовых
  // банков якорей нет вовсе — «0 находок» там означает «не смотрели», а не «чисто».
  if (res.driftCoverage && res.driftCoverage.docsWithRefs > 0) {
    const { docsWithRefs, docsCovered } = res.driftCoverage;
    const pct = Math.round((docsCovered / docsWithRefs) * 100);
    const dc0 = res.driftCoverage;
    console.log(
      `[memory-audit] сверка память↔код покрывает ${docsCovered} из ${docsWithRefs} доков со ссылками на код (${pct}%)` +
        (dc0.tier1Total != null
          ? `; сводок Tier 1 с якорями — ${dc0.tier1Anchored} из ${dc0.tier1Total}${dc0.tier1Exempt ? ` (не о коде: ${dc0.tier1Exempt})` : ""}; правил с якорями — ${dc0.rulesAnchored} из ${dc0.rulesTotal}`
          : "")
    );
    if (pct < 50)
      console.log(
        `[memory-audit] ⚠ у ${docsWithRefs - docsCovered} доков нет даты-якоря (updated/last_verified) — CODE-DRIFT по ним слеп, «0 находок» ≠ «чисто». Банк без frontmatter → рехидратация, см. HEAL.md`
      );
  }
  // --drift-report (эксперимент B5): отчёт + строка телеметрии в changelog/drift-report.log (локально, .gitignore).
  if (res.driftReport) {
    const dr = res.driftReport;
    if (dr.error) console.log(`[drift-report] ${dr.error}`);
    else {
      const sym = dr.items.filter((x) => x.symHit);
      console.log(
        `[drift-report] ЭКСПЕРИМЕНТ, не гейт: доков с якорями ${dr.docs}; код изменён после коммита сверки — ${dr.items.length} (символы из текста задеты — ${sym.length}); без точки отсчёта — ${dr.unverifiable.length}${dr.shallow ? "; ⚠ shallow clone — история неполная" : ""}`
      );
      for (const x of [...sym, ...dr.items.filter((y) => !y.symHit)])
        console.log(
          `  ${x.symHit ? "!" : "·"} ${x.doc} — сверка ${x.base.sha === "WORKTREE" ? "не закоммичена" : `${x.base.sha.slice(0, 7)} (${x.base.date})`}: ` +
            x.hits.map((h) => `${h.file}${h.syms.length ? ` [${h.syms.join(", ")}]` : ""}`).join("; ")
        );
      try {
        const head = spawnSync("git", ["-C", root, "rev-parse", "--short", "HEAD"], { encoding: "utf8" }).stdout.trim();
        const line = `${todayISO()} ${head} docs=${dr.docs} drift=${dr.items.length} sym=${sym.length} unverifiable=${dr.unverifiable.length} sym_docs=${sym.map((x) => x.doc).join(",") || "-"}\n`;
        const logFile = join(root, ".memory_bank", "changelog", "drift-report.log");
        writeFileSync(logFile, (existsSync(logFile) ? readFileSync(logFile, "utf8") : "") + line);
      } catch {
        /* телеметрия не обязательна */
      }
    }
  }
  // Машинная строка метрик для пассивного сбора (metrics-append.sh / CI-summary): footprint + частота находок.
  if (args.includes("--metrics")) {
    const kb = (b) => (b / 1024).toFixed(1);
    const cats = Object.keys(res.byCategory).sort().map((c) => `${c}=${res.byCategory[c]}`).join(" ");
    const dc = res.driftCoverage;
    const cov = dc && dc.docsWithRefs > 0 ? ` drift_cov=${dc.docsCovered}/${dc.docsWithRefs}` : "";
    console.log(
      `METRICS date=${todayISO()} docs=${res.docCount} tier0_kb=${kb(res.alwaysOnBytes)} corpus_kb=${kb(res.corpusBytes)} footprint_pct=${res.footprintPct ?? "NA"} findings=${res.problems.length} warns=${res.warnings.length}${cov}${cats ? " " + cats : ""}`
    );
  }
  // Предупреждения печатаем всегда, но на exit code они не влияют (фаза сбора эмпирики).
  if (res.warnings.length) {
    console.log(`[memory-audit] ⚠ предупреждений: ${res.warnings.length} (не блокируют)`);
    for (const w of res.warnings) console.log("  ~ " + w);
  }
  if (res.ok) {
    console.log("[memory-audit] ✓ проблем не найдено");
    process.exit(0);
  }
  console.log(`[memory-audit] ✗ найдено проблем: ${res.problems.length}`);
  for (const p of res.problems) console.log("  - " + p);
  process.exit(1);
}
