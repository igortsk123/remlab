#!/usr/bin/env node
// memory-project-audit — ПРОЕКТНЫЕ проверки Memory Bank (project-owned; дополняет kit-owned
// tools/memory-audit.mjs, который НЕ трогаем). Без внешних зависимостей (Node >= 18, ESM).
// Тесты: tests/memory-project-audit.test.mjs (`node --test`).
//
// Зачем отдельный файл: кит проверяет общую структуру банка (frontmatter, уровни, ссылки), а здесь —
// соглашения ЭТОГО проекта: тома ADR + индекс, словарь статусов планов, блокнот захвата, чистота
// canonical-доков от сырья `_intake/`, секрет-файлы, целостность kit-файлов, нумерация уроков.
//
// Классы находок (как у кита): problems → exit 1; warnings → печатаются, exit не меняют.
//
// Категории:
//   ADR-DUP            номер ADR встречается в заголовках томов decisions/adr-*.md больше одного раза
//   ADR-RANGE          номер вне диапазона тома по имени файла (adr-0151-0200 → 151…200; 0000 — в первом)
//   ADR-NOT-INDEXED    номер есть в томе, а в decisions.md нет строки с **ADR-NNNN**
//   ADR-INDEX-ORPHAN   в индексе есть **ADR-NNNN**, а в томах нет
//   ADR-IN-INDEX       в decisions.md появился заголовок `## ADR-` (текст дописали в индекс вместо тома)
//   ADR-FORMAT         (warning) заголовок в томе не по формату `## ADR-NNNN — YYYY-MM-DD — Название`
//   PLAN-STATUS        status плана вне словаря {draft, in_progress, partial, completed, cancelled}
//   PLAN-DRAFT-STALE   draft с updated старше --draft-days и без review_after (или review_after в прошлом)
//   PLAN-PARTIAL-NO-REASON  partial без поля pause_reason во frontmatter
//   PLAN-NO-TITLE      (warning) у плана нет title:
//   SCRATCH-STALE      в _intake/session-scratch.md после метки SCRATCH START есть записи `- YYYY-MM-DD …`
//                      старше --scratch-days (блокнот не сведён /memory-check)
//   CANON-INTAKE-REF   (warning) content-док с source_of_truth: canonical ссылается в теле на _intake/ — провенанс допустим, истина должна быть в доке
//                      (кроме _intake/session-scratch.md) — истина не должна опираться на сырьё
//   SECRET-FILE        вне _secrets/: .env*/.pem/.key-файл, либо .txt/.json/.md с приватным ключом /
//                      sk-… / AKIA… / ghp_… / xox[bap]-… (сканируются и _intake/, и archive/)
//   KIT-MODIFIED       (warning) md5 файла из _kit/manifest.txt не совпадает с диском (или файла нет) —
//                      локальная правка kit-owned файла потеряется при upgrade кита
//   LESSON-DUP         (warning) номер урока в lessons/*.md встречается дважды и не признан в строке
//                      «дубли» lessons/README.md
//   LESSON-NEXT        (warning) «следующий номер: N» в lessons/README.md ≤ максимального найденного
//
// Использование:
//   node tools/memory-project-audit.mjs [root] [--check] [--json] [--brief]
//     --check          принимается для симметрии с китом (инструмент и так ничего не пишет)
//     --json           вместо текста — один JSON-объект {ok, problems, warnings, notes, byCategory}
//     --brief          одна строка-сводка для SessionStart-хука (молчит, когда чисто)
//     --scratch-days N порог блокнота (7) · --draft-days N порог draft-планов (30)
//
// Exit code: 0 — чисто; 1 — есть problems; 2 — ошибка запуска (нет .memory_bank).

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, relative, resolve, basename, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Те же исключения, что у кита: в этих каталогах не «content-доки» (для CANON-INTAKE-REF)
const SKIP_DIRS = new Set(["_intake", "completed_plans", "archive", "changelog", "_secrets", "_kit"]);
const SKIP_FILES = new Set(["README.md", "_template.md", "INDEX.md", "METADATA_SCHEMA.md", "CLEANUP_POLICY.md"]);
const PLAN_STATUSES = new Set(["draft", "in_progress", "partial", "completed", "cancelled"]);
const SCRATCH_MARK = "SCRATCH START";
const SECRET_SCAN_EXT = new Set([".txt", ".json", ".md", ".pem", ".key"]);
const SECRET_PATTERNS = [
  ["private key", /BEGIN [A-Z ]*PRIVATE KEY/],
  ["sk-…", /sk-[A-Za-z0-9]{20,}/],
  ["AKIA…", /AKIA[0-9A-Z]{16}/],
  ["ghp_…", /ghp_[A-Za-z0-9]{30,}/],
  ["xox[bap]-…", /xox[bap]-/],
];
const ADR_HEAD_RE = /^## ADR-(\d{4})\b(.*)$/;
const ADR_HEAD_OK_RE = /^## ADR-\d{4} — \d{4}-\d{2}-\d{2} — \S/;
const VOLUME_RE = /^adr-(\d{4})-(\d{4})\.md$/;
const LESSON_NUM_RES = [/^\*\*(\d+)\./, /^- (\d+) \[/, /^(\d+)\. \[/];

const stripBom = (s) => (s.charCodeAt(0) === 0xfeff ? s.slice(1) : s);
const readDoc = (f) => stripBom(readFileSync(f, "utf8"));
const isDate = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || "");
const toPosix = (p) => p.split(sep).join("/");

export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function daysBetween(aISO, bISO) {
  return Math.round((Date.parse(bISO) - Date.parse(aISO)) / 86400000);
}

// Минимальный парсер frontmatter (key: value между --- ---), как у кита: значения — плоские строки.
export function parseFrontmatter(text) {
  text = stripBom(text);
  const fm = {};
  if (!text.startsWith("---")) return { fm, end: 0 };
  const end = text.indexOf("\n---", 3);
  if (end === -1) return { fm, end: 0 };
  for (const raw of text.slice(3, end).split(/\r?\n/)) {
    const m = raw.replace(/\r$/, "").match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (m) fm[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  // end + 4 — позиция сразу после закрывающего "\n---"
  return { fm, end: end + 4 };
}

function walkAll(dir, skipDirs) {
  const out = [];
  for (const name of readdirSync(dir).sort()) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (skipDirs.has(name)) continue;
      out.push(...walkAll(full, skipDirs));
    } else out.push(full);
  }
  return out;
}

const listMd = (dir) =>
  !existsSync(dir) ? [] : readdirSync(dir).sort().filter((n) => n.endsWith(".md")).map((n) => join(dir, n));

// ---------- основной прогон ----------
// opts: { scratchDays, draftDays, today }
// Возвращает { ok, fatal?, problems, warnings, notes, byCategory }. ok — только по problems.
export function runChecks(root, opts = {}) {
  const o = { scratchDays: 7, draftDays: 30, today: todayISO(), ...opts };
  root = resolve(root);
  const mbDir = join(root, ".memory_bank");
  if (!existsSync(mbDir)) {
    return { ok: false, fatal: `не найдено .memory_bank в ${root}`, problems: [], warnings: [], notes: [], byCategory: {} };
  }
  const problems = [];
  const warnings = [];
  const notes = [];
  const rel = (f) => toPosix(relative(mbDir, f));

  // 1) ADR: тома decisions/adr-*.md ↔ индекс decisions.md
  const decDir = join(mbDir, "decisions");
  const indexFile = join(mbDir, "decisions.md");
  const volumes = listMd(decDir).filter((f) => VOLUME_RE.test(basename(f)));
  if (!volumes.length) {
    notes.push("decisions/adr-*.md не найдены — ADR-проверки пропущены");
  } else {
    const seen = new Map(); // num -> [{rel, line}]
    const inVolumes = new Set();
    const los = volumes.map((f) => Number(basename(f).match(VOLUME_RE)[1]));
    const firstLo = Math.min(...los);
    for (const f of volumes) {
      const [, loS, hiS] = basename(f).match(VOLUME_RE);
      const lo = Number(loS);
      const hi = Number(hiS);
      const lines = readDoc(f).split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(ADR_HEAD_RE);
        if (!m) continue;
        const num = Number(m[1]);
        const where = `${rel(f)}:${i + 1}`;
        inVolumes.add(num);
        if (!seen.has(num)) seen.set(num, []);
        seen.get(num).push(where);
        const zeroOk = num === 0 && lo === firstLo;
        if (!zeroOk && (num < lo || num > hi))
          problems.push(`ADR-RANGE ${where} — ADR-${m[1]} вне диапазона тома ${loS}…${hiS} — перенеси в свой том`);
        if (!ADR_HEAD_OK_RE.test(lines[i]))
          warnings.push(`ADR-FORMAT ${where} — заголовок не по формату \`## ADR-NNNN — YYYY-MM-DD — Название\``);
      }
    }
    for (const [num, places] of seen) {
      if (places.length > 1)
        problems.push(
          `ADR-DUP ADR-${String(num).padStart(4, "0")} — встречается ${places.length}× (${places.join(", ")}) — номера не переиспользуются, выдай новый`
        );
    }
    if (!existsSync(indexFile)) {
      notes.push("decisions.md не найден — сверка индекса с томами пропущена");
    } else {
      const idxText = readDoc(indexFile);
      const idxLines = idxText.split(/\r?\n/);
      const inIndex = new Set();
      for (let i = 0; i < idxLines.length; i++) {
        for (const m of idxLines[i].matchAll(/\*\*ADR-(\d{4})\*\*/g)) inIndex.add(Number(m[1]));
        if (ADR_HEAD_RE.test(idxLines[i]))
          problems.push(`ADR-IN-INDEX decisions.md:${i + 1} — заголовок \`## ADR-\` в индексе — полный текст пиши в текущий том decisions/`);
      }
      for (const num of [...inVolumes].sort((a, b) => a - b)) {
        if (!inIndex.has(num))
          problems.push(
            `ADR-NOT-INDEXED ${seen.get(num)[0]} — ADR-${String(num).padStart(4, "0")} есть в томе, но нет строки **ADR-${String(num).padStart(4, "0")}** в decisions.md`
          );
      }
      for (const num of [...inIndex].sort((a, b) => a - b)) {
        if (!inVolumes.has(num))
          problems.push(`ADR-INDEX-ORPHAN decisions.md — **ADR-${String(num).padStart(4, "0")}** есть в индексе, но ни в одном томе`);
      }
    }
  }

  // 2) Планы: статус, залежавшиеся draft, partial без причины, title
  const planFiles = listMd(join(mbDir, "plans")).filter((f) => !["README.md", "_template.md"].includes(basename(f)));
  for (const f of planFiles) {
    const r = rel(f);
    const { fm } = parseFrontmatter(readDoc(f));
    const status = fm.status || "";
    if (!PLAN_STATUSES.has(status))
      problems.push(`PLAN-STATUS ${r} — status '${status || "—"}' вне словаря {${[...PLAN_STATUSES].join(", ")}}`);
    if (status === "draft") {
      const anchor = isDate(fm.updated) ? fm.updated : isDate(fm.created) ? fm.created : null;
      const age = anchor ? daysBetween(anchor, o.today) : null;
      const reviewOk = isDate(fm.review_after) && daysBetween(fm.review_after, o.today) <= 0;
      if (age !== null && age > o.draftDays && !reviewOk)
        problems.push(
          `PLAN-DRAFT-STALE ${r} — draft ${age} д без движения (${anchor}) и без актуального review_after — реши: в работу, cancelled или review_after`
        );
    }
    if (status === "partial" && !fm.pause_reason)
      problems.push(`PLAN-PARTIAL-NO-REASON ${r} — partial без pause_reason во frontmatter — почему остановлен и что вернёт в работу`);
    if (!fm.title) warnings.push(`PLAN-NO-TITLE ${r} — нет title: (реестр планов покажет slug вместо названия)`);
  }

  // 3) Блокнот: записи старше порога после метки SCRATCH START
  const scratchFile = join(mbDir, "_intake", "session-scratch.md");
  if (existsSync(scratchFile)) {
    const lines = readDoc(scratchFile).split(/\r?\n/);
    let start = lines.findIndex((l) => l.includes(SCRATCH_MARK));
    if (start === -1) {
      notes.push("в session-scratch.md нет метки SCRATCH START — проверяется весь файл");
      start = -1;
    }
    const stale = [];
    for (let i = start + 1; i < lines.length; i++) {
      const m = lines[i].match(/^- (\d{4}-\d{2}-\d{2})\b/);
      if (!m) continue;
      const age = daysBetween(m[1], o.today);
      if (Number.isFinite(age) && age > o.scratchDays) stale.push({ line: i + 1, date: m[1], age });
    }
    if (stale.length) {
      const oldest = stale.reduce((a, b) => (b.age > a.age ? b : a));
      problems.push(
        `SCRATCH-STALE _intake/session-scratch.md:${stale[0].line} — записей старше ${o.scratchDays} д: ${stale.length} (самая старая ${oldest.date}, ${oldest.age} д) — сведи в банк через /memory-check`
      );
    }
  }

  // 4) canonical-доки, опирающиеся на сырьё _intake/
  const contentDocs = walkAll(mbDir, SKIP_DIRS).filter(
    (f) => f.endsWith(".md") && !SKIP_FILES.has(basename(f)) && !rel(f).startsWith("plans/")
  );
  for (const f of contentDocs) {
    const text = readDoc(f);
    const { fm, end } = parseFrontmatter(text);
    if (fm.source_of_truth !== "canonical") continue;
    // provenance `source: _intake/...` во frontmatter — легитимен; смотрим только тело
    const bodyLines = text.slice(end).split(/\r?\n/);
    const fmLines = text.slice(0, end).split(/\r?\n/).length - 1;
    const hits = [];
    for (let i = 0; i < bodyLines.length; i++) {
      const refs = [...bodyLines[i].matchAll(/_intake\/[A-Za-z0-9_\-./]*/g)].map((m) => m[0]);
      if (refs.some((x) => x !== "_intake/session-scratch.md" && !x.startsWith("_intake/session-scratch.md")))
        hits.push(fmLines + i + 1);
    }
    if (hits.length)
      warnings.push(
        `CANON-INTAKE-REF ${rel(f)}:${hits[0]} — canonical ссылается на _intake/ (${hits.length} стр.) — перенеси факт в канон, сырьё — в archive/ или убери ссылку`
      );
  }

  // 5) Секрет-файлы вне _secrets/ (включая _intake/ и archive/)
  for (const f of walkAll(mbDir, new Set(["_secrets"]))) {
    const name = basename(f);
    const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
    const r = rel(f);
    if (name.startsWith(".env") || ext === ".pem" || ext === ".key") {
      problems.push(`SECRET-FILE ${r} — файл ${name.startsWith(".env") ? ".env*" : ext} вне _secrets/ — перенеси в _secrets/ (вне git)`);
      continue;
    }
    if (!SECRET_SCAN_EXT.has(ext)) continue;
    let text;
    try {
      text = readDoc(f);
    } catch {
      continue;
    }
    const lines = text.split(/\r?\n/);
    outer: for (let i = 0; i < lines.length; i++) {
      for (const [label, re] of SECRET_PATTERNS) {
        if (re.test(lines[i])) {
          problems.push(`SECRET-FILE ${r}:${i + 1} — похоже на секрет (${label}) вне _secrets/ — перенеси значение в _secrets/, здесь оставь указатель`);
          break outer; // одна находка на файл, значение не печатаем
        }
      }
    }
  }

  // 6) Целостность kit-owned файлов по манифесту
  const manifest = join(mbDir, "_kit", "manifest.txt");
  if (existsSync(manifest)) {
    for (const line of readDoc(manifest).split(/\r?\n/)) {
      const m = line.trim().match(/^([0-9a-f]{32})\s+\*?(.+)$/);
      if (!m) continue;
      const target = join(root, m[2]);
      if (!existsSync(target)) {
        warnings.push(`KIT-MODIFIED ${m[2]} — файла из _kit/manifest.txt нет на диске — кит неполный или файл удалён`);
        continue;
      }
      const md5 = createHash("md5").update(readFileSync(target)).digest("hex");
      if (md5 !== m[1])
        warnings.push(`KIT-MODIFIED ${m[2]} — md5 не совпадает с _kit/manifest.txt — локальная правка kit-owned файла потеряется при upgrade кита`);
    }
  }

  // 7) Уроки: дубли номеров и «следующий номер» (только если lessons/ уже есть)
  const lessonsDir = join(mbDir, "lessons");
  if (existsSync(lessonsDir)) {
    const readmeFile = join(lessonsDir, "README.md");
    const readme = existsSync(readmeFile) ? readDoc(readmeFile) : "";
    const known = new Set();
    for (const l of readme.split(/\r?\n/)) {
      if (/дубл/i.test(l)) for (const m of l.matchAll(/\d+/g)) known.add(Number(m[0]));
    }
    const nums = new Map(); // num -> [where]
    let max = 0;
    for (const f of listMd(lessonsDir).filter((x) => basename(x) !== "README.md")) {
      const lines = readDoc(f).split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        for (const re of LESSON_NUM_RES) {
          const m = lines[i].match(re);
          if (!m) continue;
          const n = Number(m[1]);
          if (!nums.has(n)) nums.set(n, []);
          nums.get(n).push(`${rel(f)}:${i + 1}`);
          if (n > max) max = n;
          break;
        }
      }
    }
    for (const [n, places] of [...nums].sort((a, b) => a[0] - b[0])) {
      if (places.length > 1 && !known.has(n))
        warnings.push(`LESSON-DUP урок ${n} — ${places.length}× (${places.join(", ")}) и не признан в строке «дубли» lessons/README.md`);
    }
    const nx = readme.match(/следующий номер\D{0,5}(\d+)/i);
    if (nx && Number(nx[1]) <= max)
      warnings.push(`LESSON-NEXT lessons/README.md — «следующий номер: ${nx[1]}» ≤ максимального найденного ${max} — подними счётчик`);
  }

  const byCategory = {};
  for (const p of [...problems, ...warnings]) {
    const cat = p.split(/\s+/)[0];
    byCategory[cat] = (byCategory[cat] ?? 0) + 1;
  }
  return { ok: problems.length === 0, problems, warnings, notes, byCategory };
}

