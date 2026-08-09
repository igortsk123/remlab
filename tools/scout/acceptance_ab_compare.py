#!/usr/bin/env python3
"""L3-A/B (MASTER-layout-v5): сравнение двух приёмочных отчётов посценно.

Запуск: python3 acceptance_ab_compare.py acceptance-report-zoned-l0-baseline.json acceptance-report-zoned.json
Выход: изменившиеся сцены (ok/fails/missing/skipped), дельта retention по ролям, инвариант
«0 сцен хуже по hard».
"""
import collections
import json
import sys

a_path, b_path = sys.argv[1], sys.argv[2]
A = {r['scene']: r for r in json.load(open(a_path))}
B = {r['scene']: r for r in json.load(open(b_path))}
BASE = lambda r: r.split()[0]

worse_hard, better, changed = [], [], []
for sc in A:
    a, b = A[sc], B.get(sc)
    if b is None:
        continue
    if a['ok'] and not b['ok']:
        worse_hard.append((sc, b['fails'], b['missing']))
    if not a['ok'] and b['ok']:
        better.append(sc)
    da = set(a.get('skipped', [])) | set(a.get('missing', []))
    db = set(b.get('skipped', [])) | set(b.get('missing', []))
    if da != db:
        changed.append((sc, sorted(da - db), sorted(db - da)))

def lost_counter(rep):
    c = collections.Counter()
    for r in rep.values():
        for x in r.get('skipped', []) + r.get('missing', []):
            c[BASE(x)] += 1
    return c

la, lb = lost_counter(A), lost_counter(B)
print(f'=== A/B: {a_path} → {b_path} ({len(B)} сцен) ===')
print(f"ok: {sum(1 for r in A.values() if r['ok'])} → {sum(1 for r in B.values() if r['ok'])}")
print(f'ХУЖЕ по hard ({len(worse_hard)}):')
for w in worse_hard:
    print('  ', w)
print(f'лучше по hard ({len(better)}):', better)
print('\nДельта потерь по ролям (баз. → новое, меньше = лучше):')
for role in sorted(set(la) | set(lb), key=lambda r: (lb[r] - la[r])):
    if la[role] != lb[role]:
        print(f'  {role:<16}{la[role]:>4} → {lb[role]:<4} ({lb[role]-la[role]:+d})')
print(f'\nСцены с изменённым составом потерь ({len(changed)}):')
for sc, gained, lost in changed[:40]:
    print(f'  {sc}: вернулось {gained or "—"}, потерялось {lost or "—"}')
