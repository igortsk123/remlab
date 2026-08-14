#!/usr/bin/env python3
"""Пакет C свода №8 (MASTER-zones-v2): агрегатор TEMPLATE_GAP по артефактам экзамена.

Читает v3set*-layout-acc-zoned-*.json (артефакты acceptance_run) → missing_templates.md:
какие зоны/классы шаблонов запрашивались, но не были реализованы библиотекой, по каким
причинам и в каких классах комнат. Питает план template-library-v2.
"""
import glob
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'missing_templates.md')


def main() -> None:
    gaps = []
    files = sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json')))
    for f in files:
        try:
            art = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for g in art.get('_template_gaps') or []:
            g = dict(g)
            g['_scene'] = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
            gaps.append(g)
    by_key = defaultdict(list)
    for g in gaps:
        by_key[(g.get('zone'), g.get('requested_mode'), g.get('reason'))].append(g)
    lines = ['# Дыры библиотеки шаблонов (TEMPLATE_GAP) — по последнему экзамену\n',
             f'Артефактов просмотрено: {len(files)}; событий: {len(gaps)}.\n']
    for (zone, mode, reason), gg in sorted(by_key.items(),
                                           key=lambda kv: -len(kv[1])):
        rooms = Counter(g.get('room_class') for g in gg)
        scenes = ', '.join(sorted(g['_scene'] for g in gg)[:12])
        more = '' if len(gg) <= 12 else f' … (+{len(gg) - 12})'
        lines.append(f'## {zone} / {mode} — {reason}: {len(gg)} сцен')
        lines.append(f'- классы комнат: ' +
                     ', '.join(f'{k}×{v}' for k, v in rooms.most_common()))
        lines.append(f'- сцены: {scenes}{more}\n')
    if not gaps:
        lines.append('Дыр не зафиксировано: все запрошенные зоны реализованы '
                     'существующими шаблонами (или зоны не запрашивались).')
    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'OK: {len(gaps)} событий → {OUT}')


if __name__ == '__main__':
    main()
