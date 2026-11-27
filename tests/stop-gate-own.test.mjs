// Тест: Stop-хук — «только свои правки» и «строка стража только у директора и только по его правкам» (T-20261127-175/5):
//   node --test tests/stop-gate-own.test.mjs
// Временный git-репозиторий + стенограмма-заглушка (JSONL с tool_use Edit/Write) + страж-заглушка (скрипт печатает строку).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, openSync, ftruncateSync, closeSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { ownEditedPaths, readOwnEdits, onlyOwn, parseStrazh, strazhVerdict, dropForeignProblems, porcelainPath, defaultStrazhCmd, runStrazh, strazhAnswer, mentions } from "../tools/stop-gate-own.mjs";

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

// ── п.7–9 (T-175 срочно 27.11): длинная стенограмма читается кусками; «не читается» ≠ «правок нет» ──
function mixedTranscript(root, files, { filler = 40, tailNoNewline = false } = {}) {
  // между правками — строки-«шум» разной длины (с кириллицей: многобайтные знаки режутся границами кусков) и строка без tool_use
  const p = join(root, "..", `trl-${Math.random().toString(36).slice(2)}.jsonl`);
  const lines = [];
  files.forEach((f, i) => {
    for (let k = 0; k < filler; k++) lines.push(JSON.stringify({ message: { content: [{ type: "text", text: "шум ".repeat(1 + ((i * 7 + k) % 9)) }] } }));
    lines.push(JSON.stringify({ message: { content: [{ type: "tool_use", name: "Edit", input: { file_path: join(root, f) } }] } }));
  });
  writeFileSync(p, lines.join("\n") + (tailNoNewline ? "" : "\n"));
  MADE.push(p);
  return p;
}

test("п.7 читает кусками: на пределе куска 7 / 64 / 1000 байт и без «\\n» в конце — те же правки, что при большом куске (границы режут строки и кириллицу)", () => {
  const { root } = mk();
  const files = ["mine.txt", "sub/ёж.md", ".memory_bank/rules/P-070.md", "a/б/в.txt"];
  for (const tailNoNewline of [false, true]) {
    const tr = mixedTranscript(root, files, { tailNoNewline });
    const base = readOwnEdits(tr, root);
    assert.deepEqual([...base.own].sort(), [...files].sort());
    for (const chunk of [7, 64, 1000]) {
      const r = readOwnEdits(tr, root, { chunk });
      assert.deepEqual([...r.own].sort(), [...base.own].sort(), `chunk=${chunk} tail=${tailNoNewline}`);
      assert.equal(r.skipped, 0);
      assert.equal(r.bytes, readFileSync(tr).length, "прочитан весь файл");
    }
  }
});

test("п.7 строка длиннее предела пропускается с учётом (skipped), не роняет и не мешает остальным", () => {
  const { root } = mk();
  const p = join(root, "..", `trlong-${Math.random().toString(36).slice(2)}.jsonl`);
  const ok = (f) => JSON.stringify({ message: { content: [{ type: "tool_use", name: "Edit", input: { file_path: join(root, f) } }] } });
  const big = JSON.stringify({ message: { content: [{ type: "text", text: "я".repeat(5000) }] } });
  const bigEdit = JSON.stringify({ message: { content: [{ type: "tool_use", name: "Write", input: { file_path: join(root, "huge.txt"), content: "x".repeat(5000) } }] } });
  writeFileSync(p, [ok("before.txt"), big, bigEdit, ok("after.txt")].join("\n") + "\n" + big); // и последняя строка без «\n» — тоже длинная
  MADE.push(p);
  for (const chunk of [64, 4096, 1 << 20]) {
    const r = readOwnEdits(p, root, { chunk, maxLine: 1000 });
    assert.deepEqual([...r.own].sort(), ["after.txt", "before.txt"], `chunk=${chunk}`);
    assert.equal(r.skipped, 3, `chunk=${chunk}: big, bigEdit и хвост пропущены с учётом`);
  }
});

