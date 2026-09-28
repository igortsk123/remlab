#!/usr/bin/env node
// code-touch-hint — связь «файл кода → доки памяти, которые его описывают» (кит v1.9; пилот sup2 27.09.2026).
//
// Зачем. Память расходится с кодом не потому, что сессия забыла записать, а потому что код поменяли, а
// описание — нет (слепой замер 27.09: 7 устаревших утверждений при «чистом» аудите). Дешевле всего поймать это
// в момент правки: у агента весь контекст изменения, и он может поправить описание в том же изменении.
// Ставится хуком PostToolUse (matcher `Edit|Write`) — apply/merge-settings кита (пресеты, stop-hook.example.json).
//
// Режимы:
//   1) PostToolUse-хук (Claude Code, matcher `Edit|Write`): stdin — JSON события (session_id, tool_input.file_path).
//      Ответ — JSON `hookSpecificOutput.additionalContext`: модель получает этот текст (простой stdout PostToolUse
//      до модели не доходит — проверено опытом 27.09). Один сигнал на (сессия, файл), не больше 3 доков.
//   2) CLI: `node tools/code-touch-hint.mjs --docs-for <файл…>` — какие доки описывают файлы (для /memory-check,
//      этап 1.6 «сверка затронутого»). Печатает «файл → док, док».
//
// Ссылка = inline-код в доке: `путь`, `путь:символ`, `путь#символ`, `путь:123`, или голое имя файла, если оно в
// репо уникально. Папки не считаются (слишком широко). Скан: .memory_bank (без archive/completed_plans/_intake/
// changelog/plans/_secrets/_kit и без журналов: decisions, project-state, source-of-truth, anti-patterns, lessons) +
// .claude/rules. Никогда не падает и не блокирует: любая ошибка → exit 0.
import { readFileSync, writeFileSync, appendFileSync, readdirSync, existsSync, mkdirSync, statSync, realpathSync } from "node:fs";
import { join, relative, isAbsolute, basename } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

const CODE_EXT = new Set([
  "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "go", "rs", "rb", "php", "java", "sql", "sh", "vue", "svelte",
  "css", "scss", "html", "yml", "yaml",
]);
const SKIP_DIRS = new Set(["archive", "completed_plans", "_intake", "changelog", "plans", "_secrets", "_kit"]);
const SKIP_PREFIX = [".memory_bank/", ".claude/", "node_modules/", ".git/", ".next/"];
// Журналы, снимок и уроки — не описание текущего поведения, задним числом их не правят (аудит в CODE-DRIFT
// исключает только decisions / project-state / source-of-truth; хук строже — уроки подсказками не шумят).
const HISTORY_DOC = /^\.memory_bank\/(decisions(\.md|\/)|project-state\.md|source-of-truth\.md|anti-patterns\.md|core\/lessons\.md)/;
const MAX_DOCS = 3;

