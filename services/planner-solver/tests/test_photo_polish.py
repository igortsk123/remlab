"""Расстановка под съёмку (demo-05 п.2a, `planner/photo_polish.py`): торшер — у торца дивана, дальнего от входа; перенос только
без новых жёстких нарушений, кроме одного принятого — «нет коридора к торшеру», если торшер вплотную к дивану (разбор Codex 15.10)."""
from planner.models import Item, Layout, Opening, Placement, Room, Severity, Violation
from planner.photo_polish import lamp_far_from_entry


def _room():
    # дверь на восточной стене у северного угла: «ближний» торец дивана — восточный
    return Room(width_cm=400, depth_cm=300, openings=[Opening(kind='door', wall='east', offset_cm=180, width_cm=90, swing_cm=90)])


def _scene(lamp_x=300.0, extra=None):
    sofa = Placement(role='диван', x=180, y=255, rot=180, tpl_id='seating', item=Item(role='диван', w_cm=200, d_cm=90, h_cm=85))
    lamp = Placement(role='торшер', x=lamp_x, y=275, rot=180, tpl_id='seating', item=Item(role='торшер', w_cm=22, d_cm=30, h_cm=160))
    return [sofa, lamp] + (extra or [])


def _val(hard_for):
    """Подменная проверка: жёсткие нарушения — функция от расстановки."""
    def v(room, ps):
        return Layout(room=room, placements=ps, violations=[Violation(code=c, severity=Severity.HARD, message=c, roles=list(r))
                                                 for c, r in hard_for(ps)])
    return v


def _lamp(ps):
    return next(p for p in ps if p.role == 'торшер')


def test_lamp_moves_to_far_end():
    ps, why, ok = lamp_far_from_entry(_room(), _scene(), _val(lambda ps: []))
    assert why and _lamp(ps).x < 100, (why, _lamp(ps).x)        # ушёл к западному торцу
    assert abs(_lamp(ps).y - 275) < 1e-6                        # «за плечом» — продольная координата та же
    assert ok == set()


def test_already_far_or_no_door_no_change():
    ps0 = _scene(lamp_x=60.0)
    ps, why, _ = lamp_far_from_entry(_room(), ps0, _val(lambda ps: []))
    assert not why and ps is ps0
    ps, why, _ = lamp_far_from_entry(Room(width_cm=400, depth_cm=300), _scene(), _val(lambda ps: []))
    assert not why


def test_collision_blocks_move():
    shelf = Placement(role='стеллаж', x=50, y=275, rot=180, item=Item(role='стеллаж', w_cm=60, d_cm=40, h_cm=180))
    ps, why, _ = lamp_far_from_entry(_room(), _scene(extra=[shelf]), _val(lambda ps: []))
    assert not why


def test_only_seat_adjacent_unreachable_is_accepted():
    unreach = lambda ps: [('UNREACHABLE', ('торшер',))] if _lamp(ps).x < 100 else []
    ps, why, ok = lamp_far_from_entry(_room(), _scene(), _val(unreach))
    assert why and ok == {('UNREACHABLE', ('торшер',))}
    # то же нарушение, но любое другое новое hard рядом — перенос отменяется
    both = lambda ps: ([('UNREACHABLE', ('торшер',)), ('RADIATOR_TOO_CLOSE', ('торшер',))] if _lamp(ps).x < 100 else [])
    ps, why, _ = lamp_far_from_entry(_room(), _scene(), _val(both))
    assert not why


def test_unreachable_far_from_sofa_is_not_accepted():
    # торшер дальше 25 см от торца: в новом месте он уже не «светильник посадки» — коридор нужен
    unreach = lambda ps: [('UNREACHABLE', ('торшер',))] if _lamp(ps).x < 100 else []
    sc = _scene(lamp_x=330.0)                                     # 50 см от торца — отражение тоже в 50 см
    ps, why, _ = lamp_far_from_entry(_room(), sc, _val(unreach))
    assert not why


def test_pair_of_lamps_untouched():
    lamp2 = Placement(role='торшер 2', x=60, y=275, rot=180, item=Item(role='торшер 2', w_cm=22, d_cm=30, h_cm=160))
    ps, why, _ = lamp_far_from_entry(_room(), _scene(extra=[lamp2]), _val(lambda ps: []))
    assert not why


def test_idempotent():
    ps1, why1, _ = lamp_far_from_entry(_room(), _scene(), _val(lambda ps: []))
    ps2, why2, _ = lamp_far_from_entry(_room(), ps1, _val(lambda ps: []))
    assert why1 and not why2
