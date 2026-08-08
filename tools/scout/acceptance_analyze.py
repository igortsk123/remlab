#!/usr/bin/env python3
"""L1 (MASTER-layout-v5): классификация провалов приёмки + retention запрошенного состава.

Читает acceptance-report-<engine>.json + артефакты раскладок v3set<N>-layout-acc-<engine>-<scene>.json.
Запрошенный состав сцены = placed(артефакт) ∪ skipped ∪ missing — отдельного файла состава нет,
компоновка живёт в БД (compose2), поэтому восстанавливаем из выходов прогона.

Запуск: python3 acceptance_analyze.py [zoned]
Выход: сводка в stdout + acceptance-analysis-<engine>.json (машиночитаемо, для отчёта L1).
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
engine = sys.argv[1] if len(sys.argv) > 1 else 'zoned'

report = json.load(open(os.path.join(HERE, f'acceptance-report-{engine}.json')))

BASE = lambda r: r.split()[0] if r.split() and r.split()[-1].isdigit() else r  # «кресло 2»→«кресло»


def classify(rec):
    """Таксономия V5 (адаптация): провалы сцены → категория."""
    if rec['fails'] == ['TIMEOUT']:
        return 'SEARCH_COMPLEXITY'          # солвер не уложился в 300 с
    if rec.get('rc'):
        return 'INFRA_CRASH'                # rc!=0 — среда/крэш, см. err
    if rec['missing']:
        return 'UNPLACED_REQUIRED'          # база не встала — кандидаты/поиск
    if rec['fails']:
        codes = {f.split()[1] for f in rec['fails'] if len(f.split()) > 1}
        h0 = {'OUT_OF_ROOM', 'COLLISION', 'DOOR_SWING', 'NO_PASSAGE', 'UNREACHABLE',
              'ACCESS_BLOCKED', 'RADIATOR', 'WINDOW_BLOCKED', 'DOOR_UNREACHABLE'}
        return 'H0_FAIL' if codes & h0 else 'H1_OR_STYLE_FAIL'
    return 'CLEAN'


placed_roles = {}
for rec in report:
    path = os.path.join(HERE, f"v3set{rec['set']}-layout-acc-{engine}-{rec['scene']}.json")
    try:
        lay = json.load(open(path))
        placed_roles[rec['scene']] = [k for k in lay if not k.startswith('_')]
    except FileNotFoundError:
        placed_roles[rec['scene']] = None    # артефакта нет (крэш/таймаут до записи)

cat = collections.Counter()
fail_codes = collections.Counter()
req_n = collections.Counter()      # сцен, где роль запрошена
lost_skip = collections.Counter()  # потеряна ярусом (skipped)
lost_miss = collections.Counter()  # не размещена (missing)
by_cat_scenes = collections.defaultdict(list)
rows = []
for rec in report:
    c = classify(rec)
    cat[c] += 1
    by_cat_scenes[c].append(rec['scene'])
    for f in rec['fails']:
        p = f.split()
        if len(p) > 1:
            fail_codes[p[1]] += 1
    pl = placed_roles.get(rec['scene']) or []
    requested = sorted(set(pl) | set(rec.get('skipped', [])) | set(rec.get('missing', [])))
    for r in requested:
        req_n[BASE(r)] += 1
    for r in rec.get('skipped', []):
        lost_skip[BASE(r)] += 1
    for r in rec.get('missing', []):
        lost_miss[BASE(r)] += 1
    rows.append(dict(scene=rec['scene'], cat=c, requested=requested,
                     skipped=rec.get('skipped', []), missing=rec.get('missing', []),
                     group=rec.get('group')))

n = len(report)
print(f'=== {engine}: {n} сцен ===')
print('Категории:', dict(cat))
print('Hard-коды:', dict(fail_codes.most_common()))
print(f'\n{"роль":<16}{"запрошено":>10}{"дроп ярусом":>12}{"не встало":>10}{"retention":>10}')
ret = {}
for role in sorted(req_n, key=lambda r: -(lost_skip[r] + lost_miss[r])):
    lost = lost_skip[role] + lost_miss[role]
    ret[role] = round(1 - lost / req_n[role], 3)
    print(f'{role:<16}{req_n[role]:>10}{lost_skip[role]:>12}{lost_miss[role]:>10}{ret[role]:>10.1%}')
for c, scenes in sorted(by_cat_scenes.items()):
    if c != 'CLEAN':
        print(f'\n{c} ({len(scenes)}): {scenes}')

json.dump(dict(engine=engine, n=n, categories=dict(cat), fail_codes=dict(fail_codes),
               retention=ret, requested=dict(req_n),
               lost_skipped=dict(lost_skip), lost_missing=dict(lost_miss), scenes=rows),
          open(os.path.join(HERE, f'acceptance-analysis-{engine}.json'), 'w'),
          ensure_ascii=False, indent=1)
print(f'\n→ acceptance-analysis-{engine}.json')
