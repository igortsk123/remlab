"""Аудит Юли 21.08 (план canons-audit-julia): контракты движка, введённые разбором.

№13 — armchair_pair предпочитает паспортный приставной; №27/31 — свет за плечом, не за
спинкой; №28 — в эркере торшер уходит к устью, а не выбрасывается; №41 — простенок между
окон имеет НАСТОЯЩУЮ реализацию (прод-дыра: _window_candidates центрирует по окну);
№46 — консоль короче 2/3 дивана помечается деградацией (+short)."""
from planner.models import Item, Opening, Placement, Room
from planner import template as T
from planner.zones import usable_polygon


def _door(wall='west', off=40):
    return Opening(kind='door', wall=wall, offset_cm=off, width_cm=90, swing_cm=90)


def test_armchair_pair_prefers_side_table():
    by = {'кресло': Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
          'кресло 2': Item(role='кресло 2', w_cm=80, d_cm=82, h_cm=80),
          'столик': Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
          'приставной': Item(role='приставной', w_cm=45, d_cm=45, h_cm=55),
          'ковёр': Item(role='ковёр', w_cm=290, d_cm=200, h_cm=1)}
    b = T.build_block('armchair_pair', by, variant='default')
    assert b is not None
    roles = [it.role for it, *_ in b.rel]
    assert 'приставной' in roles and 'столик' not in roles


def test_reading_lamp_beside_not_behind():
    """Угловой уголок: торшер за плечом (сбоку), а не на оси спинки кресла."""
    room = Room(width_cm=440, depth_cm=420, openings=[_door()])
    items = [Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
             Item(role='торшер', w_cm=35, d_cm=35, h_cm=165),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55)]
    ps = T.place_reading(room, items, usable_polygon(room))
    assert ps is not None
    arm = next(p for p in ps if p.role == 'кресло')
    lamp = next(p for p in ps if p.role == 'торшер')
    import math
    r = math.radians(arm.rot)
    dx, dy = lamp.x - arm.x, lamp.y - arm.y
    lateral = abs(math.cos(r) * dx - math.sin(r) * dy)     # поперёк оси взгляда
    assert lateral > 30.0, f'торшер на оси спинки (lateral={lateral:.0f})'


def test_bay_full_kit_keeps_lamp():
    """№28: полный комплект чтения в эркере больше не худеет до кресла — свет к устью."""
    room = Room(width_cm=440, depth_cm=420,
                openings=[_door(), Opening(kind='window', wall='north', offset_cm=140,
                                           width_cm=160, sill_cm=80)],
                contour=[[0, 0], [440, 0], [440, 300], [320, 300], [320, 420],
                         [120, 420], [120, 300], [0, 300]])
    items = [Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
             Item(role='торшер', w_cm=35, d_cm=35, h_cm=165),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55)]
    ps = T.place_reading(room, items, usable_polygon(room))
    assert ps is not None
    assert any(p.role == 'торшер' for p in ps), 'торшер выброшен каскадом'


def test_between_windows_candidates_center_on_pier():
    room = Room(width_cm=560, depth_cm=430, openings=[
        _door(off=300),
        Opening(kind='window', wall='north', offset_cm=60, width_cm=120, sill_cm=80),
        Opening(kind='window', wall='north', offset_cm=380, width_cm=120, sill_cm=80)])
    stand = Item(role='тв-тумба', w_cm=150, d_cm=40, h_cm=50)
    cands = T._between_windows_candidates(room, stand, usable_polygon(room))
    assert cands, 'простенок 200 см не дал кандидата'
    # простенок 180..380 → ось 280
    assert any(abs(c.placement.x - 280) < 1.0 for c in cands)
    assert all(c.topology == 'between_windows' for c in cands)


def test_console_short_is_tagged_degraded():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    sofa = Placement(role='диван', x=310, y=240, rot=180,
                     item=Item(role='диван', w_cm=220, d_cm=95, h_cm=85))
    free = usable_polygon(room).difference(
        __import__('planner.geometry', fromlist=['footprint']).footprint(sofa))
    for w, short in ((150, False), (120, True)):
        it = Item(role='комод', w_cm=w, d_cm=35, h_cm=75)
        ps = T.place_console_behind_sofa(room, [it], free, fixed=[sofa])
        assert ps, f'консоль {w} не встала: {T.CONSOLE_DIAG}'
        v = ps[0].tpl_variant
        assert v.endswith('+short') == short, f'w={w}: variant={v}'
