#!/usr/bin/env node
// precompact-guard — PreCompact-hook: закрывает главную дыру потери контекста в длинных сессиях.
// Авто-компакция сжимает середину диалога — durable-факты сессии, не выписанные в память,
// пропадают. Если работа была (изменения вне .memory_bank/), а блокнот захвата пуст — ОДИН раз
// блокируем компакцию ({"decision":"block","reason":"..."}): Claude получает reason, дописывает
// факты в _intake/session-scratch.md и продолжает; компакция повторится сама.
// Одноразовость — маркер-файл в tmpdir на session_id: повторный PreCompact той же сессии
// пропускается (никаких вечных блоков, компакция не может зависнуть).
// Подключение — пресеты settings-presets/* (hooks.PreCompact).
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";

const root = resolve(process.argv[2] ?? process.cwd());

let hookInput = {};
if (!process.stdin.isTTY) {
  try {
    hookInput = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    /* не-JSON — работаем дальше */
  }
}

// Одноразовость на сессию (session_id приходит в stdin-JSON любого хука).
const sid = String(hookInput.session_id || "unknown").replace(/[^A-Za-z0-9_-]/g, "");
const marker = join(tmpdir(), `mb-precompact-${sid}`);
if (existsSync(marker)) process.exit(0);

let changed = [];
try {
  const out = execFileSync("git", ["-C", root, "status", "--porcelain"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  changed = out
    .split("\n")
    .filter(Boolean)
    .filter((l) => !l.slice(3).startsWith(".memory_bank/"));
} catch {
  process.exit(0); // не git-репо — молчим
}
if (!changed.length) process.exit(0);

// Блокнот захвата на ходу пуст? (нет строк после метки SCRATCH START)
function scratchEmpty() {
  const f = join(root, ".memory_bank", "_intake", "session-scratch.md");
  if (!existsSync(f)) return true;
  try {
    const txt = readFileSync(f, "utf8");
    const i = txt.indexOf("SCRATCH START");
    const tail = i === -1 ? txt : txt.slice(txt.indexOf("\n", i) + 1);
    return tail.replace(/<!--[\s\S]*?-->/g, "").trim().length === 0;
  } catch {
    return true;
  }
}
if (!scratchEmpty()) process.exit(0); // захват на ходу вёлся — компакции ничего не мешает

try {
  writeFileSync(marker, new Date().toISOString(), "utf8");
} catch {
  /* tmpdir недоступен — всё равно блокируем один раз в рамках этого вызова */
}

console.log(
  JSON.stringify({
    decision: "block",
    reason:
      `Перед компакцией: в сессии есть работа (файлов вне .memory_bank/: ${changed.length}), ` +
      `а блокнот захвата пуст. Допиши durable-факты сессии в .memory_bank/_intake/session-scratch.md ` +
      `(1–2 строки на факт: решения, изменённые файлы, команды тестов, next steps), затем продолжай — ` +
      `компакция повторится автоматически.`,
  })
);
