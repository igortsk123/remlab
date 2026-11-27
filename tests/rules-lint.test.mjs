// Тесты линтера реестра правил: node --test tests/rules-lint.test.mjs
// Фикстуры — временный репозиторий (mkdtemp): эталон чистый, каждый дефект ловится своей категорией.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { lintRules, addViolation, isPureManual, counterProblem } from "../tools/rules-lint.mjs";

const TODAY = "2026-11-20";
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
// временное — как у правила remlab_tmp: REMLAB_TMP (если задан), иначе системная; каждая фикстура убирается в after()
const TMP_BASE = process.env.REMLAB_TMP || tmpdir();
const MADE = [];
after(() => {
  for (const d of MADE) rmSync(d, { recursive: true, force: true });
});

function pfile(id, o = {}) {
  const f = { id, status: "working", rule_status: "active", approval_ref: "TG 100 (01.11)", review_after: "2027-02-20", supersedes: "", superseded_by: "", ...o };
  return `---\ntier: 2\ntopic: rule-${id.toLowerCase()}\n${Object.entries(f).map(([k, v]) => `${k}: ${v}`).join("\n")}\n---\n\n# ${id}\n`;
}

// spec: { P-001: {…поля…}, … }; opts.regIndex / opIndex — список id для индексов (по умолчанию все), layer — доп. байты в CLAUDE.md
function mk(spec, opts = {}) {
  mkdirSync(TMP_BASE, { recursive: true });
  const root = mkdtempSync(join(TMP_BASE, "rl-"));
  MADE.push(root);
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
  // свод 23.11: снятое правило в индексе «всегда в контексте» не обязательно (там только действующие), но если есть — предупреждение
  assert.ok(good.warnings.some((w) => w.includes("снятое правило в 00-operating-index.md")));
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

// ---- RULES-STALE (T-20261123-23 п.3): директор-машина как в шапке плана; минуты trigger = заголовок
const STALE_CFG = { stale: { machines: ["pakardev", "algor", "router", "common"] } };
function withPlan(root, director) {
  writeFileSync(join(root, ".memory_bank/plan-zadach.md"), `<!--\nДиректор: ${director} с 23.11 06:37 (владелец TG 1811)\n-->\n# План\n`);
}
function withBody(root, id, title, body, trigger = "обход", extra = {}) {
  const f = join(root, `.memory_bank/rules/${id}.md`);
  const t = pfile(id, { trigger, ...extra }).replace(`# ${id}\n`, `# ${id} · ${title}\n\n${body}\n`);
  writeFileSync(f, t);
}
const stale = (r) => r.warnings.filter((w) => w.startsWith("RULES-STALE"));

test("RULES-STALE: директор названа не та машина → предупреждение; нужная и оговорённые строки — нет", () => {
  const root = mk({ "P-001": {} }, { config: STALE_CFG });
  withPlan(root, "algor");
  withBody(root, "P-001", "роли", "Директор — ведущий на pakardev, остальные работают.");
  const r = lint(root);
  assert.deepEqual(r.errors, []);
  assert.equal(stale(r).length, 1);
  assert.match(stale(r)[0], /P-001\.md:\d+ — директор «pakardev», а в шапке plan-zadach\.md «Директор: algor»/);
  withBody(root, "P-001", "роли", "Директор — ведущий на algor.\npakardev — директор (устарело с 23.11).\nДо 23.11 директор — pakardev, подхват — router.");
  assert.deepEqual(stale(lint(root)), []);
  withBody(root, "P-001", "роли", "pakardev — директор.");
  assert.equal(stale(lint(root)).length, 1, "форма «машина — директор» тоже ловится");
});

test("RULES-STALE: снятые правила, нет шапки плана или списка машин — тишина", () => {
  const root = mk({ "P-001": { rule_status: "superseded", superseded_by: "P-002" }, "P-002": { supersedes: "P-001" } }, { config: STALE_CFG });
  withPlan(root, "algor");
  withBody(root, "P-001", "роли", "Директор — ведущий на pakardev.", "обход", { rule_status: "superseded", superseded_by: "P-002" });
  assert.deepEqual(stale(lint(root)), []);
  const r2 = mk({ "P-001": {} });
  withPlan(r2, "algor");
  withBody(r2, "P-001", "роли", "Директор — ведущий на pakardev.");
  assert.deepEqual(stale(lint(r2)), [], "без stale.machines в конфиге — нет списка машин, проверка молчит");
  const r3 = mk({ "P-001": {} }, { config: STALE_CFG });
  withBody(r3, "P-001", "роли", "Директор — ведущий на pakardev.");
  assert.deepEqual(stale(lint(r3)), [], "нет plan-zadach.md — нечего сверять");
});

test("RULES-STALE: минуты в trigger не совпали с заголовком (тип P-020)", () => {
  const root = mk({ "P-001": {} });
  withBody(root, "P-001", "Обход: днём каждые 5 мин, ночью каждые 30 мин", "текст", "обход директора (днём 15 мин, ночью 30)");
  const s = stale(lint(root));
  assert.equal(s.length, 1);
  assert.match(s[0], /минуты \{15,30\}, в заголовке \{5,30\}/);
  withBody(root, "P-001", "Обход: днём каждые 5 мин, ночью каждые 30 мин", "текст", "обход директора (днём 5 мин, ночью 30)");
  assert.deepEqual(stale(lint(root)), []);
  withBody(root, "P-001", "Обход директора", "текст", "обход (днём 5 мин, ночью 30)");
  assert.deepEqual(stale(lint(root)), [], "в заголовке минут нет — сверять не с чем");
});

// ---- T-20261127-175/6: предел числа действующих, счётчик у «вручную», журнал нарушений ----
const ids6 = (n, o = {}) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`P-${String(i + 1).padStart(3, "0")}`, { enforcement: "code", ...o }]));
const writeViol = (root, lines) => writeFileSync(join(root, ".memory_bank", "rules", "violations.jsonl"), lines.join("\n") + "\n");

