#!/usr/bin/env node
// read-logger — PostToolUse(Read)-hook: логирует чтения доков Memory Bank в
// .memory_bank/changelog/reads.log (строка: YYYY-MM-DD <путь-внутри-банка>).
// Зачем: «свежесть по контакту» (ROADMAP #4) — верифицировать в первую очередь те доки,
// которые часто читаются, но давно не сверялись. Только пути внутри .memory_bank/, только *.md;
// _intake/ и changelog/ не логируем (шум). Всегда exit 0 — логгер не должен мешать работе.
// reads.log — локальная частотная статистика (в .gitignore), не память проекта.
import { readFileSync, appendFileSync, existsSync } from "node:fs";
import { resolve, join, relative, sep } from "node:path";

const root = resolve(process.argv[2] ?? process.cwd());

let hookInput = {};
if (!process.stdin.isTTY) {
  try {
    hookInput = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    process.exit(0);
  }
}

const fp = hookInput?.tool_input?.file_path;
if (!fp || typeof fp !== "string" || !fp.endsWith(".md")) process.exit(0);

const mbDir = join(root, ".memory_bank");
if (!existsSync(mbDir)) process.exit(0);

const rel = relative(mbDir, resolve(fp)).split(sep).join("/");
if (rel.startsWith("..") || rel.startsWith("_intake/") || rel.startsWith("changelog/") || rel.startsWith("_secrets/"))
  process.exit(0);

try {
  const date = new Date().toISOString().slice(0, 10);
  appendFileSync(join(mbDir, "changelog", "reads.log"), `${date} ${rel}\n`, "utf8");
} catch {
  /* нет каталога changelog / нет прав — молчим */
}
