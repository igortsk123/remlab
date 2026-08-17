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


# ---------- Q5 свода №13 (Codex по №181/№183): контракт pod + edge-gap ----------
def _p(r, x, y, rot, w, d, h=80, tpl=None, var=None):
    p = Placement(role=r, x=x, y=y, rot=rot, item=Item(role=r, w_cm=w, d_cm=d, h_cm=h))
    if tpl:
        p.tpl_id = tpl
    if var:
        p.tpl_variant = var
    return p


def test_quiet_chat_requires_surface_and_angles():
    from planner.template import build_quiet
    a = {'кресло 3': Item(role='кресло 3', w_cm=75, d_cm=82, h_cm=80),
         'кресло 4': Item(role='кресло 4', w_cm=75, d_cm=82, h_cm=80)}
    assert build_quiet(a, variant='quiet_chat') is None, 'пара без поверхности не собирается (№181)'
    b = build_quiet(dict(a, **{'столик 2': Item(role='столик 2', w_cm=50, d_cm=50, h_cm=45)}), variant='quiet_chat')
    assert b is not None
    rots = sorted(int(r[3]) % 360 for r in b.rel if r[0].role.startswith('кресло'))
    assert rots == [35, 325], rots          # к общему центру (вдоль стены), не «интервью» 0/180


def test_check_quiet_contract_flags_bare_pair_and_far_fireplace():
    from planner.validate import check_quiet_contract
    room = _large_room()
    ps = _main_zone()
    bare = ps + [_p('кресло 3', 90, 150, 90, 75, 82, tpl='quiet', var='quiet_chat'),
                 _p('кресло 4', 280, 150, 270, 75, 82, tpl='quiet', var='quiet_chat')]
    assert 'QUIET_POD_NO_SURFACE' in {v.code for v in check_quiet_contract(room, bare)}
    # «интервью» лицом-к-лицу (90/270) даже со столиком — не контракт (сходимость 180°)
    interview = bare + [_p('столик 2', 185, 150, 0, 50, 50, 45, tpl='quiet', var='quiet_chat')]
    assert 'QUIET_POD_GEOMETRY' in {v.code for v in check_quiet_contract(room, interview)}
    ok = ps + [_p('столик 2', 185, 50, 0, 50, 50, 45, tpl='quiet', var='quiet_chat'),
               _p('кресло 3', 105, 83, 35, 75, 82, tpl='quiet', var='quiet_chat'),
               _p('кресло 4', 265, 83, 325, 75, 82, tpl='quiet', var='quiet_chat')]
    assert not check_quiet_contract(room, ok)
    far = ps + [_p('камин', 20, 600, 90, 120, 42, 100),
                _p('кресло 3', 500, 150, 180, 75, 82, tpl='quiet', var='fireplace_flank'),
                _p('кресло 4', 600, 150, 180, 75, 82, tpl='quiet', var='fireplace_flank')]
    assert 'QUIET_POD_FOCUS' in {v.code for v in check_quiet_contract(room, far)}   # «к камину» за 5 м (№183)


def test_place_quiet_diag_and_skip_rich_primary():
    from planner import template as T
    room = _large_room()
    fixed = _main_zone() + [_p('кресло', 200, 300, 90, 75, 82, tpl='seating'),
                            _p('кресло 2', 500, 300, 270, 75, 82, tpl='seating')]
    items = [Item(role='кресло 3', w_cm=75, d_cm=82, h_cm=80), Item(role='кресло 4', w_cm=75, d_cm=82, h_cm=80),
             Item(role='столик 2', w_cm=50, d_cm=50, h_cm=45)]
    free = usable_polygon(room).difference(unary_union([footprint(p) for p in fixed]))
    assert T.place_quiet(room, items, free, fixed=fixed) is None
    assert T.QUIET_DIAG.get('skip') == 'primary_rich'
    fixed2 = _main_zone()
    assert T.place_quiet(room, items[:2], free, fixed=fixed2) is None
    assert T.QUIET_DIAG.get('quiet_chat') == 'no_surface'


def test_armchair_edge_gap_independent_of_depth():
    """Q5 (Codex): зазор кресло↔столик — по кромкам футпринтов: клон d=90 и d=118 при
    одинаковом зазоре судятся одинаково."""
    from planner.validate import check_zone
    room = _large_room()
    for d in (90, 118):
        ps = [_p('диван', 350, 420, 180, 220, 95, 85, tpl='seating'),
              _p('столик', 350, 300, 180, 110, 55, 42, tpl='seating'),
              _p('тв-тумба', 350, 25, 0, 150, 40, 50, tpl='media')]
        # кресло напротив дивана за столиком; ближняя кромка кресла в 40 см от кромки столика, сбоку от оси ТВ
        y = 300 - 55 / 2 - 40 - d / 2
        ps.append(_p('кресло', 150, y, 0, 80, d, tpl='seating'))
        codes = {v.code for v in check_zone(ps)}
        assert 'ARMCHAIR_ACROSS_TABLE' not in codes and 'ARMCHAIR_TOO_FAR' not in codes, (d, codes)


def test_armchair_facing_sofa_not_too_deep():
    """Q5 (реплей set105): кресло НАПРОТИВ дивана лицом к нему (П/facing) — не ARMCHAIR_TOO_DEEP;
    кресло флангом, уехавшее за столик к ТВ (лицом к экрану) — по-прежнему нарушение."""
    from planner.validate import check_layout_rules
    room = _large_room()
    base = [_p('диван', 350, 420, 180, 220, 95, 85, tpl='seating'),
            _p('столик', 350, 300, 180, 110, 55, 42, tpl='seating'),
            _p('тв-тумба', 350, 25, 0, 150, 40, 50, tpl='media')]
    facing = base + [_p('кресло', 350, 180, 0, 80, 90, tpl='seating')]        # напротив дивана, лицом к нему
    drifted = base + [_p('кресло', 150, 150, 180, 80, 90, tpl='seating')]     # сбоку, лицом к экрану, за столиком
    assert 'ARMCHAIR_TOO_DEEP' not in {v.code for v in check_layout_rules(room, facing)}
    assert 'ARMCHAIR_TOO_DEEP' in {v.code for v in check_layout_rules(room, drifted)}


def test_two_sofa_L_right_mirrors_left():
    from planner.models import Item
    from planner.template import build_block
    by = {'диван': Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
          'диван 2': Item(role='диван 2', w_cm=180, d_cm=90, h_cm=85),
          'столик': Item(role='столик', w_cm=110, d_cm=60, h_cm=45)}
    l = build_block('sofa_loveseat', by, variant='default')
    r = build_block('sofa_loveseat', by, variant='L_right')
    assert l is not None and r is not None
    xl = next(rel[1] for rel in l.rel if rel[0].role == 'диван 2')
    xr = next(rel[1] for rel in r.rel if rel[0].role == 'диван 2')
    assert xl < 0 < xr and abs(xl + xr) < 1e-6
