"""P2 свода №12: beam по планировочным гипотезам — инварианты.

- greedy-результат всегда гипотеза №0 (среди кандидатов);
- выбранный план лексикографически не хуже greedy по plan_key;
- детерминизм: два запуска — одинаковый выбор и ключ;
- enumerate_k: первый вариант == single-результат place_template;
- конфиг beam с пруфом.
"""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules')


def _scene():
    from planner.models import Item, Room
    room = Room(width_cm=520, depth_cm=430, openings=[])
    items = [Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
             Item(role='кресло', w_cm=80, d_cm=85, h_cm=80),
             Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
             Item(role='ковёр', w_cm=200, d_cm=140, h_cm=1),
             Item(role='тв-тумба', w_cm=160, d_cm=45, h_cm=50),
             Item(role='стол обеденный', w_cm=120, d_cm=75, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стеллаж', w_cm=80, d_cm=35, h_cm=180)]
    return room, items


def test_beam_config_has_proof():
    z = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    b = z['beam']
    assert b['enabled'] is True
    assert 1 <= int(b['ladder_steps']) <= 6 and 1 <= int(b['blocks_per_step']) <= 8
    assert 'greedy' in b['_why'].lower() or 'гипотез' in b['_why']


def test_enumerate_first_equals_single():
    from planner.template import place_template
    from planner.zones import usable_polygon
    room, items = _scene()
    one = place_template(room, 'sofa_armchair', items, usable_polygon(room))
    many = place_template(room, 'sofa_armchair', items, usable_polygon(room), enumerate_k=4)
    assert one and many and len(many) >= 1
    k = lambda ps: [(p.role, round(p.x), round(p.y), int(p.rot) % 360) for p in ps]
    assert k(many[0]) == k(one), 'первый вариант перечисления обязан совпадать с single'


def test_greedy_is_hypothesis_zero_and_not_worse():
    from planner.zones import solve_zoned, solve_zoned_beam
    room, items = _scene()
    outs_b, gid_b = solve_zoned_beam(room, items)
    outs_g, gid_g = solve_zoned(room, items)
    assert outs_b and outs_b[0].placements
    bm = outs_b[0].meta.get('beam')
    assert bm and bm['hypotheses'][0]['name'] == 'greedy'
    assert bm['hypotheses'][0]['gid'] == gid_g
    assert tuple(bm['chosen_key']) <= tuple(bm['greedy_key'])


def test_beam_deterministic():
    from planner.zones import solve_zoned_beam
    room, items = _scene()
    a, ga = solve_zoned_beam(room, items)
    b, gb = solve_zoned_beam(room, items)
    assert ga == gb
    ka = a[0].meta['beam']['chosen_key']; kb = b[0].meta['beam']['chosen_key']
    assert ka == kb and a[0].meta['beam']['chosen'] == b[0].meta['beam']['chosen']
    pa = [(p.role, round(p.x), round(p.y)) for p in a[0].placements]
    pb = [(p.role, round(p.x), round(p.y)) for p in b[0].placements]
    assert pa == pb
