"""Пакет D свода №8 (MASTER-zones-v2): виртуальная плоскость экрана media-шаблона.

Сторожа: SCREEN_OVER_WINDOW (H0) бьёт носитель спиной к оконной стене с экраном на
проёме; низкая тумба у окна БЕЗ горизонтального перекрытия легальна; ширина экрана
берётся из canonical-конфига (share/ниша), не из кода.
"""
from planner.models import Item, Opening, Placement, Room
from planner.tv import screen_width_cm
from planner.validate import check_openings


def _room():
    return Room(width_cm=500, depth_cm=450,
                openings=[Opening(kind='window', wall='south', offset_cm=180,
                                  width_cm=140, sill_cm=90)])


def _stand(x, rot=0.0, w=160.0):
    it = Item(role='тв-тумба', w_cm=w, d_cm=40, h_cm=50)
    return Placement(role='тв-тумба', x=x, y=20, rot=rot, item=it)


def test_screen_over_window_fires():
    # тумба спиной к южной стене, центр напротив окна (180..320) → экран на проёме
    vs = check_openings(_room(), [_stand(250)])
    assert any(v.code == 'SCREEN_OVER_WINDOW' for v in vs), [v.code for v in vs]
    # сам носитель низкий (50 < подоконник 90) — WINDOW_BLOCKED молчит
    assert not any(v.code == 'WINDOW_BLOCKED' for v in vs)


def test_low_stand_off_window_is_legal():
    # та же стена, но носитель сдвинут: экран (min-ширина) не накрывает проём
    vs = check_openings(_room(), [_stand(60)])
    assert not any(v.code == 'SCREEN_OVER_WINDOW' for v in vs), [v.code for v in vs]


def test_facing_wall_not_penalized():
    # носитель у СЕВЕРНОЙ стены (спина north, rot 180) — окно на юге не при чём
    it = Item(role='тв-тумба', w_cm=160, d_cm=40, h_cm=50)
    p = Placement(role='тв-тумба', x=250, y=430, rot=180, item=it)
    vs = check_openings(_room(), [p])
    assert not any(v.code == 'SCREEN_OVER_WINDOW' for v in vs)


def test_screen_width_from_canonical_rules():
    lo = screen_width_cm(160, 'тв-тумба', 'min')
    hi = screen_width_cm(160, 'тв-тумба', 'max')
    assert 0 < lo < hi <= 160
    # стенка: ниша, clamp половиной ширины
    assert screen_width_cm(300, 'стенка', 'max') <= 160
    assert screen_width_cm(180, 'стенка', 'max') <= 90
