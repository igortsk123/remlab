#!/usr/bin/env python3
"""Стенд расписания тарифа `batch_window.sh` без сети и без Telegram (T-20261106-86).

ЗАЧЕМ. 06.11 15:00 пришла ложная тревога «НЕ УДАЛОСЬ погасить mesh-batch-6 (HTTP 404)»: группу удалили в Salad 23.10, а правила
её ещё отдавали. Теперь 404 на СТОПЕ — строка в лог «группы нет — гасить нечего» (не тревога, не сбой), 404 на СТАРТЕ — тревога
(ошибка списка), прочий отказ стопа — тревога и код 1, как прежде; удалённая в правилах (`deleted`) группа расписанию не отдаётся.
Настоящий bash и настоящий скрипт: `curl`, `pgrep` — заглушки в PATH, тревога — `MESH_ALERT`, `HOME` — временная папка
(salad.env, стоп-файл, журнал).

  python3 tools/scout/salad/tests_batch_window.py
"""
import json
import os
import subprocess
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_batch_window')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'batch_window.sh')

CURL = r'''#!/bin/bash
url="${@: -1}"; act="${url##*/}"; rest="${url%/*}"; g="${rest##*/}"
echo "$act $g" >> "$TD/curl.calls"
code=$(echo ",$CODES," | sed -n "s/.*,$g=\([0-9]*\),.*/\1/p")
printf '%s' "${code:-200}"
'''
PGREP = '#!/bin/bash\nexit 0\n'                      # «конвейер жив» — подъём не отменяется
ALERT = '#!/bin/bash\necho "$*" >> "$TD/alerts"\n'


def run(action: str, codes: str, groups: str | None = None, rules: dict | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix='bw-') as td:
        bind = os.path.join(td, 'bin')
        os.makedirs(bind)
        os.makedirs(os.path.join(td, 'scout-scenes'))
        for name, body in (('curl', CURL), ('pgrep', PGREP), ('alert.sh', ALERT)):
            p = os.path.join(bind, name)
            open(p, 'w').write(body)
            os.chmod(p, 0o755)
        open(os.path.join(td, 'scout-scenes', 'salad.env'), 'w').write('SALAD_API_KEY=x\nSALAD_GROUP=g\n')
        rp = os.path.join(td, 'rules.json')
        json.dump(rules or {'groups': {}}, open(rp, 'w'))
        env = {'PATH': bind + ':' + os.environ.get('PATH', ''), 'HOME': td, 'TD': td, 'CODES': codes,
               'MESH_PY': sys.executable, 'MESH_ALERT': os.path.join(bind, 'alert.sh'), 'MESH_GROUPS_RULES': rp,
               'MESH_PRICE_HALT': os.path.join(td, 'нет-запрета.json'), 'MESH_BATCH_LOG': os.path.join(td, 'bw.log')}
        if groups is not None:
            env['MESH_BATCH_GROUPS'] = groups
        p = subprocess.run(['bash', SCRIPT, action], env=env, capture_output=True, text=True, timeout=60)

        def rd(n):
            f = os.path.join(td, n)
            return open(f, encoding='utf-8').read() if os.path.exists(f) else ''
        return {'rc': p.returncode, 'log': rd('bw.log'), 'alerts': rd('alerts').splitlines(), 'calls': rd('curl.calls').splitlines(),
                'err': p.stderr}


def main() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra: object = '') -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    r = run('down', 'mesh-a=200,mesh-b=404', 'mesh-a mesh-b')
    ok('стоп: 404 — «группы нет в Salad, гасить нечего» в журнал, без тревоги, код 0',
       r['rc'] == 0 and not r['alerts'] and 'стоп mesh-b: HTTP 404 — группы нет в Salad, гасить нечего' in r['log']
       and 'стоп mesh-a: HTTP 200' in r['log'], r)
    r = run('down', 'mesh-a=500,mesh-b=200', 'mesh-a mesh-b')
    ok('стоп: прочий отказ (500) — тревога «НЕ УДАЛОСЬ погасить» и код 1, как прежде',
       r['rc'] == 1 and len(r['alerts']) == 1 and 'НЕ УДАЛОСЬ погасить группу mesh-a' in r['alerts'][0]
       and 'стоп mesh-a: HTTP 500' in r['log'], r)
    r = run('down', 'mesh-a=000', 'mesh-a')
    ok('стоп: нет связи (000) — тревога и код 1', r['rc'] == 1 and len(r['alerts']) == 1, r)
    r = run('up', 'mesh-a=400,mesh-b=404', 'mesh-a mesh-b')
    ok('старт: 404 — тревога «группы нет в Salad» (ошибка списка), 400 «уже запущена» — без тревоги',
       r['rc'] == 0 and len(r['alerts']) == 1 and 'mesh-b' in r['alerts'][0] and 'нет в Salad' in r['alerts'][0]
       and 'старт mesh-a: HTTP 400' in r['log'], r)
    rules = {'groups': {'mesh-live': {'tier': 'batch', 'window_utc': [0, 24]},
                        'mesh-gone': {'tier': 'batch', 'window_utc': [0, 24], 'deleted': '2026-10-23'},
                        'mesh-low': {'tier': 'low'}}}
    for act in ('up', 'down'):
        r = run(act, 'mesh-live=200', None, rules)
        ok(f'{act}: список из правил — удалённая (deleted) группа расписанию не отдаётся, к Salad не ходим',
           r['rc'] == 0 and r['calls'] == [f"{'start' if act == 'up' else 'stop'} mesh-live"] and not r['alerts'], r)
    print(f'tests_batch_window: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
