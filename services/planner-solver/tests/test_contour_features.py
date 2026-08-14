"""M-C (свод №5): классификация осевого контура — эркер / колонна / квадрат.

Контуры — референсы экзамена (acceptance_scenes.CONTOURS) + синтетический L
(сцен L в экзамене нет — механика C2 проверяется здесь, юнитом)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from planner.models import Opening, Room
from planner.room_map import build_room_map, contour_features

BAY = [(0, 0), (500, 0), (500, 380), (350, 380), (350, 440), (150, 440),
       (150, 380), (0, 380)]
PYLONS = [(0, 0), (600, 0), (600, 200), (560, 200), (560, 260), (600, 260),
          (600, 460), (0, 460)]
TRAPEZOID = [(0, 0), (520, 0), (520, 420), (390, 420), (390, 470), (260, 470),
             (260, 520), (0, 520)]
L_SHAPE = [(0, 0), (500, 0), (500, 300), (200, 300), (200, 500), (0, 500)]

WIN = Opening(kind='window', wall='north', offset_cm=180, width_cm=140)


def _room(contour, openings=()):
    xs = [p[0] for p in contour]
    ys = [p[1] for p in contour]
    return Room(width_cm=max(xs), depth_cm=max(ys), contour=contour,
                openings=list(openings))


def test_bay_detected_with_window():
    bays, cols, sq = contour_features(_room(BAY, [WIN]))
    assert len(bays) == 1 and not cols
    x1, y1, x2, y2 = bays[0].bounds
    assert (round(x1), round(y1), round(x2), round(y2)) == (150, 380, 350, 440)


def test_bay_without_window_still_bay():
    # окно экзамена — на востоке; выступ без окна = ниша, приоритет декора тот же
    # (bay_needs_window=false в паспорте, включить при появлении окна в эркере)
    bays, _, _ = contour_features(_room(BAY))
    assert len(bays) == 1


def test_pylon_detected_as_column_not_bay():
    bays, cols, _ = contour_features(_room(PYLONS, [WIN]))
    assert not bays and len(cols) == 1


def test_trapezoid_steps_are_neither():
    bays, cols, _ = contour_features(_room(TRAPEZOID, [WIN]))
    assert not bays and not cols


def test_square_rect_and_L_machinery():
    assert contour_features(Room(width_cm=400, depth_cm=400))[2] is True
    assert contour_features(Room(width_cm=400, depth_cm=500))[2] is False
    bays, cols, sq = contour_features(_room(L_SHAPE))
    assert not bays and not cols and sq is False


def test_room_map_carries_features():
    rmap = build_room_map(_room(PYLONS, [WIN]))
    assert len(rmap.columns) == 1 and rmap.bays == [] and rmap.square is False


def test_no_sofa_ladder_reachable():
    """E1 (M-E, свод №5): диван физически не встаёт (огромный угловой) — лестница
    легально уходит в armchair_pair (кресла+приставной), сцена НЕ пустая. До фикса
    состав фильтровался ролями одной группы pick_group, и кресла выбрасывались до
    спуска — ступень «без дивана» была недостижима."""
    from planner.models import Item
    from planner.zones import solve_zoned
    room = Room(width_cm=300, depth_cm=300,
                openings=[Opening(kind='door', wall='south', offset_cm=105,
                                  width_cm=90),
                          Opening(kind='window', wall='east', offset_cm=60,
                                  width_cm=180)])
    items = [Item(role='диван', w_cm=280, d_cm=280, h_cm=85, corner=True),
             Item(role='кресло', w_cm=75, d_cm=80, h_cm=80),
             Item(role='кресло 2', w_cm=75, d_cm=80, h_cm=80),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55),
             Item(role='ковёр', w_cm=160, d_cm=120, h_cm=1),
             Item(role='тв-тумба', w_cm=120, d_cm=40, h_cm=50)]
    lays, gid = solve_zoned(room, items)
    assert lays and lays[0].placements, 'сцена не должна быть пустой'
    roles = {p.role for p in lays[0].placements}
    assert 'диван' not in roles and 'кресло' in roles and 'кресло 2' in roles, \
        (gid, roles)


def test_window_block_score_scales_with_height():
    """D3 (M-D, свод №5): перекрытие окна — низкая тумба 0, высокий стеллаж > 0."""
    from planner.models import Item, Placement
    from planner.template import _window_block_score
    room = Room(width_cm=400, depth_cm=400,
                openings=[Opening(kind='window', wall='east', offset_cm=100,
                                  width_cm=160)])
    low = Placement(role='тв-тумба', x=385, y=180, rot=270,
                    item=Item(role='тв-тумба', w_cm=140, d_cm=40, h_cm=45))
    tall = Placement(role='стеллаж', x=385, y=180, rot=270,
                     item=Item(role='стеллаж', w_cm=140, d_cm=40, h_cm=200))
    assert _window_block_score(room, low) == 0.0
    assert _window_block_score(room, tall) > 0.2


def test_high_ceiling_prefers_tall_anchor():
    """D5 (M-D, свод №5): при ceiling>=300 якорь ряда хранения — высокий корпус."""
    from planner.models import Item
    from planner.template import build_storage
    by_role = {'комод': Item(role='комод', w_cm=180, d_cm=45, h_cm=80),
               'стеллаж': Item(role='стеллаж', w_cm=80, d_cm=35, h_cm=200)}
    b_norm = build_storage(dict(by_role), ceiling_cm=None)
    b_high = build_storage(dict(by_role), ceiling_cm=320)
    assert b_norm.anchor.role == 'комод'      # шире — якорь по умолчанию
    assert b_high.anchor.role == 'стеллаж'    # высокий потолок — вертикаль первой


def test_seat_axis_origin_corner():
    """N3а (свод №6): ось Г-дивана — центр главной секции, сдвиг на section/2."""
    from planner.geometry import seat_axis_origin
    from planner.models import Item, Placement
    it = Item(role='диван', w_cm=220, d_cm=150, h_cm=85, corner=True,
              corner_section_cm=80)
    p = Placement(role='диван', x=100, y=100, rot=0, item=it)
    x, y = seat_axis_origin(p)
    assert (round(x), round(y)) == (60, 100)      # плечо на +x → секция смещена в −x
    straight = Placement(role='диван', x=100, y=100, rot=0,
                         item=Item(role='диван', w_cm=200, d_cm=95, h_cm=85))
    assert seat_axis_origin(straight) == (100, 100)


def test_seating_access_pinched():
    """N0 (свод №6): спинка ко входу — нужен проход вокруг торца."""
    from planner.models import Item, Placement
    from planner.validate import check_seating_access
    room = Room(width_cm=300, depth_cm=450,
                openings=[Opening(kind='door', wall='south', offset_cm=100,
                                  width_cm=90)])
    sofa = Item(role='диван', w_cm=260, d_cm=95, h_cm=85)
    # диван почти во всю ширину — оба торцевых зазора < 60
    tight = Placement(role='диван', x=150, y=250, rot=0, item=sofa)
    assert check_seating_access(room, [tight])
    # узкий диван — проход есть
    ok = Placement(role='диван', x=110, y=250, rot=0,
                   item=Item(role='диван', w_cm=180, d_cm=95, h_cm=85))
    assert not check_seating_access(room, [ok])


def test_corner_adrift_functional_gap():
    """N3в (свод №6): зазор от угла легален при функции (радиатор), штраф — без."""
    from planner.models import Item, Placement, Radiator
    from planner.validate import validate
    sofa = Item(role='диван', w_cm=219, d_cm=142, h_cm=85, corner=True,
                corner_section_cm=70)
    room_plain = Room(width_cm=400, depth_cm=460)
    p = Placement(role='диван', x=71, y=192, rot=90, item=sofa)
    codes = {v.code for v in validate(room_plain, [p]).violations}
    assert 'CORNER_SOFA_ADRIFT' in codes
    room_rad = Room(width_cm=400, depth_cm=460,
                    radiators=[Radiator(wall='south', offset_cm=20, width_cm=120,
                                        depth_cm=15)])
    codes2 = {v.code for v in validate(room_rad, [p]).violations}
    assert 'CORNER_SOFA_ADRIFT' not in codes2


def test_dining_share_watchdog():
    """Свод №7: доля планов со столовой — планка по лучшему замеру (172/252,
    14.08), двигается только вверх. Отчёт приёмки нужен свежий."""
    import json, os
    rep = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools',
                       'scout', 'acceptance-report-zoned.jsonl')
    if not os.path.exists(rep):
        import pytest
        pytest.skip('нет отчёта приёмки')
    n = din = 0
    for line in open(rep, encoding='utf-8'):
        r = json.loads(line)
        n += 1
        din += ('+din' in r.get('templates', ''))
    assert n == 252, f'отчёт неполный: {n}'
    assert din >= 172, f'доля столовой упала: {din}/252 (планка 172 — лучший замер)'