test("п.7 файл > 512 МБ (предел строки V8): старый readFileSync падает ERR_STRING_TOO_LONG, новое чтение — нет и находит правки до него", () => {
  const { root } = mk();
  const p = join(root, "..", `trbig-${Math.random().toString(36).slice(2)}.jsonl`);
  writeFileSync(p, JSON.stringify({ message: { content: [{ type: "tool_use", name: "Edit", input: { file_path: join(root, "mine.txt") } }] } }) + "\n");
  const fd = openSync(p, "a");
  ftruncateSync(fd, 600 * 1024 * 1024); // 600 МБ нулей (разреженный файл, диск почти не занимает): одна гигантская «строка» без «\n»
  closeSync(fd);
  MADE.push(p);
  assert.throws(() => readFileSync(p, "utf8"), (e) => e.code === "ERR_STRING_TOO_LONG", "контроль: так читал старый код");
  const r = readOwnEdits(p, root);
  assert.deepEqual([...r.own], ["mine.txt"]);
  assert.equal(r.skipped, 1, "гигантский хвост пропущен с учётом");
});

test("п.8 не читается (каталог вместо файла / файла нет / путь не передан) → own=null И причина, не «правок нет»", () => {
  const { root } = mk();
  const dir = join(root, "ката-лог");
  mkdirSync(dir);
  for (const [tr, re] of [[dir, /EISDIR/], [join(root, "нет.jsonl"), /файла стенограммы нет/], [undefined, /не получил путь/]]) {
    const r = readOwnEdits(tr, root);
    assert.equal(r.own, null);
    assert.match(r.why, re);
  }
});

test("п.8 гейт: стенограмма не читается → директору БЛОК «стенограмма не читается: причина» (--strazh при файлах правил, --own-edits при несохранённом); остальным — предупреждение, без блока", () => {
  const dir = (root) => {
    const d = join(root, "ката-лог");
    mkdirSync(d, { recursive: true });
    return d;
  };
  { // --strazh: несохранённый файл правил, стенограмма — каталог
    const { root, cmd } = rulesRepo(GREEN);
    const r = hook(root, dir(root), DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
    const d = JSON.parse(r.stdout);
    assert.equal(d.decision, "block", r.stdout + r.stderr);
    assert.match(d.reason, /стенограмма не читается: EISDIR/);
    assert.ok(d.reason.includes("tools/"), d.reason); // git status сворачивает неотслеживаемый каталог: «tools/» может держать файлы правил
    // не директор / менеджер: без блока, но с предупреждением в stderr
    for (const env of [{}, { REMLAB_ROLE: "менеджер" }]) {
      const o = hook(root, dir(root), env, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
      assert.equal(o.stdout.trim(), "", JSON.stringify(env) + o.stdout);
      assert.match(o.stderr, /стенограмма не читается: EISDIR/);
    }
    // только --strazh: решает ОДНО — есть ли несохранённые файлы правил; `?? tools/` (git сворачивает каталог) — возможный файл правил, блок
    const s = JSON.parse(hook(root, dir(root), DIRECTOR, ["--strazh", "--strazh-cmd", cmd]).stdout);
    assert.match(s.reason, /стенограмма не читается: EISDIR/);
    // файла стенограммы нет — тоже блок у директора
    const m = JSON.parse(hook(root, join(root, "нет.jsonl"), DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]).stdout);
    assert.match(m.reason, /файла стенограммы нет/);
    // путь не передан хуку вовсе
    const n = JSON.parse(hook(root, undefined, DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]).stdout);
    assert.match(n.reason, /не получил путь к стенограмме/);
  }
  { // нечего проверять (всё закоммичено) — не блокируем, как раньше
    const { root, cmd } = rulesRepo(GREEN);
    spawnSync("git", ["add", "-A"], { cwd: root });
    spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], { cwd: root });
    const r = hook(root, dir(root), DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
    assert.equal(r.stdout.trim(), "", r.stdout);
  }
  { // только --own-edits (без --strazh): в дереве есть несохранённое — директору блок
    const { root } = mk();
    const d = JSON.parse(hook(root, dir(root), DIRECTOR, ["--own-edits"]).stdout);
    assert.equal(d.decision, "block");
    assert.match(d.reason, /стенограмма не читается/);
  }
});

