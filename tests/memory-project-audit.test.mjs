// Тесты проектного аудита памяти: node --test tests/memory-project-audit.test.mjs
// Каждая категория — временный банк (mkdtemp) с минимальными файлами: позитив (находка есть)
// и негатив (чисто). Плюс прогон по реальному репо — не должен падать исключением.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { runChecks } from "../tools/memory-project-audit.mjs";

const TODAY = "2026-09-05";
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");

// files: { "относительный/путь/от/root": "текст" }; .memory_bank/ создаётся всегда
function mkBank(files = {}) {
  const root = mkdtempSync(join(tmpdir(), "mpa-"));
  mkdirSync(join(root, ".memory_bank"), { recursive: true });
  for (const [p, text] of Object.entries(files)) {
    const full = join(root, p);
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, text);
  }
  return root;
}

function run(files, opts = {}) {
  const root = mkBank(files);
  try {
    return runChecks(root, { today: TODAY, ...opts });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

const cats = (list) => list.map((x) => x.split(/\s+/)[0]);
const has = (list, cat) => cats(list).includes(cat);
const md5 = (s) => createHash("md5").update(s).digest("hex");

const fm = (obj) => "---\n" + Object.entries(obj).map(([k, v]) => `${k}: ${v}`).join("\n") + "\n---\n";
const adr = (n, title = "Название") => `## ADR-${String(n).padStart(4, "0")} — 2026-09-01 — ${title}\nТело.\n`;
const idxLine = (n) => `- **ADR-${String(n).padStart(4, "0")}** · 2026-09-01 · тема · Название\n`;
const M = ".memory_bank/";

test("нет .memory_bank → fatal, без исключения", () => {
  const root = mkdtempSync(join(tmpdir(), "mpa-empty-"));
  try {
    const res = runChecks(root, { today: TODAY });
    assert.equal(res.ok, false);
    assert.match(res.fatal, /\.memory_bank/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("пустой банк — чисто", () => {
  const res = run({});
  assert.equal(res.ok, true);
  assert.deepEqual(res.problems, []);
  assert.deepEqual(res.warnings, []);
});

// ---------- ADR ----------
test("ADR: том + индекс согласованы — чисто", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: adr(0) + adr(1) + adr(2),
    [M + "decisions.md"]: fm({ topic: "decisions" }) + idxLine(0) + idxLine(1) + idxLine(2),
  });
  assert.deepEqual(res.problems, []);
  assert.deepEqual(res.warnings, []);
});

test("ADR-DUP: один номер дважды (в т.ч. в разных томах)", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: adr(1) + adr(1),
    [M + "decisions/adr-0051-0100.md"]: adr(51) + adr(51),
    [M + "decisions.md"]: idxLine(1) + idxLine(51),
  });
  const dups = res.problems.filter((p) => p.startsWith("ADR-DUP"));
  assert.equal(dups.length, 2);
  assert.match(dups[0], /ADR-0001/);
  assert.match(dups[1], /ADR-0051/);
});

test("ADR-RANGE: номер вне диапазона тома; 0000 допустим только в первом томе", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: adr(0) + adr(60),
    [M + "decisions/adr-0051-0100.md"]: adr(0, "второй ноль") + adr(51),
    [M + "decisions.md"]: idxLine(0) + idxLine(60) + idxLine(51),
  });
  const ranges = res.problems.filter((p) => p.startsWith("ADR-RANGE"));
  assert.equal(ranges.length, 2);
  assert.ok(ranges.some((p) => /adr-0001-0050\.md:\d+ — ADR-0060/.test(p)));
  assert.ok(ranges.some((p) => /adr-0051-0100\.md:\d+ — ADR-0000/.test(p)));
});

test("ADR-NOT-INDEXED / ADR-INDEX-ORPHAN: расхождение тома и индекса", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: adr(1) + adr(2),
    [M + "decisions.md"]: idxLine(1) + idxLine(3),
  });
  const ni = res.problems.filter((p) => p.startsWith("ADR-NOT-INDEXED"));
  const or = res.problems.filter((p) => p.startsWith("ADR-INDEX-ORPHAN"));
  assert.equal(ni.length, 1);
  assert.match(ni[0], /ADR-0002/);
  assert.equal(or.length, 1);
  assert.match(or[0], /ADR-0003/);
});

