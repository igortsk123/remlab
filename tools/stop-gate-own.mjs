// stop-gate-own — чистые функции для Stop-хука session-reminder.mjs (T-20261127-175/5, Fable 27 § 2–3, задача 5):
//  1) «только свои правки»: какие файлы ЭТА сессия правила своими Edit/Write (из стенограммы hookInput.transcript_path);
//     чужая незакоммиченная правка в общей рабочей копии гейт не блокирует (27.11: гейт остановил сессию из-за чужого файла);
//  2) «строка стража — только у директора и только по его правкам»: разбор строки `tools/ops/rules_guard.py`
//     «правила: просрочено N, вне реестра M, сообщений владельца без разбора K, выключателей на удаление D».
// Без побочных эффектов, кроме runStrazh (запускает команду стража без оболочки, таймаут). Любой сбой → «не знаю» (null), а не блок:
// приоритет — 0 ложных блокировок чужих сессий.
import { readFileSync, existsSync } from "node:fs";
import { resolve, relative, isAbsolute, join } from "node:path";
import { execFileSync } from "node:child_process";

const EDIT_TOOLS = new Set(["Edit", "Write", "MultiEdit", "NotebookEdit"]);

/** Относительные (к root) пути файлов, которые сессия правила инструментами Edit/Write. null — стенограммы нет/не читается («не знаю»). */
export function ownEditedPaths(transcriptPath, root) {
  if (!transcriptPath || !existsSync(transcriptPath)) return null;
  let txt;
  try {
    txt = readFileSync(transcriptPath, "utf8");
  } catch {
    return null;
  }
  const own = new Set();
  for (const line of txt.split("\n")) {
    if (!line.includes('"tool_use"')) continue;
    let rec;
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    const content = rec?.message?.content;
    if (!Array.isArray(content)) continue;
    for (const c of content) {
      if (c?.type !== "tool_use" || !EDIT_TOOLS.has(c.name)) continue;
      const p = c.input?.file_path ?? c.input?.notebook_path;
      if (typeof p !== "string" || !p) continue;
      const abs = isAbsolute(p) ? p : resolve(root, p);
      const rel = relative(root, abs).split("\\").join("/");
      if (!rel.startsWith("..")) own.add(rel);
    }
  }
  return own;
}

/** Путь из строки `git status --porcelain` (после «XY »), для переименования — новый путь; кавычки сняты. */
export function porcelainPath(line) {
  let p = line.slice(3);
  const i = p.indexOf(" -> ");
  if (i !== -1) p = p.slice(i + 4);
  return p.replace(/^"|"$/g, "");
}

/** Файл (или каталог `dir/` из `?? dir/`) принадлежит своим правкам. */
export function isOwn(path, own) {
  if (!own) return false;
  if (own.has(path)) return true;
  if (path.endsWith("/")) for (const o of own) if (o.startsWith(path)) return true;
  return false;
}

/** Из списка строк porcelain оставить только те, что правила сама сессия (own=null → ничего не оставляем: «не знаю» ≠ блок). */
export function onlyOwn(porcelainLines, own) {
  if (!own) return [];
  return porcelainLines.filter((l) => isOwn(porcelainPath(l), own));
}

/** Файлы правил: правка таких файлов — повод проверить строку стража. */
export const RULES_PATH_RE = /^(\.memory_bank\/rules\/|\.memory_bank\/decisions\/|tools\/scout\/rules\/|\.claude\/rules\/|\.memory_bank\/plans\/mesh-type-rules-01\.md$|\.memory_bank\/plans\/rules-registry-01\.md$)/;

export function ownRulesEdits(own) {
  return own ? [...own].filter((p) => RULES_PATH_RE.test(p)) : [];
}

const FIELDS = {
  "просрочено": /просрочено\s*[:=]?\s*(\d+)/i,
  "вне реестра": /вне реестра\s*[:=]?\s*(\d+)/i,
  "без разбора": /без разбора\s*[:=]?\s*(\d+)/i,
  "на удаление": /на удаление\s*[:=]?\s*(\d+)/i,
};

/** Разбор строки стража → {просрочено, вне реестра, без разбора, на удаление} или null, если нет ни одного числа. */
export function parseStrazh(text) {
  const out = {};
  let n = 0;
  for (const [k, re] of Object.entries(FIELDS)) {
    const m = re.exec(text || "");
    if (m) {
      out[k] = Number(m[1]);
      n++;
    }
  }
  return n ? out : null;
}

/** Поля, по которым директору блокируем (по умолчанию — то, что он сам может исправить правкой: срок и реестр). */
export const DEFAULT_BLOCK_FIELDS = ["просрочено", "вне реестра"];

export function strazhVerdict(parsed, blockFields = DEFAULT_BLOCK_FIELDS) {
  if (!parsed) return { block: false, bad: [] };
  const bad = blockFields.filter((f) => (parsed[f] ?? 0) > 0).map((f) => `${f} ${parsed[f]}`);
  return { block: bad.length > 0, bad };
}

/** Запуск стража без оболочки: cmd — массив [исполняемый, аргументы…]; первая непустая строка stdout. null — не запускался/упал/таймаут. */
export function runStrazh(cmd, cwd, timeoutMs = 20000) {
  try {
    const out = execFileSync(cmd[0], cmd.slice(1), { cwd, encoding: "utf8", timeout: timeoutMs, stdio: ["ignore", "pipe", "ignore"] });
    return out.split("\n").find((l) => l.trim()) ?? null;
  } catch (e) {
    // страж может вернуть код ≠ 0 при «не ноль» — строка всё равно в stdout
    const o = typeof e?.stdout === "string" ? e.stdout : "";
    return o.split("\n").find((l) => l.trim()) ?? null;
  }
}

/** Команда стража по умолчанию: tools/ops/rules_guard.py --line; файла нет — null (страж ещё не влит → проверка молчит). */
export function defaultStrazhCmd(root) {
  const f = join(root, "tools", "ops", "rules_guard.py");
  return existsSync(f) ? ["python3", f, "--line"] : null;
}

/** Проблемы memory-audit, относящиеся ТОЛЬКО к чужим незакоммиченным файлам, — исключить: проблема «чужая», если называет чужой грязный
 *  файл и не называет ни одного своего. Проблема без путей — общая, остаётся. */
export function dropForeignProblems(problems, dirtyAll, own) {
  const foreign = dirtyAll.filter((p) => !isOwn(p, own));
  return problems.filter((pr) => {
    const namesForeign = foreign.some((f) => pr.includes(f));
    const namesOwn = [...(own ?? [])].some((o) => pr.includes(o));
    return !(namesForeign && !namesOwn);
  });
}