test("п.9 хук целиком на длинной стенограмме при малых пределах (STOP_GATE_CHUNK_BYTES=16): свои правки найдены → страж виден, блок «просрочено 2»", () => {
  const { root, cmd } = rulesRepo(RED);
  const tr = mixedTranscript(root, ["tools/scout/rules/rule-registry.json", "mine.txt"], { filler: 60 });
  const r = hook(root, tr, { ...DIRECTOR, STOP_GATE_CHUNK_BYTES: "16", STOP_GATE_MAX_LINE_BYTES: "100000" }, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
  const d = JSON.parse(r.stdout);
  assert.equal(d.decision, "block", r.stdout + r.stderr);
  assert.match(d.reason, /просрочено 2/);
  assert.doesNotMatch(d.reason, /стенограмма не читается/);
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

test("--strazh (в): стража нет (нет команды и tools/ops/rules_guard.py) — гейт директора НЕ молчит: блок «страж не найден: путь»", () => {
  const { root } = rulesRepo(RED);
  const r = hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--own-edits"]);
  const d = JSON.parse(r.stdout);
  assert.equal(d.decision, "block", r.stdout + r.stderr);
  assert.ok(d.reason.includes(`страж не найден: ${join(root, "tools/ops/rules_guard.py")}`), d.reason); // путь назван целиком — видно, где искали
  assert.match(d.reason, /проверить их нечем/);
  // не директор / правок правил нет — по-прежнему молчим (чужие сессии не трогаем)
  for (const env of [{}, { REMLAB_ROLE: "рабочий" }]) noBlock(hook(root, transcript(root, ["tools/scout/rules/rule-registry.json"]), env, ["--strazh", "--own-edits"]), JSON.stringify(env));
  noBlock(hook(root, transcript(root, ["mine.txt"]), { REMLAB_ROLE: "директор" }, ["--strazh", "--own-edits"]));
  // указанная --strazh-cmd команда не нашлась — тоже «не найден», а не «не ответил: код ENOENT»
  const e = JSON.parse(asDirector(root, join(root, "нет-такого-стража.sh")).stdout);
  assert.equal(e.decision, "block");
  assert.ok(e.reason.includes("страж не найден: ") && e.reason.includes("нет-такого-стража.sh"), e.reason);
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

// ── T-175/fix-3-5-7: правки по вердиктам Fable к принятым №3/№5 ─────────────────────────────────────────────────────────────────────────────────────────

const RULES_EDIT = "tools/scout/rules/rule-registry.json";
const DIRECTOR = { REMLAB_ROLE: "директор" };
const DEBT_OK = "правила: просрочено 0, вне реестра: новых 0 (старый долг 167), сообщений владельца без разбора ?, выключателей на удаление 0";
const DEBT_NEW = "правила: просрочено 0, вне реестра: новых 2 (старый долг 167), сообщений владельца без разбора ?, выключателей на удаление 0";

function mkScript(root, name, body) {
  const f = join(root, name);
  writeFileSync(f, body);
  return `sh ${f}`;
}

function asDirector(root, cmd) {
  return hook(root, transcript(root, [RULES_EDIT]), DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]);
}

test("п.2 строка с долгом: «вне реестра: новых N (старый долг M)» — берётся N, долг M гейт не считает", () => {
  assert.equal(parseStrazh(DEBT_OK)["вне реестра"], 0, "долг 167 не должен читаться как «вне реестра 167»");
  assert.equal(parseStrazh(DEBT_NEW)["вне реестра"], 2);
  assert.equal(strazhVerdict(parseStrazh(DEBT_OK)).block, false);
  assert.deepEqual(strazhVerdict(parseStrazh(DEBT_NEW)).bad, ["вне реестра 2"]);
  assert.equal(parseStrazh("правила: просрочено 0, вне реестра 0, без разбора 1, на удаление 0")["вне реестра"], 0, "старый формат строки по-прежнему читается");
});

test("п.2 строка с долгом через хук: долг — не блок, новые — блок", () => {
  const a = rulesRepo(GREEN);
  noBlock(asDirector(a.root, mkStrazh(a.root, DEBT_OK)));
  const b = rulesRepo(GREEN);
  const d = JSON.parse(asDirector(b.root, mkStrazh(b.root, DEBT_NEW)).stdout);
  assert.equal(d.decision, "block");
  assert.match(d.reason, /вне реестра 2/);
});

test("п.1 страж команда по умолчанию — `--check` (ключа `--line` у стража нет)", () => {
  const { root } = rulesRepo(GREEN);
  assert.equal(defaultStrazhCmd(root), null, "стража в дереве нет — null (молчим)");
  mkdirSync(join(root, "tools/ops"), { recursive: true });
  writeFileSync(join(root, "tools/ops/rules_guard.py"), "");
  const cmd = defaultStrazhCmd(root);
  assert.deepEqual(cmd.slice(2), ["--check"]);
  assert.ok(!cmd.includes("--line"));
});

test("п.1 runStrazh/strazhAnswer: код и причина не теряются; строка при коде 1 читается", () => {
  const { root } = rulesRepo(GREEN);
  const sh = (name, body) => mkScript(root, name, body).split(" ");
  const red = runStrazh(sh("red.sh", `echo "${RED}"\nexit 1\n`), root);
  assert.equal(red.code, 1);
  assert.equal(strazhAnswer(red).ok, true, "код 1 со строкой — это «не ноль», а не отказ стража");
  const dead = strazhAnswer(runStrazh(sh("dead.sh", "exit 2\n"), root));
  assert.equal(dead.ok, false);
  assert.match(dead.silent, /страж не ответил: код 2/);
  const junk = strazhAnswer(runStrazh(sh("junk.sh", "echo мусор без чисел\n"), root));
  assert.equal(junk.ok, false);
  assert.match(junk.silent, /страж не ответил: код 0, вывод не разобран/);
  const missing = strazhAnswer(runStrazh(["/нет/такого/файла"], root));
  assert.equal(missing.ok, false);
  assert.match(missing.silent, /страж не найден: \/нет\/такого\/файла/);
  assert.equal(strazhAnswer({ line: "правила: реестр не читается (файла нет или он не JSON), просрочено ?, вне реестра: ? (старый долг ?), сообщений владельца без разбора ?, выключателей на удаление ?", code: 1 }).kind, "registry");
});

test("п.1 страж упал / молчит — гейт директора НЕ молчит: блок «страж не ответил: код N»", () => {
  for (const [body, re] of [
    ["exit 2\n", /страж не ответил: код 2, пустой вывод/],
    ["echo 'Traceback' >&2\nexit 1\n", /страж не ответил: код 1/],
    ["echo мусор\n", /страж не ответил: код 0, вывод не разобран/],
  ]) {
    const { root } = rulesRepo(GREEN);
    const d = JSON.parse(asDirector(root, mkScript(root, "s.sh", body)).stdout);
    assert.equal(d.decision, "block", body);
    assert.match(d.reason, re);
  }
});

test("п.1 страж упал, но роль не директор / правок правил нет — по-прежнему молчим (чужие сессии не трогаем)", () => {
  const { root } = rulesRepo(GREEN);
  const cmd = mkScript(root, "s.sh", "exit 2\n");
  for (const env of [{}, { REMLAB_ROLE: "менеджер" }, { REMLAB_ROLE: "рабочий" }]) noBlock(hook(root, transcript(root, [RULES_EDIT]), env, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]), JSON.stringify(env));
  noBlock(hook(root, transcript(root, ["mine.txt"]), DIRECTOR, ["--strazh", "--strazh-cmd", cmd, "--own-edits"]));
});

// Сквозной: НАСТОЯЩИЙ страж (копия файлов из репозитория) в временном корне; гейт зовёт его командой ПО УМОЛЧАНИЮ (без --strazh-cmd).
// journalEvents — строки журнала сообщений владельца (формат tools/ops/zhurnal_vladeltsa.py); файл лежит ВНЕ корня репо, страж находит его по $OWNER_JOURNAL (jpath в результате).
function realGuardRepo(overdue, journalEvents = null) {
  const m = rulesRepo(GREEN);
  for (const f of ["rules_guard.py", "rule_registry_audit.py", "rule_switch_guard.py", "zhurnal_vladeltsa.py"]) m.w(`tools/ops/${f}`, readFileSync(join(REPO, "tools/ops", f), "utf8"));
  m.jpath = join(m.root, "..", `journal-${Math.random().toString(36).slice(2)}.jsonl`); // нет события — нет файла: страж честно «?»
  MADE.push(m.jpath);
  if (journalEvents) writeFileSync(m.jpath, journalEvents.map((e) => JSON.stringify(e)).join("\n") + "\n");
  m.w("tools/scout/rules/rules-guard.json", readFileSync(join(REPO, "tools/scout/rules/rules-guard.json"), "utf8"));
  const reg = { version: 3, decide_by_max: "2099-01-01", groups: overdue ? { G1: { decide_by: "2020-01-01" } } : {}, rules: overdue ? [{ rule_id: "R-1", state: "trial", group: "G1" }] : [] };
  m.w(RULES_EDIT, JSON.stringify(reg));
  m.w("tools/scout/rules/switch-settings.json", JSON.stringify({ scan: [], skip_files: { "tools/scout/rules/rules-guard.json": "настройки стража, не выключатели" }, settings: {} }));
  m.w("tools/scout/rules/switch-guard-threshold.json", JSON.stringify({ max_uncovered: 0, known: [] }));
  return m;
}

test("п.1 сквозной: настоящий страж не ноль (просрочено 1) → гейт директора блокирует командой по умолчанию", () => {
  const { root, jpath } = realGuardRepo(true);
  const r = hook(root, transcript(root, [RULES_EDIT]), { ...DIRECTOR, OWNER_JOURNAL: jpath }, ["--strazh", "--own-edits"]);
  const d = JSON.parse(r.stdout);
  assert.equal(d.decision, "block", r.stdout + r.stderr);
  assert.match(d.reason, /просрочено 1/);
  assert.doesNotMatch(d.reason, /страж не ответил/, "связка живая: страж ответил строкой, а не упал");
});

test("п.1 сквозной: настоящий страж чистый → гейт не блокирует; строка стража несёт долг", () => {
  const { root, jpath } = realGuardRepo(false);
  noBlock(hook(root, transcript(root, [RULES_EDIT]), { ...DIRECTOR, OWNER_JOURNAL: jpath }, ["--strazh", "--own-edits"]));
  process.env.OWNER_JOURNAL = jpath;
  try {
    const line = runStrazh(defaultStrazhCmd(root), root).line;
    assert.match(line, /^правила: просрочено 0, вне реестра: новых 0 \(старый долг \d+\), сообщений владельца без разбора \?, /, line); // журнала нет — «?» (не ноль и не «чисто»)
  } finally {
    delete process.env.OWNER_JOURNAL;
  }
});

test("п.6 сквозной: в журнале (формат журнала) сообщение ждёт > 2 ч → строка настоящего стража показывает его, гейт директора видит и блокирует по «без разбора»", () => {
  const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();
  const ev = [
    { t: "msg", bot: "tg-remlab", id: 3612, ts: ago(3), chat: "95903801", user: "igor", tip: "text", nachalo: "Регламент — жду" },
    { t: "msg", bot: "tg-remlab", id: 3613, ts: ago(0.2), chat: "95903801", user: "igor", tip: "text", nachalo: "свежее" },
    { t: "msg", bot: "tg-remlab", id: 3614, ts: ago(5), chat: "95903801", user: "igor", tip: "text", nachalo: "закрытое" },
    { t: "zakryt", bot: "tg-remlab", id: 3614, ts: ago(4), adres: "задача T-20261127-175", kto: "директор" },
  ];
  const { root, jpath } = realGuardRepo(false, ev);
  const env = { ...DIRECTOR, OWNER_JOURNAL: jpath };
  process.env.OWNER_JOURNAL = jpath;
  try {
    const line = runStrazh(defaultStrazhCmd(root), root).line;
    assert.match(line, /сообщений владельца без разбора 2, /, line); // 3612 и 3613 ждут, 3614 закрыто; «?» больше нет
    assert.equal(parseStrazh(line)["без разбора"], 2);
  } finally {
    delete process.env.OWNER_JOURNAL;
  }
  const strict = ["--strazh", "--own-edits", "--strazh-fields", "просрочено,вне реестра,без разбора"];
  const d = JSON.parse(hook(root, transcript(root, [RULES_EDIT]), env, strict).stdout);
  assert.equal(d.decision, "block");
  assert.match(d.reason, /без разбора 2/);
  // по умолчанию без разбора гейт не держит (держит срок и реестр — их директор закрывает правкой файла правил); число он при этом ВИДИТ в строке
  noBlock(hook(root, transcript(root, [RULES_EDIT]), env, ["--strazh", "--own-edits"]));
  // все закрыты — гейт и со строгими полями молчит
  const closed = realGuardRepo(false, ev.slice(0, 2).concat([{ t: "zakryt", bot: "tg-remlab", id: 3612, ts: ago(1), adres: "P-069", kto: "директор" }, { t: "zakryt", bot: "tg-remlab", id: 3613, ts: ago(1), adres: "P-069", kto: "директор" }]));
  noBlock(hook(closed.root, transcript(closed.root, [RULES_EDIT]), { ...DIRECTOR, OWNER_JOURNAL: closed.jpath }, strict));
});

test("п.(б) сквозной: реестр не читается (нет файла / битый) → настоящий страж говорит «реестр не читается», гейт директора блокирует с причиной, а не «вне реестра N»", () => {
  for (const [how, body] of [["битый JSON", "{не json"], ["нет файла", null]]) {
    const { root, jpath } = realGuardRepo(false);
    if (body === null) rmSync(join(root, RULES_EDIT));
    else writeFileSync(join(root, RULES_EDIT), body);
    process.env.OWNER_JOURNAL = jpath;
    try {
      const line = runStrazh(defaultStrazhCmd(root), root).line;
      assert.match(line, /^правила: реестр не читается \(/, `${how}: ${line}`);
      assert.doesNotMatch(line, /новых \d/, how);
    } finally {
      delete process.env.OWNER_JOURNAL;
    }
    // правку файла правил директор «сделал» (стенограмма) — файла реестра нет, но он в стенограмме и в git status как удалённый/изменённый
    const r = hook(root, transcript(root, [RULES_EDIT]), { ...DIRECTOR, OWNER_JOURNAL: jpath }, ["--strazh", "--own-edits"]);
    const d = JSON.parse(r.stdout || "{}");
    assert.equal(d.decision, "block", `${how}: ${r.stdout}${r.stderr}`);
    assert.match(d.reason, /реестр правил не читается/, how);
    assert.doesNotMatch(d.reason, /вне реестра \d|страж не ответил|страж не найден/, `${how}: причина — реестр, не страж и не счётчик`);
    assert.match(d.reason, /rule-registry\.json/, how);
  }
});

test("п.3 находка аудита от 27.11 дословно: «core/access-and-integrations.md — 3,4 КБ» про чужой .memory_bank/core/... отсеивается", () => {
  const finding = "`core/access-and-integrations.md` — 3,4 КБ";
  const dirty = [".memory_bank/core/access-and-integrations.md", "mine.txt"];
  assert.deepEqual(dropForeignProblems([finding], dirty, new Set(["mine.txt"])), [], "чужая находка должна уйти");
  assert.deepEqual(dropForeignProblems([finding], dirty, new Set([".memory_bank/core/access-and-integrations.md"])), [finding], "свой файл банка — находка держит");
  assert.deepEqual(dropForeignProblems(["общая: бюджет INDEX"], dirty, new Set(["mine.txt"])), ["общая: бюджет INDEX"]);
  assert.deepEqual(dropForeignProblems([".memory_bank/core/access-and-integrations.md — 3,4 КБ"], dirty, new Set(["mine.txt"])), [], "с приставкой — как раньше");
  assert.deepEqual(dropForeignProblems(["`core/other.md` — 9 КБ"], dirty, new Set(["mine.txt"])), ["`core/other.md` — 9 КБ"], "про не-грязный файл — остаётся");
});

test("п.3 mentions: путь с приставкой и без; кусок чужого пути за совпадение не считается", () => {
  assert.equal(mentions("`core/a.md` — 1 КБ", ".memory_bank/core/a.md"), true);
  assert.equal(mentions("core/a.md: нет метаданных", ".memory_bank/core/a.md"), true);
  assert.equal(mentions(".memory_bank/core/a.md — 1 КБ", ".memory_bank/core/a.md"), true);
  assert.equal(mentions("архив/core/a.md — 1 КБ", ".memory_bank/core/a.md"), false);
  assert.equal(mentions("core/b.md", ".memory_bank/core/a.md"), false);
  assert.equal(mentions("mine.txt: плохо", "mine.txt"), true);
});
