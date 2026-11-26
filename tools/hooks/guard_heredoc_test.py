#!/usr/bin/env python3
"""Тест хука `guard_heredoc.py` (T-20261126-98/1; план heredoc-guard-01). Запуск: python3 tools/hooks/guard_heredoc_test.py
Случаи — строками в этом файле (не в командной строке); хук запускается настоящим процессом, конфиг и журнал — во временной папке."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, 'guard_heredoc.py')
TMP = tempfile.mkdtemp(prefix='heredoc-guard-')
CFG = os.path.join(TMP, 'cfg.json')
LOG = os.path.join(TMP, 'sub', 'heredoc-guard.log')
LT = '<'
HD = LT * 2          # heredoc
HS = LT * 3          # herestring
FAILS = []
N = 0


def setmode(m):
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump({'mode': m}, f)


def run(stdin, mode='warn', cfg=True):
    if cfg:
        setmode(mode)
    env = dict(os.environ, HEREDOC_GUARD_CONFIG=CFG if cfg else os.path.join(TMP, 'нет-такого.json'), HEREDOC_GUARD_LOG=LOG)
    p = subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, text=True, env=env, timeout=30)
    return p.returncode, p.stderr


def bash(cmd, session='s1'):
    return json.dumps({'tool_name': 'Bash', 'session_id': session, 'tool_input': {'command': cmd}}, ensure_ascii=False)


def check(name, ok, info=''):
    global N
    N += 1
    if not ok:
        FAILS.append(f'{name}: {info}')
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else '  ' + str(info)))


def log_lines():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8') as f:
        return f.read().splitlines()


HIT = [   # (имя, команда) — срабатывание (в режиме block — код 2)
    ('heredoc голый', f'cat {HD}EOF\nтекст\nEOF'),
    ('heredoc в одинарных кавычках', f"cat {HD}'EOF'\nтекст $x\nEOF"),
    ('heredoc в двойных кавычках', f'cat {HD}"EOF"\nтекст\nEOF'),
    ('heredoc с дефисом (<<-)', f'cat {HD}-EOF\n\tтекст\n\tEOF'),
    ('heredoc с пробелом после <<', f'python3 - {HD} PY\nprint(1)\nPY'),
    ('heredoc в записи файла', f'cat > a.txt {HD}EOF\nx\nEOF'),
    ('heredoc внутри $( )', f'x=$(cat {HD}EOF\nx\nEOF\n)'),
    ('herestring', f'grep x {HS} "текст"'),
    ('herestring без кавычек', f'bc {HS} 1+2'),
    ('пустой heredoc', f"cat {HD}''\n\n"),
    ('после комментария на прошлой строке', f'echo hi # cat {HD}EOF не считается\ncat {HD}EOF\nx\nEOF'),
]
MISS = [  # (имя, команда) — не срабатывает
    ('<< в одинарных кавычках', f"echo '{HD}EOF'"),
    ('<< в двойных кавычках', f'echo "a {HD}EOF b"'),
    ('арифметика $(( ))', 'echo $(( 1 << 2 ))'),
    ('арифметика без пробелов', 'x=$((a' + HD + '2)); echo $x'),
    ('арифметика (( ))', '(( n = 1 << 3 )); echo $n'),
    ('комментарий', f'echo hi # cat {HD}EOF'),
    ('комментарий в начале', f'# cat {HD}EOF\nls'),
    ('экранированный <<', f'echo \\{HD}EOF'),
    ('обычное перенаправление и конвейер', 'cat a.txt | tee b.txt > c.txt 2>&1'),
    ('одиночный < и ввод из файла', 'sort < in.txt'),
    ('<< без слова (сдвиг в конце)', f'echo a {HD}'),
    ('git commit -m с текстом про heredoc', f'git commit -m "запрет {HD}EOF и {HS}"'),
    ('printf', "printf '%s\\n' a b > x.txt"),
]


def main():
    for name, cmd in HIT:
        rc, err = run(bash(cmd), 'block')
        check('block: ' + name, rc == 2 and 'Write' in err and 'printf' in err and 'git commit -m' in err, (rc, err[:120]))
    for name, cmd in MISS:
        rc, err = run(bash(cmd), 'block')
        check('нет срабатывания: ' + name, rc == 0 and err == '', (rc, err[:120]))
    # режим warn: выход 0 + предупреждение
    rc, err = run(bash(f'cat {HD}EOF\nx\nEOF'), 'warn')
    check('warn: код 0 и предупреждение в stderr', rc == 0 and 'ПРЕДУПРЕЖДЕНИЕ' in err and 'Write' in err, (rc, err[:120]))
    # конфиг: нет файла / битый / чужое значение → warn (не block)
    rc, err = run(bash(f'cat {HD}EOF\nx\nEOF'), cfg=False)
    check('нет конфига → warn, код 0', rc == 0 and 'ПРЕДУПРЕЖДЕНИЕ' in err, (rc, err[:80]))
    with open(CFG, 'w', encoding='utf-8') as f:
        f.write('{не json')
    env = dict(os.environ, HEREDOC_GUARD_CONFIG=CFG, HEREDOC_GUARD_LOG=LOG)
    p = subprocess.run([sys.executable, HOOK], input=bash(f'cat {HD}EOF\nx\nEOF'), capture_output=True, text=True, env=env, timeout=30)
    check('битый конфиг → warn, код 0', p.returncode == 0 and 'ПРЕДУПРЕЖДЕНИЕ' in p.stderr, (p.returncode, p.stderr[:80]))
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump({'mode': 'что-то'}, f)
    p = subprocess.run([sys.executable, HOOK], input=bash(f'cat {HD}EOF\nx\nEOF'), capture_output=True, text=True, env=env, timeout=30)
    check('чужое значение mode → warn, код 0', p.returncode == 0 and 'ПРЕДУПРЕЖДЕНИЕ' in p.stderr, (p.returncode, p.stderr[:80]))
    # пустой ввод, битый JSON, не Bash, пустая команда, не строка — выход 0 без шума и без журнала
    n0 = len(log_lines())
    for name, stdin in (('пустой ввод', ''), ('битый JSON', '{"tool_name": "Bash", '), ('не объект', '[1,2]'),
                        ('пустая команда', bash('')), ('нет команды', json.dumps({'tool_name': 'Bash', 'tool_input': {}})),
                        ('команда не строка', json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 5}})),
                        ('другой инструмент (Write с heredoc в тексте)', json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': 'a', 'command': f'cat {HD}EOF\nx\nEOF'}}))):
        rc, err = run(stdin, 'block')
        check('fail-open: ' + name, rc == 0 and err == '', (rc, err[:80]))
    check('на них журнал не писался', len(log_lines()) == n0, (n0, len(log_lines())))
    # журнал: строка на каждое срабатывание — время, сессия, режим, вид, первые 80 символов
    os.path.exists(LOG) and os.remove(LOG)
    long_cmd = f'cat {HD}EOF\n' + 'я' * 200 + '\nEOF'
    run(bash(long_cmd, session='sess-42'), 'block')
    run(bash(f'grep a {HS} b', session='sess-43'), 'warn')
    ls = log_lines()
    check('журнал: две строки (по срабатыванию)', len(ls) == 2, ls)
    if len(ls) == 2:
        a = ls[0].split('\t')
        check('журнал: сессия, режим, вид', a[1] == 'sess-42' and a[2] == 'block' and a[3] == 'heredoc', a)
        check('журнал: первые 80 символов, перевод строки → ⏎', a[4] == long_cmd[:80].replace('\n', '⏎') and len(a[4]) == 80, a[4])
        check('журнал: время в UTC', a[0].endswith('Z') and len(a[0]) == 20, a[0])
        b = ls[1].split('\t')
        check('журнал: herestring в режиме warn', b[1] == 'sess-43' and b[2] == 'warn' and b[3] == 'herestring', b)
    # журнал недоступен — не мешает (fail-open)
    env2 = dict(os.environ, HEREDOC_GUARD_CONFIG=CFG, HEREDOC_GUARD_LOG='/proc/нельзя/писать/heredoc-guard.log')
    setmode('block')
    p = subprocess.run([sys.executable, HOOK], input=bash(f'cat {HD}EOF\nx\nEOF'), capture_output=True, text=True, env=env2, timeout=30)
    check('журнал недоступен: режим block всё равно отказывает (код 2)', p.returncode == 2, (p.returncode, p.stderr[:80]))
    # конфиг репозитория: режим — block (директор, 26.11, после warn-суток)
    with open(os.path.join(HERE, 'guard-heredoc.json'), encoding='utf-8') as f:
        check('guard-heredoc.json: mode block', json.load(f).get('mode') == 'block')
    print(f'\nпроверок: {N}, провалов: {len(FAILS)}')
    for x in FAILS:
        print('  ', x)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
