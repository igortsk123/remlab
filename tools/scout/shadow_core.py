#!/usr/bin/env python3
"""V4-H2 свода №10: DINING-AWARE CORE SHADOW — только диагностика, продакшен не меняет.

Для сцен класса «medium/large + dining EDGE + island_infeasible»: перебираем
альтернативные hard-valid ПОЗИЦИИ той же посадочной ступени (carve выбранной позиции,
как V3-D) и dry-run классов dining на каждой. Отчёт: дал бы другой core остров?

Запуск:  ~/venvs/scout/bin/python shadow_core.py set68-base set68-long ...
или без аргументов — автоотбор по последнему экзамену (medium/large, edge, infeasible).
Активация по §40 советника: пропускаем сцены, где usable-регион после дверного резерва
заведомо не вмещает dining (проба региона на ПУСТОЙ комнате).
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from planner.geometry import footprint  # noqa: E402
from planner.models import Item, Opening, Room  # noqa: E402
from planner.template import (dining_island_feasible, place_dining,  # noqa: E402
                              place_template)
from planner.zones import usable_polygon, usable_m2  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def _scene_room_items(sid: str):
    scenes = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))
    sc = next(s for s in scenes if s['id'] == sid)
    art = glob.glob(os.path.join(HERE, f"v3set{sc['set']}-layout-acc-zoned-{sid}.json"))
    a = json.load(open(art[0]))
    rm = a['_room']
    room = Room(width_cm=rm['w'], depth_cm=rm['d'],
                contour=[tuple(p) for p in rm['contour']] if rm.get('contour') else None,
                openings=[Opening(**{k: v for k, v in op.items()
                                     if k in ('kind', 'wall', 'offset_cm', 'width_cm',
                                              'swing_cm', 'sill_cm')})
                          for op in (rm.get('openings') or [])])
    sets_ = json.load(open(os.path.join(HERE, 'sets3.json')))
    items = []
    for r, d in (sets_[sc['set'] - 1].get('items') or {}).items():
        if not isinstance(d, dict):
            continue
        kw = {}
        if r == 'диван' and (a.get('диван') or {}).get('corner'):
            kw = dict(corner=True,
                      corner_section_cm=(a['диван'].get('section') or 95),
                      corner_left=bool(a['диван'].get('corner_left')))
        items.append(Item(role=r, w_cm=float(d.get('w') or 60),
                          d_cm=float(d.get('d') or 60), h_cm=(d.get('h') or None),
                          name=d.get('name'), **kw))
    ss = a.get('_seating_search') or {}
    step = next((k for k, v in ss.items() if v.get('winner')), None)
    return room, items, step, a


def shadow(sid: str, alts: int = 3) -> dict:
    room, items, step, art = _scene_room_items(sid)
    tbl = next((i for i in items if i.role == 'стол обеденный'), None)
    out = {'scene': sid, 'step': step, 'alternatives': []}
    if tbl is None or step is None:
        out['skip'] = 'нет стола или ступени'
        return out
    up = usable_polygon(room)
    # §40: регион в ПУСТОЙ usable-комнате вообще способен вместить остров?
    if not dining_island_feasible(tbl, up):
        out['skip'] = 'регион после дверного резерва не вмещает остров даже пустым'
        return out
    carve = None
    for n in range(alts + 1):
        free = up if carve is None else up.difference(carve)
        blk = place_template(room, step, items, free)
        if not blk:
            break
        sofa = next((p for p in blk if p.role.split(' ')[0] == 'диван'), blk[0])
        occ = unary_union([footprint(p) for p in blk
                           if p.role.split(' ')[0] != 'ковёр'])
        din_free = up.difference(occ)
        import planner.template as T
        ps = place_dining(room, items, din_free, usable_m2(room), fixed=list(blk))
        d = T.LAST_DINING_DIAG or {}
        out['alternatives'].append({
            'n': n, 'sofa': [round(sofa.x), round(sofa.y), int(sofa.rot)],
            'dining_placed': ps is not None,
            'mode_path': d.get('mode_path'), 'mode': d.get('mode'),
            'island_feasible': d.get('island_feasible')})
        carve = footprint(sofa).buffer(25) if carve is None \
            else carve.union(footprint(sofa).buffer(25))
    isl = [a for a in out['alternatives'][1:]
           if a['dining_placed'] and (a.get('mode_path') or '').endswith('island')]
    out['verdict'] = ('ALT-CORE ДАЁТ ОСТРОВ — search gap' if isl else
                      'остров не достижим и с альтернативных позиций')
    return out


def main():
    sids = sys.argv[1:]
    if not sids:
        rows = [json.loads(l) for l in open(os.path.join(HERE,
                'acceptance-report-zoned.jsonl'))]
        for r in rows:
            f = glob.glob(os.path.join(
                HERE, f"v3set{r['set']}-layout-acc-zoned-{r['scene']}.json"))
            if not f:
                continue
            a = json.load(open(f[0]))
            d = a.get('_dining') or {}
            rm = a.get('_room') or {}
            m2 = (rm.get('w', 0) * rm.get('d', 0)) / 10_000
            if m2 >= 22 and (d.get('mode_path') == 'edge') \
                    and d.get('island_feasible') is False:
                sids.append(r['scene'])
        sids = sids[:12]
        print(f'автоотбор: {len(sids)} сцен: {sids}')
    report = [shadow(s) for s in sids]
    outp = os.path.join(HERE, 'shadow-core-report.json')
    json.dump(report, open(outp, 'w'), ensure_ascii=False, indent=1)
    gaps = [r['scene'] for r in report if 'ALT-CORE' in (r.get('verdict') or '')]
    print(f'OK → {outp}; сцен {len(report)}, доказанных search-gap: {len(gaps)} {gaps}')


if __name__ == '__main__':
    main()