test("ADR-IN-INDEX: полный текст дописали в индекс", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: adr(1),
    [M + "decisions.md"]: idxLine(1) + "\n" + adr(1),
  });
  assert.ok(has(res.problems, "ADR-IN-INDEX"));
});

test("ADR-FORMAT (warning): заголовок не по формату, exit не меняет", () => {
  const res = run({
    [M + "decisions/adr-0001-0050.md"]: "## ADR-0001: Стек проекта\nТело.\n" + adr(2),
    [M + "decisions.md"]: idxLine(1) + idxLine(2),
  });
  assert.equal(res.ok, true);
  assert.ok(has(res.warnings, "ADR-FORMAT"));
  assert.equal(res.warnings.length, 1);
});

test("ADR: без decisions/ — проверки пропущены (note), без падения", () => {
  const res = run({ [M + "decisions.md"]: idxLine(1) });
  assert.equal(res.ok, true);
  assert.ok(res.notes.some((n) => /ADR/.test(n)));
});

// ---------- планы ----------
const plan = (extra) => fm({ slug: "x", title: "План", status: "draft", updated: TODAY, ...extra }) + "\n## Цель\n";

test("планы: валидные статусы, README и _template игнорируются — чисто", () => {
  const res = run({
    [M + "plans/README.md"]: "# реестр\n",
    [M + "plans/_template.md"]: fm({ status: "draft", updated: "YYYY-MM-DD" }),
    [M + "plans/a.md"]: plan({ status: "in_progress" }),
    [M + "plans/b.md"]: plan({ status: "partial", pause_reason: "ждём владельца" }),
    [M + "plans/c.md"]: plan({ status: "cancelled" }),
    [M + "plans/d.md"]: plan({ status: "draft", updated: "2026-01-01", review_after: "2026-12-01" }),
  });
  assert.deepEqual(res.problems, []);
  assert.deepEqual(res.warnings, []);
});

test("PLAN-STATUS: статус вне словаря и отсутствующий", () => {
  const res = run({
    [M + "plans/a.md"]: plan({ status: "active" }),
    [M + "plans/b.md"]: fm({ title: "без статуса" }),
  });
  const st = res.problems.filter((p) => p.startsWith("PLAN-STATUS"));
  assert.equal(st.length, 2);
  assert.match(st[0], /plans\/a\.md — status 'active'/);
  assert.match(st[1], /plans\/b\.md — status '—'/);
});

test("PLAN-DRAFT-STALE: старый draft без review_after; свежий и с review_after — нет; порог настраивается", () => {
  const files = {
    [M + "plans/old.md"]: plan({ updated: "2026-07-01" }),
    [M + "plans/fresh.md"]: plan({ updated: "2026-08-20" }),
    [M + "plans/reviewed.md"]: plan({ updated: "2026-07-01", review_after: "2026-10-01" }),
    [M + "plans/review-passed.md"]: plan({ updated: "2026-07-01", review_after: "2026-08-01" }),
    [M + "plans/nodate.md"]: fm({ title: "x", status: "draft" }),
  };
  const res = run(files);
  const stale = res.problems.filter((p) => p.startsWith("PLAN-DRAFT-STALE"));
  assert.deepEqual(
    stale.map((p) => p.split(" ")[1]).sort(),
    ["plans/old.md", "plans/review-passed.md"]
  );
  const wide = run(files, { draftDays: 365 });
  assert.equal(wide.problems.filter((p) => p.startsWith("PLAN-DRAFT-STALE")).length, 0);
});

test("PLAN-PARTIAL-NO-REASON: partial без pause_reason", () => {
  const res = run({
    [M + "plans/a.md"]: plan({ status: "partial" }),
    [M + "plans/b.md"]: plan({ status: "partial", pause_reason: "заморозка владельца" }),
  });
  const r = res.problems.filter((p) => p.startsWith("PLAN-PARTIAL-NO-REASON"));
  assert.equal(r.length, 1);
  assert.match(r[0], /plans\/a\.md/);
});

test("PLAN-NO-TITLE (warning): нет title", () => {
  const res = run({ [M + "plans/a.md"]: fm({ status: "draft", updated: TODAY }) });
  assert.equal(res.ok, true);
  assert.ok(has(res.warnings, "PLAN-NO-TITLE"));
});

