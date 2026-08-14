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


def test_cascade_full_island_preferred_in_space():
    """Пакет C: в просторной комнате остров с полным envelope выигрывает у стены."""
    from planner.geometry import room_polygon
    from planner.template import LAST_DINING_DIAG, place_dining  # noqa: F401
    import planner.template as T
    room = Room(width_cm=520, depth_cm=470,
                openings=[Opening(kind='door', wall='south', offset_cm=86, width_cm=90)])
    items = [Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=85),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=85)]
    ps = place_dining(room, items, room_polygon(room), 24.4)
    assert ps is not None
    assert T.LAST_DINING_DIAG['mode'] == 'full_island', T.LAST_DINING_DIAG


def test_cascade_edge_fallback_when_island_infeasible():
    """Пакет C: узкая комната — остров честно невозможен, edge с названной причиной."""
    from planner.geometry import room_polygon
    from planner.template import place_dining
    import planner.template as T
    room = Room(width_cm=500, depth_cm=170,
                openings=[Opening(kind='door', wall='east', offset_cm=40, width_cm=90)])
    items = [Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=85),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=85)]
    ps = place_dining(room, items, room_polygon(room), 8.5)
    d = T.LAST_DINING_DIAG
    assert d['island_feasible'] is False
    if ps is not None:
        assert d['mode'] == 'edge' and d['fallback_reason'] == 'island_infeasible', d


def test_no_silent_edge_in_exam_artifacts():
    """Сторож «тихого edge» (свод №8 v2, ключевой инвариант): остров возможен по
    пробе → edge не выбирается. Скан артефактов последнего экзамена."""
    import glob
    import json as _j
    import os
    import pytest
    arts = glob.glob(os.path.join(os.path.dirname(__file__), '..', '..', '..',
                                  'tools', 'scout', 'v3set*-layout-acc-zoned-*.json'))
    if not arts:
        pytest.skip('нет артефактов экзамена')
    silent = []
    for f in arts:
        try:
            d = (_j.load(open(f, encoding='utf-8')) or {}).get('_dining') or {}
        except Exception:
            continue
        if d.get('island_feasible') and d.get('mode') == 'edge' and \
                d.get('fallback_reason') != 'island_rejected_by_quality_gate':
            silent.append(os.path.basename(f))
    assert not silent, f'тихий edge при возможном острове: {silent}'


def test_search_trace_present():
    """V3-B свода №9: счётчики поиска по классам — в диагнозе."""
    from planner.models import Item, Opening, Room
    from planner.zones import solve_zoned
    room = Room(width_cm=520, depth_cm=460,
                openings=[Opening(kind='door', wall='south', offset_cm=86, width_cm=90),
                          Opening(kind='window', wall='west', offset_cm=140, width_cm=158)])
    lays, gid = solve_zoned(room, _scene_items())
    d = lays[0].meta.get('dining') or {}
    sr = d.get('search') or {}
    assert set(sr) >= {'full_island', 'compact_island', 'edge'}
    if '+din' in gid:
        m = d.get('mode')
        cls = {'full_island': 'full_island', 'compact_island': 'compact_island',
               'edge': 'edge'}[m]
        assert sr[cls].get('hard_valid', 0) >= 1 or d.get('fallback_reason')
        assert sr[cls].get('quality_valid') == 1
    if d.get('gate'):
        assert set(d['gate']) >= {'failed_axes', 'before', 'after'}
