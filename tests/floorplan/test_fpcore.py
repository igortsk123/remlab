"""Чистые функции стенда планировок (T-20261109-02) на синтетических картинках."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import fpcore as fc  # noqa: E402


def box_room(w, h, t=6, pad=10):
    """Стены прямоугольной комнаты w×h px (внутренний размер), толщина t."""
    m = np.zeros((h + 2 * t + 2 * pad, w + 2 * t + 2 * pad), np.uint8)
    cv2.rectangle(m, (pad, pad), (pad + w + 2 * t - 1, pad + h + 2 * t - 1), 1, -1)
    m[pad + t:pad + t + h, pad + t:pad + t + w] = 0
    return m


def test_stroke_thickness_matches_drawn_wall():
    m = box_room(200, 120, t=8)
    assert abs(fc.stroke_thickness(m) - 8) <= 2


def test_free_components_inside_and_outside():
    m = box_room(100, 80)
    n, lab, outside = fc.free_components(m)
    inner = [i for i in range(1, n) if not outside[lab == i].any()]
    assert len(inner) == 1
    assert (lab == inner[0]).sum() == 100 * 80


def test_room_extents_axis_and_rotated():
    m = box_room(150, 90)
    _, lab, outside = fc.free_components(m)
    room = (lab == lab[60, 60]).astype(np.uint8)
    e = fc.room_extents(room, 0.0)
    assert e['p95'] == pytest.approx((150, 90), abs=1)
    # та же комната, повёрнутая на 30°: по углу семейства размеры возвращаются
    big = np.pad(room, 80)
    M = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), 30, 1.0)
    rot = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), flags=cv2.INTER_NEAREST)
    e2 = fc.room_extents(rot, -30.0)
    assert e2['p95'][0] == pytest.approx(150, abs=4)
    assert e2['p95'][1] == pytest.approx(90, abs=4)


def _obs(name, dims_m, px, s=0.02):
    """Наблюдение комнаты с подписью: размеры в метрах и «нарисованные» px при масштабе s м/px."""
    w, h = px
    ext = {'p95': (w, h), 'med': (w * 0.97, h * 0.97), 'bbox': (w + 6, h + 6)}
    return {'id': name, 'dims': dims_m, 'ext': ext, 'angle': 0.0}


def test_fit_scale_ransac_ignores_outlier_and_reads_convention():
    s = 0.02
    obs = [_obs(f'r{i}', (a, b), (a / s, b / s)) for i, (a, b) in enumerate([(4.1, 3.45), (2.6, 3.0), (5.2, 4.0), (3.3, 2.2)])]
    obs.append(_obs('bad', (9.0, 1.0), (100, 100)))            # подпись не от этой комнаты
    f = fc.fit_scale(obs)
    assert f['s'] == pytest.approx(s, rel=1e-3)
    assert 'bad' not in [i for i, _, _ in f['inliers']]
    c, p, share = fc.convention(f)
    assert (c, p) == ('p95', 0) and share == 1.0


def test_fit_scale_swapped_label_order():
    s = 0.025
    obs = [_obs(f'r{i}', (a, b), (b / s, a / s)) for i, (a, b) in enumerate([(4.1, 3.45), (2.6, 3.0), (5.2, 4.0)])]
    f = fc.fit_scale(obs)
    assert f['s'] == pytest.approx(s, rel=1e-3)
    assert fc.convention(f)[1] == 1                            # первое число — по вертикали


def test_leave_one_out_predicts_held_out_room():
    s = 0.02
    dims = [(4.1, 3.45), (2.6, 3.0), (5.2, 4.0), (3.3, 2.2)]
    rows = fc.leave_one_out([_obs(f'r{i}', d, (d[0] / s, d[1] / s)) for i, d in enumerate(dims)])
    summ = fc.loo_summary(rows)
    assert summ['n_dims'] == 8 and summ['mae'] < 0.01


def test_bridge_lines_closes_gap_up_to_max_gap():
    m = np.zeros((40, 300), np.uint8)
    m[18:24, 10:120] = 1
    m[18:24, 160:290] = 1                                      # разрыв 40 px между длинными стенами
    assert fc.bridge_lines(m, max_gap=60, min_flank=9)[18:24, 120:160].mean() > 0.9
    assert fc.bridge_lines(m, max_gap=30, min_flank=9)[18:24, 120:160].sum() == 0   # разрыв длиннее max_gap


def test_xy_cut_splits_two_plans_on_one_sheet():
    m = np.zeros((200, 500), np.uint8)
    m[:, :] = 0
    a, b = box_room(150, 120), box_room(150, 120)
    m[20:20 + a.shape[0], 10:10 + a.shape[1]] |= a
    m[20:20 + b.shape[0], 300:300 + b.shape[1]] |= b
    regs = fc.xy_cut(m, min_gap=40)
    assert len(regs) == 2


def test_frame_coverage_window_vs_empty():
    line = np.zeros((60, 200), np.uint8)
    line[30, 50:150] = 1                                       # одна линия рамы вдоль разрыва
    ys, xs = np.mgrid[27:34, 50:150]
    assert fc.frame_coverage(ys.ravel(), xs.ravel(), line) > 0.9
    assert fc.frame_coverage(ys.ravel(), xs.ravel(), np.zeros_like(line)) == 0


def test_door_evidence_sees_quarter_arc():
    thin = np.zeros((200, 200), np.uint8)
    # разрыв по x 60..120 на y=100 (стена горизонтальная), петля — слева; дуга радиуса 60 вниз
    cv2.ellipse(thin, (60, 100), (60, 60), 0, 0, 90, 1, 1)
    cv2.line(thin, (60, 100), (60, 160), 1, 1)                 # створка
    ys, xs = np.mgrid[97:104, 60:121]
    c, u, n, L, d = fc.gap_axes(ys.ravel(), xs.ravel())
    assert fc.door_evidence(thin, c, u, n, L, d) >= 0.75
    assert fc.door_evidence(np.zeros_like(thin), c, u, n, L, d) < 0.2


def test_feet_to_m_and_gold_labels_consistent():
    assert fc.feet_to_m("13'6\"") == pytest.approx(4.1148, abs=1e-4)
    # эталоны: метры и футы каждой подписи согласованы (UK-листы округляют дюймы — допуск 3")
    for plan in 'ABC':
        gold = json.loads((ROOT / 'tools' / 'floorplan' / 'gold' / f'{plan}.json').read_text())
        for r in gold['rooms']:
            if 'dims_ft' in r:
                assert max(abs(x) for x in fc.check_feet(r['dims_m'], r['dims_ft'])) <= 3.0, (plan, r['name'])


def test_regularize_contour_snaps_to_family():
    m = np.zeros((200, 200), np.uint8)
    pts = np.array([[20, 20], [180, 22], [179, 170], [21, 168]], np.int32)   # почти прямоугольник, перекос ~0,7°
    cv2.fillPoly(m, [pts], 1)
    polys, edges = fc.mask_polygons(m, [0.0, 90.0], min_area=10)
    assert len(polys) == 1
    outer = np.array(polys[0][0], float)
    d = np.diff(np.vstack([outer, outer[:1]]), axis=0)
    ang = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 90
    assert np.all(np.minimum(ang, 90 - ang) < 0.5)
