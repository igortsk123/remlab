// Разборщик части B anti-patterns.md (уроки) и новых lessons/*.md.
// Общий модуль для split-lessons.mjs и verify.mjs.
import fs from 'node:fs';

export const PART_A_LINES = 128; // строки 1–128 — часть A (код-антипаттерны + M1–M5 + комментарий)

const RE_HEADER = /^(#{2,3}) (.+?)\s*$/;
const RE_NUM_DOT = /^(\d+)\. \[/;                    // 13. [2026-07-31] …
const RE_BOLD_NUM = /^\*\*(\d+(?:-бис)?)\. /;        // **374. … / **399-бис. …
const RE_DASH_PAREN = /^- \((\d+)\) /;               // - (243) …
const RE_DASH_NUM = /^- (\d+) /;                     // - 253 [14.08] … / - 214 книжная …
const RE_DASH = /^- /;                                // прочие маркеры
const RE_ALSO = /; (\d{3}) [а-яё]/g;                  // «…; 219 дроппер …» — второй урок в строке

export function parseRange(title) {
  // «Уроки 334–338 (…)» / «Архив уроков 20–25 (…)» — диапазон для безномерных записей
  const m = title.match(/^(?:Уроки|Архив уроков) (\d+)–(\d+)/);
  return m ? [Number(m[1]), Number(m[2])] : null;
}

function trimTrailingBlank(lines) {
  const out = lines.slice();
  while (out.length && out[out.length - 1].trim() === '') out.pop();
  return out;
}

/**
 * Разбирает массив строк (уроки) в записи.
 * Заголовок секции: `## …` или `### …` (в новых файлах — `### из «…»` → title без обёртки).
 * Возвращает { sections: [{title, line}], records: [{num, also, inferred, section, text, line}] }.
 */
export function parseLessons(lines, { lineOffset = 0, newFormat = false } = {}) {
  const sections = [];
  const records = [];
  let section = null;
  let cur = null;
  let started = !newFormat; // в новом формате всё до первого `### из` — преамбула

  const flush = () => {
    if (cur) {
      cur.lines = trimTrailingBlank(cur.lines);
      cur.text = cur.lines.join('\n');
      delete cur.lines;
      records.push(cur);
      cur = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const lineNo = i + 1 + lineOffset;
    const h = raw.match(RE_HEADER);
    if (h) {
      let title = h[2];
      if (newFormat) {
        const m = title.match(/^из «(.+)»$/);
        if (!m) {
          if (h[1] === '##') { flush(); continue; } // подраздел файла (например «## Source-KB») — не секция-источник
          if (!started) continue;
          throw new Error(`Неожиданный заголовок в новом файле, строка ${lineNo}: ${raw}`);
        }
        title = m[1];
        started = true;
      }
      flush();
      section = { title, line: lineNo, range: parseRange(title), unnumbered: 0 };
      sections.push(section);
      continue;
    }
    if (!started) continue;
    if (!section) throw new Error(`Текст до первой секции, строка ${lineNo}: ${raw}`);

    let m;
    let num = null;
    let also = [];
    let isStart = false;
    if ((m = raw.match(RE_NUM_DOT)) || (m = raw.match(RE_BOLD_NUM)) || (m = raw.match(RE_DASH_PAREN)) || (m = raw.match(RE_DASH_NUM))) {
      num = m[1];
      isStart = true;
      if (RE_DASH_NUM.test(raw) && !RE_DASH_PAREN.test(raw)) {
        for (const a of raw.matchAll(RE_ALSO)) also.push(a[1]);
      }
    } else if (RE_DASH.test(raw)) {
      isStart = true;
    }

    if (isStart) {
      flush();
      cur = { num, also, inferred: false, section: section.title, sectionLine: section.line, line: lineNo, lines: [raw] };
      if (num === null) {
        section.unnumbered += 1;
        const r = section.range;
        if (r && !newFormat) {
          const n = r[0] + section.unnumbered - 1;
          if (n <= r[1]) { cur.num = String(n); cur.inferred = true; }
          else { cur.overflow = true; }
        }
      }
      continue;
    }
    if (cur) { cur.lines.push(raw); continue; }
    if (raw.trim() === '') continue;
    throw new Error(`Строка вне записи, ${lineNo}: ${raw}`);
  }
  flush();
  return { sections, records };
}

export function readOld(path) {
  const all = fs.readFileSync(path, 'utf8').split('\n');
  const partA = all.slice(0, PART_A_LINES);
  const partB = all.slice(PART_A_LINES);
  return { all, partA, partB, partBOffset: PART_A_LINES };
}

/** Ключ записи для карты: номер, либо «б/н». */
export function recKey(r) { return r.num ?? 'б/н'; }

/** Числовое значение для сортировки. */
export function numVal(num) {
  if (num == null) return null;
  const m = String(num).match(/^(\d+)(-бис)?$/);
  return Number(m[1]) + (m[2] ? 0.5 : 0);
}

export function firstWords(text, n = 90) {
  const s = text.split('\n')[0].replace(/^(- \(\d+\) |- \d+ |\d+\. |- |\*\*)/, '').replace(/\*\*/g, '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
