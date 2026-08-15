"""V4-F свода №10 (MASTER-zones-v4): role-скоуп правил за спинкой дивана.

Q42: TALL_(SOLID_)BEHIND_SOFA — про высокое ГЛУХОЕ хранение; обеденный стул за
floating-диваном легален (ADR-0078: столовая за спинкой — канонный приём).
"""
from planner.models import Item, Opening, Placement, Room
from planner.validate import validate


def _room():
    return Room(width_cm=460, depth_cm=520,
                openings=[Opening(kind='door', wall='south', offset_cm=40,
                                  width_cm=90, swing_cm=92)])


def _sofa_floating():
    # диван отодвинут, спинка на юг — за спинкой полоса ~180 см
    return Placement(role='диван', x=230, y=280, rot=0,
                     item=Item(role='диван', w_cm=200, d_cm=95, h_cm=85))


def test_dining_chair_behind_sofa_legal():
    ps = [_sofa_floating(),
          Placement(role='стол обеденный', x=230, y=120, rot=0,
                    item=Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75)),
          Placement(role='стул', x=230, y=40, rot=0,
                    item=Item(role='стул', w_cm=45, d_cm=50, h_cm=103)),
          Placement(role='стул 2', x=230, y=200, rot=180,
                    item=Item(role='стул 2', w_cm=45, d_cm=50, h_cm=103))]
    codes = {v.code for v in validate(_room(), ps).violations}
    assert 'TALL_SOLID_BEHIND_SOFA' not in codes, codes


def test_tall_storage_behind_sofa_still_banned():
    ps = [_sofa_floating(),
          Placement(role='стеллаж', x=230, y=140, rot=0,
                    item=Item(role='стеллаж', w_cm=120, d_cm=40, h_cm=200))]
    codes = {v.code for v in validate(_room(), ps).violations}
    assert 'TALL_SOLID_BEHIND_SOFA' in codes, codes
