#!/usr/bin/env node
// memory-impact — какие доки памяти описывают код, изменённый в диапазоне коммитов (кит v1.11; план remlab
// mem-freshness-01, гейт при приёмке работы исполнителя). Только чтение: ничего не пишет и не правит.
//
//   node tools/memory-impact.mjs --base <ref> --head <ref> [--root <dir>] [--json] [--strict]
//
// Diff — `git diff -z --name-status --no-renames <base>...<head>` (изменения ветки head от общего предка; пути с
// пробелами и любыми символами — безопасно). Файлы кода → доки, где они упомянуты в inline-коде, — то же
// отображение, что у хука `tools/code-touch-hint.mjs` (`docsFor`), но доки и уникальность голых имён берутся из
// РЕВИЗИИ head (`git ls-tree` / `git cat-file --batch`), а не с диска — проверяется ветка как она есть.
// Статус дока:
//   обновлён          — сам док изменён в том же diff;
//   сверен без правок — в diff добавлена строка `changelog/verify-log.tsv` с этим доком (сверка была, правка не нужна);
//   в очередь сверки  — ни того ни другого: описание могло устареть.
// Вывод: таблица «док | файлы | статус» + строка о файлах, которых память не описывает. Пустой diff — пусто.
// «Не описан» не доказывает «не влияет»: ссылки — только точные файловые якоря, папки не считаются.
// Exit: 0 (предупреждение); с --strict — 1, если есть «в очередь сверки»; 2 — ошибка запуска.
import { spawnSync } from "node:child_process";
import { resolve, basename } from "node:path";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { docsFor, isCodePath, isDescribingDoc } from "./code-touch-hint.mjs";

const VLOG = ".memory_bank/changelog/verify-log.tsv";
const MAX_BUF = 512 * 1024 * 1024;

function git(root, args, input) {
  const r = spawnSync("git", ["-C", root, ...args], { input, maxBuffer: MAX_BUF, stdio: [input ? "pipe" : "ignore", "pipe", "pipe"] });
  if (r.error || r.status !== 0) throw new Error(`git ${args.join(" ")}: ${(r.stderr || "").toString().trim() || r.error}`);
  return r.stdout; // Buffer
}
const z = (buf) => buf.toString("utf8").split("\0").filter(Boolean);

/** Тексты файлов ревизии одним `git cat-file --batch` → {path: text}. */
function readBlobs(root, rev, paths) {
  if (!paths.length) return {};
  const out = git(root, ["cat-file", "--batch"], paths.map((p) => `${rev}:${p}`).join("\n") + "\n");
  const res = {};
  let pos = 0;
  for (const p of paths) {
    const nl = out.indexOf(10, pos);
    const head = out.subarray(pos, nl).toString("utf8");
    pos = nl + 1;
    const m = head.match(/^\S+ blob (\d+)$/);
    if (!m) continue; // missing / не blob
    const size = Number(m[1]);
    res[p] = out.subarray(pos, pos + size).toString("utf8");
    pos += size + 1;
  }
  return res;
}

