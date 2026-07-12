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
// Категории проверок (exit 1 при любой находке):
//   ORPHAN          content-док без frontmatter `topic` (невидим в навигации)
//   STALE           Tier 1 сводка, чей tier2-док новее (Tier2.updated > Tier1.updated)
//   BROKEN          указатели tier1/tier2 и [[ссылки]], которые не резолвятся; нет маркеров GENERATED
//   LAGGING         Tier 1 док отстаёт от project-state.updated более чем на --stale-days (дрейф слоя)
//   REVIEW          review_after в прошлом — пересмотреть актуальность
//   UNVERIFIED      source_of_truth: canonical без last_verified
//   BLOATED         project-state.md больше --ps-max-kb (снимок превратился в журнал)
//   NO-TIER1        domain/-док без парной Tier 1 сводки (не попадёт в decision tree)
//   PLACEHOLDER     незаполненные {{...}} в живых доках / INDEX.md / корневом CLAUDE.md
//   DUP-TOPIC       два content-дока с одинаковым topic
//   TIER1-BLOAT     Tier 1 сводка больше --tier1-max-kb (детали должны уйти в Tier 2)
//   TIER0-BLOAT     CLAUDE.md (корень) + INDEX.md суммарно больше --tier0-max-kb
//   PLAN-STUCK      план in_progress без движения дольше --plan-stale-days
//   PLAN-MISPLACED  completed-план в plans/ или не-completed в completed_plans/
//   BAD-FM          YAML-массив/вложенность в frontmatter (схема требует плоские строки)
//   INDEX-REF       путь в ручной части INDEX.md указывает на несуществующий файл
//   REGISTRY-STALE  GENERATED-блок устарел (в --check режиме)
//   DIVERGENCE      найдена вторая .memory_bank (в предках до git-root или внутри проекта)
//   SECRET          _secrets/ без .gitignore при git-репо; похожее на значение секрета вне _secrets/
//   CODE-REF        backtick-путь к файлу кода в памяти не найден в дереве репозитория (память отстала от кода)
//   FROZEN-MEMORY   код менялся в >N коммитах с момента последнего коммита в .memory_bank/ (замерзание памяти)
//
// Использование:
//   node tools/memory-audit.mjs [projectRoot]           (default: cwd; write-режим — регенерит блоки)
//   node tools/memory-audit.mjs --check [root]          (не писать, только проверка; для CI/hook)
//   Флаги порогов: --stale-days N (30) · --ps-max-kb N (12) · --tier1-max-kb N (3)
//                  --tier0-max-kb N (8) · --plan-stale-days N (14) · --frozen-commits N (12)
//   --no-git: отключить git-проверку FROZEN-MEMORY (иначе включается при наличии .git и git в PATH).
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

