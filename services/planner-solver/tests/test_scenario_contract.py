"""P0 свода №12 (MASTER-zones-v6): единый контракт метрик и сценариев.

- один источник капа пола: solver (validate/score band_scale) и композитор читают
  occupancy.json → dynamic.floor_cap_pct; плоская floor_cap_pct — указатель, не таблица;
- scenario_needs: media_need/dining_need — вход из данных с общепринятыми дефолтами
  (media=required, dining=preferred), override через kw, off выключает зону.
"""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules')
SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def _occ():
    return json.load(open(os.path.join(RULES, 'occupancy.json'), encoding='utf-8'))


def test_single_floor_cap_source():
    o = _occ()
    flat = o['floor_cap_pct']
    # плоская таблица больше не содержит band-ключей — только указатель/историю
    assert not any(k in flat for k in ('14-16', '31-40', '50+')), \
        'плоская floor_cap_pct снова стала таблицей — вторая истина капа'
    assert '_deprecated_pointer' in flat
    dyn = o['dynamic']['floor_cap_pct']
    for band in ('14-16', '17-20', '21-25', '26-30', '31-40', '41-50', '50+'):
        lo, hi = dyn[band]
        assert 0 < lo < hi <= 60
    # композитор читает dynamic (OCC = occupancy['dynamic']) и floor_cap_pct из него
    src = open(os.path.join(SCOUT, 'compose2.py'), encoding='utf-8').read()
    assert "['dynamic']" in src.split('OCC=')[1].split('\n')[0]
    assert "OCC['floor_cap_pct']" in src


def test_composer_cap_equals_solver_cap():
    from planner.clearances import band_scale
    o = _occ()
    dyn = o['dynamic']['floor_cap_pct']
    for band, v in dyn.items():
        if band.startswith('_'):
            continue
        lo, hi = v
        assert band_scale('floor_cap_pct', band, [0, 0]) == [lo, hi]


def test_scenario_needs_defaults_and_override():
    from planner.zones import scenario_needs
    d = scenario_needs()
    assert d == {'media': 'required', 'dining': 'preferred'}, d
    assert scenario_needs(dining_need='off')['dining'] == 'off'
    assert scenario_needs(media_need='off')['media'] == 'off'
    # мусор → дефолт, не тихий off
    assert scenario_needs(media_need='whatever')['media'] == 'required'


def test_scenario_needs_have_provenance():
    z = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    sn = z['zone_priority']['scenario_needs']
    for k in ('media_need', 'dining_need'):
        assert sn[k]['default'] in sn[k]['values']
        assert len(sn[k].get('why', '')) > 40, f'{k}: нужен пруф/источник'


def test_dining_off_removes_dining_zone():
    """dining_need=off: цепочка не зовёт place_dining, +din не появляется."""
    from planner.models import Item, Room
    from planner.zones import solve_zoned
    room = Room(width_cm=600, depth_cm=450, openings=[])
    items = [Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
             Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
             Item(role='тв-тумба', w_cm=160, d_cm=45, h_cm=50),
             Item(role='стол обеденный', w_cm=140, d_cm=80, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=90)]
    outs, gid = solve_zoned(room, items, dining_need='off')
    assert outs
    assert '+din' not in gid, gid
    assert not any(p.role == 'стол обеденный' for p in outs[0].placements)
    assert outs[0].meta.get('scenario_needs', {}).get('dining') == 'off'
