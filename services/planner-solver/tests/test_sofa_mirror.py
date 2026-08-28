"""Пакет E свода №8 (MASTER-zones-v2): зеркала Г-дивана в шаблонном пути.

До пакета «обратная буква Г» была недостижима: corner_left читался как данность
(зеркало перебирал только поштучный candidates.py). Сцена: 280×430, дверь на
востоке — влезает ТОЛЬКО corner_left=False.
"""
import os

import pytest

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
    """V3-H: обе стороны решаются и сравниваются (не first-clean). До фикса знака
    corner_active_lat левое зеркало было недостижимо ГЛОБАЛЬНО (8 мест хардкодили
    +section/2) — прежняя контрольная «односторонняя» сцена была артефактом бага."""
    import planner.template as T
    room = _room()
    ps = place_template(room, 'compact_sectional', _items(True, fixed=False),
                        usable_polygon(room))
    assert ps is not None, 'зеркала Г-дивана не перебраны'
    st = T.LAST_MIRROR_STATS
    assert st is not None and st.get('winner') in ('left', 'right')
    assert st['left']['generated'] == 1 and st['right']['generated'] == 1
    sofa = next(p for p in ps if p.role == 'диван')
    assert ('left' if sofa.item.corner_left else 'right') == st['winner']


def test_fixed_side_respected():
    room = _room()
    ps = place_template(room, 'compact_sectional', _items(False, fixed=True),
                        usable_polygon(room))
    assert ps is not None
    sofa = next(p for p in ps if p.role == 'диван')
    assert sofa.item.corner_left is False


def _set21_items(fixed_cl=None):
    import json
    import os
    sets = json.load(open(os.path.join(os.path.dirname(__file__), '..', '..', '..',
                                       'tools', 'scout', 'sets3.json'),
                          encoding='utf-8'))
    out = []
    for r, d in (sets[20].get('items') or {}).items():
        if not isinstance(d, dict):
            continue
        kw = {}
        if r == 'диван':
            kw = dict(corner=True, corner_section_cm=95)
            if fixed_cl is not None:
                kw.update(corner_left=fixed_cl, corner_side_fixed=True)
        out.append(Item(role=r, w_cm=float(d.get('w') or 60),
                        d_cm=float(d.get('d') or 60), h_cm=(d.get('h') or None),
                        name=d.get('name'), **kw))
    return out


_SETS3 = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout', 'sets3.json')


@pytest.mark.skipif(not os.path.exists(_SETS3),
                    reason='нет tools/scout/sets3.json (артефакт дневного прогона, вне git)')
def test_mirror_quality_pick_beats_first_clean():
    """V3-H (поправка рефери №3): оба зеркала hard-valid — победитель выбирается
    по существующему quality-ключу, а не first-clean. Сцена №272: побеждает LEFT,
    хотя перебор начинает с right."""
    from planner.zones import solve_zoned
    room = Room(width_cm=360, depth_cm=450,
                openings=[Opening(kind='door', wall='north', offset_cm=135,
                                  width_cm=90, swing_cm=92),
                          Opening(kind='window', wall='east', offset_cm=100,
                                  width_cm=120, sill_cm=90)])
    lays, _ = solve_zoned(room, _set21_items())
    st = (lays[0].meta or {}).get('mirror') or {}
    assert st.get('left', {}).get('hard_valid') == 1
    assert st.get('right', {}).get('hard_valid') == 1
    # 17.08: проверяем МЕХАНИЗМ, а не сторону: победитель — с минимальным quality-ключом.
    # Прежнее «побеждает LEFT» перестало быть верным после снятия допусков схемы (владелец:
    # «только каноны»): обе стороны канонические и в этой сцене дают РАВНЫЙ ключ, победа
    # решается стабильным порядком перебора. Жёсткая сторона в тесте фиксировала артефакт
    # старой геометрии, а не контракт.
    from planner.score import score_layout
    from planner.template import place_template
    from planner.zones import lexo_key, usable_polygon
    items = _set21_items()
    sofa = next(i for i in items if i.role == 'диван')
    keys = {}
    for cl in (False, True):
        it2 = [i if i.role != 'диван' else sofa.model_copy(
            update={'corner_left': cl, 'corner_side_fixed': True}) for i in items]
        ps = place_template(room, 'sofa_armchair', it2, usable_polygon(room))
        if ps:
            keys['left' if cl else 'right'] = tuple(lexo_key(0, 0, score_layout(room, ps).terms))
    best = min(keys.values())
    assert keys[st['winner']] == best, (st, keys)


def test_corner_active_lat_signed():
    """Корень бага «правое зеркало всегда»: активный центр зависит от corner_left."""
    from planner.geometry import corner_active_lat
    it_r = Item(role='диван', w_cm=219, d_cm=142, h_cm=85, corner=True,
                corner_section_cm=95, corner_left=False)
    it_l = it_r.model_copy(update={'corner_left': True})
    assert corner_active_lat(it_r) == 47.5
    assert corner_active_lat(it_l) == -47.5
