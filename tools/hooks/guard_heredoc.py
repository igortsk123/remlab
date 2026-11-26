#!/usr/bin/env python3
"""PreToolUse-хук Claude: heredoc / herestring в Bash агентов (T-20261126-98/1; план heredoc-guard-01).

ЗАЧЕМ. Тело heredoc не видят ни разбор команд, ни гард конвейера (guard_conveyor.py), а правки файлов через него уходят мимо Write.
Правило директора 25.11 запрещает их; за 25–26.11 нарушений 31 у трёх рабочих — словами не держится. Хук guard-bash.mjs на algor молчит (нет node), поэтому проверка на python.

ПРАВИЛО. Bash-команда содержит heredoc (`<<СЛОВО`, `<<-СЛОВО`, `<<'СЛОВО'`, `<<"СЛОВО"`, `<< СЛОВО`) или herestring (`<<<`) ВНЕ кавычек → срабатывание.
Не срабатывает: `<<` в строке в кавычках (`'…'`, `"…"`), арифметика (`$(( a << 2 ))`, `(( a<<2 ))`), текст после `#` (комментарий), `\\<<`.
Режим — `tools/hooks/guard-heredoc.json`: `"mode": "warn"` — выход 0 + предупреждение в stderr; `"block"` — выход 2, причина и подсказка. Нет файла/битый/другое значение → warn.
Каждое срабатывание — строка в `~/.local/state/remlab/heredoc-guard.log`: время (UTC), сессия, режим, первые 80 символов команды (переводы строк → ⏎).
НАМЕРЕННО fail-open: своя ошибка (пустой/битый ввод, нет прав на журнал) → выход 0. Хук не читает и не пишет ничего, кроме журнала.

Пути можно подменить для теста: HEREDOC_GUARD_CONFIG, HEREDOC_GUARD_LOG.
Тест: python3 tools/hooks/guard_heredoc_test.py   (строку в .claude/settings.json — PreToolUse, matcher Bash — добавляет директор)
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get('HEREDOC_GUARD_CONFIG') or os.path.join(HERE, 'guard-heredoc.json')
LOG = os.environ.get('HEREDOC_GUARD_LOG') or os.path.expanduser('~/.local/state/remlab/heredoc-guard.log')
HINT = ('heredoc/herestring в Bash запрещены (правило директора 25.11): файл — инструментом Write, в Bash только запуск; '
        'короткий текст — printf; текст коммита — git commit -m "…".')
SPACE = ' \t'
DELIM_START = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_\'"\\')
WORD_START = set(' \t\n;|&()<>')          # перед `#` слово начинается → это комментарий


def find_heredoc(cmd):
    """Первый heredoc/herestring вне кавычек, арифметики и комментариев → 'heredoc' | 'herestring' | None. Разбор по символам (кавычки, \\, $(( )), не по подстроке."""
    n, i = len(cmd), 0
    sq = dq = False            # внутри '…' / "…"
    arith = 0                  # глубина $(( )) / (( ))
    while i < n:
        c = cmd[i]
        if sq:
            sq = c != "'"
            i += 1
            continue
        if c == '\\':
            i += 2
            continue
        if dq:
            dq = c != '"'
            i += 1
            continue
        if c == "'":
            sq = True
        elif c == '"':
            dq = True
        elif c == '#' and (i == 0 or cmd[i - 1] in WORD_START):
            j = cmd.find('\n', i)
            if j < 0:
                return None
            i = j
        elif c == '(' and cmd.startswith('((', i):
            arith += 1
            i += 2
            continue
        elif c == ')' and arith and cmd.startswith('))', i):
            arith -= 1
            i += 2
            continue
        elif c == '<' and not arith and cmd.startswith('<<', i):
            if cmd.startswith('<<<', i):
                return 'herestring'
            j = i + 2
            if j < n and cmd[j] == '-':
                j += 1
            while j < n and cmd[j] in SPACE:
                j += 1
            if j < n and cmd[j] in DELIM_START:
                return 'heredoc'
            i += 2
            continue
        i += 1
    return None


def mode():
    try:
        with open(CONFIG, encoding='utf-8') as f:
            m = str((json.load(f) or {}).get('mode', 'warn')).lower()
    except (OSError, ValueError, AttributeError):
        return 'warn'
    return m if m in ('warn', 'block') else 'warn'


def log(inp, cmd, kind, md):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        head = cmd[:80].replace('\r', '').replace('\n', '⏎')
        sess = str(inp.get('session_id') or '-')
        t = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'{t}\t{sess}\t{md}\t{kind}\t{head}\n')
    except OSError:
        pass


def main():
    try:
        inp = json.loads(sys.stdin.read() or '{}')
        if not isinstance(inp, dict) or inp.get('tool_name', 'Bash') != 'Bash':
            return 0
        cmd = (inp.get('tool_input') or {}).get('command')
        if not isinstance(cmd, str) or not cmd:
            return 0
        kind = find_heredoc(cmd)
        if not kind:
            return 0
        md = mode()
        log(inp, cmd, kind, md)
        if md == 'block':
            sys.stderr.write('ОТКАЗ: ' + HINT + '\n')
            return 2
        sys.stderr.write('ПРЕДУПРЕЖДЕНИЕ (режим warn; потом block): ' + HINT + '\n')
        return 0
    except Exception:   # noqa: BLE001 — fail-open: сломанный хук не должен останавливать работу
        return 0


if __name__ == '__main__':
    sys.exit(main())
