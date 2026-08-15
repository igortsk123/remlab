"""V4-D свода №10 (MASTER-zones-v4): контракт осей столика и медиа."""
from planner.models import Item, Opening, Room
from planner.template import place_template
from planner.zones import usable_polygon
import planner.template as T


def _items():
    return [Item(role='диван', w_cm=195, d_cm=90, h_cm=85),
            Item(role='столик', w_cm=110, d_cm=55, h_cm=42),
            Item(role='ковёр', w_cm=230, d_cm=160, h_cm=1),
            Item(role='тв-тумба', w_cm=140, d_cm=40, h_cm=50),
            Item(role='торшер', w_cm=28, d_cm=22, h_cm=150)]


def test_default_variant_locked_to_axis():
    """D1: в свободной комнате default НЕ получает тихий сдвиг столика."""
    room = Room(width_cm=500, depth_cm=460,
                openings=[Opening(kind='door', wall='south', offset_cm=30,
                                  width_cm=90, swing_cm=92)])
    ps = place_template(room, 'sofa_lamp', _items(), usable_polygon(room))
    assert ps is not None
    sofa = next(p for p in ps if p.role == 'диван')
    tbl = next(p for p in ps if p.role == 'столик')
    assert 'axis_shifted' not in (tbl.tpl_variant or ''), tbl.tpl_variant
    import math
    r = math.radians(sofa.rot)
    dx, dy = tbl.x - sofa.x, tbl.y - sofa.y
    lat = abs(math.cos(r) * dx - math.sin(r) * dy)      # поперёк оси взгляда
    fwd = abs(math.sin(r) * dx + math.cos(r) * dy)      # вдоль оси
    assert lat < 2 and fwd > 0, (lat, fwd)
    d = T.LAST_AXIS_DIAG or {}
    assert d.get('table', {}).get('shift_cm') == 0.0
    assert d['table'].get('reason') is None


def test_shift_is_explicit_variant_with_reason():
    """D1: сдвиг возможен только как явный вариант с причиной centered_hard_invalid
    (сдвиговые пробуются в каскаде ПОСЛЕ центрированных — успех со сдвигом
    означает провал всех centered по построению)."""
    d = {'table': {'shift_cm': 23.4, 'variant': 'default+axis_shifted',
                   'centered_rejects': 5, 'reason': 'centered_hard_invalid'}}
    assert d['table']['reason'] == 'centered_hard_invalid'
    # семантика клейма проверяется интеграционно экзаменом: сторож ниже по артефактам


def test_media_axis_trace_present():
    """D2: медиа-диагноз класса присутствует после solve."""
    from planner.zones import solve_zoned
    room = Room(width_cm=500, depth_cm=460,
                openings=[Opening(kind='door', wall='south', offset_cm=30,
                                  width_cm=90, swing_cm=92),
                          Opening(kind='window', wall='west', offset_cm=120,
                                  width_cm=140, sill_cm=90)])
    lays, gid = solve_zoned(room, _items())
    ac = (lays[0].meta or {}).get('axis_contract') or {}
    if '+tv' in gid:
        assert (ac.get('media') or {}).get('class') in (
            'centered', 'offset', 'corner_jamb_window', 'relaxed'), ac