// ---------- блокнот ----------
const scratch = (entries) =>
  "# Session scratch\n\n> Как писать — 2026-01-01 не запись.\n\n<!-- SCRATCH START — метка -->\n" + entries.join("");

test("SCRATCH-STALE: запись старше порога после метки; до метки не считается", () => {
  const res = run({
    [M + "_intake/session-scratch.md"]: scratch(["- 2026-08-20 — старое — куда\n", "- 2026-09-04 19:42 UTC — свежее\n"]),
  });
  const s = res.problems.filter((p) => p.startsWith("SCRATCH-STALE"));
  assert.equal(s.length, 1);
  assert.match(s[0], /session-scratch\.md:6 — записей старше 7 д: 1 \(самая старая 2026-08-20, 16 д\)/);
});

test("SCRATCH-STALE: свежий блокнот чисто; порог --scratch-days", () => {
  const files = { [M + "_intake/session-scratch.md"]: scratch(["- 2026-09-01 — недавнее\n", "  продолжение строки\n"]) };
  assert.equal(run(files).ok, true);
  assert.ok(has(run(files, { scratchDays: 2 }).problems, "SCRATCH-STALE"));
});

test("SCRATCH-STALE: без метки проверяется весь файл (note)", () => {
  const res = run({ [M + "_intake/session-scratch.md"]: "# без метки\n- 2026-01-01 — древнее\n" });
  assert.ok(has(res.problems, "SCRATCH-STALE"));
  assert.ok(res.notes.some((n) => /SCRATCH START/.test(n)));
});

// ---------- canonical → _intake ----------
const canon = (body, extra = {}) =>
  fm({ tier: 1, topic: "t", source_of_truth: "canonical", source: "_intake/raw.md", ...extra }) + "\n# Док\n" + body;

test("CANON-INTAKE-REF: canonical ссылается на _intake/ в теле", () => {
  const res = run({ [M + "core/a.md"]: canon("см. `_intake/codex-answer.md` и ещё _intake/x.md\n") });
  const r = res.warnings.filter((p) => p.startsWith("CANON-INTAKE-REF"));
  assert.equal(r.length, 1);
  assert.match(r[0], /core\/a\.md:\d+ — canonical ссылается на _intake\/ \(1 стр\.\)/);
});

test("CANON-INTAKE-REF: session-scratch, provenance во frontmatter, не-canonical, plans/ и archive/ — чисто", () => {
  const res = run({
    [M + "core/a.md"]: canon("блокнот — `_intake/session-scratch.md`\n"),
    [M + "core/b.md"]: fm({ topic: "b", source_of_truth: "derived" }) + "\n_intake/raw.md\n",
    [M + "plans/p.md"]: fm({ status: "draft", title: "p", updated: TODAY, source_of_truth: "canonical" }) + "\n_intake/raw.md\n",
    [M + "archive/old.md"]: canon("_intake/raw.md\n"),
    [M + "_intake/z.md"]: canon("_intake/raw.md\n"),
  });
  assert.deepEqual(res.problems, []);
});

// ---------- секреты ----------
test("SECRET-FILE: паттерны в .txt/.json/.md вне _secrets/ (включая _intake/); .pem/.env — по факту наличия", () => {
  const res = run({
    [M + "_intake/dump.txt"]: "token: sk-" + "a".repeat(24) + "\n",
    [M + "archive/cfg.json"]: '{"aws":"AKIA' + "B".repeat(16) + '"}\n',
    [M + "core/x.md"]: fm({ topic: "x" }) + "-----BEGIN RSA PRIVATE KEY-----\n",
    [M + "guides/gh.md"]: "ghp_" + "c".repeat(36) + "\n",
    [M + "domain/slack.md"]: "xoxb-123\n",
    [M + "_intake/id.pem"]: "whatever\n",
    [M + "_intake/.env.local"]: "X=1\n",
  });
  const s = res.problems.filter((p) => p.startsWith("SECRET-FILE"));
  assert.equal(s.length, 7);
  assert.ok(s.some((p) => /_intake\/dump\.txt:1 — похоже на секрет \(sk-…\)/.test(p)));
  assert.ok(s.some((p) => /archive\/cfg\.json:1/.test(p)));
  assert.ok(s.some((p) => /core\/x\.md:4 .*private key/.test(p))); // 3 строки frontmatter + 1
  assert.ok(s.some((p) => /_intake\/id\.pem — файл \.pem/.test(p)));
  assert.ok(s.some((p) => /_intake\/\.env\.local — файл \.env\*/.test(p)));
  // значение секрета в тексте находки не печатается
  assert.ok(!s.some((p) => p.includes("a".repeat(24))));
});

