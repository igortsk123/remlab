#!/usr/bin/env python3
"""V3-G свода №9 (MASTER-zones-v3): агрегатор событий дыр по артефактам экзамена.

Таксономия (поправка рефери — «регион невозможен» ≠ «шаблона нет»):
  NO_FEASIBLE_REGION — регион под зону геометрически невозможен (не gap библиотеки);
  QUALITY_REJECTED   — кандидаты hard-valid были, отверг гейт качества (не gap);
  PRODUCT_RULE_SKIPPED — зону снял продуктовый префильтр (не gap);
  TEMPLATE_GAP       — регион есть, кандидаты были, hard-valid ноль — ИСТИННАЯ дыра.

В missing_templates.md (питает template-library-v2) попадают ТОЛЬКО истинные
TEMPLATE_GAP, с frequency для приоритизации; остальные классы — сводкой ниже.
"""
import glob
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'missing_templates.md')
TRUE_GAP = 'TEMPLATE_GAP'


def collect() -> list[dict]:
    gaps = []
    for f in sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json'))):
        try:
            art = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for g in art.get('_template_gaps') or []:
            g = dict(g)
            g['_scene'] = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
            gaps.append(g)
    return gaps


def main() -> None:
    gaps = collect()
    n_arts = len(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json')))
    true_gaps = [g for g in gaps if g.get('type') == TRUE_GAP]
    other = [g for g in gaps if g.get('type') != TRUE_GAP]
    lines = ['# Дыры библиотеки шаблонов — по последнему экзамену\n',
             f'Артефактов: {n_arts}; событий всего: {len(gaps)}; '
             f'ИСТИННЫХ TEMPLATE_GAP: {len(true_gaps)}.\n']
    if true_gaps:
        by_key = defaultdict(list)
        for g in true_gaps:
            by_key[(g.get('zone'), g.get('requested_mode'))].append(g)
        lines.append('## Истинные дыры (регион есть, библиотека не покрывает) — '
                     'приоритет по frequency\n')
        for (zone, mode), gg in sorted(by_key.items(), key=lambda kv: -len(kv[1])):
            rooms = Counter(g.get('room_class') for g in gg)
            scenes = ', '.join(sorted(g['_scene'] for g in gg)[:12])
            more = '' if len(gg) <= 12 else f' … (+{len(gg) - 12})'
            lines.append(f'### {zone} / {mode}: {len(gg)} сцен')
            lines.append('- классы комнат: '
                         + ', '.join(f'{k}×{v}' for k, v in rooms.most_common()))
            lines.append(f'- сцены: {scenes}{more}\n')
    else:
        lines.append('Истинных дыр библиотеки не зафиксировано.\n')
    if other:
        cnt = Counter((g.get('type'), g.get('zone')) for g in other)
        lines.append('## Не-дыры (для полноты; задачи на шаблоны НЕ создавать)')
        for (t, z), n in cnt.most_common():
            lines.append(f'- {t} / {z}: {n} сцен')
    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'OK: {len(gaps)} событий ({len(true_gaps)} истинных) → {OUT}')


if __name__ == '__main__':
    main()
