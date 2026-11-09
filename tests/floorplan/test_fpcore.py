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


def test_door_evidence_leaf_rescues_partial_arc():
    """Дуга срезана (видна половина), но прямая створка у петли есть → дверь (≥ LEAF_SCORE); без створки — нет."""
    arc = np.zeros((200, 200), np.uint8)
    cv2.ellipse(arc, (60, 100), (60, 60), 0, 50, 90, 1, 1)      # только половина дуги — у створки
    ys, xs = np.mgrid[97:104, 60:121]
    c, u, n, L, d = fc.gap_axes(ys.ravel(), xs.ravel())
    assert fc.door_evidence(arc, c, u, n, L, d) < 0.75
    with_leaf = arc.copy()
    cv2.line(with_leaf, (60, 100), (60, 160), 1, 1)
    assert fc.door_evidence(with_leaf, c, u, n, L, d) >= fc.LEAF_SCORE


def test_mouth_strip_keeps_only_doorway_of_closet():
    """Перемычка залила каморку целиком + проём в правой стене → остаётся полоса у проёма, не вся каморка."""
    wall = np.zeros((100, 100), np.uint8)
    wall[20:26, 20:80] = 1; wall[74:80, 20:80] = 1; wall[20:80, 20:26] = 1; wall[20:80, 74:80] = 1
    wall[40:60, 74:80] = 0                                     # проём
    comp = np.zeros_like(wall)
    comp[26:74, 26:74] = 1; comp[40:60, 74:80] = 1
    sy, sx = fc.mouth_strip(comp, wall, t=6)
    assert sx.min() >= 66 and 38 <= sy.min() and sy.max() <= 62
    assert len(sy) < 0.2 * comp.sum()


def test_largest_rect_and_core_extent_of_l_room():
    m = np.zeros((120, 160), np.uint8)
    m[10:110, 10:150] = 1
    m[10:50, 110:150] = 0                                      # L-комната: вырез угла 40×40
    w, h = fc.largest_rect(m)
    assert w * h == 100 * 100 or (w, h) == (140, 60)            # 100×100 (тело) больше 140×60
    assert (w, h) == (100.0, 100.0)
    ext = fc.room_extents(m, 0.0, core=True)
    assert ext['core'] == (100.0, 100.0) and ext['bbox'] == (140.0, 100.0)


def test_leave_one_out_near_candidate_and_label_flag():
    s = 0.02
    dims = [(4.1, 3.45), (2.6, 3.0), (5.2, 4.0), (3.3, 2.2)]
    obs = [_obs(f'r{i}', d, (d[0] / s, d[1] / s)) for i, d in enumerate(dims)]
    obs[1]['ext']['core'] = obs[1]['ext']['p95']               # у части комнат есть «тело»
    obs.append(_obs('nisha', (3.0, 2.0), (3.6 / s, 2.0 / s)))   # подпись без ниши: ни один кандидат не ближе 0,15
    rows = {r['id']: r for r in fc.leave_one_out(obs)}
    assert rows['nisha']['flag_label'] and not rows['r0']['flag_label']
    near, clean = fc.loo_summary(list(rows.values()), 'near'), fc.loo_summary(list(rows.values()), 'near_clean')
    assert clean['n_dims'] == near['n_dims'] - 2 and clean['mae'] < near['mae']


def _two_rooms_with_thin_split():
    """Коробка 6 px; настоящая внутренняя стена 6 px (справа — комната без подписи, «санузел»); в левой комнате —
    тонкий штрих 2 px поперёк (ложная стена): сверху подпись, снизу кусок без подписи."""
    w = np.zeros((300, 300), np.uint8)
    w[10:16, 10:290] = 1; w[284:290, 10:290] = 1; w[10:290, 10:16] = 1; w[10:290, 284:290] = 1
    w[16:284, 150:156] = 1                                     # настоящая стена
    w[16:284, 220:226] = 1                                     # ещё одна (типичная толщина внутренних — 6 px)
    final = w.copy()
    final[120:122, 16:150] = 1                                 # ложный штрих 2 px
    n, lab, outside = fc.free_components(final)
    areas = np.bincount(lab.ravel(), minlength=n)
    rooms = [i for i in range(1, n) if areas[i] > 50 and not outside[lab == i].any()]
    return w, final, lab, rooms


