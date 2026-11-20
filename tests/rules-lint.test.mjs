// Тесты линтера реестра правил: node --test tests/rules-lint.test.mjs
// Фикстуры — временный репозиторий (mkdtemp): эталон чистый, каждый дефект ловится своей категорией.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { lintRules } from "../tools/rules-lint.mjs";

const TODAY = "2026-11-20";
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");

function pfile(id, o = {}) {
  const f = { id, status: "working", rule_status: "active", approval_ref: "TG 100 (01.11)", review_after: "2027-02-20", supersedes: "", superseded_by: "", ...o };
  return `---\ntier: 2\ntopic: rule-${id.toLowerCase()}\n${Object.entries(f).map(([k, v]) => `${k}: ${v}`).join("\n")}\n---\n\n# ${id}\n`;
}

// spec: { P-001: {…поля…}, … }; opts.regIndex / opIndex — список id для индексов (по умолчанию все), layer — доп. байты в CLAUDE.md
function mk(spec, opts = {}) {
  const root = mkdtempSync(join(tmpdir(), "rl-"));
  const w = (p, t) => {
    mkdirSync(dirname(join(root, p)), { recursive: true });
    writeFileSync(join(root, p), t);
  };
  const all = Object.keys(spec);
  for (const [id, o] of Object.entries(spec)) w(`.memory_bank/rules/${opts.fileOf?.[id] || id}.md`, pfile(id, o));
  const rows = (opts.regIndex || all).map((id) => `| [${id}](${id}.md) | тема | ${spec[id]?.rule_status || "active"} | текст | TG 100 |`);
  w(".memory_bank/rules/INDEX.md", `---\ntier: 1\n---\n| id | тема | статус | правило | approval_ref |\n|---|---|---|---|---|\n${rows.join("\n")}\n`);
  w(".claude/rules/00-operating-index.md", `# индекс\n\n${(opts.opIndex || all).map((id) => `${id} · тема · коротко`).join("\n")}\n`);
  w("CLAUDE.md", "# проект\n" + "x".repeat(opts.claudeBytes || 100));
  w(".memory_bank/INDEX.md", "# index\n");
  if (opts.config) w(".memory_bank/rules/lint-config.json", JSON.stringify(opts.config));
  return root;
}
const cats = (r, k = "errors") => r[k].map((x) => x.split(" ")[0]);
const lint = (root, extra = {}) => lintRules(root, { today: TODAY, memoryMd: null, ...extra });

test("эталон чистый", () => {
  const r = lint(mk({ "P-001": {}, "P-002": { rule_status: "trial", review_after: "2026-12-01", approval_ref: "TG 5" } }));
  assert.deepEqual(r.errors, []);
  assert.deepEqual(r.warnings, []);
  assert.equal(r.count, 2);
});

test("дубль id и id не по имени файла", () => {
  const r = lint(mk({ "P-001": {}, "P-002": { id: "P-001" } }));
  assert.ok(r.errors.some((e) => e.startsWith("RULES-ID") && e.includes("не совпадает")));
  assert.ok(r.errors.some((e) => e.startsWith("RULES-ID") && e.includes("дубль")));
});

test("словари rule_status и status", () => {
  const r = lint(mk({ "P-001": { rule_status: "enabled" }, "P-002": { status: "active" } }));
  assert.equal(cats(r).filter((c) => c === "RULES-STATUS").length, 2);
});

test("active без approval_ref; ADR, TG с именем и legacy принимаются", () => {
  const bad = lint(mk({ "P-001": { approval_ref: "" } }));
  assert.ok(bad.errors.some((e) => e.startsWith("RULES-APPROVAL")));
  const ok = lint(mk({ "P-001": { approval_ref: "ADR-0415" }, "P-002": { approval_ref: "TG tamara 842 (16.11)" }, "P-003": { approval_ref: "legacy:CLAUDE.md:3" } }));
  assert.deepEqual(ok.errors, []);
});

test("цикл замен, битая ссылка, несогласованность и superseded без замены", () => {
  const cyc = lint(mk({ "P-001": { rule_status: "superseded", superseded_by: "P-002", supersedes: "P-002" }, "P-002": { rule_status: "superseded", superseded_by: "P-001", supersedes: "P-001" } }));
  assert.ok(cyc.errors.some((e) => e.includes("цикл замен")));
  const dead = lint(mk({ "P-001": { superseded_by: "P-099" } }));
  assert.ok(dead.errors.some((e) => e.includes("несуществующее P-099")));
  const half = lint(mk({ "P-001": { rule_status: "superseded", superseded_by: "P-002" }, "P-002": {} }));
  assert.ok(half.errors.some((e) => e.includes("нет supersedes: P-001")));
  const none = lint(mk({ "P-001": { rule_status: "superseded" } }));
  assert.ok(none.errors.some((e) => e.includes("superseded без superseded_by")));
  const good = lint(mk({ "P-001": { rule_status: "superseded", superseded_by: "P-002" }, "P-002": { supersedes: "P-001" } }));
  assert.deepEqual(good.errors, []);
});