test("SECRET-FILE: _secrets/ не сканируется; .log и обычный текст — чисто", () => {
  const res = run({
    [M + "_secrets/ACCESS.md"]: "sk-" + "a".repeat(24) + "\n",
    [M + "_secrets/key.pem"]: "-----BEGIN PRIVATE KEY-----\n",
    [M + "_intake/run.log"]: "AKIA" + "B".repeat(16) + "\n",
    [M + "core/y.md"]: fm({ topic: "y" }) + "ключ лежит в _secrets/ACCESS.md; паттерн sk-short\n",
  });
  assert.deepEqual(res.problems, []);
});

// ---------- kit manifest ----------
test("KIT-MODIFIED (warning): md5 сходится — чисто; изменён / отсутствует — предупреждение", () => {
  const ok = run({
    "tools/kit.mjs": "console.log(1)\n",
    [M + "_kit/manifest.txt"]: md5("console.log(1)\n") + " tools/kit.mjs\n",
  });
  assert.deepEqual(ok.warnings, []);
  const bad = run({
    "tools/kit.mjs": "console.log(2)\n",
    [M + "_kit/manifest.txt"]: md5("console.log(1)\n") + " tools/kit.mjs\n" + md5("x") + " tools/gone.mjs\n# коммент\n",
  });
  assert.equal(bad.ok, true);
  const k = bad.warnings.filter((w) => w.startsWith("KIT-MODIFIED"));
  assert.equal(k.length, 2);
  assert.match(k[0], /tools\/kit\.mjs — md5 не совпадает/);
  assert.match(k[1], /tools\/gone\.mjs — файла .* нет на диске/);
});

// ---------- уроки ----------
const lessonsReadme = (dups, next) => `# Уроки\n\nДубли (признаны, не перенумеровывать): ${dups}\n\nСледующий номер: ${next}\n`;

test("LESSON-*: без lessons/ — молчит; согласованные уроки — чисто", () => {
  assert.deepEqual(run({}).warnings, []);
  const res = run({
    [M + "lessons/README.md"]: lessonsReadme("10/29", 400),
    [M + "lessons/a.md"]: "**10.** урок\n- 11 [ADR] урок\n12. [тема] урок\n",
    [M + "lessons/b.md"]: "**10.** дубль признан\n**399.** последний\n",
  });
  assert.deepEqual(res.warnings, []);
});

test("LESSON-DUP / LESSON-NEXT (warning): непризнанный дубль и отставший счётчик", () => {
  const res = run({
    [M + "lessons/README.md"]: lessonsReadme("10", 300),
    [M + "lessons/a.md"]: "**10.** x\n**57.** y\n",
    [M + "lessons/b.md"]: "**10.** x2\n- 57 [ADR-1] y2\n**305.** z\n",
  });
  assert.equal(res.ok, true);
  const d = res.warnings.filter((w) => w.startsWith("LESSON-DUP"));
  assert.equal(d.length, 1);
  assert.match(d[0], /урок 57 — 2× \(lessons\/a\.md:2, lessons\/b\.md:2\)/);
  const n = res.warnings.filter((w) => w.startsWith("LESSON-NEXT"));
  assert.equal(n.length, 1);
  assert.match(n[0], /300.*305/);
});

// ---------- сводка и реальный репо ----------
test("byCategory считает и problems, и warnings", () => {
  const res = run({
    [M + "plans/a.md"]: fm({ status: "weird" }),
  });
  assert.equal(res.byCategory["PLAN-STATUS"], 1);
  assert.equal(res.byCategory["PLAN-NO-TITLE"], 1);
});

test("реальный репо: прогон не падает исключением и возвращает структуру", () => {
  const res = runChecks(REPO);
  assert.equal(typeof res.ok, "boolean");
  assert.ok(Array.isArray(res.problems));
  assert.ok(Array.isArray(res.warnings));
  assert.ok(Array.isArray(res.notes));
});
