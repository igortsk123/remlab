// stop-gate-own — чистые функции для Stop-хука session-reminder.mjs (T-20261127-175/5, Fable 27 § 2–3, задача 5):
//  1) «только свои правки»: какие файлы ЭТА сессия правила своими Edit/Write (из стенограммы hookInput.transcript_path);
//     чужая незакоммиченная правка в общей рабочей копии гейт не блокирует (27.11: гейт остановил сессию из-за чужого файла);
//  2) «строка стража — только у директора и только по его правкам»: разбор строки `tools/ops/rules_guard.py`
//     «правила: просрочено N, вне реестра M, сообщений владельца без разбора K, выключателей на удаление D».
// Без побочных эффектов, кроме runStrazh (запускает команду стража без оболочки, таймаут). Сбой чтения стенограммы → «не знаю» (own=null) и ПРИЧИНА (readOwnEdits):
// «не знаю» не означает «правок нет» — session-reminder у директора блокирует («стенограмма не читается»), у остальных пишет предупреждение; 0 ложных блокировок чужих сессий.
import { existsSync, openSync, readSync, closeSync } from "node:fs";
import { resolve, relative, isAbsolute, join } from "node:path";
import { execFileSync } from "node:child_process";

const EDIT_TOOLS = new Set(["Edit", "Write", "MultiEdit", "NotebookEdit"]);

// Размеры чтения стенограммы (байты). Стенограмма директора — 1,29 ГБ: `readFileSync(…, "utf8")` на ней падает ERR_STRING_TOO_LONG (предел строки V8 ≈ 512 МБ), `null` читался как
// «правок нет», и гейт со стражем молчали (живая проверка 27.11). Теперь читаем кусками фиксированного размера по `readSync` и режем по «\n»; в памяти — один кусок + недочитанная строка.
// Для теста пределы можно занизить переменными окружения STOP_GATE_CHUNK_BYTES / STOP_GATE_MAX_LINE_BYTES (боевой хук их не задаёт).
const CHUNK_BYTES = 8 * 1024 * 1024;
const MAX_LINE_BYTES = 64 * 1024 * 1024; // строка JSONL длиннее (скриншот в base64 и т. п.) — пропускается с учётом, не падаем

function limits(opts = {}) {
  const num = (v, d) => (Number.isInteger(Number(v)) && Number(v) > 0 ? Number(v) : d);
  return { chunk: num(opts.chunk ?? process.env.STOP_GATE_CHUNK_BYTES, CHUNK_BYTES), maxLine: num(opts.maxLine ?? process.env.STOP_GATE_MAX_LINE_BYTES, MAX_LINE_BYTES) };
}

/** Вызывает onLine(Buffer) на каждую строку файла (без «\n»), читая кусками. Строка длиннее maxLine не собирается — считается в skipped. → {skipped, bytes}. Ошибки чтения — наружу. */
export function forEachLine(path, onLine, opts = {}) {
  const { chunk, maxLine } = limits(opts);
  const fd = openSync(path, "r");
  try {
    const buf = Buffer.allocUnsafe(chunk);
    let carry = []; // части строки, оборвавшейся на границе куска
    let carryLen = 0;
    let overflow = false; // текущая строка уже длиннее maxLine — выбрасываем до её конца
    let skipped = 0;
    let bytes = 0;
    const take = (piece) => {
      // piece — вид на общий buf (перезапишется): копируем только то, что переносим
      if (overflow) return;
      if (carryLen + piece.length > maxLine) {
        overflow = true;
        carry = [];
        carryLen = 0;
        return;
      }
      carry.push(Buffer.from(piece));
      carryLen += piece.length;
    };
    const finish = (piece) => {
      if (overflow) {
        skipped++;
        overflow = false;
        return;
      }
      if (carryLen + piece.length > maxLine) {
        skipped++;
      } else {
        onLine(carryLen ? Buffer.concat([...carry, piece]) : piece);
      }
      carry = [];
      carryLen = 0;
    };
    for (;;) {
      const n = readSync(fd, buf, 0, chunk, null);
      if (n === 0) break;
      bytes += n;
      const view = buf.subarray(0, n);
      let start = 0;
      while (start < n) {
        const nl = view.indexOf(10, start);
        if (nl === -1) {
          take(view.subarray(start));
          break;
        }
        finish(view.subarray(start, nl));
        start = nl + 1;
      }
    }
    if (overflow) skipped++;
    else if (carryLen) onLine(Buffer.concat(carry)); // последняя строка без «\n»
    return { skipped, bytes };
  } finally {
    closeSync(fd);
  }
}

