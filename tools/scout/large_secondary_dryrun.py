#!/usr/bin/env python3
"""V4-J свода №10: dry-run ВТОРОЙ разговорной зоны (существующий armchair_pair /
quiet) в больших комнатах с крупным незакреплённым регионом. Только диагностика.

Запуск: ~/venvs/scout/bin/python large_secondary_dryrun.py [мин_м² unassigned, деф. 12]
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from planner.geometry import footprint  # noqa: E402
from planner.models import Item, Opening, Placement, Room  # noqa: E402
from planner.template import build_quiet, place_quiet  # noqa: E402
from planner.zones import usable_polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def main():
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    sets_ = json.load(open(os.path.join(HERE, 'sets3.json')))
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json'))):
        a = json.load(open(f))
        rm = a.get('_room') or {}
        m2 = (rm.get('w', 0) * rm.get('d', 0)) / 10_000
        zc = ((a.get('_axes') or {}).get('zone_cohesion') or {})
        if m2 < 35 or zc.get('largest_unassigned_m2', 0) < thr:
            continue
        sid = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
        n = int(sid.split('-')[0].replace('set', ''))
        bank = sets_[n - 1].get('items') or {}
        has_pair = 'кресло 3' in bank and 'кресло 4' in bank
        rec = {'scene': sid, 'm2': round(m2, 1),
               'unassigned_m2': zc.get('largest_unassigned_m2'),
               'chairs34_in_bank': has_pair, 'quiet_placed_now':
               any(r.startswith('кресло 3') for r in a if isinstance(a.get(r), dict))}
        if has_pair and not rec['quiet_placed_now']:
            room = Room(width_cm=rm['w'], depth_cm=rm['d'],
                        contour=[tuple(p) for p in rm['contour']] if rm.get('contour') else None,
                        openings=[Opening(**{k: v for k, v in op.items()
                                             if k in ('kind', 'wall', 'offset_cm',
                                                      'width_cm', 'swing_cm', 'sill_cm')})
                                  for op in (rm.get('openings') or [])])
            fixed = [Placement(role=r, x=v['x'], y=v['z'], rot=float(v.get('rot') or 0),
                               item=Item(role=r, w_cm=v.get('w') or 40,
                                         d_cm=v.get('d') or 40, h_cm=80))
                     for r, v in a.items()
                     if not r.startswith('_') and isinstance(v, dict) and 'x' in v]
            items = [Item(role=r, w_cm=float(d.get('w') or 60),
                          d_cm=float(d.get('d') or 60), h_cm=(d.get('h') or None))
                     for r, d in bank.items() if isinstance(d, dict)]
            occ = unary_union([footprint(p) for p in fixed
                               if p.role.split(' ')[0] != 'ковёр'])
            free = usable_polygon(room).difference(occ)
            got = place_quiet(room, items, free, fixed=fixed)
            rec['quiet_dryrun_places'] = bool(got)
        out.append(rec)
    outp = os.path.join(HERE, 'large-secondary-report.json')
    json.dump(out, open(outp, 'w'), ensure_ascii=False, indent=1)
    cand = [r for r in out if r.get('quiet_dryrun_places')]
    nb = [r for r in out if not r['chairs34_in_bank']]
    print(f'OK → {outp}: больших сцен с unassigned≥{thr}: {len(out)}; '
          f'вторая зона (quiet) встаёт dry-run: {len(cand)}; '
          f'нет кресел 3/4 в банке: {len(nb)} (вопрос к композитору)')


if __name__ == '__main__':
    main()
