#!/usr/bin/env python3
"""Быстрый цикл качества на десятке (решение владельца 08.08: «не перегонять 252 каждый раз»).

Решает N сетов параллельно БЕЗ картинок/публикации и печатает ровно то, что проверяет
владелец: hard-коды, группа req→actual, центровка/ориентация столика, позиции кресел,
носитель ТВ, coverage. Итерация ~1–2 мин; полный 252 — только финал волны.

  ~/venvs/scout/bin/python quick10.py            # дефолтная десятка
  ~/venvs/scout/bin/python quick10.py 55 59 66 84 113 117   # только проблемные
"""
import concurrent.futures as cf
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DEFAULT = [1, 14, 21, 29, 55, 59, 66, 84, 113, 117]


def solve(n: int) -> str:
    env = dict(os.environ, LAYOUT_ENGINE='zoned', LAYOUT_SUFFIX=f'-q10-{n}')
    r = subprocess.run([PY, os.path.join(HERE, 'solver_run.py'), str(n), '--v3'],
                       capture_output=True, text=True, timeout=420, env=env)
    return r.stdout


def report(n: int, out: str) -> str:
    fails = [l.strip() for l in out.splitlines() if l.startswith('FAIL')]
    gid = next((l.split(':', 1)[1].strip() for l in out.splitlines()
                if l.startswith('зонная группа')), '?')
    try:
        L = json.load(open(os.path.join(HERE, f'v3set{n}-layout-q10-{n}.json')))
    except FileNotFoundError:
        return f'set{n}: НЕТ РАСКЛАДКИ; fails={fails}'
    L.pop('_room', None)
    sofa, tbl = L.get('диван'), L.get('столик')
    lines = [f'set{n} [{gid}]' + (f'  FAILS: {fails}' if fails else '  чисто')]
    roles = sorted(L)
    lines.append(f'  роли: {roles}')
    if sofa and tbl:
        r = math.radians(sofa['rot'])
        fx, fy = math.sin(r), math.cos(r)
        dx, dy = tbl['x'] - sofa['x'], tbl['z'] - sofa['z']
        lat = dx * (-fy) + dy * fx
        sec = sofa.get('section') or 0 if sofa.get('corner') else 0
        act_lat = sec / 2
        act_w = max(sofa['w'] - sec, 80)
        dev = abs(lat - act_lat)
        along = tbl['w'] if int(tbl['rot']) % 180 == int(sofa['rot']) % 180 else tbl['d']
        ori = 'длинной' if along >= max(tbl['w'], tbl['d']) - 1 else 'КОРОТКОЙ!'
        lines.append(f'  столик: центровка {dev:.0f} см ({dev / act_w * 100:.0f}% посадки), '
                     f'{ori} стороной к дивану')
    bearer = 'стенка' if 'стенка' in L else ('тв-тумба' if 'тв-тумба' in L else 'НЕТ НОСИТЕЛЯ ТВ!')
    lines.append(f'  носитель ТВ: {bearer}')
    arms = [k for k in L if k.split(' ')[0] == 'кресло']
    if arms:
        lines.append(f'  кресла: {len(arms)} размещено')
    return '\n'.join(lines)


def main():
    ns = [int(a) for a in sys.argv[1:] if a.isdigit()] or DEFAULT
    with cf.ThreadPoolExecutor(max_workers=min(8, len(ns))) as ex:
        outs = list(ex.map(solve, ns))
    for n, out in zip(ns, outs):
        print(report(n, out))
    print(f'\nготово {len(ns)} сетов (быстрый цикл; 252 гоняем только в финале волны)')


if __name__ == '__main__':
    main()
