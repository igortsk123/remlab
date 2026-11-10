"""T-20261110-03: косая дверь в углу комнаты — проём срезает угол, обе стены угла кончаются, не дойдя до вершины.
Синтетика: квартира-коробка 12×7 м (ppm 40, стена 8 px), в левом верхнем углу ванная; её правая и нижняя стены обрываются
у общего угла на `leg` px, проём между торцами — наискось. Прямые двери и проходы без створки — как раньше."""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402

PPM, T = 40.0, 8
VX, HY = 200, 160            # правая стена ванной — столбцы 200..207, нижняя — строки 160..167


def plan(leg: int | None, arc: bool = True, straight: bool = False):
    """→ (серое, маска стен). leg — сколько px не доходят обе стены ванной до угла (None — угол целый);
    arc — нарисована створка с дугой (петля у торца нижней стены, открывается в ванную); straight — вместо косой
    прямая дверь 0,9 м в нижней стене ванной (угол целый)."""
    g = np.full((320, 520), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (500, 300), 244, -1)
    wall = np.zeros_like(g)
    wall[20:28, 20:500] = 1; wall[292:300, 20:500] = 1; wall[20:300, 20:28] = 1; wall[20:300, 492:500] = 1
    xh, yv = (VX + 8, HY) if leg is None else (VX - leg, HY - leg)
    wall[20:yv, VX:VX + 8] = 1                                      # правая стена ванной до торца yv
    wall[HY:HY + 8, 20:xh] = 1                                      # нижняя — до торца xh
    if straight:
        wall[HY:HY + 8, 100:136] = 0                                # прямая дверь 0,9 м
        if arc:
            cv2.ellipse(g, (100, HY), (36, 36), 0, -90, 0, 0, 1); cv2.line(g, (100, HY), (100, HY - 36), 0, 1)
    elif leg is not None and arc:
        a, b = (xh, HY), (VX, yv)                                   # петля — угол торца нижней стены, полотно — до торца правой
        R = int(round(math.hypot(b[0] - a[0], b[1] - a[1])))
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))   # закрытое положение (−45°)
        cv2.ellipse(g, a, (R, R), 0, ang - 90, ang, 0, 1)          # дуга до открытого (в ванную)
        o = math.radians(ang - 90)
        cv2.line(g, a, (int(round(a[0] + R * math.cos(o))), int(round(a[1] + R * math.sin(o)))), 0, 1)   # створка открыта
    g[wall > 0] = 0
    return g, wall


def analyze(g, wall):
    fams = fc.angle_families(wall)
    return bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, PPM, fams, T)


def test_corner_door_closes_bathroom_from_landing():
    """Косая дверь ~0,9 м в углу ванной со створкой → две комнаты (ванная отдельно), закрытие — дверь между торцами."""
    g, wall = plan(26)
    r = analyze(g, wall)
    assert len(r['rooms']) == 2
    bath = r['lab'][60, 60]
    assert bath in r['rooms'] and r['lab'][250, 400] in r['rooms'] and r['lab'][250, 400] != bath
    near = [q for q in r['gaps'] if abs(q.cx - (VX - 13)) <= 15 and abs(q.cy - (HY - 13)) <= 15]
    assert [q.kind for q in near] == ['door']
    assert 0.8 * PPM <= near[0].length <= 1.3 * PPM


def test_corner_door_without_fix_merges_rooms(monkeypatch):
    """Тот же лист без закрытия косого проёма — ванная сливается с площадкой (так было до T-20261110-03)."""
    monkeypatch.setattr(fc, 'corner_cut_doors', lambda *a, **k: [])
    g, wall = plan(26)
    assert len(analyze(g, wall)['rooms']) == 1


def test_wide_corner_opening_without_leaf_stays_open():
    """Косой проход ~1,4 м без створки (арка) — не дверь: не закрываем, как прямой проход без створки."""
    g, wall = plan(40, arc=False)
    assert len(analyze(g, wall)['rooms']) == 1


def test_corner_opening_wider_than_closure_limit_stays_open_even_with_arc():
    """Шире предела закрытия межкомнатных проёмов (`Ls` = 1,7 м в `bench._analyze`) — не закрываем и со створкой."""
    g, wall = plan(56)
    assert len(analyze(g, wall)['rooms']) == 1


def test_straight_door_unchanged_by_corner_step(monkeypatch):
    """Прямая дверь в нижней стене ванной: две комнаты, и закрытия те же, что без шага косых дверей (регресса нет)."""
    g, wall = plan(None, straight=True)
    r = analyze(g, wall)
    assert len(r['rooms']) == 2
    monkeypatch.setattr(fc, 'corner_cut_doors', lambda *a, **k: [])
    r0 = analyze(g, wall)
    assert np.array_equal(r['add'], r0['add'])


def test_corner_cut_doors_pairs_only_real_cut_corner():
    """Кандидат один — у срезанного угла; целая коробка, Т-стык и торцы на одной линии (прямой проём) кандидатов не дают."""
    _, wall = plan(26)
    c = fc.corner_cut_doors(wall, wall, int(1.7 * PPM), 12, T)
    assert len(c) == 1
    ys, xs = np.nonzero(c[0])
    assert VX - 30 <= xs.mean() <= VX and HY - 30 <= ys.mean() <= HY
    _, whole = plan(None)
    assert fc.corner_cut_doors(whole, whole, int(1.7 * PPM), 12, T) == []
    _, st = plan(None, straight=True, arc=False)
    assert fc.corner_cut_doors(st, st, int(1.7 * PPM), 12, T) == []


def test_corner_cut_doors_on_rotated_plan():
    """Тот же срезанный угол на листе, повёрнутом на 20°: кандидат находится в рамке семейства."""
    _, wall = plan(26)
    big = cv2.copyMakeBorder(wall, 120, 120, 120, 120, cv2.BORDER_CONSTANT, value=0)
    M = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), 20, 1.0)
    rot = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), flags=cv2.INTER_NEAREST)
    fams = fc.angle_families(rot)
    c = fc.corner_cut_doors(rot, rot, int(1.7 * PPM), 12, T, bench.rot_angles(fams))
    assert len(c) == 1