// ---------- основной прогон ----------
// opts: { write, staleDays, psMaxKb, tier1MaxKb, tier0MaxKb, planStaleDays, today }
// Возвращает { ok, fatal?, problems, notes, docCount, psUpdated, psAgeDays }.
export function runChecks(root, opts = {}) {
  const o = {
    write: false,
    staleDays: 30,
    psMaxKb: 12,
    tier1MaxKb: 3,
    tier0MaxKb: 8,
    planStaleDays: 14,
    frozenCommits: 12,
    noGit: false,
    today: todayISO(),
    ...opts,
  };
  root = resolve(root);
  const mbDir = join(root, ".memory_bank");
  if (!existsSync(mbDir)) {
    return { ok: false, fatal: `не найдено .memory_bank в ${root}`, problems: [], notes: [] };
  }

  const problems = [];
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
      if (isDate(d.fm.updated) && daysBetween(d.fm.updated, ps.fm.updated) > o.staleDays) {
        problems.push(
          `LAGGING ${d.rel} (updated ${d.fm.updated}) отстаёт от project-state (${ps.fm.updated}) на >${o.staleDays}д — сверь с реальностью`
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
    const size = Buffer.byteLength(d.text, "utf8");
    if (size > o.tier1MaxKb * 1024)
      problems.push(
        `TIER1-BLOAT ${d.rel} — ${(size / 1024).toFixed(1)}KB > ${o.tier1MaxKb}KB. Сводка = вход в тему; детали унеси в Tier 2`
      );
  }
  {
    let t0 = 0;
    for (const f of [join(root, "CLAUDE.md"), join(mbDir, "INDEX.md")]) {
      if (existsSync(f)) t0 += Buffer.byteLength(readDoc(f), "utf8");
    }
    if (t0 > o.tier0MaxKb * 1024)
      problems.push(
        `TIER0-BLOAT CLAUDE.md+INDEX.md — ${(t0 / 1024).toFixed(1)}KB > ${o.tier0MaxKb}KB. Tier 0 всегда в контексте — ужми, детали в Tier 1/2`
      );
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

  // 11) Планы: PLAN-STUCK / PLAN-MISPLACED
  for (const p of planDocs) {
    const st = p.fm.status || "";
    if (st === "completed")
      problems.push(`PLAN-MISPLACED ${p.rel} — status completed, но лежит в plans/ (перенеси в completed_plans/)`);
    const refDate = isDate(p.fm.updated) ? p.fm.updated : isDate(p.fm.created) ? p.fm.created : null;
    if (st === "in_progress" && refDate && daysBetween(refDate, o.today) > o.planStaleDays)
      problems.push(
        `PLAN-STUCK ${p.rel} — in_progress без движения с ${refDate} (> ${o.planStaleDays}д) — доведи, переведи в partial или отмени`
      );
  }
  for (const p of completedDocs) {
    if ((p.fm.status || "") !== "completed")
      problems.push(`PLAN-MISPLACED ${p.rel} — status '${p.fm.status || "—"}' ≠ completed, но лежит в completed_plans/`);
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
    const rows = tier1.map((d) => {
      const task = d.fm.scope || d.fm.topic;
      const t2 = isPlaceholder(d.fm.tier2) ? "—" : `\`${d.fm.tier2}\``;
      return `| ${task} | \`${d.rel}\` | ${t2} |`;
    });
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
      const seen = new Set(); // одна находка на (doc, path)
      for (const d of contentDocs) {
        for (const m of d.text.matchAll(/`([^`\n]+)`/g)) {
          let tok = m[1].trim().replace(/^\.\//, "");
          if (!looksLikePath(tok)) continue;
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
          const resolved = [join(root, bare), join(mbDir, bare)].find((p) => existsSync(p));
          const ok = resolved && (isDir ? statSync(resolved).isDirectory() : true);
          if (!ok)
            problems.push(
              `CODE-REF ${d.rel} — \`${tok}\` не найден в дереве репозитория (память отстала от кода? обнови ссылку или добавь в _kit/code-ref-ignore.txt)`
            );
        }
      }
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
  const byCategory = {};
  for (const p of problems) {
    const cat = p.split(/\s+/)[0];
    byCategory[cat] = (byCategory[cat] || 0) + 1;
  }

  return {
    ok: problems.length === 0,
    problems,
    notes,
    docCount: docs.length,
    psUpdated: ps && isDate(ps.fm.updated) ? ps.fm.updated : null,
    psAgeDays,
    alwaysOnBytes,
    corpusBytes,
    footprintPct,
    byCategory,
  };
}

// ---------- CLI ----------
const isMain =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  const flagVal = (name, def) => {
    const i = args.indexOf(name);
    if (i === -1 || i + 1 >= args.length) return def;
    const n = Number(args[i + 1]);
    return Number.isFinite(n) ? n : def;
  };
  const BOOL_FLAGS = new Set(["--check", "--no-git", "--metrics"]); // не забирают значение → не съедают позиционный root
  const positional = args.filter(
    (a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--") && !BOOL_FLAGS.has(args[i - 1]))
  );
  const root = resolve(positional[0] ?? process.cwd());
  const res = runChecks(root, {
    write: !args.includes("--check"),
    staleDays: flagVal("--stale-days", 30),
    psMaxKb: flagVal("--ps-max-kb", 12),
    tier1MaxKb: flagVal("--tier1-max-kb", 3),
    tier0MaxKb: flagVal("--tier0-max-kb", 8),
    planStaleDays: flagVal("--plan-stale-days", 14),
    frozenCommits: flagVal("--frozen-commits", 12),
    noGit: args.includes("--no-git"),
  });
  if (res.fatal) {
    console.error(`[memory-audit] ${res.fatal}`);
    process.exit(2);
  }
  console.log(`[memory-audit] root=${root}`);
  const regen = res.notes.length ? res.notes.join("; ") : args.includes("--check") ? "GENERATED-блоки (--check: не переписаны)" : "GENERATED-блоки актуальны";
  console.log(`[memory-audit] доков: ${res.docCount}; ${regen}`);
  if (res.footprintPct !== null)
    console.log(
      `[memory-audit] Tier 0 (всегда в контексте): ${(res.alwaysOnBytes / 1024).toFixed(1)}KB — ${res.footprintPct}% активного корпуса (${(res.corpusBytes / 1024).toFixed(1)}KB)`
    );
  if (res.psAgeDays !== null && res.psAgeDays > 14)
    console.log(`[memory-audit] ⚠ project-state обновлялся ${res.psAgeDays}д назад (${res.psUpdated}) — возможно, снимок отстал`);
  // Машинная строка метрик для пассивного сбора (metrics-append.sh / CI-summary): footprint + частота находок.
  if (args.includes("--metrics")) {
    const kb = (b) => (b / 1024).toFixed(1);
    const cats = Object.keys(res.byCategory).sort().map((c) => `${c}=${res.byCategory[c]}`).join(" ");
    console.log(
      `METRICS date=${todayISO()} docs=${res.docCount} tier0_kb=${kb(res.alwaysOnBytes)} corpus_kb=${kb(res.corpusBytes)} footprint_pct=${res.footprintPct ?? "NA"} findings=${res.problems.length}${cats ? " " + cats : ""}`
    );
  }
  if (res.ok) {
    console.log("[memory-audit] ✓ проблем не найдено");
    process.exit(0);
  }
  console.log(`[memory-audit] ✗ найдено проблем: ${res.problems.length}`);
  for (const p of res.problems) console.log("  - " + p);
  process.exit(1);
}
