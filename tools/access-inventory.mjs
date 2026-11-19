#!/usr/bin/env node
/**
 * Инвентаризация доступов: что за ключи реально лежат на машине и все ли они в реестре.
 *
 * Зачем: ключ fal.ai лежал в .env СОСЕДНЕГО проекта, реестр про него не знал, и агент спросил
 * владельца «есть ли у нас доступ» вместо того, чтобы посмотреть. Правило простое: прежде чем
 * сказать «у нас нет доступа», прогнать этот скрипт.
 *
 *   node tools/access-inventory.mjs            # что найдено и чего нет в реестре
 *   node tools/access-inventory.mjs --json     # машиночитаемо
 *
 * Значения ключей НЕ печатаются — только имена, файл и первые 4 символа (у ключей из .env).
 * Из `_secrets/ACCESS.md` читаются ТОЛЬКО ИМЕНА переменных (`ИМЯ=значение`): значение не сохраняется и не
 * печатается — ни начала, ни длины (у T-20261119-95: ключ RunPod лежал только там, и «ключа нет» говорили зря).
 * Переменные для тестов: ACCESS_INVENTORY_SECRETS / ACCESS_INVENTORY_REGISTRY (пути к файлам), HOME (где искать .env*).
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOME = homedir();
// где на этой машине исторически живут ключи: проекты владельца + системные места
const SEARCH_DIRS = [
  join(HOME, "igor"),
  join(HOME, "mltest"),
  join(HOME, ".config"),
];
const ENV_NAMES = [".env", ".env.local", ".env.production", "env", "secrets.env"];
const KEY_RE = /^([A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|DSN|WEBHOOK|API)[A-Z0-9_]*)\s*=\s*(.+)$/;
const REGISTRY_REL = ".memory_bank/core/access-and-integrations.md";
const SECRETS_REL = ".memory_bank/_secrets/ACCESS.md";
const SELF_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// корень ОСНОВНОЙ копии репо: в git-worktree `_secrets/` (вне git) лежит только там
function mainRoot() {
  try {
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
      { cwd: SELF_ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    return common ? dirname(common) : null;
  } catch {
    return null;
  }
}

// первый существующий путь из кандидатов (явный, от cwd, от самого скрипта, от основной копии репо)
function locate(rel, envVar) {
  if (process.env[envVar]) {                    // путь задан явно (тесты) — другие места не смотрим
    const only = process.env[envVar];
    return { path: existsSync(only) ? only : null, tried: [only] };
  }
  const roots = [process.cwd(), SELF_ROOT, mainRoot()].filter(Boolean);
  const cands = roots.map((r) => join(r, rel));
  return { path: cands.find((c) => existsSync(c)) ?? null, tried: cands };
}
const REGISTRY = locate(REGISTRY_REL, "ACCESS_INVENTORY_REGISTRY").path ?? REGISTRY_REL;
const secretsLoc = locate(SECRETS_REL, "ACCESS_INVENTORY_SECRETS");
const SECRETS = secretsLoc.path ?? SECRETS_REL;

// ИМЕНА переменных из ACCESS.md по шаблону `ИМЯ=значение`; значение читается только ради признака «не пусто / не заглушка»
// и сразу выбрасывается — в результат попадают имя и этот признак, больше ничего.
function secretNames(text) {
  const byName = new Map();
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*(?:[-*]\s+)?(?:export\s+)?`?([A-Z][A-Z0-9_]{2,})`?\s*=(.*)$/);
    if (!m) continue;
    const v = m[2].trim().replace(/^[`"']+|[`"']+$/g, "");
    const present = v.length > 0 && !v.startsWith("<") && !v.includes("...");
    byName.set(m[1], (byName.get(m[1]) ?? false) || present);
  }
  return [...byName].map(([name, present]) => ({ name, present }));
}

function walk(dir, depth = 0, out = []) {
  if (depth > 3 || !existsSync(dir)) return out;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (["node_modules", ".git", "venv", ".venv", "__pycache__", "dist", ".next"].includes(e.name)) continue;
      walk(p, depth + 1, out);
    } else if (ENV_NAMES.includes(e.name)) {
      out.push(p);
    }
  }
  return out;
}

const found = [];
for (const dir of SEARCH_DIRS) {
  for (const file of walk(dir)) {
    let text;
    try {
      if (statSync(file).size > 512 * 1024) continue;
      text = readFileSync(file, "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) {
      const m = line.trim().match(KEY_RE);
      if (!m) continue;
      const value = m[3].replace(/^["']|["']$/g, "");
      if (!value || value.length < 8 || value.startsWith("<") || value.includes("...")) continue;
      if (m[1].startsWith("NEXT_PUBLIC_") || /_URL$|_BASE$/.test(m[1])) continue;   // адреса, не секреты
      found.push({ name: m[1], file, hint: value.slice(0, 4) + "…", len: value.length });
    }
  }
}

const registry = existsSync(REGISTRY) ? readFileSync(REGISTRY, "utf8") : "";
const secrets = existsSync(SECRETS) ? readFileSync(SECRETS, "utf8") : "";
const known = (registry + secrets).toLowerCase();
const registryLc = registry.toLowerCase();

// вендор угадываем по имени переменной — реестр ведётся по вендорам, а не по именам env
const vendorOf = (name) => {
  const n = name.toLowerCase();
  for (const v of ["fal", "openai", "gemini", "google", "yandex", "telegram", "gdeslon",
                   "replicate", "huggingface", "anthropic", "posthog", "yookassa", "smtp", "salad", "runpod"]) {
    if (n.includes(v)) return v;
  }
  return name.toLowerCase();
};

// ключи соседних проектов учитываются одной строкой реестра «Чужие ключи на машине» —
// такие файлы не должны подсвечиваться как пропущенные
const FOREIGN_DIRS = ["igor/sib", "igor/sing", "igor/sup2"];
const foreignCovered = /чужие ключи на машине/i.test(registry);
const rows = found.map((f) => {
  const foreign = FOREIGN_DIRS.some((d) => f.file.includes(d));
  return {
    ...f,
    vendor: vendorOf(f.name),
    foreign,
    inRegistry: known.includes(vendorOf(f.name)) || (foreign && foreignCovered),
  };
});

// блок «есть в ACCESS.md»: имя, есть ли оно в .env на диске, упомянут ли вендор в реестре
const onDiskNames = new Set(found.map((f) => f.name));
const accessRows = secretNames(secrets).filter((n) => n.present).map(({ name }) => ({
  name,
  source: "ACCESS.md",
  onDisk: onDiskNames.has(name),
  inRegistry: registryLc.includes(vendorOf(name)) || registryLc.includes(name.toLowerCase()),
}));
const onlyInAccess = accessRows.filter((r) => !r.onDisk);

if (process.argv.includes("--json")) {
  console.log(JSON.stringify([...rows, ...accessRows], null, 1));
} else {
  console.log(`[access-inventory] найдено ключей: ${rows.length}\n`);
  for (const r of rows) {
    const mark = r.foreign ? "· чужой" : r.inRegistry ? "✓" : "✗ НЕ В РЕЕСТРЕ";
    console.log(`  ${mark.padEnd(14)} ${r.name.padEnd(26)} ${r.hint} (${r.len})  ${r.file.replace(HOME, "~")}`);
  }
  const missing = rows.filter((r) => !r.inRegistry);
  if (missing.length) {
    console.log(`\n  ${missing.length} доступ(ов) есть на машине, но нет в ${REGISTRY} —`);
    console.log("  добавь их туда (значения — только в _secrets/ACCESS.md, вне git).");
  } else {
    console.log("\n  всё найденное учтено в реестре.");
  }

  console.log(`\n[access-inventory] есть в ACCESS.md (только имена; значения не читаются): ${accessRows.length}`);
  if (!secretsLoc.path) {
    console.log(`  ACCESS.md не найден (искал: ${secretsLoc.tried.map((t) => t.replace(HOME, "~")).join(", ")}) — это НЕ значит «ключей нет».`);
  }
  for (const r of accessRows) {
    console.log(`  ✓ ${r.name.padEnd(30)} в реестре: ${r.inRegistry ? "да" : "НЕТ"} · в .env на диске: ${r.onDisk ? "да" : "нет"}`);
  }
  if (onlyInAccess.length) {
    console.log(`\n  ключ ЕСТЬ, лежит только в ACCESS.md: ${onlyInAccess.map((r) => r.name).join(", ")} —`);
    console.log("  «нет ключа» говорить нельзя; значение берёт скрипт запуска из ACCESS.md при старте (не копировать на диск).");
  }
}
