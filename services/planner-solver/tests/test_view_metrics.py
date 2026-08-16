"""Q0 свода №13: метрики «как видит владелец» — только диагностика.

Fixtures: прямоугольник, несколько дверей, стенка как носитель; направление метрик
совпадает со слепой оценкой раунда 1 (pair05/07/10) на синтетических аналогах.
Инвариант Q0: view_metrics нигде не импортируется солвером (выбор плана не меняется).
"""
import glob
import os

from planner.models import Item, Opening, Placement, Room
from planner.view_metrics import (armchair_tv_angles, dining_view_cone_overlap_pct,
                                  entry_sightline_gap_cm, frontal_companions,
                                  realized_seating, view_metrics)

PLANNER = os.path.join(os.path.dirname(__file__), '..', 'planner')


def _pl(role, x, y, rot, w, d, h=80):
    return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))


def _room(doors):
    return Room(width_cm=500, depth_cm=400,
                openings=[Opening(kind='door', wall=w, offset_cm=o, width_cm=90, swing_cm=90) for w, o in doors])


def test_entry_sightline_gap_door_in_corridor_vs_aside():
    # диван у северной стены смотрит на юг (rot=180), ТВ у южной стены по оси x=250
    ps = [_pl('диван', 250, 350, 180, 200, 90), _pl('тв-тумба', 250, 20, 0, 140, 40, 50)]
    in_cor = entry_sightline_gap_cm(_room([('south', 205)]), ps)   # дверь прямо под ТВ/в коридоре
    aside = entry_sightline_gap_cm(_room([('west', 100)]), ps)     # дверь сбоку
    assert in_cor is not None and aside is not None
    assert in_cor < aside and in_cor <= 5.0


def test_armchair_angle_media_capable_vs_facing_sofa():
    tv = _pl('тв-тумба', 250, 20, 0, 140, 40, 50)
    sofa = _pl('диван', 250, 350, 180, 200, 90)
    to_tv = _pl('кресло', 80, 200, 180, 80, 85)      # смотрит на юг, ТВ впереди-справа
    to_sofa = _pl('кресло', 80, 200, 0, 80, 85)      # смотрит на север (к дивану), ТВ сзади
    a1 = armchair_tv_angles([tv, sofa, to_tv])[0]
    a2 = armchair_tv_angles([tv, sofa, to_sofa])[0]
    assert a1 <= 45.0 < a2


def test_dining_in_view_cone_vs_behind_sofa():
    room = _room([('west', 100)])
    tv = _pl('тв-тумба', 250, 20, 0, 140, 40, 50)
    sofa = _pl('диван', 250, 300, 180, 200, 90)
    table_front = _pl('стол обеденный', 400, 120, 0, 120, 80, 75)   # между диваном и ТВ, в конусе
    table_back = _pl('стол обеденный', 400, 370, 0, 120, 80, 75)    # за спинкой
    front = dining_view_cone_overlap_pct(room, [tv, sofa, table_front])
    back = dining_view_cone_overlap_pct(room, [tv, sofa, table_back])
    assert front is not None and back is not None
    assert front > 50.0 and back < 10.0


def test_frontal_companions_on_tv_wall_only():
    tv = _pl('тв-тумба', 250, 20, 0, 140, 40, 50)
    on_wall = _pl('стеллаж', 60, 18, 0, 80, 35, 190)
    other_wall = _pl('витрина', 20, 200, 90, 80, 40, 190)
    comps = frontal_companions(_room([]), [tv, on_wall, other_wall])
    assert comps == ['стеллаж']


def test_realized_seating_footrest_vs_flex():
    sofa = _pl('диван', 250, 300, 180, 200, 90)
    near = _pl('пуф', 250, 200, 0, 45, 45, 42)     # в зоне ног
    far = _pl('пуф', 30, 30, 0, 45, 45, 42)        # в углу — flex-seat
    r = realized_seating([sofa, near, far])
    assert r == {'armchairs': 0, 'footrest': 1, 'flex_seats': 1, 'sofas': 1}


def test_wall_unit_as_carrier_and_full_dict():
    room = _room([('west', 100)])
    ps = [_pl('диван', 250, 350, 180, 200, 90), _pl('стенка', 250, 22, 0, 260, 45, 190)]
    m = view_metrics(room, ps)
    assert set(m) >= {'entry_sightline_gap_cm', 'armchair_tv_angles', 'dining_view_cone_overlap_pct',
                      'frontal_companions', 'seating', 'sofa_tv_dist_cm'}
    assert m['sofa_tv_dist_cm'] and m['sofa_tv_dist_cm'] > 200


def test_view_metrics_not_used_by_solver():
    """Q0/Q4: диагностика; читает её ТОЛЬКО plan_key_v2 (Q4, shadow) в zones.py —
    validate/score/template/candidates её не импортируют (hard-правила и формы не зависят)."""
    for f in glob.glob(os.path.join(PLANNER, '*.py')):
        if os.path.basename(f) in ('view_metrics.py', 'zones.py'):
            continue
        src = open(f, encoding='utf-8').read()
        assert 'import view_metrics' not in src and 'from .view_metrics' not in src \
            and 'view_metrics import' not in src, \
            f'{os.path.basename(f)} импортирует view_metrics — запрещено (выбор не меняется)'
