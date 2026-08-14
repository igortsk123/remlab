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
