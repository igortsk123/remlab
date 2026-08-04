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
 * Значения ключей НЕ печатаются — только имена, файл и первые 4 символа.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const HOME = homedir();
// где на этой машине исторически живут ключи: проекты владельца + системные места
const SEARCH_DIRS = [
  join(HOME, "igor"),
  join(HOME, "mltest"),
  join(HOME, ".config"),
];
const ENV_NAMES = [".env", ".env.local", ".env.production", "env", "secrets.env"];
const KEY_RE = /^([A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|DSN|WEBHOOK|API)[A-Z0-9_]*)\s*=\s*(.+)$/;
const REGISTRY = ".memory_bank/core/access-and-integrations.md";
const SECRETS = ".memory_bank/_secrets/ACCESS.md";

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

// вендор угадываем по имени переменной — реестр ведётся по вендорам, а не по именам env
const vendorOf = (name) => {
  const n = name.toLowerCase();
  for (const v of ["fal", "openai", "gemini", "google", "yandex", "telegram", "gdeslon",
                   "replicate", "huggingface", "anthropic", "posthog", "yookassa", "smtp"]) {
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

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(rows, null, 1));
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
}
