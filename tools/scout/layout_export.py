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
    return {
        'set': n, 'style': s.get('style'), 'band_m2': s.get('band'),
        'seating_group': s.get('group'), 'usable_m2': s.get('usable_m2'),
        'room': {'width_cm': room['w'], 'depth_cm': room['d'],
                 'openings': room.get('openings', [])},
        'items': items,
        'skipped': sorted(r for r in in_set if r not in placed
                          and r.split(' ')[0] not in
                          ('подушка', 'плед', 'шторы', 'люстра', 'ваза', 'лампа', 'картина')),
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
