"""T-20261110-03: косая дверь в углу комнаты — проём срезает угол, обе стены угла кончаются, не дойдя до вершины.
Синтетика: квартира-коробка 12×7 м (ppm 40, стена 8 px), в левом верхнем углу ванная; её правая и нижняя стены обрываются
у общего угла на `leg` px, проём между торцами — наискось. Прямые двери и проходы без створки — как раньше."""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

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


# --- T-20261110-03/2: рисунок PlanUp — стены кончаются скосом 45° с точкой-косяком ---------------------------------------------
R2 = math.sqrt(2)


def _bevel(img, wall, end_a, end_b, d, b, t):
    """Скос: от торца стены (грань end_a–end_b) короткая полоса толщиной t длиной b по направлению d, на конце — точка-косяк.
    → центр точки (x, y)."""
    p0 = (np.array(end_a, float) + end_b) / 2
    d = np.array(d, float) / np.hypot(*d)
    n = np.array([-d[1], d[0]])
    p1 = p0 + d * b
    pts = [end_a, end_b, p0 + n * t / 2, p0 - n * t / 2, p1 + n * t / 2, p1 - n * t / 2]
    hull = cv2.convexHull(np.round(np.array(pts)).astype(np.int32))
    for m, v in ((img, (0, 0, 0)), (wall, 1)):
        cv2.fillConvexPoly(m, hull, v, cv2.LINE_AA if m is img else cv2.LINE_8)
    r = int(round(0.65 * t))
    c = tuple(int(round(v)) for v in p1)
    cv2.circle(img, c, r, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(wall, c, r, 1, -1)
    return p1


def _door_arc(img, hinge, other, r_dot, into):
    """Створка от точки-косяка: дуга радиусом до края другой точки, выгнута в сторону into, полотно открыто."""
    h, o = np.array(hinge, float), np.array(other, float)
    R = float(np.hypot(*(o - h))) - r_dot
    ang = math.degrees(math.atan2(*(o - h)[::-1]))
    a0, a1 = (ang - 90, ang) if into < 0 else (ang, ang + 90)
    hc = tuple(int(round(v)) for v in h)
    cv2.ellipse(img, hc, (int(round(R)), int(round(R))), 0, a0, a1, (70, 70, 70), 1, cv2.LINE_AA)
    o_ang = math.radians(a0 if into < 0 else a1)
    cv2.line(img, hc, (int(round(h[0] + R * math.cos(o_ang))), int(round(h[1] + R * math.sin(o_ang)))), (70, 70, 70), 1,
             cv2.LINE_AA)


def plan_planup(kind: str, gap_m: float = 0.8, bevel_t: float = 1.25, jpeg: int = 70, seed: int = 0):
    """Лист в стиле PlanUp → (BGR после JPEG, серое, маска стен из картинки как у листа, толщина стены).
    kind: 'corner' — косая дверь в углу ванной (обе стены угла кончаются скосом 45° на диагонали угла, точки-косяки, проём
    gap_m между точками в свету, створка от точки внутрь ванной); 'straight' — прямая дверь 0,9 м в нижней стене ванной,
    торцы со скосом к проёму и точками; 'straight_plain' — та же прямая дверь без скосов; 'corner_open' — косой проём без
    створки. Заливка комнат — бежевая с текстурой, шум JPEG."""
    rng = np.random.default_rng(seed)
    t = T
    img = np.full((320, 520, 3), 255, np.uint8)
    beige = np.array([196, 222, 236], float)
    tex = cv2.GaussianBlur(rng.normal(0, 1, (280, 480)), (0, 0), 6) * 40 + rng.normal(0, 4, (280, 480))
    img[20:300, 20:500] = np.clip(beige[None, None, :] + tex[..., None], 0, 255).astype(np.uint8)
    wall = np.zeros((320, 520), np.uint8)
    for y0, y1, x0, x1 in ((20, 28, 20, 500), (292, 300, 20, 500), (20, 300, 20, 28), (20, 300, 492, 500)):
        wall[y0:y1, x0:x1] = 1
    b, r_dot = bevel_t * t, int(round(0.65 * t))
    cx, cy = VX + t / 2, HY + t / 2
    if kind.startswith('corner'):
        g = gap_m * PPM + 2 * r_dot                       # между центрами точек
        bp = b / R2
        xh = int(round(cx - 2 * bp - g / R2))
        yv = int(round(xh + cy - cx))
        wall[20:yv, VX:VX + t] = 1
        wall[HY:HY + t, 20:xh] = 1
        img[wall > 0] = 0
        pv = _bevel(img, wall, (VX, yv), (VX + t, yv), (-1, 1), b, t)
        ph = _bevel(img, wall, (xh, HY), (xh, HY + t), (1, -1), b, t)
        if kind == 'corner':
            _door_arc(img, ph, pv, r_dot, -1)
    else:
        wall[20:300, VX:VX + t] = 1
        xl, xr = 100, 136
        wall[HY:HY + t, 20:xl] = 1
        wall[HY:HY + t, xr:VX] = 1
        img[wall > 0] = 0
        if kind == 'straight':
            pl = _bevel(img, wall, (xl, HY), (xl, HY + t), (1, 1), b, t)
            pr = _bevel(img, wall, (xr, HY), (xr, HY + t), (-1, 1), b, t)
            _door_arc(img, pl, pr, r_dot, -1)
        else:
            _door_arc(img, (xl, HY), (xr, HY), 0, -1)
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    w = bench.build_mask(img, bench.auto_cfg(img))
    return img, gray, w, fc.stroke_thickness(w)


def analyze_img(img, gray, w, t):
    """Как лист в конвейере: пороги тонких линий и стекла — из `bench.auto_cfg` (`bench.run_plan`)."""
    cfg = bench.auto_cfg(img)
    return bench.analyze(img, gray, w, PPM, fc.angle_families(w), t, None, cfg['thin'], cfg['glaze'])


def test_planup_corner_door_closes_bathroom():
    """Рисунок PlanUp: косая дверь 0,8 м в углу ванной, стены кончаются скосом 45° с точкой-косяком, створка-дуга от точки,
    бежевая заливка с текстурой, JPEG → ванная отдельно от площадки, закрытие — дверь."""
    img, gray, w, t = plan_planup('corner')
    r = analyze_img(img, gray, w, t)
    assert len(r['rooms']) == 2
    bath, land = r['lab'][60, 60], r['lab'][250, 400]
    assert bath in r['rooms'] and land in r['rooms'] and bath != land
    near = [q for q in r['gaps'] if abs(q.cx - (VX - 25)) <= 25 and abs(q.cy - (HY - 25)) <= 25]
    assert [q.kind for q in near] == ['door']
    assert 0.6 * PPM <= near[0].length <= 1.1 * PPM


def test_planup_corner_door_found_only_by_bevel_step(monkeypatch):
    """Без шага скосов тот же лист сливается (так было в /1 на закрытом листе: кандидатов 0); прямоугольные торцы
    (`corner_cut_doors`) скос не видят."""
    img, gray, w, t = plan_planup('corner')
    assert fc.corner_cut_doors(w, w, int(1.7 * PPM), max(3, round(1.5 * t)), t) == []
    c = fc.bevel_corner_doors(w, w, int(1.7 * PPM), t)
    assert len(c) == 1
    monkeypatch.setattr(fc, 'bevel_corner_doors', lambda *a, **k: [])
    assert len(analyze_img(img, gray, w, t)['rooms']) == 1


def test_planup_corner_opening_without_leaf_stays_open():
    """Тот же косой проём со скосами, но без створки (проход) — не закрываем."""
    assert len(analyze_img(*plan_planup('corner_open'))['rooms']) == 1


def test_planup_corner_wider_than_limit_stays_open():
    """Косой проём шире предела закрытия (1,7 м) со створкой — открыт."""
    assert len(analyze_img(*plan_planup('corner', gap_m=1.9))['rooms']) == 1


def test_planup_straight_door_with_bevels_same_as_without(monkeypatch):
    """Прямая дверь 0,9 м, торцы со скосом и точками: как без скосов — ванная отдельно от комнаты под ней (три комнаты
    листа), дверь на месте проёма, шаг скосов ничего не добавляет (стены торцов на одной линии — не угол)."""
    for kind in ('straight', 'straight_plain'):
        img, gray, w, t = plan_planup(kind)
        assert fc.bevel_corner_doors(w, w, int(1.7 * PPM), t) == []
        r = analyze_img(img, gray, w, t)
        assert len(r['rooms']) == 3, kind
        assert r['lab'][60, 60] != r['lab'][250, 60]
        near = [q for q in r['gaps'] if abs(q.cx - 118) <= 20 and abs(q.cy - (HY + 4)) <= 15]
        assert [q.kind for q in near] == ['door'], kind
        monkeypatch.setattr(fc, 'bevel_corner_doors', lambda *a, **k: [])
        assert np.array_equal(analyze_img(img, gray, w, t)['add'], r['add'])
        monkeypatch.undo()


@pytest.mark.parametrize('bevel_t', [1.0, 1.5])
@pytest.mark.parametrize('seed', [1, 2])
def test_planup_corner_door_bevel_length_and_noise(bevel_t, seed):
    """Скос 1 и 1,5 толщины, другой шум заливки и JPEG — ванная отдельно."""
    assert len(analyze_img(*plan_planup('corner', bevel_t=bevel_t, jpeg=60, seed=seed))['rooms']) == 2


def test_bevel_zone_only_for_paired_ends():
    """Зона «не продлевать» (`bevel_end_zone`) — только у торцов со скосом, у которых есть пара-проём (прямая дверь или
    угол); одиночный скос и Г-образный короткий отросток (поворот ~90°) — как раньше, зоны нет."""
    Ls = int(1.7 * PPM)
    for kind in ('corner', 'straight'):
        _, _, w, t = plan_planup(kind)
        n = cv2.connectedComponents(fc.bevel_end_zone(w, t, Ls))[0] - 1
        assert n >= 1, kind
    img = np.full((320, 520, 3), 255, np.uint8)
    w = np.zeros((320, 520), np.uint8)
    w[20:28, 20:500] = 1
    w[20:200, 200:208] = 1                                          # одиночная стена со скосом на конце
    _bevel(img, w, (200, 200), (208, 200), (-1, 1), 10, T)
    w[20:120, 400:408] = 1                                          # Г-отросток: стена и поворот на 90° длиной 1,2 t
    w[112:120, 400:418] = 1
    assert fc.bevel_end_zone(w, T, Ls).sum() == 0


def test_planup_corner_door_on_rotated_sheet():
    """Лист PlanUp, повёрнутый на 15°: скелет от поворота не зависит — кандидат один, у среза угла."""
    img, gray, w, t = plan_planup('corner')
    big = cv2.copyMakeBorder(w, 120, 120, 120, 120, cv2.BORDER_CONSTANT, value=0)
    M = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), 15, 1.0)
    rot = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), flags=cv2.INTER_NEAREST)
    c = fc.bevel_corner_doors(rot, rot, int(1.7 * PPM), t)
    assert len(c) == 1
    p = (c[0][1] + c[0][2]) / 2
    q = M @ np.array([VX - 25 + 120, HY - 25 + 120, 1.0])
    assert np.hypot(*(p - q)) <= 25


def test_corner_cut_doors_on_rotated_plan():
    """Тот же срезанный угол на листе, повёрнутом на 20°: кандидат находится в рамке семейства."""
    _, wall = plan(26)
    big = cv2.copyMakeBorder(wall, 120, 120, 120, 120, cv2.BORDER_CONSTANT, value=0)
    M = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), 20, 1.0)
    rot = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), flags=cv2.INTER_NEAREST)
    fams = fc.angle_families(rot)
    c = fc.corner_cut_doors(rot, rot, int(1.7 * PPM), 12, T, bench.rot_angles(fams))
    assert len(c) == 1