test("RULES-LIMIT: 20 действующих — можно, 21 — ошибка; снятые не считаются, trial считаются", () => {
  assert.deepEqual(cats(lint(mk(ids6(20)))), []);
  const r21 = lint(mk(ids6(21)));
  assert.deepEqual(cats(r21), ["RULES-LIMIT"]);
  assert.match(r21.errors[0], /21 > 20/);
  const gone = { ...ids6(20), "P-021": { rule_status: "superseded", superseded_by: "P-001", enforcement: "code" } };
  gone["P-001"] = { enforcement: "code", supersedes: "P-021" };
  assert.deepEqual(cats(lint(mk(gone))), [], "superseded не считается");
  const withTrial = { ...ids6(20), "P-021": { rule_status: "trial", review_after: "2026-12-30", approval_ref: "TG 5", enforcement: "code" } };
  assert.deepEqual(cats(lint(mk(withTrial))), ["RULES-LIMIT"], "trial считается");
});

test("RULES-LIMIT: предел задаётся в конфиге (limits.max_active)", () => {
  const r = lint(mk(ids6(3), { config: { limits: { max_active: 2 } } }));
  assert.deepEqual(cats(r), ["RULES-LIMIT"]);
});

test("isPureManual: только manual — «вручную»; смешанное с кодом/скриптом — нет", () => {
  assert.equal(isPureManual("manual"), true);
  assert.equal(isPureManual("manual;manual"), true);
  assert.equal(isPureManual("manual;script:~/.local/bin/plan-procent"), false);
  assert.equal(isPureManual("code"), false);
  assert.equal(isPureManual(""), false);
});

test("counterProblem: пусто и заглушки — причина; имя счётчика — ок; несуществующий путь — причина, существующий — ок", () => {
  const root = mk({ "P-001": {} });
  assert.ok(counterProblem("", root));
  assert.ok(counterProblem("—", root));
  assert.ok(counterProblem("manual", root));
  assert.equal(counterProblem("rules_guard: просрочено", root), null);
  assert.equal(counterProblem("violations.jsonl", root), null);
  assert.match(counterProblem("tools/ops/нет_такого.py: строка", root), /нет_такого\.py/);
  assert.equal(counterProblem("CLAUDE.md: раздел «Критично»", root), null);
});

test("RULES-MANUAL: «вручную» без счётчика — предупреждение до error_from, ошибка после; со счётчиком и смешанные — чисто", () => {
  const spec = { "P-001": { enforcement: "manual" }, "P-002": { enforcement: "manual", counter: "rules_guard: просрочено" }, "P-003": { enforcement: "manual;script:x.sh" } };
  const cfg = { manual: { mode: "warn", error_from: "2026-12-04" } };
  const before = lint(mk(spec, { config: cfg }));
  assert.deepEqual(cats(before), []);
  assert.deepEqual(cats(before, "warnings"), ["RULES-MANUAL"]);
  assert.match(before.warnings[0], /P-001/);
  assert.match(before.warnings[0], /с 2026-12-04/);
  const after2 = lint(mk(spec, { config: cfg }), { today: "2026-12-04" });
  assert.deepEqual(cats(after2), ["RULES-MANUAL"]);
  assert.deepEqual(cats(lint(mk(spec, { config: { manual: { mode: "error" } } }))), ["RULES-MANUAL"], "mode error — сразу ошибка");
  const bad = lint(mk({ "P-001": { enforcement: "manual", counter: "tools/ops/нет_такого.py" } }, { config: { manual: { mode: "error" } } }));
  assert.match(bad.errors[0], /нет_такого\.py/);
});

test("RULES-MANUAL: снятое правило «вручную» без счётчика не проверяется", () => {
  const spec = { "P-001": { enforcement: "manual", rule_status: "superseded", superseded_by: "P-002" }, "P-002": { enforcement: "code", supersedes: "P-001" } };
  const r = lint(mk(spec, { config: { manual: { mode: "error" } } }));
  assert.deepEqual(r.errors, []);
});

