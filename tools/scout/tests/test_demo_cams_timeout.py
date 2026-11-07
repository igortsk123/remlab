"""Ракурсы окна не валят сборку витрины (T-20261107-47). Без сети, базы и node.

07.11 подбор ракурсов (`tools/flat3d/demo-cams.mjs`) после видов спальни с двух концов шёл 259 с при пороге 300; таймаут не
перехватывался — `TimeoutExpired` ронял `flat215_demo`, публикация витрины пропускалась. Проверяем `flat215_demo.demo_cams`:
  1) таймаут → строка WARN:demo_cams с причиной «таймаут», без исключения; временный файл подмены убран, данные целы;
  2) код ≠ 0 → WARN:demo_cams с кодом; 3) успех → хвост вывода скрипта;
  4) настоящий таймаут на живом процессе (sleep вместо node) — исключение не вылетает, процесс убит по сроку;
  5) команда — через `exec node` (таймаут убивает сам node, а не только bash).
    python3 tools/scout/tests/test_demo_cams_timeout.py"""
import json
import os
import subprocess
import sys
import time

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_demo_cams_timeout')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

import tempfile  # noqa: E402

import flat215_demo as F  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


d = tempfile.mkdtemp(prefix='cams-')
path = os.path.join(d, 'demo-data.json')
json.dump({'variants': [{'id': 'set1'}]}, open(path, 'w'))
tmp = path + '.cams-12345.tmp'
seen = {}


def run_timeout(cmd, **kw):
    seen['cmd'], seen['kw'] = cmd, kw
    open(tmp, 'w').write('{"обрывок')
    raise subprocess.TimeoutExpired(cmd, kw.get('timeout'), output=b'bedroom-2: one pair\n')


line = F.demo_cams('/root', path, run=run_timeout)
check('таймаут — WARN:demo_cams', line.startswith('WARN:demo_cams:'), line)
check('таймаут — причина «таймаут» и срок', 'таймаут 300 с' in line, line)
check('таймаут — хвост вывода в строке', 'bedroom-2: one pair' in line, line)
check('таймаут — временный файл подмены убран', not os.path.exists(tmp))
check('таймаут — данные целы', json.load(open(path)) == {'variants': [{'id': 'set1'}]})
check('срок — 300 с по умолчанию', seen['kw'].get('timeout') == 300, str(seen['kw']))
check('команда — exec node (таймаут убивает node)', 'exec node' in seen['cmd'][-1] and seen['cmd'][-1].endswith(f'"{path}"'),
      seen['cmd'][-1])

line = F.demo_cams('/root', path, run=lambda c, **k: subprocess.CompletedProcess(c, 2, '', 'boom'))
check('код ≠ 0 — WARN с кодом', line.startswith('WARN:demo_cams:') and 'rc=2' in line and 'boom' in line, line)

line = F.demo_cams('/root', path, run=lambda c, **k: subprocess.CompletedProcess(c, 0, 'x\nракурсы окна в данных: 16\n', ''))
check('успех — хвост вывода', line == 'x\nракурсы окна в данных: 16', line)


def run_sleep(cmd, **kw):   # настоящий процесс, который не укладывается в срок
    return subprocess.run(['bash', '-c', 'exec sleep 30'], **kw)


t0 = time.time()
try:
    line = F.demo_cams('/root', path, timeout=1, run=run_sleep)
    ok = True
except subprocess.TimeoutExpired:
    ok, line = False, ''
check('живой таймаут — без исключения, WARN', ok and line.startswith('WARN:demo_cams:') and 'таймаут 1 с' in line, line)
check('живой таймаут — убит по сроку (< 10 с)', time.time() - t0 < 10, f'{time.time() - t0:.1f} с')

print(f'\n{"OK" if not fails else "FAIL"}: провалов {fails}')
sys.exit(1 if fails else 0)
