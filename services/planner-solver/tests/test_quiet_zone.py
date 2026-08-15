"""C-4 свода №11 (MASTER-zones-v5): разблокировка тихой зоны (Кодекс Q-B)."""
from planner.models import Item, Opening, Placement, Room
from planner.template import place_quiet
from planner.validate import validate
from planner.zones import usable_polygon
from planner.geometry import footprint
from shapely.ops import unary_union


def _large_room():
    return Room(width_cm=700, depth_cm=650,
                openings=[Opening(kind='door', wall='south', offset_cm=40,
                                  width_cm=90, swing_cm=92)])


def _main_zone():
    mk = lambda r, x, y, rot, w, d, h: Placement(
        role=r, x=x, y=y, rot=rot, item=Item(role=r, w_cm=w, d_cm=d, h_cm=h))
    ps = [mk('диван', 350, 420, 180, 220, 95, 85),
          mk('столик', 350, 300, 180, 110, 55, 42),
          mk('тв-тумба', 350, 25, 0, 150, 40, 50)]
    for p in ps:
        p.tpl_id = 'seating' if p.role != 'тв-тумба' else 'media'
    return ps


def test_quiet_places_in_large_room_middle():
    room = _large_room()
    fixed = _main_zone()
    items = [Item(role='кресло 3', w_cm=75, d_cm=82, h_cm=80),
             Item(role='кресло 4', w_cm=75, d_cm=82, h_cm=80),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55)]
    occ = unary_union([footprint(p) for p in fixed])
    free = usable_polygon(room).difference(occ)
    got = place_quiet(room, items, free, fixed=fixed)
    assert got is not None, 'тихая зона не встала в просторной комнате'
    assert all(p.tpl_id == 'quiet' for p in got if p.role.startswith('кресло'))


def test_quiet_chairs_not_judged_by_main_group():
    """Кресла quiet вдали от главного столика/дивана — НЕ нарушение."""
    room = _large_room()
    ps = _main_zone()
    for i, (x, y, rot) in enumerate((( 90, 150, 90), (280, 150, 270)), 3):
        p = Placement(role=f'кресло {i}', x=x, y=y, rot=rot,
                      item=Item(role=f'кресло {i}', w_cm=75, d_cm=82, h_cm=80))
        p.tpl_id = 'quiet'
        ps.append(p)
    codes = {v.code for v in validate(room, ps).violations}
    for bad in ('SEATS_TOO_FAR', 'ARMCHAIR_TABLE_DIST', 'ARMCHAIR_BEHIND_SOFA',
                'DEAD_ZONE_BEHIND_SOFA'):
        assert bad not in codes, (bad, codes)