/** Пути правок сессии из стенограммы. → {own: Set<относительный путь>|null, why: причина, если own=null, skipped: пропущено слишком длинных строк, bytes}.
 *  null НЕ значит «правок нет»: вызывающий обязан сказать «стенограмма не читается: why» (директору — блоком), а не молчать. */
export function readOwnEdits(transcriptPath, root, opts = {}) {
  if (!transcriptPath) return { own: null, why: "хук не получил путь к стенограмме (transcript_path пуст)", skipped: 0, bytes: 0 };
  if (!existsSync(transcriptPath)) return { own: null, why: `файла стенограммы нет: ${transcriptPath}`, skipped: 0, bytes: 0 };
  const own = new Set();
  const onLine = (line) => {
    if (line.indexOf('"tool_use"') === -1) return; // дешёвый отсев по байтам: большинство строк — не вызовы инструментов, в текст их не переводим
    let rec;
    try {
      rec = JSON.parse(line.toString("utf8"));
    } catch {
      return;
    }
    const content = rec?.message?.content;
    if (!Array.isArray(content)) return;
    for (const c of content) {
      if (c?.type !== "tool_use" || !EDIT_TOOLS.has(c.name)) continue;
      const p = c.input?.file_path ?? c.input?.notebook_path;
      if (typeof p !== "string" || !p) continue;
      const abs = isAbsolute(p) ? p : resolve(root, p);
      const rel = relative(root, abs).split("\\").join("/");
      if (!rel.startsWith("..")) own.add(rel);
    }
  };
  try {
    const { skipped, bytes } = forEachLine(transcriptPath, onLine, opts);
    return { own, why: null, skipped, bytes };
  } catch (e) {
    const msg = String(e?.message ?? e).replace(/^[A-Z_]+:\s*/, "").slice(0, 120); // у Node message уже начинается с кода — второй раз не пишем
    return { own: null, why: `${e?.code ?? "ошибка"}: ${msg}`, skipped: 0, bytes: 0 };
  }
}

/** Свои правки, уже вынутые из стенограммы на ДРУГОЙ машине (common: стенограмма лежит там, хук идёт через `r` на pakardev, где её нет). Обёртка `tools/ops/stop_own_edits.py`
 *  читает стенограмму на своей стороне и кладёт в stdin-JSON хука `own_edits_abs` (абсолютные пути) и `own_meta` ({skipped, bytes} или {why}). Пути → относительно root, чужие каталоги — вон. */
export function ownFromList(list, root, meta = {}) {
  const own = new Set();
  for (const p of list) {
    if (typeof p !== "string" || !p) continue;
    const abs = isAbsolute(p) ? p : resolve(root, p);
    const rel = relative(root, abs).split("\\").join("/");
    if (!rel.startsWith("..")) own.add(rel);
  }
  return { own, why: null, skipped: Number(meta?.skipped) || 0, bytes: Number(meta?.bytes) || 0, source: "обёртка" };
}

/** Откуда брать свои правки: список от обёртки (own_edits_abs) → он; обёртка не смогла прочесть (own_meta.why) → «не читается» с её причиной (она знает больше, чем «файла нет» на этой машине);
 *  иначе — сама стенограмма по transcript_path (pakardev и всё, где путь виден хуку). → {own|null, why, skipped, bytes, source}. */
