#!/usr/bin/env python3
"""V4-C свода №10: диагностика композитора — только чтение, sets3.json НЕ трогает.

C1: сцены, где в банке нет кресла (роль есть в composition band) — список.
C2: dry-run «виртуальное кресло»: добавляем кресло В ПАМЯТИ к банку таких сцен и
решаем солвером — выиграла бы armchair-ступень? (продакшен-банк не меняется).

Запуск: ~/venvs/scout/bin/python composer_dryrun.py [N сцен для dry-run, default 6]
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from planner.models import Item, Opening, Room  # noqa: E402
from planner.zones import solve_zoned  # noqa: E402


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sets_ = json.load(open(os.path.join(HERE, 'sets3.json')))
    scenes = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))
    no_arm = []
    for i, st in enumerate(sets_, 1):
        items = st.get('items') or {}
        if 'диван' in items and 'кресло' not in items \
                and 14 <= (st.get('m2') or 0):
            no_arm.append((i, st.get('m2'), st.get('band'), st.get('style')))
    print(f'C1: сетов с диваном БЕЗ кресла (≥14 м²): {len(no_arm)} из {len(sets_)}')
    for n, m2, band, style in no_arm[:20]:
        print(f'  set{n}: {m2} м², band {band}, стиль {style}')
    # C2: dry-run на сценах base этих сетов
    results = []
    done = 0
    for n, m2, band, style in no_arm:
        if done >= lim:
            break
        sid = f'set{n}-base'
        sc = next((s for s in scenes if s['id'] == sid), None)
        art = glob.glob(os.path.join(HERE, f'v3set{n}-layout-acc-zoned-{sid}.json'))
        if sc is None or not art:
            continue
        a = json.load(open(art[0]))
        rm = a['_room']
        room = Room(width_cm=rm['w'], depth_cm=rm['d'],
                    contour=[tuple(p) for p in rm['contour']] if rm.get('contour') else None,
                    openings=[Opening(**{k: v for k, v in op.items()
                                         if k in ('kind', 'wall', 'offset_cm',
                                                  'width_cm', 'swing_cm', 'sill_cm')})
                              for op in (rm.get('openings') or [])])
        items = [Item(role=r, w_cm=float(d.get('w') or 60),
                      d_cm=float(d.get('d') or 60), h_cm=(d.get('h') or None),
                      name=d.get('name'))
                 for r, d in (sets_[n - 1].get('items') or {}).items()
                 if isinstance(d, dict)]
        # ВИРТУАЛЬНОЕ кресло (типовой габарит каталога) — только в памяти
        virt = items + [Item(role='кресло', w_cm=75, d_cm=82, h_cm=80,
                             name='ВИРТУАЛЬНОЕ (dry-run)')]
        lays, gid = solve_zoned(room, virt)
        win = (gid or '').split('+')[0]
        used_arm = bool(lays and lays[0].placements and
                        any(p.role == 'кресло' for p in lays[0].placements))
        results.append({'scene': sid, 'm2': m2, 'winner': win,
                        'virtual_armchair_used': used_arm})
        done += 1
        print(f'C2 {sid}: победитель {win}, виртуальное кресло '
              f'{"ИСПОЛЬЗОВАНО" if used_arm else "не использовано"}')
    outp = os.path.join(HERE, 'composer-dryrun-report.json')
    json.dump({'sets_without_armchair': no_arm, 'dryrun': results},
              open(outp, 'w'), ensure_ascii=False, indent=1)
    used = sum(1 for r in results if r['virtual_armchair_used'])
    print(f'ИТОГ: dry-run {len(results)} сцен, кресло использовано в {used} → {outp}')


if __name__ == '__main__':
    main()
