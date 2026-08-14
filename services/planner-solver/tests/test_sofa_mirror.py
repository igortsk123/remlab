"""Пакет E свода №8 (MASTER-zones-v2): зеркала Г-дивана в шаблонном пути.

До пакета «обратная буква Г» была недостижима: corner_left читался как данность
(зеркало перебирал только поштучный candidates.py). Сцена: 280×430, дверь на
востоке — влезает ТОЛЬКО corner_left=False.
"""
from planner.models import Item, Opening, Room
from planner.template import place_template
from planner.zones import usable_polygon


def _items(cl, fixed=False):
    return [Item(role='диван', w_cm=240, d_cm=160, h_cm=85, corner=True,
                 corner_section_cm=90, corner_left=cl, corner_side_fixed=fixed),
            Item(role='столик', w_cm=110, d_cm=55, h_cm=42),
            Item(role='ковёр', w_cm=230, d_cm=160, h_cm=1),
            Item(role='тв-тумба', w_cm=140, d_cm=40, h_cm=50)]


def _room():
    return Room(width_cm=280, depth_cm=430,
                openings=[Opening(kind='door', wall='east', offset_cm=20,
                                  width_cm=90, swing_cm=92),
                          Opening(kind='window', wall='north', offset_cm=80,
                                  width_cm=120)])


def test_mirror_enumerated_in_template_path():
    room = _room()
    # фиксированное «неудачное» зеркало — блок не встаёт (контроль сцены)
    assert place_template(room, 'compact_sectional', _items(True, fixed=True),
                          usable_polygon(room)) is None
    # то же зеркало БЕЗ фиксации — перебор находит отражение и ставит блок
    ps = place_template(room, 'compact_sectional', _items(True, fixed=False),
                        usable_polygon(room))
    assert ps is not None, 'зеркало Г-дивана не перебрано'
    sofa = next(p for p in ps if p.role == 'диван')
    assert sofa.item.corner_left is False, 'должно встать отражение corner_left=False'


def test_fixed_side_respected():
    room = _room()
    ps = place_template(room, 'compact_sectional', _items(False, fixed=True),
                        usable_polygon(room))
    assert ps is not None
    sofa = next(p for p in ps if p.role == 'диван')
    assert sofa.item.corner_left is False