export function transcriptFromInput(hookInput, root, opts = {}) {
  const meta = hookInput?.own_meta && typeof hookInput.own_meta === "object" ? hookInput.own_meta : null;
  if (Array.isArray(hookInput?.own_edits_abs)) return ownFromList(hookInput.own_edits_abs, root, meta ?? {});
  if (meta?.why) return { own: null, why: `обёртка на стороне стенограммы: ${String(meta.why).slice(0, 160)}`, skipped: 0, bytes: 0, source: "обёртка" };
  return { ...readOwnEdits(hookInput?.transcript_path, root, opts), source: "хук" };
}

/** Относительные (к root) пути файлов, которые сессия правила инструментами Edit/Write. null — стенограммы нет/не читается (причину даёт readOwnEdits). */
export function ownEditedPaths(transcriptPath, root, opts = {}) {
  return readOwnEdits(transcriptPath, root, opts).own;
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
  "вне реестра": /вне реестра\s*[:=]?\s*(?:новых\s*)?(\d+)/i, // и «вне реестра 0», и «вне реестра: новых 0 (старый долг 167)» — долг в счёт гейта не входит
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

/** Путь из `git status` может быть СВЁРНУТЫМ каталогом (`?? tools/` — весь каталог не отслежен): внутри могут лежать файлы правил. Когда «свои правки» неизвестны
 *  (стенограмма не читается), такой каталог тоже считаем возможным файлом правил. */
const RULES_DIR_PREFIXES = [".memory_bank/rules/", ".memory_bank/decisions/", "tools/scout/rules/", ".claude/rules/", ".memory_bank/plans/"];
export function mayHoldRules(path) {
  return RULES_PATH_RE.test(path) || (path.endsWith("/") && RULES_DIR_PREFIXES.some((pre) => pre.startsWith(path) || path.startsWith(pre)));
}

/** Поля, по которым директору блокируем (по умолчанию — то, что он сам может исправить правкой: срок и реестр). */
export const DEFAULT_BLOCK_FIELDS = ["просрочено", "вне реестра"];

export function strazhVerdict(parsed, blockFields = DEFAULT_BLOCK_FIELDS) {
  if (!parsed) return { block: false, bad: [] };
  const bad = blockFields.filter((f) => (parsed[f] ?? 0) > 0).map((f) => `${f} ${parsed[f]}`);
  return { block: bad.length > 0, bad };
}

/** Запуск стража без оболочки: cmd — массив [исполняемый, аргументы…]. → {line, code, why}:
 *  line — первая непустая строка stdout (страж с `--check` при «не ноль» возвращает код 1, но строка в stdout — её читаем);
 *  code — код возврата (0 / число / «таймаут» / «сигнал X» / код ошибки запуска); why — причина, если строки нет. «Не ответил» не прячем: вызывающий пишет её в блок. */
export function runStrazh(cmd, cwd, timeoutMs = 20000) {
  const first = (s) => (typeof s === "string" ? s.split("\n").find((l) => l.trim()) ?? null : null);
  try {
    const out = execFileSync(cmd[0], cmd.slice(1), { cwd, encoding: "utf8", timeout: timeoutMs, stdio: ["ignore", "pipe", "ignore"] });
    return { line: first(out), code: 0 };
  } catch (e) {
    const code = e?.code === "ETIMEDOUT" ? "таймаут" : typeof e?.status === "number" ? e.status : e?.signal ? `сигнал ${e.signal}` : (e?.code ?? "?");
    return { line: first(e?.stdout), code, cmd: cmd[0] };
  }
}

/** Путь стража относительно корня — один источник для defaultStrazhCmd и текста «страж не найден». */
export const STRAZH_REL = join("tools", "ops", "rules_guard.py");

/** Стража в дереве нет → {ok:false, silent} (гейт не молчит: без стража правки правил проверить нечем). */
export function strazhNotFound(path) {
  return { ok: false, parsed: null, line: null, kind: "strazh", silent: `страж не найден: ${path}` };
}

/** Команда стража по умолчанию: tools/ops/rules_guard.py --check (строка-счётчик — первая строка stdout, код 1 при «не ноль»; ключа `--line` у стража нет —
 *  Fable proverka-t175-3 § 2 п.1: гейт звал его и молчал). Файла нет — null (страж не влит → проверка молчит). */
export function defaultStrazhCmd(root) {
  const f = join(root, STRAZH_REL);
  return existsSync(f) ? ["python3", f, "--check"] : null;
}

/** Ответ стража → {ok, parsed, line, silent: текст «страж не ответил: …» или null}. Строки нет или в ней нет ни одного счётчика — страж не ответил
 *  (пустой вывод при коде 2 — падение, а не «чисто»): гейт НЕ молчит, а называет код. */
export function strazhAnswer(res) {
  // реестр не читается: страж ответил, но «просрочено»/«вне реестра» не измерил (там «?») — это не «0» и не ответ-счётчик; блок с причиной (kind "registry")
  const reg = /реестр не читается\s*\(([^)]*)\)/.exec(res?.line ?? "");
  if (reg) return { ok: false, parsed: null, line: res.line.trim(), kind: "registry", silent: `реестр правил не читается (${reg[1].trim().slice(0, 100)}) — сроки и выключатели не измерены` };
  // сторож выключателей не отработал (нет настроек/порога): «вне реестра»/«на удаление» там «?», а не 0 — тоже не ответ-счётчик
  const sw = /сторож выключателей не работает\s*\(([^)]*)\)/.exec(res?.line ?? "");
  if (sw) return { ok: false, parsed: null, line: res.line.trim(), kind: "switches", silent: `сторож выключателей не работает (${sw[1].trim().slice(0, 100)}) — «вне реестра» и «на удаление» не измерены` };
  const parsed = parseStrazh(res?.line);
  if (parsed) return { ok: true, parsed, line: res.line.trim(), silent: null };
  if (res?.code === "ENOENT") return strazhNotFound(res.cmd ?? "?"); // команда стража не нашлась в системе (нет python3 / указанного файла)
  const code = res?.code ?? "?";
  const what = res?.line ? `вывод не разобран: «${res.line.trim().slice(0, 80)}»` : "пустой вывод";
  return { ok: false, parsed: null, line: res?.line ?? null, kind: "strazh", silent: `страж не ответил: код ${code}, ${what}` };
}