/** Ядро (экспорт для тестов): → {rows:[{doc, files:[{path, deleted}], status, line}], undescribed:[path], codeFiles, empty} */
export function memoryImpact(root, base, head) {
  const range = `${base}...${head}`;
  const st = z(git(root, ["diff", "-z", "--name-status", "--no-renames", range]));
  const changed = new Map(); // path → status letter
  for (let i = 0; i + 1 < st.length; i += 2) changed.set(st[i + 1], st[i][0]);
  if (!changed.size) return { rows: [], undescribed: [], codeFiles: 0, empty: true };

  const tree = z(git(root, ["ls-tree", "-r", "-z", "--name-only", head]));
  const docs = tree.filter(isDescribingDoc);
  const cache = { byBase: {}, text: readBlobs(root, head, docs) };
  for (const f of tree) cache.byBase[basename(f)] = (cache.byBase[basename(f)] || 0) + 1;
  const read = (doc) => {
    if (doc in cache.text) return cache.text[doc];
    throw new Error("нет в ревизии");
  };

  // Сверки, записанные в этом же diff (новые строки verify-log.tsv): док → сверен без правок.
  const verified = new Set();
  if (changed.has(VLOG)) {
    const d = git(root, ["diff", "--no-color", "-U0", range, "--", VLOG]).toString("utf8");
    for (const l of d.split("\n"))
      if (l.startsWith("+") && !l.startsWith("+++")) {
        const doc = (l.slice(1).split("\t")[1] || "").trim().replace(/^\.memory_bank\//, "");
        if (doc) verified.add(`.memory_bank/${doc}`);
      }
  }

  const byDoc = new Map();
  const undescribed = [];
  let codeFiles = 0;
  for (const [path, s] of changed) {
    if (!isCodePath(path)) continue;
    codeFiles++;
    const hits = docsFor(root, path, docs, cache, read);
    if (!hits.length) undescribed.push(path);
    for (const h of hits) {
      if (!byDoc.has(h.doc)) byDoc.set(h.doc, { doc: h.doc, files: [], line: h.line });
      byDoc.get(h.doc).files.push({ path, deleted: s === "D" });
    }
  }
  const rank = { "в очередь сверки": 0, "сверен без правок": 1, "обновлён": 2 };
  const rows = [...byDoc.values()]
    .map((r) => ({ ...r, status: changed.has(r.doc) ? "обновлён" : verified.has(r.doc) ? "сверен без правок" : "в очередь сверки" }))
    .sort((a, b) => rank[a.status] - rank[b.status] || a.doc.localeCompare(b.doc));
  return { rows, undescribed, codeFiles, empty: false };
}

const cell = (s) => s.replace(/\|/g, "\\|");
function render(res) {
  if (res.empty || !res.codeFiles) return "";
  const n = (s) => res.rows.filter((r) => r.status === s).length;
  const described = res.codeFiles - res.undescribed.length;
  const out = [
    `Память о коде диапазона: доков ${res.rows.length} (обновлено ${n("обновлён")}, сверено без правок ${n("сверен без правок")}, ` +
      `в очередь сверки ${n("в очередь сверки")}) · файлов кода ${res.codeFiles}, описаны памятью ${described}`,
  ];
  if (res.rows.length) {
    out.push("", "| док | файлы | статус |", "|---|---|---|");
    for (const r of res.rows)
      out.push(`| ${cell(r.doc)} | ${r.files.map((f) => `\`${cell(f.path)}\`${f.deleted ? " (удалён)" : ""}`).join(", ")} | ${r.status} |`);
  }
  if (res.undescribed.length) {
    const shown = res.undescribed.slice(0, 10).map((p) => `\`${p}\``).join(", ");
    out.push("", `Не описаны памятью (${res.undescribed.length}): ${shown}${res.undescribed.length > 10 ? " …" : ""}`);
  }
  return out.join("\n");
}

function main() {
  const args = process.argv.slice(2);
  const arg = (k) => {
    const i = args.indexOf(k);
    return i >= 0 ? args[i + 1] : undefined;
  };
  const base = arg("--base");
  const head = arg("--head") || "HEAD";
  const root = resolve(arg("--root") || process.cwd());
  if (!base || base.startsWith("--") || head.startsWith("--")) {
    console.error("использование: node tools/memory-impact.mjs --base <ref> --head <ref> [--root <dir>] [--json] [--strict]");
    process.exit(2);
  }
  let res;
  try {
    res = memoryImpact(root, base, head);
  } catch (e) {
    console.error(`memory-impact: ${e.message}`);
    process.exit(2);
  }
  if (args.includes("--json")) console.log(JSON.stringify(res, null, 1));
  else {
    const text = render(res);
    if (text) console.log(text);
  }
  process.exit(args.includes("--strict") && res.rows.some((r) => r.status === "в очередь сверки") ? 1 : 0);
}

const isMain = () => {
  try {
    return !!process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
};
if (isMain()) main();
