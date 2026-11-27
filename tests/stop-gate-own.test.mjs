// Тест: Stop-хук — «только свои правки» и «строка стража только у директора и только по его правкам» (T-20261127-175/5):
//   node --test tests/stop-gate-own.test.mjs
// Временный git-репозиторий + стенограмма-заглушка (JSONL с tool_use Edit/Write) + страж-заглушка (скрипт печатает строку).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { ownEditedPaths, onlyOwn, parseStrazh, strazhVerdict, dropForeignProblems, porcelainPath } from "../tools/stop-gate-own.mjs";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
const TMP_BASE = process.env.REMLAB_TMP || tmpdir();
const MADE = [];
after(() => {
  for (const d of MADE) rmSync(d, { recursive: true, force: true });
});

function mk() {
  mkdirSync(TMP_BASE, { recursive: true });
  const root = mkdtempSync(join(TMP_BASE, "sg-"));
  MADE.push(root);
  const w = (p, t) => {
    mkdirSync(dirname(join(root, p)), { recursive: true });
    writeFileSync(join(root, p), t);
  };
  w(".memory_bank/plans/p.md", "---\nstatus: in_progress\n---\n# план\n");
  w(".memory_bank/_intake/session-scratch.md", "# блокнот\nSCRATCH START\n");
  w("mine.txt", "моя правка\n");
  w("foreign.txt", "чужая правка\n");
  spawnSync("git", ["init", "-q"], { cwd: root });
  return { root, w };
}

function transcript(root, files) {
  const p = join(root, "..", `tr-${Math.random().toString(36).slice(2)}.jsonl`);
  const lines = files.map((f) => JSON.stringify({ message: { content: [{ type: "tool_use", name: "Edit", input: { file_path: join(root, f) } }] } }));
  lines.push(JSON.stringify({ message: { content: [{ type: "text", text: "готово" }] } }));
  writeFileSync(p, lines.join("\n") + "\n");
  MADE.push(p);
  return p;
}

function hook(root, tr, env = {}, args = []) {
  const e = { ...process.env, ...env };
  if (!("REMLAB_ROLE" in env)) delete e.REMLAB_ROLE;
  const input = JSON.stringify(tr ? { transcript_path: tr } : {});
  return spawnSync("node", [join(REPO, "tools/session-reminder.mjs"), root, "--block", ...args], { encoding: "utf8", env: e, input });
}

test("ownEditedPaths: пути Edit/Write относительно корня, чужие каталоги и не-правки не считаются", () => {
  const { root } = mk();
  const tr = transcript(root, ["mine.txt", "sub/a.md"]);
  const own = ownEditedPaths(tr, root);
  assert.deepEqual([...own].sort(), ["mine.txt", "sub/a.md"]);
  assert.equal(ownEditedPaths(join(root, "нет.jsonl"), root), null);
  assert.equal(ownEditedPaths(undefined, root), null);
});

test("onlyOwn: каталог ?? dir/ — своё, если внутри свой файл; переименование — по новому пути", () => {
  const own = new Set(["dir/x.md", "new.txt"]);
  assert.deepEqual(onlyOwn(["?? dir/", "?? other/", "R  old.txt -> new.txt", " M foreign.txt"], own), ["?? dir/", "R  old.txt -> new.txt"]);
  assert.deepEqual(onlyOwn([" M a"], null), []);
  assert.equal(porcelainPath('?? "a b.txt"'), "a b.txt");
});

test("без --own-edits: как раньше — чужая правка блокирует (обратная совместимость)", () => {
  const { root } = mk();
  const r = hook(root, transcript(root, []));
  assert.equal(JSON.parse(r.stdout).decision, "block");
});

test("--own-edits: сессия ничего не правила (все правки чужие) — ложной блокировки нет (0)", () => {
  const { root } = mk();
  const r = hook(root, transcript(root, []), {}, ["--own-edits"]);
  assert.equal(r.status, 0);
  assert.equal(r.stdout.trim(), "");
});

test("--own-edits: стенограммы нет — «не знаю» ≠ блок", () => {
  const { root } = mk();
  const r = hook(root, null, {}, ["--own-edits"]);
  assert.equal(r.stdout.trim(), "");
});

test("--own-edits: сессия правила свой файл + блокнот пуст — блок, как у обычного гейта", () => {
  const { root } = mk();
  const r = hook(root, transcript(root, ["mine.txt"]), {}, ["--own-edits"]);
  assert.equal(JSON.parse(r.stdout).decision, "block");
});

test("--own-edits: у рабочего по-прежнему молчит", () => {
  const { root } = mk();
  const r = hook(root, transcript(root, ["mine.txt"]), { REMLAB_ROLE: "рабочий" }, ["--own-edits"]);
  assert.equal(r.stdout.trim(), "");
});

