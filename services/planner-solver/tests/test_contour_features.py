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
