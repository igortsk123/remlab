"""Пакет B свода №8 (MASTER-zones-v2): объяснимость выбора dining.

Сторожа: solve_zoned кладёт в Layout.meta['dining'] диагноз (mode / island_feasible /
why_selected / fallback_reason); island_feasible-проба отличает «остров невозможен»
от «кандидаты не нашли».
"""
from shapely.geometry import box

from planner.models import Item, Opening, Room
from planner.template import dining_island_feasible
from planner.zones import solve_zoned


def _scene_items():
    return [Item(role='диван', w_cm=190, d_cm=95, h_cm=85),
            Item(role='столик', w_cm=120, d_cm=50, h_cm=40),
            Item(role='ковёр', w_cm=230, d_cm=160, h_cm=1),
            Item(role='тв-тумба', w_cm=120, d_cm=38, h_cm=50),
            Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75),
            Item(role='стул', w_cm=45, d_cm=50, h_cm=85),
            Item(role='стул 2', w_cm=45, d_cm=50, h_cm=85)]


def test_meta_dining_present_when_placed():
    room = Room(width_cm=520, depth_cm=460,
                openings=[Opening(kind='door', wall='south', offset_cm=86, width_cm=90),
                          Opening(kind='window', wall='east', offset_cm=140, width_cm=158)])
    lays, gid = solve_zoned(room, _scene_items())
    assert lays and lays[0].placements
    d = lays[0].meta.get('dining')
    assert isinstance(d, dict), 'диагноз dining обязан попадать в meta'
    assert d.get('island_feasible') in (True, False)
    if '+din' in gid:
        assert d.get('mode') in ('full_island', 'compact_island', 'edge')
        assert d.get('why_selected') in (
            'preferred_coverage', 'mandatory_residual_R', 'preferred_coverage+sacrifice')
        if d['mode'] == 'edge':
            assert d.get('fallback_reason'), 'edge без причины — «тихий edge» запрещён'
    else:
        assert d.get('why_selected') == 'not_placed'


def test_island_feasible_probe_distinguishes():
    tbl = Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75)
    # просторно: 5×5 м пустого пола — остров очевидно возможен
    assert dining_island_feasible(tbl, box(0, 0, 500, 500))
    # тесно: полоса 500×150 — стол+2×90 см не помещается ни в одной ориентации
    assert not dining_island_feasible(tbl, box(0, 0, 500, 150))