// ---------- CLI ----------
const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  const flagVal = (name, def) => {
    const i = args.indexOf(name);
    if (i === -1 || i + 1 >= args.length) return def;
    const n = Number(args[i + 1]);
    return Number.isFinite(n) ? n : def;
  };
  const BOOL_FLAGS = new Set(["--check", "--json", "--brief"]);
  const positional = args.filter(
    (a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--") && !BOOL_FLAGS.has(args[i - 1]))
  );
  const root = resolve(positional[0] ?? process.cwd());
  const res = runChecks(root, { scratchDays: flagVal("--scratch-days", 7), draftDays: flagVal("--draft-days", 30) });
  const tag = "[memory-project-audit]";
  if (res.fatal) {
    if (args.includes("--json")) console.log(JSON.stringify({ ok: false, fatal: res.fatal }));
    else if (!args.includes("--brief")) console.error(`${tag} ${res.fatal}`);
    process.exit(2);
  }
  if (args.includes("--json")) {
    console.log(JSON.stringify(res, null, 2));
    process.exit(res.ok ? 0 : 1);
  }
  const byCat = (list) => {
    const counts = {};
    for (const p of list) counts[p.split(/\s+/)[0]] = (counts[p.split(/\s+/)[0]] ?? 0) + 1;
    return Object.entries(counts).map(([c, n]) => (n > 1 ? `${c}×${n}` : c)).join(", ");
  };
  if (args.includes("--brief")) {
    // SessionStart-хук: одна строка, тишина = чисто (полный список — pnpm memory:project-audit)
    const parts = [];
    if (!res.ok) parts.push(`${res.problems.length} пробл. (${byCat(res.problems)})`);
    if (res.warnings.length) parts.push(`⚠ ${res.warnings.length} предупр. (${byCat(res.warnings)})`);
    if (parts.length) console.log(`🧠 project-audit: ${parts.join("; ")} → pnpm memory:project-audit / /memory-check`);
    process.exit(res.ok ? 0 : 1);
  }
  console.log(`${tag} root=${root}`);
  for (const n of res.notes) console.log(`${tag} ${n}`);
  if (res.warnings.length) {
    console.log(`${tag} ⚠ предупреждений: ${res.warnings.length} (не блокируют)`);
    for (const w of res.warnings) console.log("  ~ " + w);
  }
  if (res.ok) {
    console.log(`${tag} ✓ проблем не найдено`);
    process.exit(0);
  }
  console.log(`${tag} ✗ найдено проблем: ${res.problems.length} (${byCat(res.problems)})`);
  for (const p of res.problems) console.log("  - " + p);
  process.exit(1);
}
