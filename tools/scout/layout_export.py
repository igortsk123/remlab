#!/usr/bin/env python3
"""Экспорт раскладок в машиночитаемый JSON для внешнего ИИ (вопрос владельца 08.08:
«JSON или фотки?» — JSON первичен, план-PNG вторичная проверка).

Самодостаточный формат: система координат и единицы описаны В САМОМ файле (_schema), чтобы
внешняя модель ничего не угадывала. Источник — те же v3setN-layout.json, что рисует план.

  ~/venvs/scout/bin/python layout_export.py 1 14 21 ...       # → ~/scout-scenes/layout10/layouts.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.path.expanduser(os.environ.get('SCENE_DIR', '~/scout-scenes'))
OUT = os.path.join(SCENE_DIR, 'layout10', 'layouts.json')

SCHEMA = {
    'units': 'centimeters',
    'coordinates': ('origin = south-west corner of the room; x grows east (room width), '
                    'y grows north (room depth); every position is the CENTER of the item '
                    'footprint'),
    'rotation': ('degrees; 0 = item faces north (+y), 90 = faces east (+x), 180 = south, '
                 '270 = west; footprint w×d swaps at 90/270'),
    'openings': ('wall ∈ {south,north,west,east}; offset_cm — from the wall start '
                 '(south/north: from west corner; west/east: from south corner); '
                 'sill_cm — height of window glass bottom above floor'),
    'items': ('role — functional role (Russian); w/d/h — width/depth/height of the SKU; '
              'name/product — catalog item; skipped — roles the solver honestly dropped '
              '(retention-priority tiers), not a failure'),
}


_ZONES = json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver',
                                     'rules', 'zones.json')))
_GROUPS = {g['id']: g for g in _ZONES['seating_groups']}


def _base(r):
    p = r.rsplit(' ', 1)
    return p[0] if len(p) == 2 and p[1].isdigit() else r


def group_slots(requested: str, set_items: set, placed: set) -> tuple[list, str]:
    """P0.1/P0.7 (ревью рефери 08.08): каждый слот заявленной группы обязан иметь terminal
    state — ни один не «исчезает». actual_group — самая вместительная группа, чьи required
    покрыты фактически размещёнными посадочными ролями."""
    g = _GROUPS.get(requested)
    slots = []
    if g:
        for role in list(g['roles'].get('required', [])) + list(g['roles'].get('optional', [])) :
            kind = 'required' if role in g['roles'].get('required', []) else 'optional'
            if role in placed:
                st = 'PLACED'
            elif role in set_items:
                st = 'DROPPED'          # был в составе, солвер честно снял
            else:
                st = 'NOT_IN_CATALOG'   # состав не смог набрать роль (гейт/дефицит SKU)
            slots.append({'slot': role, 'kind': kind, 'state': st})
    actual = None
    for gid, gg in sorted(_GROUPS.items(), key=lambda kv: -kv[1]['seats']):
        req = set(gg['roles'].get('required', []))
        if req and req <= placed:
            actual = gid
            break
    seats_placed = {r for r in placed if _base(r) in ('диван', 'кресло', 'пуф')}
    return slots, (actual or ('/'.join(sorted(seats_placed)) or 'none'))


def export_one(n: int) -> dict:
    L = json.load(open(os.path.join(HERE, f'v3set{n}-layout.json')))
    room = L.pop('_room')
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]
    items = []
    for role, p in L.items():
        it = (s['items'].get(role) or {})
        items.append({
            'role': role, 'name': it.get('name'),
            'w_cm': p['w'], 'd_cm': p['d'], 'h_cm': it.get('h'),
            'x_cm': round(p['x'], 1), 'y_cm': round(p['z'], 1), 'rot_deg': int(p['rot']) % 360,
        })
    in_set = set(s.get('items', {}))
    placed = set(L)
    slots, actual = group_slots(s.get('group') or '', in_set, placed)
    # P0.2 QA: перепроверка РЕКОНСТРУКЦИИ канон-валидатором (scene_build → validate) —
    # экспорт не имеет права отдавать наружу геометрию, отличную от решённой (set66)
    recheck = []
    try:
        sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
        sys.path.insert(0, HERE)
        from scene_build import load_scene
        from planner.validate import validate
        from planner.models import Severity
        rm, ps = load_scene(n)
        # только напольные роли самой раскладки: производные сцены (подушки НА диване,
        # ТВ НА тумбе, плед) законно «пересекаются» в проекции пола
        floor_ps = [p for p in ps if p.role in placed]
        recheck = sorted({v.code for v in validate(rm, floor_ps).violations
                          if v.severity is Severity.HARD})
    except Exception as e:  # QA не должна валить экспорт, но молчать нельзя
        recheck = [f'RECHECK_ERROR: {e}']
    return {
        'set': n, 'style': s.get('style'), 'band_m2': s.get('band'),
        'requested_group': s.get('group'), 'actual_group': actual,
        'group_slots': slots, 'usable_m2': s.get('usable_m2'),
        'room': {'width_cm': room['w'], 'depth_cm': room['d'],
                 'openings': room.get('openings', [])},
        'items': items,
        'skipped': sorted(r for r in in_set if r not in placed
                          and r.split(' ')[0] not in
                          ('подушка', 'плед', 'шторы', 'люстра', 'ваза', 'лампа', 'картина')),
        'recheck_hard': recheck,
        'plan_png': f'set{n}-plan.png',
    }


def main():
    ns = [int(a) for a in sys.argv[1:] if a.isdigit()] or [1, 14, 21, 29, 55, 59, 66, 84, 113, 117]
    doc = {'_schema': SCHEMA, 'scenes': []}
    for n in ns:
        try:
            doc['scenes'].append(export_one(n))
        except FileNotFoundError:
            print(f'set{n}: нет v3set{n}-layout.json — сперва solver_run/страница', file=sys.stderr)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'{OUT}: {len(doc["scenes"])} сцен')


if __name__ == '__main__':
    main()
