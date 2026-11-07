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


# СЦЕНА №272 — СОСТАВ СЕТА 21 ЗАМОРОЖЕН (T-20261107-24): раньше брался из живого банка `sets3.json`, и тест ломался, когда
# банк менял сет, а не механизм. С 19.10 в сете 21 модульный «Брера 2» 198×124: в комнате 360×450 солвер честно отказывает
# MEDIA_MISSING (ТВ обязателен, №177), зеркал нет — тест красный при верном коде. Состав — банк 29.08 (`sets3.json.bak-nonton`):
# прямой «Риббл-10» 215×108, на нём обе стороны зеркала годны. (роль, w, d, h, название)
_SET21 = (
    ('диван', 215.0, 108.0, 72.0, 'Диван прямой divan.ru Риббл-10 Букле Мятный'),
    ('кресло', 85.0, 82.0, 81.0, 'Кресло поворотное divan.ru Теоп Букле Светло-серый'),
    ('стол обеденный', 90.0, 90.0, 75.0, 'Стол обеденный TC 90х90х75 см'),
    ('стул', 50.5, None, 79.5, 'Стул ТС Wishbone темный орех 57х50,5х79,5 см'),
    ('стеллаж', 80.0, 35.0, 205.0, 'Стеллаж divan.ru Моррис 80x205 Светло-бежевый'),
    ('комод', 102.0, 40.0, 87.0, 'Комод divan.ru Блест 102x87 Графитовый'),
    ('тв-тумба', 160.0, 52.0, 47.0, 'ТВ-тумба divan.ru Энзо 160x47 Светло-бежевый/Терракотовый'),
    ('столик', 110.0, 60.0, 36.0, 'Журнальный стол divan.ru Хостер-1 Светло-бежевая керамика/Яс'),
    ('кашпо', 50.0, 35.0, 35.0, 'Кашпо для цветов Crocus высокое серое 35х35х50 см'),
    ('ковёр', 300.0, 200.0, None, 'Ковер divan.ru Рэдми 200x300'),
    ('люстра', 60.0, 60.0, 45.0, 'Подвесная люстра Divinare TENERIFE 7136/02 LM-6'),
    ('подушка', 45.0, 45.0, 11.0, 'Подушка декоративная Ad trend xmas stripes 45х45см в ассорти'),
    ('плед', 180.0, 220.0, None, 'Набор Tissagio покрывало 180х220 наволочка 50х70 см'),
    ('ваза', 21.0, 21.0, 20.0, 'Ваза San miguel Montana медный 20 см'),
    ('лампа', 23.0, 23.0, None, 'Настольная лампа Arti Lampadari  Gaeta E 4.1.T1 GY'),
    ('ваза 2', 22.0, 22.0, None, 'Ваза-шар Неман Гладь 100/1 22 см'),
)


def _set21_items(fixed_cl=None):
    out = []
    for r, w, dd, h, name in _SET21:
        d = {'w': w, 'd': dd, 'h': h, 'name': name}
        kw = {}
        if r == 'диван':
            kw = dict(corner=True, corner_section_cm=95)
            if fixed_cl is not None:
                kw.update(corner_left=fixed_cl, corner_side_fixed=True)
        out.append(Item(role=r, w_cm=float(d.get('w') or 60),
                        d_cm=float(d.get('d') or 60), h_cm=(d.get('h') or None),
                        name=d.get('name'), **kw))
    return out


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
