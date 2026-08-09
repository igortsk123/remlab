#!/usr/bin/env python3
"""L4: пост-хок отчёт разнообразия топологий по артефактам приёмочного прогона.

Запуск: python3 topology_report.py acceptance-report-zoned-pairs-off.json
Печатает распределение сигнатур (общее и по зонным группам) и unique_topology_count.
"""
import collections
import json
import os
import sys

from topo_sig import topo_key, topo_signature

HERE = os.path.dirname(os.path.abspath(__file__))
report = json.load(open(sys.argv[1] if len(sys.argv) > 1
                        else os.path.join(HERE, 'acceptance-report-zoned.json')))
engine = 'zoned'
sigs = collections.Counter()
by_group = collections.defaultdict(collections.Counter)
missing_artifacts = 0
for rec in report:
    path = os.path.join(HERE, f"v3set{rec['set']}-layout-acc-{engine}-{rec['scene']}.json")
    try:
        out = json.load(open(path))
    except FileNotFoundError:
        missing_artifacts += 1
        continue
    k = topo_key(topo_signature(out))
    sigs[k] += 1
    by_group[rec.get('group')][k] += 1

n = sum(sigs.values())
print(f'сцен с артефактом: {n} (без артефакта: {missing_artifacts})')
print(f'unique_topology_count: {len(sigs)}')
print('\nтоп-15 сигнатур:')
for k, c in sigs.most_common(15):
    print(f'  {c:>4}  {k}')
for g, cnt in by_group.items():
    print(f'\nгруппа {g}: {sum(cnt.values())} сцен, уникальных топологий {len(cnt)}; топ-5:')
    for k, c in cnt.most_common(5):
        print(f'  {c:>4}  {k}')