test("истёкший trial и trial без срока; active с истёкшим сроком — предупреждение", () => {
  const r = lint(mk({ "P-001": { rule_status: "trial", review_after: "2026-11-19" }, "P-002": { rule_status: "trial", review_after: "" }, "P-003": { review_after: "2026-01-01" } }));
  assert.equal(cats(r).filter((c) => c === "RULES-TRIAL").length, 2);
  assert.equal(cats(r, "warnings").filter((c) => c === "RULES-TRIAL").length, 1);
  assert.ok(!lint(mk({ "P-001": { rule_status: "trial", review_after: TODAY } })).errors.length, "срок «сегодня» ещё не истёк");
});

test("P нет в одном из индексов, лишняя строка, статус в индексе не тот", () => {
  const a = lint(mk({ "P-001": {}, "P-002": {} }, { regIndex: ["P-001"] }));
  assert.ok(a.errors.some((e) => e.includes("P-002 — нет строки в .memory_bank/rules/INDEX.md")));
  const b = lint(mk({ "P-001": {}, "P-002": {} }, { opIndex: ["P-002"] }));
  assert.ok(b.errors.some((e) => e.includes("P-001 — нет строки в .claude/rules/00-operating-index.md")));
  const c = lint(mk({ "P-001": {} }, { opIndex: ["P-001", "P-077"], regIndex: ["P-001"] }));
  assert.ok(c.errors.some((e) => e.includes("P-077") && e.includes("файла правила нет")));
  const root = mk({ "P-001": { rule_status: "trial", review_after: "2026-12-01" } });
  writeFileSync(join(root, ".memory_bank/rules/INDEX.md"), "| [P-001](P-001.md) | т | active | х | TG 1 |\n");
  assert.ok(lint(root).errors.some((e) => e.includes("статус в rules/INDEX.md")));
});

test("бюджет слоя: error по умолчанию, warn до даты, error после даты; MEMORY.md — предупреждение", () => {
  const big = { claudeBytes: 3000, config: { budget: { limit_kb: 1 } } };
  const err = lint(mk({ "P-001": {} }, big));
  assert.ok(err.errors.some((e) => e.startsWith("RULES-BUDGET")));
  const cfgWarn = { budget: { limit_kb: 1, without_memory: { mode: "warn", error_from: "2026-11-27" } } };
  const warn = lint(mk({ "P-001": {} }, { claudeBytes: 3000, config: cfgWarn }));
  assert.ok(!warn.errors.length && warn.warnings.some((w) => w.startsWith("RULES-BUDGET") && w.includes("2026-11-27")));
  const after = lintRules(mk({ "P-001": {} }, { claudeBytes: 3000, config: cfgWarn }), { today: "2026-11-27", memoryMd: null });
  assert.ok(after.errors.some((e) => e.startsWith("RULES-BUDGET")), "после даты warn → error");
  const mem = lint(mk({ "P-001": {} }, { claudeBytes: 100, config: { budget: { limit_kb: 1 } } }), { memoryMd: 5000 });
  assert.ok(mem.warnings.some((w) => w.includes("MEMORY.md")) && !mem.errors.length);
});

test("правила с paths: в слой не входят", () => {
  const root = mk({ "P-001": {} }, { claudeBytes: 100, config: { budget: { limit_kb: 1 } } });
  writeFileSync(join(root, ".claude/rules/ui.md"), "---\npaths: app/**\n---\n" + "y".repeat(5000));
  assert.deepEqual(lint(root).errors, []);
  writeFileSync(join(root, ".claude/rules/always.md"), "# всегда\n" + "y".repeat(5000));
  assert.ok(lint(root).errors.some((e) => e.startsWith("RULES-BUDGET")));
});

test("реальный реестр репо: ни одной ошибки (кроме ожидаемого бюджета в режиме warn)", () => {
  const r = lintRules(REPO, { today: TODAY, memoryMd: null });
  assert.deepEqual(r.errors, []);
  const cli = spawnSync("node", [join(REPO, "tools/rules-lint.mjs"), "--today", TODAY, REPO], { encoding: "utf8", env: { ...process.env, RULES_LINT_MEMORY_MD: "" } });
  assert.equal(cli.status, 0, cli.stdout + cli.stderr);
});
