"""Q12-3 + Codex-план 21.08 (ADR-0117): гейт семантики якоря и совместный медиа-минимум."""
from planner.models import Item, Opening, Placement, Room
from planner.validate import Severity, validate
from planner.zones import solve_zoned


def _door(wall='west', off=40):
    return Opening(kind='door', wall=wall, offset_cm=off, width_cm=90, swing_cm=90)


def _mk(role, x, y, rot, w, d, h, var=''):
    p = Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))
    if var:
        p.tpl_variant = var
    return p


def _hard(room, ps):
    return sorted({v.code for v in validate(room, ps).violations
                   if v.severity is Severity.HARD})


def test_tv_over_forbids_live_bearer():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    fp = _mk('камин', 280, 410, 180, 120, 40, 100, var='tv_over_fireplace')
    tv = _mk('тв-тумба', 100, 20, 0, 150, 40, 50)
    tv.tpl_id = 'media'                      # v2: запрещён именно МЕДИА-носитель
    assert 'ANCHOR_SEMANTICS' in _hard(room, [fp, tv])
    # та же тумба как ХРАНЕНИЕ (не медиа) — легальна (Codex: не «любая тумба»)
    tv2 = _mk('тв-тумба', 100, 20, 0, 150, 40, 50)
    tv2.tpl_id = 'storage'
    assert 'ANCHOR_SEMANTICS' not in _hard(room, [fp, tv2])


def test_side_by_side_requires_same_wall():
    room = Room(width_cm=620, depth_cm=560, openings=[_door(off=430)])
    fp = _mk('камин', 590, 280, 270, 120, 40, 100, var='fireplace_side_by_side')
    tv = _mk('тв-тумба', 310, 540, 180, 150, 40, 50, var='fireplace_side_by_side')
    assert 'ANCHOR_SEMANTICS' in _hard(room, [fp, tv])


def test_adjacent_requires_perpendicular():
    room = Room(width_cm=620, depth_cm=560, openings=[_door(off=430)])
    fp = _mk('камин', 450, 540, 180, 120, 40, 100, var='fireplace_tv_adjacent_walls')
    tv = _mk('тв-тумба', 200, 540, 180, 150, 40, 50, var='fireplace_tv_adjacent_walls')
    assert 'ANCHOR_SEMANTICS' in _hard(room, [fp, tv])


def test_corner_vignette_must_hug_corner():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    arm = _mk('кресло', 280, 215, 135, 80, 82, 80, var='corner_vignette')   # центр комнаты
    assert 'ANCHOR_SEMANTICS' in _hard(room, [arm])


def test_bay_scheme_needs_bay():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])      # без эркера
    arm = _mk('кресло', 280, 380, 0, 80, 82, 80, var='bay_anchor')
    assert 'ANCHOR_SEMANTICS' in _hard(room, [arm])


def test_joint_media_min_in_solve():
    """Свободная сцена камин+ТВ: медиа-минимум лестницы берёт СОВМЕСТНУЮ схему —
    у носителя/камина появляется вариант fireplace_side_by_side (или adjacent),
    и сцена проходит гейт семантики якоря."""
    room = Room(width_cm=620, depth_cm=560, openings=[_door(off=430)])
    items = [Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
             Item(role='тв-тумба', w_cm=150, d_cm=40, h_cm=50),
             Item(role='камин', w_cm=120, d_cm=40, h_cm=100),
             Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
             Item(role='ковёр', w_cm=290, d_cm=200, h_cm=1)]
    lays, _ = solve_zoned(room, items)
    assert lays and lays[0].placements
    lay = lays[0]
    fp = next((p for p in lay.placements if p.role == 'камин'), None)
    assert fp is not None, 'камин выпал из плана'
    assert str(getattr(fp, 'tpl_variant', '')).startswith(
        ('fireplace_side_by_side', 'fireplace_tv_adjacent_walls')), \
        f'совместная схема не применилась: {getattr(fp, "tpl_variant", "")!r}'
    assert not [v for v in lay.violations
                if v.code == 'ANCHOR_SEMANTICS'], 'гейт якоря сработал на своём же плане'


def test_side_by_side_positive_same_segment():
    room = Room(width_cm=620, depth_cm=560, openings=[_door(off=430)])
    tv = _mk('тв-тумба', 250, 540, 180, 150, 40, 50, var='fireplace_side_by_side')
    fp = _mk('камин', 445, 540, 180, 120, 40, 100, var='fireplace_side_by_side')
    assert 'ANCHOR_SEMANTICS' not in _hard(room, [tv, fp])


def test_adjacent_positive_shared_vertex():
    room = Room(width_cm=620, depth_cm=560, openings=[_door(off=40)])
    tv = _mk('тв-тумба', 380, 540, 180, 150, 40, 50, var='fireplace_tv_adjacent_walls')
    fp = _mk('камин', 600, 420, 270, 120, 40, 100, var='fireplace_tv_adjacent_walls')
    assert 'ANCHOR_SEMANTICS' not in _hard(room, [tv, fp])


def test_between_windows_contract():
    room = Room(width_cm=560, depth_cm=430, openings=[
        _door(off=300),
        Opening(kind='window', wall='north', offset_cm=60, width_cm=120, sill_cm=80),
        Opening(kind='window', wall='north', offset_cm=380, width_cm=120, sill_cm=80)])
    ok = _mk('тв-тумба', 280, 410, 180, 150, 40, 50)
    ok.cand_topology = 'between_windows'          # в простенке 180..380 целиком
    assert 'ANCHOR_SEMANTICS' not in _hard(room, [ok])
    bad = _mk('тв-тумба', 120, 410, 180, 150, 40, 50)   # перекрывает окно слева
    bad.cand_topology = 'between_windows'
    assert 'ANCHOR_SEMANTICS' in _hard(room, [bad])


def test_window_anchor_needs_window_nearby():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])   # окна нет
    arm = _mk('кресло', 280, 380, 180, 80, 82, 80, var='window_anchor')
    assert 'ANCHOR_SEMANTICS' in _hard(room, [arm])


def test_corner_tower_contract():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    ok = _mk('стеллаж', 42, 410, 180, 80, 35, 190, var='corner_tower')   # у СЗ вершины
    assert 'ANCHOR_SEMANTICS' not in _hard(room, [ok])
    bad = _mk('стеллаж', 280, 410, 180, 80, 35, 190, var='corner_tower')  # середина стены
    assert 'ANCHOR_SEMANTICS' in _hard(room, [bad])


def test_repair_preserves_anchor_attrs():
    """Сторож: перенос предмета в repair_unplaced сохраняет tpl_id/tpl_variant."""
    from planner.refine import repair_unplaced
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    fp = _mk('камин', 280, 410, 180, 120, 40, 100, var='fireplace_side_by_side')
    fp.tpl_id = 'fireplace'
    lay = validate(room, [fp])
    lay.unplaced = ['кашпо']
    out = repair_unplaced(room, lay, [Item(role='кашпо', w_cm=35, d_cm=35, h_cm=90)])
    fp2 = next(p for p in out.placements if p.role == 'камин')
    assert getattr(fp2, 'tpl_variant', '') == 'fireplace_side_by_side'
    assert getattr(fp2, 'tpl_id', '') == 'fireplace'