/** Путь p назван в тексте находки: целиком или без приставки `.memory_bank/` (аудит банка называет файл без неё: «core/x.md — 3,4 КБ»).
 *  Слева от совпадения не должно быть символа пути — иначе «a/core/x.md» сошёл бы за «core/x.md». */
export function mentions(text, p) {
  const forms = [p];
  if (p.startsWith(".memory_bank/")) forms.push(p.slice(".memory_bank/".length));
  return forms.some((f) => {
    if (!f) return false;
    for (let i = text.indexOf(f); i !== -1; i = text.indexOf(f, i + 1)) {
      if (i === 0 || !/[\w./-]/.test(text[i - 1])) return true;
    }
    return false;
  });
}

/** Проблемы memory-audit, относящиеся ТОЛЬКО к чужим незакоммиченным файлам, — исключить: проблема «чужая», если называет чужой грязный
 *  файл (с приставкой `.memory_bank/` или без неё) и не называет ни одного своего. Проблема без путей — общая, остаётся. */
export function dropForeignProblems(problems, dirtyAll, own) {
  const foreign = dirtyAll.filter((p) => !isOwn(p, own));
  return problems.filter((pr) => {
    const namesForeign = foreign.some((f) => mentions(pr, f));
    const namesOwn = [...(own ?? [])].some((o) => mentions(pr, o));
    return !(namesForeign && !namesOwn);
  });
}
