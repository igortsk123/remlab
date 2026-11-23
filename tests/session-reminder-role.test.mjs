// Тест: Stop-хук не требует /memory-check у рабочего (REMLAB_ROLE=рабочий; P-037, T-20261123-23 п.4): node --test tests/session-reminder-role.test.mjs
// Временный git-репозиторий: активный план + изменение вне .memory_bank/ + пустой блокнот → без роли хук блокирует, у рабочего молчит.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
const TMP_BASE = process.env.REMLAB_TMP || tmpdir();
const MADE = [];
after(() => {
  for (const d of MADE) rmSync(d, { recursive: true, force: true });
});

function mkRepo() {
  mkdirSync(TMP_BASE, { recursive: true });
  const root = mkdtempSync(join(TMP_BASE, "sr-"));
  MADE.push(root);
  const w = (p, t) => {
    mkdirSync(dirname(join(root, p)), { recursive: true });
    writeFileSync(join(root, p), t);
  };
  w(".memory_bank/plans/p.md", "---\nstatus: in_progress\n---\n# план\n");
  w(".memory_bank/_intake/session-scratch.md", "# блокнот\nSCRATCH START\n");
  w("code.txt", "изменение вне .memory_bank/\n");
  spawnSync("git", ["init", "-q"], { cwd: root });
  return root;
}

function hook(root, env = {}, args = []) {
  const e = { ...process.env, ...env };
  if (!("REMLAB_ROLE" in env)) delete e.REMLAB_ROLE;
  return spawnSync("node", [join(REPO, "tools/session-reminder.mjs"), root, "--block", ...args], { encoding: "utf8", env: e, input: "{}" });
}

test("без роли: пустой блокнот при активном плане и изменениях — блок", () => {
  const r = hook(mkRepo());
  assert.equal(r.status, 0);
  assert.equal(JSON.parse(r.stdout).decision, "block");
});

test("REMLAB_ROLE=рабочий: ни блока, ни напоминания", () => {
  const r = hook(mkRepo(), { REMLAB_ROLE: "рабочий" });
  assert.equal(r.status, 0);
  assert.equal(r.stdout.trim(), "");
});

test("другая роль (директор) — гейт работает как раньше", () => {
  const r = hook(mkRepo(), { REMLAB_ROLE: "директор" });
  assert.equal(JSON.parse(r.stdout).decision, "block");
});