def test_merge_false_splits_merges_thin_cut_keeps_real_room():
    w, final, lab, rooms = _two_rooms_with_thin_split()
    lab2, final2, rooms2, log = fc.merge_false_splits(lab, rooms, final, final, np.zeros_like(final), [(80, 60)], ppm=40)
    assert lab2[60, 80] == lab2[200, 80]                       # кусок без подписи вернулся в комнату с подписью
    assert lab2[150, 190] != lab2[60, 80] and lab2[150, 190] in rooms2   # «санузел» за настоящей стеной — отдельно
    assert len(rooms2) == len(rooms) - 1 and final2[121, 80] == 0      # сам штрих снят
    assert any(s['false'] for s in log) and not all(s['false'] for s in log)


def test_bay_window_extends_room_and_skips_door_swing():
    import bench
    wall = np.zeros((200, 260), np.uint8)
    wall[40:46, 60:250] = 1; wall[180:186, 60:250] = 1; wall[40:186, 244:250] = 1
    wall[40:80, 60:66] = 1; wall[140:186, 60:66] = 1             # левая наружная стена с окном y 80..140
    keep = np.zeros_like(wall); keep[80:140, 60:66] = 1          # окно закрыто перемычкой
    thin = np.zeros_like(wall)
    cv2.line(thin, (30, 78), (59, 78), 1, 1); cv2.line(thin, (30, 141), (59, 141), 1, 1)
    cv2.line(thin, (30, 78), (30, 141), 1, 1)                     # эркер: рама П-образно снаружи, к торцам стены
    bay, bay_in = bench.bay_windows(wall, keep, thin, thin, ppm=40, t=6)
    assert bay.any() and bay_in[110, 45] and keep.sum() == 0      # комната продолжается в эркер, его контур — окно
    keep2 = np.zeros_like(wall); keep2[80:140, 60:66] = 1
    arc = np.zeros_like(wall)
    cv2.ellipse(arc, (59, 80), (60, 60), 0, 90, 180, 1, 1)        # дуга створки снаружи (четверть круга)
    cv2.line(arc, (59, 80), (0, 80), 1, 1)
    bay2, _ = bench.bay_windows(wall, keep2, arc, arc, ppm=40, t=6)
    assert not bay2.any() and keep2.sum() > 0


def test_one_open_hole_does_not_strip_window_closures_of_floor():
    """Комната R1 с незакрытой 3-метровой дырой наружу (без рамы) открыта аркой в R2; окно R2 с рамой должно остаться
    закрытым: «наружа с обеих сторон» считается и вне грубого контура постройки (цикл 3: C, весь этаж пропадал)."""
    import bench
    ppm, t = 40.0, 8
    g = np.full((320, 520), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (500, 300), 244, -1)                 # заливка комнат
    wall = np.zeros_like(g)
    wall[20:28, 20:500] = 1; wall[292:300, 20:500] = 1; wall[20:300, 20:28] = 1; wall[20:300, 492:500] = 1
    wall[20:120, 256:264] = 1; wall[220:300, 256:264] = 1           # стена R1|R2 с аркой 2,5 м (без створки)
    wall[292:300, 60:180] = 0                                       # R1: дыра 3 м в низу, рамы нет
    wall[20:28, 340:380] = 0                                        # R2: окно 1 м вверху, с рамой
    g[wall > 0] = 0
    for y in (22, 25):
        cv2.line(g, (340, y), (379, y), 200, 1)
    fams = fc.angle_families(wall)
    r = bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, ppm, fams, t)
    assert r['add'][22:27, 345:375].mean() > 0.5                    # окно R2 закрыто, несмотря на дыру в R1


def test_split_by_labels_cuts_at_wide_opening_neck():
    """Две подписи в одной области (комнаты соединены проёмом 1,5 м без двери) → две комнаты, граница — в проёме."""
    lab = np.zeros((200, 400), np.int32)
    lab[20:180, 20:190] = 1; lab[20:180, 210:380] = 1; lab[80:140, 190:210] = 1   # две комнаты + горло 60 px
    lab2, rooms2, log = fc.split_by_labels(lab, [1], [(100, 100), (300, 100)], ppm=40)
    assert len(rooms2) == 2 and log and log[0]['parts'] == 2
    assert lab2[100, 60] != lab2[100, 340]
    assert lab2[30, 30] == lab2[100, 60] and lab2[170, 370] == lab2[100, 340]
    lab3, rooms3, _ = fc.split_by_labels(lab, [1], [(100, 100)], ppm=40)            # одна подпись — не трогаем
    assert rooms3 == [1] and (lab3 == lab).all()


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
