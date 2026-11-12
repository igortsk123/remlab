#!/usr/bin/env python3
"""ВРЕМЯ ШАГОВ ДНЕВНОЙ СБОРКИ по строкам `STEPTIME` в refresh.log (T-20261112-56, план refresh-split-01).

`refresh_daily.sh:step()` после вывода каждого шага пишет
    STEPTIME name=<шаг> start=<ГГГГ-ММ-ДДTЧЧ:ММ:СС> end=<…> sec=<с> rc=<код> res=<итог> cpu=<с процессора детей | ->
Прогон — от строки `=== <дата время> старт ===` до `=== <дата время> готово …`. Скрипт собирает таблицу «шаг → минуты по
прогонам», строки «сумма шагов» и «прогон целиком», а с `--split <шаг>` — две суммы: до этого шага включительно (утро) и после
(вечер). `--cpu` — минуты процессора вместо стены и средняя загрузка «ядер» (cpu / стена) по прогону.

  ~/venvs/scout/bin/python refresh_step_times.py                      # последние 7 прогонов, refresh.log рядом
  ~/venvs/scout/bin/python refresh_step_times.py --days 3 --split demo_band
  ~/venvs/scout/bin/python refresh_step_times.py --log путь --json    # для скриптов
  python3 refresh_step_times.py --selftest
"""
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_START = re.compile(r'^=== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) старт ===')
RUN_END = re.compile(r'^=== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) готово')
KV = re.compile(r'(\w+)=(\S*)')


def parse_line(line: str) -> dict | None:
    """Строка STEPTIME → {'name', 'start', 'end', 'sec', 'rc', 'res', 'cpu'}; не та или битая — None."""
    if not line.startswith('STEPTIME '):
        return None
    d = dict(KV.findall(line))
    if 'name' not in d or 'sec' not in d:
        return None
    try:
        d['sec'] = int(d['sec'])
        d['rc'] = int(d.get('rc', 0))
        d['cpu'] = float(d['cpu']) if d.get('cpu') not in (None, '', '-') else None
    except ValueError:
        return None
    return d


def runs(lines) -> list[dict]:
    """Прогоны по порядку: {'start', 'end' | None, 'steps': [STEPTIME…]}. Строки до первого «старт» — в безымянный прогон."""
    out: list[dict] = []
    cur = None
    for raw in lines:
        line = raw.rstrip('\n')
        m = RUN_START.match(line)
        if m:
            cur = {'start': m.group(1), 'end': None, 'steps': []}
            out.append(cur)
            continue
        m = RUN_END.match(line)
        if m and cur is not None:
            cur['end'] = m.group(1)
            continue
        st = parse_line(line)
        if st:
            if cur is None:
                cur = {'start': None, 'end': None, 'steps': []}
                out.append(cur)
            cur['steps'].append(st)
    return out


def _min(sec: float) -> float:
    return round(sec / 60.0, 1)


def table(rs: list[dict], split: str | None = None, cpu: bool = False) -> dict:
    """{'runs': [метки], 'rows': [(шаг, [мин | None…])], 'sum', 'whole', 'split': {'утро', 'вечер'} | None}."""
    order: list[str] = []
    for r in rs:
        for s in r['steps']:
            if s['name'] not in order:
                order.append(s['name'])
    key = 'cpu' if cpu else 'sec'
    rows = []
    for name in order:
        vals = []
        for r in rs:
            v = [s[key] for s in r['steps'] if s['name'] == name and s[key] is not None]
            vals.append(_min(sum(v)) if v else None)
        rows.append((name, vals))
    tot = [_min(sum(s[key] or 0 for s in r['steps'])) for r in rs]
    whole = []
    for r in rs:
        if r['start'] and r['end']:
            a = datetime.strptime(r['start'], '%Y-%m-%d %H:%M:%S')
            b = datetime.strptime(r['end'], '%Y-%m-%d %H:%M:%S')
            whole.append(_min((b - a).total_seconds()))
        else:
            whole.append(None)
    sp = None
    if split:
        am, pm = [], []
        for r in rs:
            names = [s['name'] for s in r['steps']]
            if split not in names:
                am.append(None)
                pm.append(None)
                continue
            cut = len(names) - 1 - names[::-1].index(split)
            am.append(_min(sum(s[key] or 0 for s in r['steps'][:cut + 1])))
            pm.append(_min(sum(s[key] or 0 for s in r['steps'][cut + 1:])))
        sp = {'утро': am, 'вечер': pm}
    cores = None
    if cpu:
        cores = []
        for r in rs:
            wall = sum(s['sec'] for s in r['steps'] if s['cpu'] is not None)
            cores.append(round(sum(s['cpu'] for s in r['steps'] if s['cpu'] is not None) / wall, 2) if wall else None)
    return {'runs': [(r['start'] or '?')[:16] for r in rs], 'rows': rows, 'sum': tot, 'whole': whole, 'split': sp,
            'cores': cores, 'unit': 'мин процессора' if cpu else 'мин'}