test("RULES-VIOLATIONS: «вручную» нарушено дважды — ошибка; один раз — нет; автоматизированному правилу число не мешает", () => {
  const spec = { "P-001": { enforcement: "manual", counter: "violations.jsonl" }, "P-002": { enforcement: "code" }, "P-003": { enforcement: "manual", counter: "violations.jsonl" } };
  const root = mk(spec);
  writeViol(root, [
    JSON.stringify({ id: "P-001", date: "2026-11-20", what: "а" }),
    JSON.stringify({ id: "P-002", date: "2026-11-20", what: "б" }),
    JSON.stringify({ id: "P-002", date: "2026-11-21", what: "в" }),
    JSON.stringify({ id: "P-003", date: "2026-11-21", what: "г" }),
  ]);
  assert.deepEqual(cats(lint(root)), [], "P-001: 1, P-002 автоматизировано: 2, P-003: 1");
  writeViol(root, [JSON.stringify({ id: "P-001", date: "2026-11-20", what: "а" }), JSON.stringify({ id: "P-001", date: "2026-11-22", what: "б" })]);
  const r = lint(root);
  assert.deepEqual(cats(r), ["RULES-VIOLATIONS"]);
  assert.match(r.errors[0], /P-001/);
  assert.match(r.errors[0], /2 раз/);
});

test("RULES-VIOLATIONS: нарушение несуществующего правила и битая строка журнала — ошибки", () => {
  const root = mk({ "P-001": { enforcement: "code" } });
  writeViol(root, [JSON.stringify({ id: "P-099", date: "2026-11-20", what: "x" }), "не json"]);
  const r = lint(root);
  assert.equal(r.errors.filter((e) => e.startsWith("RULES-VIOLATIONS")).length, 2);
  assert.ok(r.errors.some((e) => e.includes("P-099")));
  assert.ok(r.errors.some((e) => e.includes("violations.jsonl:2")));
});

test("addViolation: пишет строку журнала, считает число; снятому/несуществующему/пустому отказ", () => {
  const root = mk({ "P-001": { enforcement: "manual", counter: "violations.jsonl" }, "P-002": { enforcement: "code" }, "P-003": { rule_status: "superseded", superseded_by: "P-002", enforcement: "code" } });
  const a = addViolation(root, "P-001", "не запустил страж", "2026-11-27");
  assert.equal(a.count, 1);
  assert.equal(a.manual, true);
  assert.equal(a.over, false);
  const b = addViolation(root, "P-001", "снова", "2026-11-28");
  assert.equal(b.count, 2);
  assert.equal(b.over, true);
  const lines = readFileSync(join(root, ".memory_bank", "rules", "violations.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((x) => [x.id, x.date, x.what]), [["P-001", "2026-11-27", "не запустил страж"], ["P-001", "2026-11-28", "снова"]]);
  assert.equal(addViolation(root, "P-002", "код", "2026-11-27").manual, false);
  assert.throws(() => addViolation(root, "P-003", "x"), /действующему/);
  assert.throws(() => addViolation(root, "P-099", "x"), /нет в/);
  assert.throws(() => addViolation(root, "P-001", "  "), /описание/);
});

test("CLI --add-violation: запись, предупреждение о пределе, код 2 на неизвестном правиле; --check после этого красный", () => {
  const root = mk({ "P-001": { enforcement: "manual", counter: "violations.jsonl" } });
  const run = (...a) => spawnSync("node", [join(REPO, "tools/rules-lint.mjs"), ...a], { encoding: "utf8", env: { ...process.env, RULES_LINT_MEMORY_MD: "" } });
  const one = run("--add-violation", "P-001", "первое", "--today", TODAY, root);
  assert.equal(one.status, 0, one.stdout + one.stderr);
  assert.match(one.stdout, /нарушений 1 из 2/);
  const two = run("--add-violation", "P-001", "второе", "--today", TODAY, root);
  assert.match(two.stdout, /предел достигнут/);
  const chk = run("--check", "--today", TODAY, root);
  assert.equal(chk.status, 1, chk.stdout);
  assert.match(chk.stdout, /RULES-VIOLATIONS/);
  const bad = run("--add-violation", "P-077", "x", root);
  assert.equal(bad.status, 2);
});

test("реальный реестр репо: ни одной ошибки (кроме ожидаемого бюджета в режиме warn)", () => {
  const r = lintRules(REPO, { today: TODAY, memoryMd: null });
  assert.deepEqual(r.errors, []);
  const cli = spawnSync("node", [join(REPO, "tools/rules-lint.mjs"), "--today", TODAY, REPO], { encoding: "utf8", env: { ...process.env, RULES_LINT_MEMORY_MD: "" } });
  assert.equal(cli.status, 0, cli.stdout + cli.stderr);
});
