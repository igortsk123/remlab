#!/usr/bin/env node
// intake-index.mjs — генерирует .memory_bank/_intake/README.md: что лежит во входной папке,
// когда появилось, где сведено в банк (по упоминаниям basename), статус. Zero-dep, Node >= 18.
// Запуск: node tools/intake-index.mjs [projectRoot]   (пишет README.md; --check — только печать)
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, basename, relative } from "node:path";

const ROOT = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : process.cwd();
const CHECK = process.argv.includes("--check");
const MB = join(ROOT, ".memory_bank");
const INTAKE = join(MB, "_intake");
const git = (a) => execFileSync("git", ["-C", ROOT, ...a], { encoding: "utf8" }).trim();

const tracked = git(["ls-files", ".memory_bank/_intake"]).split("\n").filter(Boolean);
// корпус, в котором ищем упоминания (весь банк без _intake + docs + правила)
const corpus = [];
function walk(d) {
  for (const n of readdirSync(d)) {
    const p = join(d, n);
    if (n === "_intake" || n === "node_modules" || n === ".git") continue;
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else if (/\.(md|mjs|py|yml|json)$/.test(n)) corpus.push(p);
  }
}
walk(MB);
for (const extra of ["docs", ".claude", "tools"]) { try { walk(join(ROOT, extra)); } catch {} }
const corpusText = corpus.map((p) => { try { return `\n@@${relative(ROOT, p)}\n` + readFileSync(p, "utf8"); } catch { return ""; } }).join("");

function firstHeading(p) {
  try {
    const t = readFileSync(p, "utf8").split("\n").slice(0, 40);
    const h = t.find((l) => /^#\s+/.test(l)) || t.find((l) => l.trim() && !l.startsWith("---") && !/^\w+:\s/.test(l));
    return (h || "").replace(/^#+\s*/, "").slice(0, 90);
  } catch { return ""; }
}
function firstDate(rel) {
  try { return git(["log", "--diff-filter=A", "--format=%cs", "--", rel]).split("\n").filter(Boolean).pop() || ""; } catch { return ""; }
}
const rows = tracked.map((rel) => {
  const p = join(ROOT, rel);
  const base = basename(rel);
  const short = rel.replace(".memory_bank/_intake/", "");
  const kit = /^(brief\/|history\/|session-scratch\.md$)/.test(short);
  const owner = /^(owner\/|owner-|dialog-|blind-|self-analysis-|zones-practice-|catalog-extract-)/.test(short) || /\.(json|txt)$/.test(short);
  const stem = base.replace(/\.(answer|prompt|stdout)?\.?(md|txt|json)$/, "");
  const refs = (corpusText.match(new RegExp(stem.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;
  const where = [...new Set([...corpusText.matchAll(/\n@@([^\n]+)\n[\s\S]*?(?=\n@@|$)/g)]
    .filter((m) => m[0].includes(stem)).map((m) => m[1]))].slice(0, 3).join(", ");
  const status = kit ? "кит (вход)" : owner ? "сырьё владельца" : refs > 0 ? "сведён/цитируется" : "не сведён";
  return { short, date: firstDate(rel), head: firstHeading(p), refs, where, status };
});
rows.sort((a, b) => (a.status > b.status ? 1 : a.status < b.status ? -1 : a.date.localeCompare(b.date)));

const counts = {};
for (const r of rows) counts[r.status] = (counts[r.status] || 0) + 1;
const today = new Date().toISOString().slice(0, 10);
const out = `# _intake — входная папка (сырьё, не хранилище)

> Здесь живёт только то, что ещё предстоит свести в канон банка: \`brief/\` и \`history/\` (вход для
> \`/memory-init\`), \`session-scratch.md\` (блокнот захвата на ходу), \`codex/\` (вопросы и ответы
> советника Codex — провенанс для ADR/планов), \`owner/\` (сырьё владельца: разметки, вердикты,
> выгрузки). **Правила:** (1) логи прогонов — НЕ в банк (складывать в \`~/scout-logs/\`);
> (2) basename intake-файлов не переименовывать — на них ссылаются ADR и планы по имени;
> (3) сведённое — остаётся как провенанс, но факты живут в \`core/\`, \`domain/\`, \`decisions/\`;
> (4) папка вне аудита кита (\`tools/memory-audit.mjs\`) — «чисто» её не проверяет; этот индекс
> регенерирует \`node tools/intake-index.mjs\` (проектный аудит проверяет, что canonical-доки
> не ссылаются сюда как на истину).

Обновлено: ${today}. Файлов в git: ${rows.length} — ${Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}.
«Сведён/цитируется» = имя файла встречается в банке/docs/правилах (где — в колонке).

| Файл | В git с | О чём | Ссылок | Где цитируется | Статус |
|------|---------|-------|-------:|----------------|--------|
${rows.map((r) => `| \`${r.short}\` | ${r.date} | ${r.head.replace(/\|/g, "\\|")} | ${r.refs} | ${r.where.replace(/\|/g, "\\|")} | ${r.status} |`).join("\n")}
`;
if (CHECK) { console.log(out.split("\n").slice(0, 20).join("\n")); console.log(`… всего строк: ${rows.length}`); }
else { writeFileSync(join(INTAKE, "README.md"), out); console.log(`[intake-index] ${rows.length} файлов → _intake/README.md (${Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(", ")})`); }