def render(t: dict) -> str:
    def cell(v):
        return '—' if v is None else f'{v:g}'
    head = '| шаг | ' + ' | '.join(t['runs']) + ' |'
    out = [f"единица: {t['unit']}", head, '|' + '---|' * (len(t['runs']) + 1)]
    for name, vals in t['rows']:
        out.append(f'| {name} | ' + ' | '.join(cell(v) for v in vals) + ' |')
    out.append('| **сумма шагов** | ' + ' | '.join(cell(v) for v in t['sum']) + ' |')
    out.append('| **прогон целиком** | ' + ' | '.join(cell(v) for v in t['whole']) + ' |')
    if t['split']:
        for k, vals in t['split'].items():
            out.append(f'| **{k}** | ' + ' | '.join(cell(v) for v in vals) + ' |')
    if t.get('cores'):
        out.append('| **ядер в среднем (cpu/стена)** | ' + ' | '.join(cell(v) for v in t['cores']) + ' |')
    return '\n'.join(out)


def _arg(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1
    log = [
        '=== 2026-11-12 10:40:01 старт ===\n',
        'вывод шага\n',
        'STEPTIME name=feeds start=2026-11-12T10:40:01 end=2026-11-12T10:40:31 sec=30 rc=0 res=ok cpu=-\n',
        'STEPTIME name=load3 start=2026-11-12T10:40:31 end=2026-11-12T10:42:31 sec=120 rc=0 res=ok cpu=60.5\n',
        'STEPTIME name=demo_band start=2026-11-12T10:42:31 end=2026-11-12T10:43:31 sec=60 rc=0 res=warn cpu=30.0\n',
        'STEPTIME name=flat215_demo start=2026-11-12T10:43:31 end=2026-11-12T10:49:31 sec=360 rc=1 res=FAIL cpu=720.0\n',
        'STEPTIME битая строка\n',
        '=== 2026-11-12 10:50:01 готово (фиды ok=1) ===\n',
        '=== 2026-11-13 10:40:01 старт ===\n',
        'STEPTIME name=load3 start=2026-11-13T10:40:01 end=2026-11-13T10:41:01 sec=60 rc=0 res=ok cpu=1.0\n',
    ]
    rs = runs(log)
    ok('два прогона, у второго нет конца', len(rs) == 2 and rs[0]['end'] == '2026-11-12 10:50:01' and rs[1]['end'] is None)
    ok('битая строка пропущена, 4 шага в первом', len(rs[0]['steps']) == 4)
    t = table(rs, split='demo_band')
    row = dict(t['rows'])
    ok('минуты шагов', row['load3'] == [2.0, 1.0] and row['feeds'] == [0.5, None] and row['flat215_demo'] == [6.0, None])
    ok('сумма и прогон целиком', t['sum'] == [9.5, 1.0] and t['whole'] == [10.0, None])
    ok('утро/вечер по demo_band', t['split'] == {'утро': [3.5, None], 'вечер': [6.0, None]})
    c = table(rs, cpu=True)
    ok('процессор: минуты и ядра (feeds без cpu не в знаменателе)', dict(c['rows'])['flat215_demo'] == [12.0, None]
       and c['cores'][0] == round((60.5 + 30 + 720) / 540, 2))
    ok('таблица рисуется', '| load3 | 2 | 1 |' in render(t))
    ok('код и итог шага', rs[0]['steps'][3]['rc'] == 1 and rs[0]['steps'][3]['res'] == 'FAIL')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    path = _arg('--log', os.path.join(HERE, 'refresh.log'))
    days = int(_arg('--days', 7))
    with open(path, encoding='utf-8', errors='replace') as f:
        rs = [r for r in runs(f) if r['steps']][-days:]
    if not rs:
        print('строк STEPTIME в журнале нет — прогон с замером ещё не шёл')
        return 0
    t = table(rs, split=_arg('--split'), cpu='--cpu' in sys.argv)
    print(json.dumps(t, ensure_ascii=False, indent=1) if '--json' in sys.argv else render(t))
    return 0


if __name__ == '__main__':
    sys.exit(main())
