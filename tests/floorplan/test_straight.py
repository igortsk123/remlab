"""Выпрямление T-20261109-04: рёбра к семействам, ступени, перемычки-прямоугольники, снап пола к стене, метрика косых."""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import fpcore as fc  # noqa: E402

AX = [0.0, 90.0]


def edge_angles(v):
    v = np.asarray(v, float)
    d = np.diff(np.vstack([v, v[:1]]), axis=0)
    L = np.hypot(d[:, 0], d[:, 1])
    a = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 180
    return a, L


def off_family(a, fams):
    return min(fc.angdiff(a, f) for f in fams)


def test_skewed_quad_floor_becomes_rectangle():
    # «косой четырёхугольник» как у пола C: стороны наклонены на 3–5°, прежнее выпрямление (допуск 3°) их оставляло
    m = np.zeros((220, 260), np.uint8)
    pts = np.array([[20, 20], [230, 36], [236, 190], [24, 180]], np.int32)
    cv2.fillPoly(m, [pts], 1)
    old, _ = fc.mask_polygons(m, AX, min_area=10)
    new, _ = fc.mask_polygons(m, AX, min_area=10, straight=True)
    assert fc.skew_stats(old, AX, 10)['skew_polys'] == 1
    assert fc.skew_stats(new, AX, 10)['skew_polys'] == 0
    a, L = edge_angles(new[0][0])
    assert all(off_family(x, AX) < 0.5 for x, l in zip(a, L) if l >= 4)


def test_wall_step_kept_as_right_angle_not_diagonal():
    # комната со ступенью 6 px (выступ стены): должна остаться ступенью под прямым углом, а не косым ребром
    m = np.zeros((200, 260), np.uint8)
    m[20:180, 20:120] = 1
    m[26:180, 120:240] = 1
    polys, _ = fc.mask_polygons(m, AX, min_area=10, straight=True)
    v = np.asarray(polys[0][0])
    a, L = edge_angles(v)
    assert all(off_family(x, AX) < 0.5 for x in a)
    assert len(v) == 6
    ys = sorted({round(p[1]) for p in v})
    assert ys[0] <= 21 and any(24 <= y <= 27 for y in ys)


def test_diagonal_family_kept():
    # эркер 45°: семейство 45/135 есть — грань остаётся диагональю (не к осям)
    m = np.zeros((240, 240), np.uint8)
    pts = np.array([[20, 20], [200, 20], [200, 140], [140, 200], [20, 200]], np.int32)
    cv2.fillPoly(m, [pts], 1)
    fams = [0.0, 90.0, 135.0]
    polys, _ = fc.mask_polygons(m, fams, min_area=10, straight=True)
    a, L = edge_angles(polys[0][0])
    assert any(fc.angdiff(x, 135) < 1 and l > 60 for x, l in zip(a, L))
    assert fc.skew_stats(polys, fams, 10)['skew_polys'] == 0


def test_panel_families_adds_bay_diagonal_with_small_share():
    m = np.zeros((600, 600), np.uint8)
    cv2.rectangle(m, (20, 20), (580, 580), 1, 8)
    cv2.line(m, (580, 200), (640, 260), 1, 8)            # короткая диагональ эркера: доля мала, длина ~85 px
    cv2.line(m, (580, 400), (520, 460), 1, 8)
    fams = fc.panel_families(m, 60)
    assert any(fc.angdiff(f, 45) < 3 for f in fams) or any(fc.angdiff(f, 135) < 3 for f in fams)
    assert all(fc.angdiff(f, 0) < 1 or fc.angdiff(f, 90) < 1 or fc.angdiff(f, 45) < 3 or fc.angdiff(f, 135) < 3
               for f in fams)


def test_rect_polygons_snaps_lintel_drawn_at_foreign_angle():
    m = np.zeros((100, 120), np.uint8)
    box = cv2.boxPoints(((60, 50), (60, 6), 6.0)).astype(np.int32)   # перемычка под 6° на осевом этаже
    cv2.fillPoly(m, [box], 1)
    polys = fc.rect_polygons(m, AX)
    assert len(polys) == 1
    a, L = edge_angles(polys[0][0])
    assert all(off_family(x, AX) < 0.5 for x in a)


def test_floor_edge_snaps_to_wall_face():
    # пол комнаты кончается в 2 px от грани стены — грань пола переносится на грань стены
    wall = np.zeros((200, 200), np.uint8)
    wall[20:180, 100:106] = 1
    wpolys, _ = fc.mask_polygons(wall, AX, min_area=3, straight=True)
    ref = fc.polygon_lines(wpolys, AX)
    floor = np.zeros_like(wall)
    floor[30:170, 30:97] = 1
    polys, _ = fc.mask_polygons(floor, AX, min_area=10, straight=True, ref=ref, ref_d=4)
    xs = [p[0] for p in polys[0][0]]
    assert max(xs) >= 99.5


def test_skew_stats_counts_off_family_length():
    sq = (np.array([[0, 0], [100, 0], [100, 100], [0, 100]], float), [])
    sk = (np.array([[0, 0], [100, 8], [100, 100], [0, 100]], float), [])
    s = fc.skew_stats([sq, sk], AX, 10)
    assert s['polys'] == 2 and s['skew_polys'] == 1
    assert 0 < s['off_share'] < 0.5
    assert math.isclose(s['worst_deg'], round(math.degrees(math.atan2(8, 100)), 1))
