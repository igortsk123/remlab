#!/usr/bin/env python3
"""ПЕРЕПИСЬ КРОВАТЕЙ ПО ШИРИНЕ СПАЛЬНОГО МЕСТА (T-20261110-02): сколько кроватей каталога и банка спальни с готовой живой моделью
(тот же сторож, что у стадии спален — `flat215_demo.room_mesh_gate('bedroom')`) в каждой полосе ширины — узкие 90–100 и 120
отдельно, без отсева узких (стадия их отсекает `trial_bedroom._bed_ok`). Только чтение БД и индекса — 0 $.

  ~/venvs/scout/bin/python tools/scout/bed_census.py [--json <файл>]
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trial_bedroom as B  # noqa: E402

BANDS = ((0, 85, '<85'), (85, 105, '90–100'), (105, 115, '110'), (115, 125, '120'), (125, 135, '130'), (135, 145, '140'),
         (145, 155, '150'), (155, 165, '160'), (165, 175, '170'), (175, 999, '180+'))


def band(sw: float) -> str:
    return next(lab for lo, hi, lab in BANDS if lo <= sw < hi)


def census(ctx: dict | None = None) -> dict:
    ctx = ctx or B.default_ctx()
    rows = {}
    for st in B.STYLES:
        for it in B.bank_pool(ctx['bank'], st, 'кровать'):
            rows.setdefault(B._sid(it), dict(it, _styles=set()))['_styles'].add(st)
    for c in ctx['catalog']:
        if 'кровать' not in c.roles:
            continue
        d = c.dims
        sid = f'{c.mid}:{c.eid}'
        r = rows.setdefault(sid, {'mid': c.mid, 'eid': c.eid, 'sid': sid, 'name': c.name or '', 'w': d.get('w'), 'd': d.get('d'),
                                  'h': d.get('h'), 'sleep_w': d.get('sleep_w'), '_styles': set()})
        r['_styles'].update(s for s in B.STYLES if _in_style(c, s, ctx['thr']))
    out = {lab: {'all': 0, 'ready': 0, 'ready_in_style': 0, 'examples': []} for _, _, lab in BANDS}
    for r in rows.values():
        if not (r.get('w') and r.get('d')):
            continue
        lab = band(B._sleep_w(r))
        cell = out[lab]
        cell['all'] += 1
        if B._ready(r, ctx['mesh_ok'], ctx['defect']):
            cell['ready'] += 1
            if r['_styles']:
                cell['ready_in_style'] += 1
            if len(cell['examples']) < 6:
                cell['examples'].append({'sid': r['sid'], 'w': r['w'], 'd': r['d'], 'sleep_w': r.get('sleep_w'),
                                         'styles': sorted(r['_styles'])})
    return {'bands': out, 'catalog_error': ctx.get('catalog_error') or '', 'total': len(rows)}


def _in_style(c, style: str, thr: float) -> bool:
    import room_profile as RP
    return bool(RP.in_style(c.style, style, thr))


def main() -> int:
    args = sys.argv[1:]
    res = census()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if '--json' in args:
        B.TD._write(args[args.index('--json') + 1], res)
    return 0


if __name__ == '__main__':
    sys.exit(main())