const extOf = (p) => (p.split(".").pop() || "").toLowerCase();
const norm = (p) => p.replace(/\\/g, "/").replace(/^\.\//, "");

function listDocs(root) {
  const out = [];
  const walk = (dir, rel) => {
    let ents = [];
    try {
      ents = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of ents) {
      if (e.isSymbolicLink()) continue; // симлинк может вести вне репо — его строки ушли бы модели
      if (e.isDirectory()) {
        if (rel === ".memory_bank" && SKIP_DIRS.has(e.name)) continue;
        walk(join(dir, e.name), `${rel}/${e.name}`);
      } else if (e.name.endsWith(".md")) out.push(`${rel}/${e.name}`);
    }
  };
  walk(join(root, ".memory_bank"), ".memory_bank");
  walk(join(root, ".claude", "rules"), ".claude/rules"); // с подпапками — как грузит Claude Code
  return out.filter((d) => !HISTORY_DOC.test(d));
}

function bareUnique(root, name, cache) {
  if (!cache.byBase) {
    cache.byBase = {};
    const r = spawnSync("git", ["-C", root, "ls-files"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 64 * 1024 * 1024 });
    if (!r.error && r.status === 0)
      for (const f of (r.stdout || "").split("\n")) if (f) cache.byBase[basename(f)] = (cache.byBase[basename(f)] || 0) + 1;
  }
  return cache.byBase[name] === 1;
}

/** Доки, где упомянут файл `rel` (репо-относительный путь). → [{doc, line}] */
function docsFor(root, rel, docs, cache) {
  const name = basename(rel);
  const hits = [];
  for (const doc of docs) {
    let text;
    try {
      text = readFileSync(join(root, doc), "utf8");
    } catch {
      continue;
    }
    if (!text.includes(name)) continue; // дёшево отсекаем большинство доков
    const lines = text.split(/\r?\n/);
    for (const line of lines) {
      let found = false;
      for (const m of line.matchAll(/`([^`\n]+)`/g)) {
        let tok = norm(m[1].trim());
        const sfx = tok.match(/^([^\s:#]+\.([A-Za-z0-9]+))[:#]\S*$/);
        if (sfx) tok = sfx[1];
        if (tok === rel || (tok === name && !tok.includes("/") && bareUnique(root, name, cache))) {
          found = true;
          break;
        }
      }
      if (found) {
        hits.push({ doc, line: line.replace(/^\s*[-*\d.]+\s*/, "").trim() });
        break; // одна строка на док — первая, где файл упомянут
      }
    }
  }
  // Сначала сводки core/ и правила — вход в тему; потом Tier 2.
  const rank = (d) => (d.startsWith(".memory_bank/core/") ? 0 : d.startsWith(".claude/rules/") ? 1 : 2);
  return hits.sort((a, b) => rank(a.doc) - rank(b.doc) || a.doc.localeCompare(b.doc));
}

const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function toRel(root, p) {
  if (!p) return null;
  const abs = isAbsolute(p) ? p : join(root, p);
  const rel = norm(relative(root, abs));
  const outside = (r) => !r || r === ".." || r.startsWith("../") || isAbsolute(r); // `..config.ts` — законное имя
  if (outside(rel)) return null;
  try {
    // Симлинк внутри репо на файл снаружи — тоже «снаружи» (сравниваем настоящие пути).
    if (existsSync(abs) && outside(norm(relative(realpathSync(root), realpathSync(abs))))) return null;
  } catch {
    return null;
  }
  return rel;
}

function main() {
  const args = process.argv.slice(2);
  const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const cache = {};

  if (args[0] === "--docs-for") {
    const docs = listDocs(root);
    for (const f of args.slice(1)) {
      const rel = toRel(root, f);
      if (!rel) continue;
      const hits = docsFor(root, rel, docs, cache);
      console.log(`${rel} → ${hits.length ? hits.map((h) => h.doc).join(", ") : "—"}`);
    }
    return;
  }

  // Режим хука.
  let input = {};
  try {
    input = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    return;
  }
  const rel = toRel(root, input?.tool_input?.file_path);
  if (!rel || SKIP_PREFIX.some((p) => rel.startsWith(p)) || !CODE_EXT.has(extOf(rel))) return;

  // Один сигнал на (сессия, файл).
  const sid = String(input.session_id || "nosession").replace(/[^\w-]/g, "");
  const stDir = join(tmpdir(), "code-touch-hint");
  const stFile = join(stDir, `${sid}.json`);
  let seen = [];
  try {
    if (existsSync(stFile) && Date.now() - statSync(stFile).mtimeMs < 7 * 864e5) seen = JSON.parse(readFileSync(stFile, "utf8"));
  } catch {
    seen = [];
  }
  if (seen.includes(rel)) return;

  const hits = docsFor(root, rel, listDocs(root), cache);
  seen.push(rel);
  try {
    mkdirSync(stDir, { recursive: true });
    writeFileSync(stFile, JSON.stringify(seen));
  } catch {
    /* без дедупликации — не страшно */
  }
  // Телеметрия (v1.9): строка на КАЖДУЮ первую правку файла кода в сессии — и с подсказкой, и без
  // («-»): знаменатель «сколько правок кода описано в памяти». Сводка — `node tools/memory-health.mjs`.
  try {
    appendFileSync(
      join(root, ".memory_bank", "changelog", "code-touch-hint.log"),
      `${new Date().toISOString()}\t${sid}\t${rel}\t${hits.map((h) => h.doc).join(",") || "-"}\n`
    );
  } catch {
    /* журнал не обязателен */
  }
  if (!hits.length) return;

  const shown = hits.slice(0, MAX_DOCS).map((h) => `\`${h.doc}\`: «${clip(h.line, 160)}»`);
  const more = hits.length > MAX_DOCS ? ` (и ещё ${hits.length - MAX_DOCS})` : "";
  const text =
    `Память о файле \`${rel}\`: ${shown.join("; ")}${more}. ` +
    `Если правка меняет описанное поведение, эти строки устареют — их можно поправить в том же изменении; ` +
    `\`last_verified\` двигается только после сверки (/memory-check, этап 1.6).`;
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: text } }));
}

try {
  main();
} catch {
  /* хук не должен мешать работе */
}
process.exit(0);