test("parseStrazh / strazhVerdict: строка стража → числа; блок по просрочено и вне реестра", () => {
  const p = parseStrazh("правила: просрочено 2, вне реестра 0, сообщений владельца без разбора 5, выключателей на удаление 7");
  assert.deepEqual(p, { "просрочено": 2, "вне реестра": 0, "без разбора": 5, "на удаление": 7 });
  assert.equal(strazhVerdict(p).block, true);
  assert.deepEqual(strazhVerdict(p).bad, ["просрочено 2"]);
  assert.equal(strazhVerdict(parseStrazh("правила: просрочено 0, вне реестра 0, без разбора 3, на удаление 9")).block, false);
  assert.equal(strazhVerdict(parseStrazh("правила: просрочено 0, вне реестра 0, без разбора 3, на удаление 9"), ["без разбора"]).block, true);
  assert.equal(parseStrazh("мусор"), null);
  assert.equal(strazhVerdict(null).block, false);
});

test("dropForeignProblems: находка только про чужой грязный файл отбрасывается, про свой и общая — остаются", () => {
  const dirty = ["foreign.txt", "mine.txt"];
  const own = new Set(["mine.txt"]);
  const left = dropForeignProblems(["foreign.txt: нет метаданных", "mine.txt: битая ссылка", "общая: бюджет INDEX", "foreign.txt и mine.txt: дубль"], dirty, own);
  assert.deepEqual(left, ["mine.txt: битая ссылка", "общая: бюджет INDEX", "foreign.txt и mine.txt: дубль"]);
});

const noBlock = (r, m) => assert.ok(!r.stdout.includes('"decision"'), m || r.stdout); // мягкое напоминание пользователю допустимо, решения block — нет

function mkStrazh(root, line) {
  const f = join(root, "strazh.sh");
  writeFileSync(f, `#!/bin/sh\necho "${line}"\n`);
  return `sh ${f}`;
}

const RED = "правила: просрочено 2, вне реестра 1, сообщений владельца без разбора 0, выключателей на удаление 3";
const GREEN = "правила: просрочено 0, вне реестра 0, сообщений владельца без разбора 4, выключателей на удаление 3";

function rulesRepo(line) {
  const m = mk();
  m.w("tools/scout/rules/rule-registry.json", "{}\n");
  m.w(".memory_bank/_intake/session-scratch.md", "# блокнот\nSCRATCH START\n- 2026-11-27 запись\n"); // блокнот НЕ пуст — память не блокирует, виден только страж
  return { ...m, cmd: mkStrazh(m.root, line) };
}

test("--strazh: директор правил файл правил, страж красный — блок со строкой стража", () => {
  const { root, cmd } = rulesRepo(RED);
  const r = hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
  const d = JSON.parse(r.stdout);
  assert.equal(d.decision, "block");
  assert.match(d.reason, /просрочено 2/);
  assert.match(d.reason, /вне реестра 1/);
});

test("--strazh: страж зелёный — не блокирует", () => {
  const { root, cmd } = rulesRepo(GREEN);
  const r = hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
  noBlock(r);
});

test("--strazh: директор НЕ правил файлы правил (красный страж — от чужих правок) — не блокирует", () => {
  const { root, cmd } = rulesRepo(RED);
  const r = hook(root, transcript(root, ["mine.txt"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
  noBlock(r);
});

test("--strazh: роль не директор (менеджер/без роли/рабочий) — страж не проверяется, ложных блокировок чужих сессий нет", () => {
  const { root, cmd } = rulesRepo(RED);
  const tr = transcript(root, ["tools/scout/rules/rule-registry.json"]);
  for (const env of [{}, { REMLAB_ROLE: "менеджер" }, { REMLAB_ROLE: "рабочий" }]) {
    const r = hook(root, tr, env, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
    noBlock(r, JSON.stringify(env));
  }
});

test("--strazh: страж не влит (нет команды и tools/ops/rules_guard.py) — молчим", () => {
  const { root } = rulesRepo(RED);
  const r = hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--own-edits"]);
  noBlock(r);
});

test("--strazh: правки правил уже закоммичены — страж не проверяется", () => {
  const { root, cmd } = rulesRepo(RED);
  spawnSync("git", ["add", "-A"], { cwd: root });
  spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], { cwd: root });
  const r = hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
  assert.equal(r.stdout.trim(), "");
});

test("--strazh: цикл-защита stop_hook_active — не блокирует повторно", () => {
  const { root, cmd } = rulesRepo(RED);
  const tr = transcript(root, ["tools/scout/rules/rule-registry.json"]);
  const e = { ...process.env, REMLAB_ROLE: "директор" };
  const r = spawnSync("node", [join(REPO, "tools/session-reminder.mjs"), root, "--block", "--strazh", "--strazh-cmd", cmd], { encoding: "utf8", env: e, input: JSON.stringify({ transcript_path: tr, stop_hook_active: true }) });
  assert.equal(r.stdout.trim(), "");
});
