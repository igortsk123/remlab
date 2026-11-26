#!/usr/bin/env node
// PreToolUse-гард на Bash: не дать агенту убить собственную оболочку.
//
// Урок 399 (случалось 4 раза, последний — 04.09): `pkill -f <шаблон>` и `pgrep -f` матчатся
// по ПОЛНОЙ командной строке, а обёртка харнесса Claude Code содержит текст запускаемой
// команды. Поэтому шаблон попадает не только в целевой процесс, но и в саму оболочку —
// Bash умирает до конца сессии, и это не лечится ни --resume, ни перезапуском окна.
//
// Правильный способ: найти PID (`ps -eo pid,comm,args | grep <имя>`) и убить точечно
// `kill <PID>`; ждать завершения — по маркеру в логе, а не по `pgrep -f`.
//
// Второе правило (T-20261126-guard-heredoc): heredoc / herestring вне кавычек → отказ, см. hasHeredoc.
//
// Гард НАМЕРЕННО fail-open: любая своя ошибка → exit 0 (пропустить). Сломанный гард не
// должен превратиться в тот же отказ Bash, от которого он защищает.

// Heredoc / herestring ВНЕ кавычек (правило директора 25.11, T-20261126-guard-heredoc).
// Проход по тексту команды: '…' — данные; "…" — данные, но `$(…)` и `…` внутри выполняются (там heredoc возможен:
// git commit -m "$(cat <<'EOF' … EOF)"); `$((…))` и `((…))` — арифметика; `#` в начале слова — комментарий; `\x` — экранирование.
// Heredoc — `<<` и затем (после `-`/пробелов) слово, кавычка или `\`; `<<<` — herestring. `<< 2`, `a<<2` в арифметике — нет.
function hasHeredoc(s) {
  const n = s.length;
  const startsWord = (i) => i === 0 || /[\s;&|(){}]/.test(s[i - 1]);
  // скан кода от i до закрывающей `)` (depth>0) / конца строки / закрывающего `\`` (back=true); → [конец, найден?]
  function code(i, close) {
    let depth = 0;
    while (i < n) {
      const c = s[i];
      if (c === '\\') { i += 2; continue; }
      if (c === "'") { const j = s.indexOf("'", i + 1); i = j < 0 ? n : j + 1; continue; }
      if (c === '"') { const r = dq(i + 1); if (r.hit) return { hit: true }; i = r.end; continue; }
      if (c === '`') { if (close === '`') return { end: i + 1 }; const r = code(i + 1, '`'); if (r.hit) return r; i = r.end; continue; }
      if (c === '#' && startsWord(i)) { const j = s.indexOf('\n', i); i = j < 0 ? n : j; continue; }
      if (c === '$' && s[i + 1] === '(') {
        if (s[i + 2] === '(') { i = arith(i + 3); continue; }
        const r = code(i + 2, ')'); if (r.hit) return r; i = r.end; continue;
      }
      if (c === '(' && s[i + 1] === '(' && (i === 0 || /[\s;&|]/.test(s[i - 1]))) { i = arith(i + 2); continue; }
      if (c === '(') depth++;
      if (c === ')') { if (close === ')' && depth === 0) return { end: i + 1 }; depth = Math.max(0, depth - 1); }
      if (c === '<' && s[i + 1] === '<') {
        if (s[i + 2] === '<') return { hit: true };
        const m = /^<<-?[ \t]*(['"\\]|[A-Za-z_])/.exec(s.slice(i, i + 40));
        if (m) return { hit: true };
        i += 2; continue;
      }
      i++;
    }
    return { end: n };
  }
  function dq(i) {
    while (i < n) {
      const c = s[i];
      if (c === '\\') { i += 2; continue; }
      if (c === '"') return { end: i + 1 };
      if (c === '$' && s[i + 1] === '(' && s[i + 2] !== '(') { const r = code(i + 2, ')'); if (r.hit) return r; i = r.end; continue; }
      if (c === '`') { const r = code(i + 1, '`'); if (r.hit) return r; i = r.end; continue; }
      i++;
    }
    return { end: n };
  }
  function arith(i) { // после `((`: до парной `))`
    let d = 2;
    while (i < n && d > 0) { if (s[i] === '(') d++; else if (s[i] === ')') d--; i++; }
    return i;
  }
  return !!code(0, null).hit;
}

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => (raw += d));
process.stdin.on('end', () => {
  let cmd = '';
  try {
    cmd = JSON.parse(raw)?.tool_input?.command ?? '';
  } catch {
    process.exit(0); // не разобрали вход — не мешаем
  }
  if (typeof cmd !== 'string' || !cmd) process.exit(0);

  // heredoc / herestring — отказ (T-20261126-guard-heredoc); своя ошибка разбора → пропуск (fail-open)
  let hd = false;
  try {
    hd = hasHeredoc(cmd);
  } catch {
    hd = false;
  }
  if (hd) {
    process.stderr.write(
      'heredoc запрещён (правило директора 25.11): скрипт — через Write в файл и запуск; текст — printf; коммит — git commit -m.\n'
    );
    process.exit(2);
  }

  // Сначала убираем то, что НЕ выполняется, иначе гард ловит сам себя: текст коммита с
  // разбором этой же граблей содержит `pkill -f` и блокировал `git commit` (поймано 04.09).
  const inert = cmd
    // тело heredoc: <<'MSG' ... MSG  (и <<-EOF, и без кавычек)
    .replace(/<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1[\s\S]*?^\s*\2\s*$/gm, ' ')
    // строки в одинарных и двойных кавычках (аргументы echo, -m, -F)
    .replace(/'[^']*'/g, ' ')
    .replace(/"[^"]*"/g, ' ');

  // `pkill`/`pgrep` с флагом -f (в т.ч. в связках вида `-af`, `-9 -f`).
  const danger = /(^|[\s;&|(])(pkill|pgrep)\b[^;&|\n]*\s-[a-zA-Z]*f/.test(inert);
  if (!danger) process.exit(0);

  process.stderr.write(
    'ЗАПРЕЩЕНО правилом проекта: `pkill -f` / `pgrep -f`.\n' +
      'Шаблон -f матчится по полной командной строке и попадает в обёртку харнесса — ' +
      'оболочка агента умирает до конца сессии (урок 399, уже 4 раза).\n' +
      'Как надо: PID через `ps -eo pid,comm,args | grep <имя>`, затем `kill <PID>`; ' +
      'ожидание процесса — по маркеру в логе, не через `pgrep -f`.\n'
  );
  process.exit(2); // 2 = заблокировать вызов и показать причину агенту
});
