// Тесты инвентаря доступов: node --test tests/access-inventory.test.mjs
// Всё на временных файлах с ФИКТИВНЫМИ значениями; настоящий ACCESS.md не открывается.
// Проверяем: имена из ACCESS.md выводятся отдельным блоком, ключ «только в ACCESS.md» не выглядит как «нет ключа»,
// значение (целиком, начало, длина) нигде не печатается.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "tools", "access-inventory.mjs");
const FAKE = "zq9Xk-FAKEVALUE-7731"; // 20 символов
const FAKE_ENV = "qq7Rm-FAKEENVVAL-4410";

function sandbox({ access, registry = "# реестр\nrunpod — GPU-аренда\n", env = {} } = {}) {
  const home = mkdtempSync(join(tmpdir(), "ai-"));
  const reg = join(home, "registry.md");
  writeFileSync(reg, registry);
  let secrets = join(home, "нет-такого", "ACCESS.md");
  if (access !== undefined) {
    secrets = join(home, "ACCESS.md");
    writeFileSync(secrets, access);
  }
  for (const [rel, text] of Object.entries(env)) {
    const f = join(home, rel);
    mkdirSync(dirname(f), { recursive: true });
    writeFileSync(f, text);
  }
  return { home, reg, secrets };
}

function run(sb, args = []) {
  return execFileSync("node", [SCRIPT, ...args], {
    cwd: sb.home,
    encoding: "utf8",
    env: { PATH: process.env.PATH, HOME: sb.home, ACCESS_INVENTORY_SECRETS: sb.secrets, ACCESS_INVENTORY_REGISTRY: sb.reg },
  });
}

test("ключ только в ACCESS.md: имя в блоке, «нет ключа говорить нельзя», значение не печатается", () => {
  const sb = sandbox({ access: `# доступы\nRUNPOD_API_KEY=${FAKE}\n- export OTHER_TOKEN=\`${FAKE}\`\nпросто текст\n` });
  const out = run(sb);
  assert.match(out, /есть в ACCESS\.md.*: 2/);
  assert.match(out, /RUNPOD_API_KEY\s+в реестре: да · в \.env на диске: нет/);
  assert.match(out, /OTHER_TOKEN\s+в реестре: НЕТ/);
  assert.match(out, /ключ ЕСТЬ, лежит только в ACCESS\.md: RUNPOD_API_KEY, OTHER_TOKEN/);
  assert.match(out, /«нет ключа» говорить нельзя/);
  for (const leak of [FAKE, "zq9X", "FAKEVALUE", "(20)", "7731"]) assert.ok(!out.includes(leak), `утечка значения: ${leak}`);
});

test("пустое значение и заглушка — не ключ; строки не по шаблону ИМЯ= игнорируются", () => {
  const sb = sandbox({ access: "EMPTY_KEY=\nHOLDER_TOKEN=<вставить>\nDOTS_SECRET=sk-...\nlower_case=abc12345\nREAL_API_KEY=abcdefgh\n" });
  const out = run(sb);
  assert.match(out, /есть в ACCESS\.md.*: 1/);
  assert.match(out, /REAL_API_KEY/);
  for (const bad of ["EMPTY_KEY", "HOLDER_TOKEN", "DOTS_SECRET", "lower_case"]) assert.ok(!out.includes(bad), bad);
});

test("имя есть и в .env на диске: «в .env на диске: да», блок «только в ACCESS.md» не показывает его", () => {
  const sb = sandbox({
    access: `FAKE_API_KEY=${FAKE}\nRUNPOD_API_KEY=${FAKE}\n`,
    env: { ".config/proj/.env": `FAKE_API_KEY=${FAKE_ENV}\n` },
  });
  const out = run(sb);
  assert.match(out, /FAKE_API_KEY\s+в реестре: НЕТ · в \.env на диске: да/);
  assert.match(out, /лежит только в ACCESS\.md: RUNPOD_API_KEY —/);
  assert.ok(!/только в ACCESS\.md: [^\n]*FAKE_API_KEY/.test(out));
  assert.ok(!out.includes(FAKE) && !out.includes("FAKEENVVAL"), "значения ключей не печатаются");
});

test("ACCESS.md не найден: понятное сообщение, не падение и не «ключей нет»", () => {
  const sb = sandbox({});
  const out = run(sb);
  assert.match(out, /есть в ACCESS\.md.*: 0/);
  assert.match(out, /ACCESS\.md не найден .* НЕ значит «ключей нет»/);
});

test("--json: строки ACCESS.md — только имя и признаки, без значения", () => {
  const sb = sandbox({ access: `RUNPOD_API_KEY=${FAKE}\n` });
  const raw = run(sb, ["--json"]);
  const rows = JSON.parse(raw);
  const r = rows.find((x) => x.source === "ACCESS.md");
  assert.deepEqual(Object.keys(r).sort(), ["inRegistry", "name", "onDisk", "source"]);
  assert.equal(r.name, "RUNPOD_API_KEY");
  assert.equal(r.onDisk, false);
  assert.ok(!raw.includes("zq9X") && !raw.includes("FAKEVALUE"));
});
