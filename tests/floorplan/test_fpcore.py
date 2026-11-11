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


def test_door_evidence_sees_tangent_arc_with_leaf_in_wall():
    """T-20261110-11 (наш пример /try): створка нарисована закрытой в линии стены, дуга «вогнутая» — касается стены у торца,
    центр в комнате на глубине ширины проёма. Это дверь; без шаблона такой дуги — нет."""
    thin = np.zeros((200, 200), np.uint8)
    cv2.line(thin, (60, 100), (120, 100), 1, 1)                 # створка в проёме
    cv2.ellipse(thin, (60, 160), (60, 60), 0, 270, 360, 1, 1)   # от торца (60,100) до (120,160), центр (60,160)
    ys, xs = np.mgrid[97:104, 60:121]
    c, u, n, L, d = fc.gap_axes(ys.ravel(), xs.ravel())
    assert fc.door_evidence(thin, c, u, n, L, d, tangent_only=True) >= 0.75
    assert fc.door_evidence(thin, c, u, n, L, d) < 0.75            # прежние рисунки (дуга от петли) её не видят
    frame = np.zeros_like(thin)
    for y in (98, 102):
        cv2.line(frame, (60, y), (120, y), 1, 1)                    # рама окна в проёме
    cv2.line(frame, (50, 88), (130, 88), 1, 1)                      # размерная линия снаружи, параллельно стене
    assert fc.door_evidence(frame, c, u, n, L, d, tangent_only=True) < 0.5
    hatch = frame.copy()
    for y in range(104, 176, 6):
        cv2.line(hatch, (40, y), (140, y), 1, 1)                    # штриховка/плитка у окна — линии на всех радиусах
    assert fc.door_evidence(hatch, c, u, n, L, d, tangent_only=True) < 0.75   # ниже порога двери (bench.DOOR_EV_GLAZED)


def test_tangent_evidence_rejects_straight_stair_line_at_window():
    """T-20261110-33/2 (aRQVC9, окно лестницы): у окна с рамой в комнате — прямая линия ступени под углом к стене. Точки
    «вогнутой» дуги ложатся вдоль неё в окне 5×5 (было 1,00 при пороге 0,9) — это окно, не дверь: середина хорды
    у прямой лежит на самой линии и продолжается за конец «дуги». Вырез тонких линий листа — `data/arq-stair-window-thin.png`.
    Настоящие «вогнутые» дуги (R 24–60 px) — по-прежнему дверь."""
    from pathlib import Path
    thin = (cv2.imread(str(Path(__file__).parent / 'data' / 'arq-stair-window-thin.png'), cv2.IMREAD_GRAYSCALE) > 0)
    c, u, n = np.array([160.5, 160.0]), np.array([0.0, 1.0]), np.array([-1.0, 0.0])
    assert fc.door_evidence(thin.astype(np.uint8), c, u, n, 63.0, 36.0, tangent_only=True) < 0.9   # bench.DOOR_EV_GLAZED
    for R in (24, 30, 40, 50, 60):
        arc = np.zeros((240, 240), np.uint8)
        for y in (98, 102):
            cv2.line(arc, (60, y), (60 + R, y), 1, 1)               # рама / створка в линии стены
        cv2.ellipse(arc, (60, 100 + R), (R, R), 0, 270, 360, 1, 1)  # «вогнутая» дуга створки
        ys, xs = np.mgrid[97:104, 60:61 + R]
        c2, u2, n2, L2, d2 = fc.gap_axes(ys.ravel(), xs.ravel())
        assert fc.door_evidence(arc, c2, u2, n2, L2, d2, tangent_only=True) >= 0.9, R


def test_tangent_evidence_keeps_outward_door_whose_arc_meets_wall():
    """T-20261110-33/2 (rgK, наружная дверь конюшни наружу): малая «вогнутая» дуга ложится на верх большой дуги створки —
    там она почти прямая (прогиб ~2 px), а «продолжение хорды» к грани упирается в линию стены. Продолжение считается
    только за дальним концом (от стены) — иначе вход становился окном. Вырез — `data/rgk-stable-door-thin.png`."""
    from pathlib import Path
    thin = (cv2.imread(str(Path(__file__).parent / 'data' / 'rgk-stable-door-thin.png'), cv2.IMREAD_GRAYSCALE) > 0)
    c, u, n = np.array([160.28, 160.131]), np.array([-0.0574, 0.9984]), np.array([-0.9984, -0.0574])
    assert fc.door_evidence(thin.astype(np.uint8), c, u, n, 47.15, 7.38, tangent_only=True) >= 0.9   # bench.DOOR_EV_GLAZED


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


def test_exterior_door_with_leaf_in_wall_is_door_framed_window_stays_window(monkeypatch):
    """T-20261110-11: наружный проём, где створка нарисована в линии стены («рама» 1,0), а в комнату идёт дуга — дверь
    (входная дверь дома на внешнем контуре); окно с рамой без дуги — окно. Прежнее правило («рама → окно») давало два окна."""
    import bench
    ppm, t = 40.0, 8
    g = np.full((320, 520), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (500, 300), 244, -1)
    wall = np.zeros_like(g)
    wall[20:28, 20:500] = 1; wall[292:300, 20:500] = 1; wall[20:300, 20:28] = 1; wall[20:300, 492:500] = 1
    wall[20:28, 100:140] = 0                                        # дверь 1 м во внешней стене
    wall[20:28, 340:380] = 0                                        # окно 1 м
    g[wall > 0] = 0
    cv2.line(g, (100, 24), (139, 24), 0, 2)                       # створка закрытой в проёме
    cv2.ellipse(g, (100, 68), (40, 40), 0, 270, 360, 0, 2)        # «вогнутая» дуга в комнату
    for y in (22, 25):
        cv2.line(g, (340, y), (379, y), 0, 1)                       # рама окна (чёрная, как на листах A/B/T)
    cv2.line(g, (330, 12), (390, 12), 0, 1)                         # размерная линия снаружи
    fams = fc.angle_families(wall)

    def kinds():
        r = bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, ppm, fams, t)
        at = lambda x0, x1: [q.kind for q in r['gaps'] if q.exterior and x0 <= q.cx <= x1]  # noqa: E731
        return at(95, 145), at(335, 385)
    assert kinds() == (['door'], ['window'])
    monkeypatch.setattr(bench, 'GLAZED_ARC', False)
    assert kinds() == (['window'], ['window'])


def test_notch_is_not_opening_and_door_width_floor():
    """T-36: полоска в 1–2 px вдоль грани стены (зазубрина маски под водяным знаком) — не проём; проём через всю толщину — да."""
    g = lambda d: fc.Gap(1, 0, 0, 30, d, 'door', 1.0, False, (0, 0, 1, 1))  # noqa: E731
    assert fc.is_notch(g(1), 10) and fc.is_notch(g(3), 10) and fc.is_notch(g(1.5), 4)
    assert not fc.is_notch(g(5), 10) and not fc.is_notch(g(10), 10)
    assert 0.4 <= fc.DOOR_MIN_M < 0.61                              # ниже самой узкой комнатной двери (UK 610 мм, ГОСТ — 600)


def test_interior_gaps_narrow_slot_and_face_notch_are_walls():
    """T-36 (лист T, CARTER & KING): перегородка с дверью 0,8 м, щелью 0,25 м без створки, зазубриной грани и дверцей
    кладовки 0,35 м со створкой → дверей две (0,8 и дверца), щель и зазубрина — стена."""
    import bench
    ppm, t = 40.0, 8
    g = np.full((320, 520), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (500, 300), 244, -1)
    wall = np.zeros_like(g)
    wall[20:28, 20:500] = 1; wall[292:300, 20:500] = 1; wall[20:300, 20:28] = 1; wall[20:300, 492:500] = 1
    wall[20:300, 256:264] = 1                                       # перегородка R1|R2
    wall[60:92, 256:264] = 0                                        # дверь 0,8 м сквозь толщину
    wall[200:210, 256:264] = 0                                      # щель 0,25 м сквозь толщину — уже нормы
    wall[140:152, 262:264] = 0                                      # зазубрина 2 px по грани (стена не прорвана)
    wall[240:254, 256:264] = 0                                      # дверца кладовки 0,35 м с нарисованной створкой
    cv2.ellipse(g, (264, 60), (32, 32), 0, 0, 90, 0, 1); cv2.line(g, (264, 60), (296, 60), 0, 1)   # створка двери
    cv2.ellipse(g, (264, 240), (14, 14), 0, 0, 90, 0, 1); cv2.line(g, (264, 240), (278, 240), 0, 1)
    g[wall > 0] = 0
    g[200:210, 256:264] = 190; g[140:152, 262:264] = 190            # водяной знак: серое в щели и зазубрине («стекло» 1,0)
    fams = fc.angle_families(wall)
    r = bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, ppm, fams, t)
    near = lambda y0, y1: [q for q in r['gaps'] if 240 <= q.cx <= 280 and y0 <= q.cy <= y1]  # noqa: E731
    assert [q.kind for q in near(55, 97)] == ['door']
    assert all(q.kind == 'wall' for q in near(195, 215) + near(135, 157))
    assert [q.kind for q in near(235, 259)] == ['door']             # узкая, но со створкой — дверь


def test_thin_partition_door_under_thick_exterior_is_opening():
    """T-20261110-33 (тур aRQVC9): наружные стены толстые (t листа 30 px), межкомнатная — 8 px. Дверь сквозь тонкую стену мельче
    порога зазубрины по t (0,35·30 = 10,5 px), но по обе стороны от неё — комнаты → проём; зазубрина грани той же стены — стена."""
    import bench
    ppm, t = 40.0, 30
    g = np.full((360, 560), 255, np.uint8)
    wall = np.zeros_like(g)
    wall[20:50, 20:540] = 1; wall[310:340, 20:540] = 1; wall[20:340, 20:50] = 1; wall[20:340, 510:540] = 1
    wall[50:310, 276:284] = 1                                       # тонкая перегородка R1|R2
    wall[90:122, 276:284] = 0                                       # дверь 0,8 м сквозь толщину 8 px
    wall[200:212, 282:284] = 0                                      # зазубрина 2 px по грани (стена не прорвана)
    cv2.ellipse(g, (284, 90), (32, 32), 0, 0, 90, 0, 1); cv2.line(g, (284, 90), (316, 90), 0, 1)   # створка двери
    g[wall > 0] = 0
    g[200:212, 282:284] = 190
    assert fc.passes_through(wall, *np.nonzero(np.pad(np.ones((32, 8), bool), ((90, 238), (276, 276)))))
    assert not fc.passes_through(wall, *np.nonzero(np.pad(np.ones((12, 2), bool), ((200, 148), (282, 276)))))
    fams = fc.angle_families(wall)
    r = bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, ppm, fams, t)
    near = lambda y0, y1: [q for q in r['gaps'] if 260 <= q.cx <= 300 and y0 <= q.cy <= y1]  # noqa: E731
    assert [q.kind for q in near(85, 127)] == ['door']
    assert all(q.kind == 'wall' for q in near(195, 217))


def _mixed_sheet():
    """Наружные 30 px, перегородки 8 px. Спальня сверху справа: дверь 0,8 м в горизонтальной перегородке между короткими косяками
    (слева — выступ 14 px от вертикальной стены, справа — ступенька стены), как спальня 3 тура aRQVC9."""
    g = np.full((360, 560), 255, np.uint8)
    wall = np.zeros_like(g)
    wall[20:50, 20:540] = 1; wall[310:340, 20:540] = 1; wall[20:340, 20:50] = 1; wall[20:340, 510:540] = 1
    wall[50:310, 276:284] = 1                                       # вертикальная перегородка
    wall[132:140, 284:290] = 1                                      # левый косяк — выступ
    wall[132:140, 322:334] = 1; wall[132:172, 326:334] = 1; wall[164:172, 334:510] = 1   # правый косяк — ступенька
    cv2.ellipse(g, (290, 132), (32, 32), 0, 270, 360, 0, 1); cv2.line(g, (290, 132), (290, 100), 0, 1)   # створка вверх
    g[wall > 0] = 0
    return g, wall


def test_thin_partition_door_between_short_jambs(monkeypatch):
    """T-20261110-33: косяки двери — выступы тонкой перегородки короче флангов 1,5·t листа → второй проход с флангом от толщины
    перегородок закрывает дверь (спальня отделена от площадки). Без него — спальня слипается с площадкой."""
    import bench
    g, wall = _mixed_sheet()
    assert fc.thin_partition_t(wall, 30) == pytest.approx(8, abs=1.5)
    u = np.zeros_like(wall); u[20:50, 20:540] = 1; u[310:340, 20:540] = 1; u[20:340, 20:50] = 1; u[20:340, 510:540] = 1
    assert fc.thin_partition_t(u, 30) is None                      # одна толщина — второго прохода нет

    def run():
        fams = fc.angle_families(wall)
        return bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, 40.0, fams, 30)
    r = run()
    doors = [q for q in r['gaps'] if q.kind == 'door' and 290 <= q.cx <= 322 and 125 <= q.cy <= 147]
    assert len(doors) == 1 and 0.7 <= doors[0].length / 40 <= 0.9
    assert r['lab'][90, 400] != r['lab'][250, 400]                  # спальня ≠ площадка
    monkeypatch.setattr(fc, 'thin_partition_t', lambda *a: None)
    r0 = run()
    assert not [q for q in r0['gaps'] if q.kind == 'door' and 290 <= q.cx <= 322 and 125 <= q.cy <= 147]


def test_room_floor_under_thin_partition_stops_at_neighbour_floor():
    """T-20261110-33/2: пол модели растёт под стену на толщину листа t (наружные 30 px), но в пол соседа за перегородкой 8 px не
    заходит — иначе контуры налезают, и двери соседа попадают в «наши» проёмы спальни. Под наружную стену — по-прежнему целиком.
    Мелкий заход (ниша проёма соседа в толще стены, 8 px) остаётся, как был: иначе на контуре зубец, и ядро спальни ломается."""
    import bench
    lab = np.zeros((260, 400), np.int32)
    lab[60:200, 30:196] = 1; lab[60:200, 204:370] = 2               # две комнаты, перегородка 8 px (196…204), наружные — 30 px
    lab[0:30, 30:370] = 3                                            # сосед сверху за стеной 30 px (30…60)
    lab[30:38, 60:100] = 3                                           # ниша его проёма в толще стены — 8 px
    outside = np.zeros_like(lab, bool)
    rooms_m = np.isin(lab, [1, 2, 3])
    dep = bench.floor_depth(lab, [1, 2, 3])
    fm = bench.room_floor_mask(lab, outside, rooms_m, 1, 30, dep, 10)
    xs = np.nonzero(fm[120])[0]
    assert xs.min() == 0 and xs.max() == 203                         # слева — вся наружная стена, справа — до пола соседа
    assert not fm[lab == 2].any()
    assert fm[32, 80] and fm[36, 80]                                 # ниша соседа сверху (мельче допуска) — под полом, как была
    assert not fm[29, 80]                                            # сам пол соседа — нет (радиус расширения не достаёт)
    assert bench.room_floor_mask(lab, outside, rooms_m, 2, 30, dep, 10)[120, 196]   # перегородка — под обоими полами, щели нет
    assert not bench.room_floor_mask(lab, outside, rooms_m, 1, 30)[lab == 2].any()  # без глубин — чужой пол снимается весь


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


def test_along_face_wedge_vs_door_through_wall():
    """T-20261111-03: клин вдоль грани стены (одна длинная сторона на стене, другая в комнате) — вдоль грани; дверь сквозь стену
    (стена у торцов), щель между двумя стенами и проём в толстой стене (глубина ~ длина) — нет."""
    wall = np.zeros((300, 300), np.uint8)
    wall[20:280, 100:108] = 1
    wedge = np.zeros_like(wall)
    for y in range(150, 200):                                       # треугольник у правой грани: глубина 0 → 6 px
        wedge[y, 108:108 + 1 + (y - 150) * 6 // 50] = 1
    assert fc.along_face(wall, *np.nonzero(wedge))
    door = wall.copy()
    door[60:84, 100:108] = 0                                        # дверь 0,8 м сквозь толщину
    assert not fc.along_face(door, *np.nonzero(np.pad(np.ones((24, 8), bool), ((60, 216), (100, 192)))))
    slot = wall.copy()
    slot[20:280, 114:122] = 1                                       # вторая стена в 6 px — щель между двумя стенами
    assert not fc.along_face(slot, *np.nonzero(np.pad(np.ones((50, 6), bool), ((150, 100), (108, 186)))))
    thick = np.zeros_like(wall)
    thick[20:280, 100:130] = 1
    thick[60:90, 100:130] = 0                                       # проём 30 px в стене 30 px
    assert not fc.along_face(thick, *np.nonzero(np.pad(np.ones((30, 30), bool), ((60, 210), (100, 170)))))


def test_along_face_wedge_behind_seam():
    """T-20261111-03/2 (rgK5… p3 Bedroom 5): клин 1,55 м вдоль правой стены отделён от НАРИСОВАННОЙ стены швом в 2 px — при поиске
    грани на 1..2 px за краем он касался стены на 0,42 длины, оставался «дверью» и резал ядро спальни (отказ opening_ambiguous).
    Грань ищем на 1..FACE_K=3 px: клин за швом — вдоль грани; щель между двумя стенами и дверь сквозь стену — по-прежнему нет."""
    wall = np.zeros((300, 300), np.uint8)
    wall[20:280, 100:108] = 1
    wedge = np.zeros_like(wall)
    for y in range(140, 200):                                       # треугольник за швом (столбцы 108–109 пусты): глубина 1 → 7 px
        wedge[y, 110:111 + (y - 140) * 6 // 60] = 1
    ys, xs = np.nonzero(wedge)
    assert max(fc.face_contact(wall, ys, xs, 2)) < fc.FACE_ON     # прежний поиск 1..2 px шва не перешагивал
    assert fc.along_face(wall, ys, xs)
    slot = wall.copy()
    slot[20:280, 116:124] = 1                                       # щель между двумя стенами, швы по 2 px с обеих сторон — не клин
    assert not fc.along_face(slot, *np.nonzero(np.pad(np.ones((60, 4), bool), ((140, 100), (110, 186)))))
    door = wall.copy()
    door[60:84, 100:108] = 0
    assert not fc.along_face(door, *np.nonzero(np.pad(np.ones((24, 8), bool), ((60, 216), (100, 192)))))


def test_tilted_family_wedges_are_not_doors():
    """T-20261111-03 (тур rgK5…): семейство углов листа с наклоном 3,2° (повёрнутый флигель) закрывает вдоль граней прямых стен
    клинья по 1,2–1,7 м; в залитых комнатах «стекло» у них высокое, и межкомнатные становились «дверями» (Bedroom 8 — 7 при одной).
    Клинья — стена, настоящая дверь перегородки — дверь."""
    import bench
    ppm, t = 30.0, 8
    g = np.full((300, 520), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (500, 280), 210, -1)                 # заливка комнат
    wall = np.zeros_like(g)
    wall[20:28, 20:500] = 1; wall[272:280, 20:500] = 1; wall[20:280, 20:28] = 1; wall[20:280, 492:500] = 1
    wall[20:280, 256:264] = 1
    wall[60:84, 256:264] = 0                                        # дверь 0,8 м
    cv2.ellipse(g, (264, 60), (24, 24), 0, 0, 90, 0, 1); cv2.line(g, (264, 60), (288, 60), 0, 1)
    g[wall > 0] = 0
    fams = list(fc.angle_families(wall)) + [3.2, 93.2]
    r = bench._analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, ppm, fams, t)
    doors = [q for q in r['gaps'] if q.kind == 'door']
    assert len(r['gaps']) > 3                                       # клинья закрыты (комнаты те же), но не двери
    assert [(round(q.cx), round(q.cy)) for q in doors] == [(260, 72)]


def test_wedge_tails_cut_from_door():
    """T-20261111-03 (rgK5… Bedroom 3): дверь 0,8 м сквозь перегородку, слитая с клином 1 м вдоль её грани, — «дверь» 1,8 м резала
    ядро спальни. Хвост-клин (срезы со стеной с одной стороны, не толще проёма) срезается; дверь без клина и Г-образное закрытие
    (толстое «колено») — не трогаются."""
    ppm = 30.0
    wall = np.zeros((220, 320), np.uint8)
    wall[100:109, 20:300] = 1
    wall[100:109, 150:174] = 0                                      # проём 24 px = 0,8 м
    door = np.zeros_like(wall)
    door[100:109, 150:174] = 1
    assert fc.wedge_tails(wall, *np.nonzero(door), ppm) is None
    gap = door.copy()
    for x in range(174, 204):                                       # клин под гранью: глубина 3 → 1 px
        gap[109:109 + 3 - (x - 174) // 11, x] = 1
    ys, xs = np.nonzero(gap)
    tail = fc.wedge_tails(wall, ys, xs, ppm)
    assert tail is not None
    assert xs[tail].min() >= 172 and (xs[tail] >= 176).sum() >= 0.9 * ((xs >= 176).sum())
    g = fc.regap(fc.Gap(1, 0, 0, 0, 0, 'door', 0.0, False, (0, 0, 0, 0)), ys[~tail], xs[~tail])
    assert abs(g.length - 24) <= 3
    knee = door.copy()
    knee[109:160, 150:174] = 1                                      # Г: колено толще проёма — не клин
    assert fc.wedge_tails(wall, *np.nonzero(knee), ppm) is None


def test_thin_light_arc_is_seen_as_door():
    """T-20261111-09 (Giraffe360, TGva…): дуга двери тонкая (1 px) и светлая (серый ~100 на заливке 244) — «чёрная шляпа»
    её берёт целиком, door_evidence — дверь. Причина 0 дверей на листе была не в дуге (см. тесты ниже)."""
    g = np.full((200, 200), 244, np.uint8)
    cv2.ellipse(g, (60, 100), (60, 60), 0, 0, 90, 100, 1)
    cv2.line(g, (60, 100), (60, 160), 100, 1)
    wall = np.zeros_like(g)
    wall[96:104, :60] = 1; wall[96:104, 121:] = 1
    thin = fc.thin_lines(g, wall)
    ys, xs = np.mgrid[97:104, 60:121]
    c, u, n, L, d = fc.gap_axes(ys.ravel(), xs.ravel())
    assert fc.door_evidence(thin, c, u, n, L, d) >= 0.75


def _giraffe_flat(t=8):
    """Квартира 400×280 px, стена t; окна во всю толщину стены слева и справа на одной высоте (как рисует Giraffe360) —
    полоса без стены через весь лист под верхней стеной; ниже — перегородка с дверью 0,8 м и дугой."""
    g = np.full((340, 460), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (439, 319), 244, -1)
    wall = np.zeros_like(g)
    wall[20:20 + t, 20:440] = 1; wall[320 - t:320, 20:440] = 1
    wall[20:320, 20:20 + t] = 1; wall[20:320, 440 - t:440] = 1
    wall[180:180 + t, 20:440] = 1                                   # перегородка
    wall[40:110, 20:20 + t] = 0; wall[40:110, 440 - t:440] = 0      # окна 1,75 м слева и справа на одной высоте
    wall[180:180 + t, 200:232] = 0                                  # дверь 0,8 м
    g[wall > 0] = 0
    for x in (22, 25):
        cv2.line(g, (x, 40), (x, 109), 120, 1)
        cv2.line(g, (x + 412, 40), (x + 412, 109), 120, 1)
    cv2.ellipse(g, (200, 180 + t), (32, 32), 0, 0, 90, 90, 1)      # дуга двери вниз
    cv2.line(g, (200, 180 + t), (200, 180 + t + 32), 90, 1)
    return g, wall


def test_merge_fragments_joins_wall_cut_by_windows_keeps_letters():
    """T-20261111-09: `xy_cut` отрезает верхнюю стену (2 t высотой) в отдельный «план» — она сливается с квартирой;
    подпись (буквы тоньше стены) и большой отдельный план — остаются сами по себе."""
    t = 8
    _, wall = _giraffe_flat(t)
    regs = fc.xy_cut(wall, max(40, 3 * t))
    assert len(regs) == 2
    merged = fc.merge_fragments(wall, regs, t)
    assert merged == [(20, 20, 440, 320)]
    sheet = np.zeros((340, 900), np.uint8)
    sheet[:, :460] = wall
    cv2.putText(sheet, 'NORTH', (560, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1, 1)
    sheet[200:320, 560:840] = box_room(264, 104, t=8, pad=0)
    regs2 = fc.xy_cut(sheet, 40)
    out = fc.merge_fragments(sheet, regs2, t)
    assert (20, 20, 440, 320) in out
    assert len(out) == len(regs2) - 1                               # слился только обломок стены


def test_windows_on_one_line_do_not_flood_flat():
    """T-20261111-09: с обломком стены в отдельном «плане» окна не закрывались, наружа заливала комнату, дверь становилась
    «наружной» (лист TGva…: 0 дверей). С `plan_regions` — окна закрыты, дверь — внутренняя."""
    import bench
    ppm, t = 40.0, 8
    g, wall = _giraffe_flat(t)
    fams = fc.angle_families(wall)
    img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    regs = bench.plan_regions(wall, t, fams)
    assert len(regs) == 1
    run = lambda rg: bench.analyze(img, g, wall, ppm, fams, t, rg, 15, 200)   # noqa: E731  пороги auto_cfg листа TGva
    r = run(regs)
    doors = [q for q in r['gaps'] if q.kind == 'door']
    assert len(doors) == 1 and not doors[0].exterior and 195 <= doors[0].cx <= 237
    assert r['add'][60:90, 20:28].mean() > 0.5 and r['add'][60:90, 432:440].mean() > 0.5
    assert not r['outside'][100, 230]
    r0 = run(fc.xy_cut(wall, max(40, 3 * t)))                       # как до: обломок стены — отдельный план
    assert r0['outside'][100, 230] and not [q for q in r0['gaps'] if q.kind == 'door' and not q.exterior]


def test_split_composite_divides_merged_closures():
    """T-20261111-09: два закрытия, сросшиеся углом (Г 50×70 px), — два разрыва; пиксели без номера — к ближайшему закрытию,
    одно закрытие и мелкий разрыв не трогаются."""
    add = np.zeros((120, 120), np.uint8)
    kid = np.zeros((120, 120), np.int32)
    add[10:18, 10:61] = 1; kid[10:18, 10:61] = 1                    # закрытие 1 — по горизонтали
    add[18:81, 53:61] = 1; kid[18:81, 53:61] = 2                    # закрытие 2 — по вертикали
    add[18:22, 10:14] = 1                                           # без номера у закрытия 1
    add[76:81, 47:53] = 1                                           # без номера у закрытия 2
    add[100:106, 90:110] = 1; kid[100:106, 90:110] = 3              # отдельный мелкий разрыв
    outside = np.zeros_like(add); outside[:, :9] = 1
    lab, gaps = fc.gap_components(add, np.zeros_like(add), outside)
    assert len(gaps) == 2
    inner = [fc.Gap(q.id, q.cx, q.cy, q.length, q.depth, q.kind, q.glaze, False, q.bbox) for q in gaps]
    assert len(fc.split_composite(lab.copy(), inner, kid, np.zeros_like(add), outside, 20)[1]) == 2   # внутренний — не делим
    lab2, out = fc.split_composite(lab.copy(), gaps, kid, np.zeros_like(add), outside, 20)
    assert len(out) == 3
    a, b = lab2[12, 20], lab2[50, 56]
    assert a != b and a > 0 and b > 0
    assert lab2[20, 11] == a and lab2[78, 49] == b                  # пиксели без номера — к ближайшему
    small = [q for q in out if q.cx > 85]
    assert len(small) == 1 and small[0].id == lab[102, 100]
    horiz = next(q for q in out if q.id == a)
    assert horiz.exterior and 49 <= horiz.length <= 53
    vert = next(q for q in out if q.id == b)
    assert not vert.exterior and 62 <= vert.length <= 66
    line = np.zeros_like(add); kl = np.zeros_like(kid)                # окно, закрытое двумя проходами в линию, — один проём
    line[10:18, 10:61] = 1; kl[10:18, 10:35] = 1; kl[10:18, 35:61] = 2
    lab3, g3 = fc.gap_components(line, np.zeros_like(add), outside)
    assert len(fc.split_composite(lab3, g3, kl, np.zeros_like(add), outside, 5)[1]) == 1


def test_text_mask_drops_label_lines_keeps_door_arcs():
    """T-20261111-09 (прихожая TGva…): перемычка поперёк прохода 0,9 м получала «дверь» 0,95 по буквам подписи «Hallway…».
    Строки подписей уходят из тонких линий (`text_mask`); дуга двери — сплошная и пунктирная — и прямая створка остаются."""
    ppm = 100.0
    ys, xs = np.mgrid[97:104, 60:121]
    c, u, n, L, d = fc.gap_axes(ys.ravel(), xs.ravel())
    text = np.zeros((260, 200), np.uint8)
    for k, s in enumerate(('Hallway', "2'11 x 12'5", '0.90 x 3.80 m')):
        cv2.putText(text, s, (40, 125 + 22 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1, 2)
    assert fc.door_evidence(text, c, u, n, L, d) >= 0.75                       # прежде — «дверь»
    tm = fc.text_mask(text, ppm)
    assert tm.sum() >= 0.8 * (text > 0).sum()
    assert fc.door_evidence(np.where(tm, 0, text).astype(np.uint8), c, u, n, L, d) < 0.5     # bench.TEXT_EV_MIN
    door = np.zeros_like(text)
    cv2.ellipse(door, (60, 100), (60, 60), 0, 0, 90, 1, 2)                     # сплошная дуга
    cv2.line(door, (60, 100), (60, 160), 1, 2)                                 # створка
    for a0 in range(0, 90, 10):                                                # пунктирная дуга соседней двери
        cv2.ellipse(door, (140, 30), (45, 45), 0, a0, a0 + 5, 1, 2)
    cv2.line(door, (10, 240), (90, 240), 1, 2)                                 # прямая створка в стене с засечкой
    cv2.line(door, (50, 234), (50, 240), 1, 2)
    assert not fc.text_mask(door, ppm).any()


def _arrow(img, x, y, vertical=False):
    """Залитая стрелка «→» как на листах rgK5… (t 8): древко 7×5 px, головка-треугольник 9 px в основании, длина 14 px."""
    pts = np.array([[0, 2], [6, 2], [6, 0], [13, 4], [6, 8], [6, 6], [0, 6]])
    if vertical:
        pts = pts[:, ::-1]
    cv2.fillPoly(img, [pts + [x, y]], 0)


def test_arrow_glyphs_drop_arrows_keep_wall_bits():
    """T-20261111-13 (rgK5… Bedroom 3): залитая стрелка у торца стены давала ложную дверь у угла спальни. Отдельный кусок маски
    в форме стрелки (головка-треугольник + древко уже головки) снимается; столб, тонкая полоска, Г-обрубок и стены — нет."""
    t = 8
    gray = np.full((200, 300), 255, np.uint8)
    cv2.rectangle(gray, (10, 10), (289, 189), 0, t)                 # наружные стены
    _arrow(gray, 60, 60)
    _arrow(gray, 120, 60, vertical=True)
    gray[60:72, 180:188] = 0                                        # столб 8×12
    gray[120:125, 60:78] = 0                                        # полоска 18×5 (тоньше стены)
    gray[120:128, 180:200] = 0                                      # Г-обрубок: стена 8 × 20 + «пятка» 8 × 8
    gray[128:136, 180:188] = 0
    wall = (gray < 100).astype(np.uint8)
    drop = fc.arrow_glyphs(wall, gray, 100, t)
    n = cv2.connectedComponents(drop)[0] - 1
    assert n == 2
    assert drop[60:69, 60:74].sum() > 0 and drop[60:74, 120:129].sum() > 0
    assert drop[:, 170:].sum() == 0 and drop[115:130, 55:80].sum() == 0 and drop[10:18, :].sum() == 0
    assert fc.arrow_glyphs(wall, gray, 100, 20).sum() == 0         # при t 20 головка 9 px — штрих, не стрелка
    assert fc.arrow_profile([1, 2, 3, 4, 5, 7, 8, 9, 5, 5, 5, 5, 5, 5])
    assert not fc.arrow_profile([5] * 14)                           # прямоугольник
    assert not fc.arrow_profile([16] * 8 + [8] * 12)                # уступ без нарастания


def test_arrow_doors_drop_wall_arrow_gap_merge_split_doorway():
    """T-20261111-13: стрелки правят только проёмы (`bench.arrow_doors`): разрыв «торец стены ↔ стрелка» (rgK, Bedroom 3) — не
    проём; стрелка посреди проёма делит его на два разрыва — один проём во всю ширину; разрыв без стрелки — как был."""
    import bench
    lab_g = np.zeros((100, 200), np.int32)
    arrows = np.zeros((100, 200), np.uint8)
    arrows[20:28, 40:54] = 1                                        # стрелка 1: у торца стены, разрыв 1 — между ними
    lab_g[20:28, 30:40] = 1
    arrows[60:68, 80:94] = 1                                        # стрелка 2 посреди проёма: разрывы 2 и 3 по бокам
    lab_g[60:68, 66:80] = 2
    lab_g[60:68, 94:108] = 3
    lab_g[60:68, 150:176] = 4                                       # обычная дверь
    arrows[85:93, 150:164] = 1                                      # стрелка 3 у длинного закрытия (зона у лестницы)
    lab_g[93:99, 120:190] = 5
    lens = {1: 10, 2: 14, 3: 14, 4: 26, 5: 70}
    gaps = [fc.Gap(i, 0, 0, lens[i], 8, 'door', 0.0, False, (0, 0, 0, 0)) for i in lens]
    drop, merged, used = bench.arrow_doors(gaps, lab_g, arrows, 8)
    assert drop == {1} and used == {2, 3} and len(merged) == 1     # длинное закрытие 5 (> 3 t) — как было
    cx, cy, L, ext = merged[0]
    assert abs(cx - 86.5) <= 1.5 and abs(L - 42) <= 2 and not ext
    assert bench.arrow_doors(gaps, lab_g, None, 8) == (set(), [], set())


def test_arrow_doors_single_gap_arrow_in_doorway_is_whole_door():
    """T-20261111-13/2 (rgK p1, санузел/Cupboard): стрелка «↓» стоит посреди двери 66 см, разрыв нашёлся только с одной стороны
    (26 см). За стрелкой по линии стены — торец стены: дверь от торца до торца, не снятие. Стрелка у торца на открытом месте
    (за ней стены нет) — щель «торец ↔ стрелка», снимается, как раньше."""
    import bench
    t = 9
    wall = np.zeros((100, 120), np.uint8)
    lab_g = np.zeros((100, 120), np.int32)
    arrows = np.zeros((100, 120), np.uint8)
    wall[40:49, 0:30] = 1                                           # стена с дверью 30..49 (20 px)
    wall[40:49, 50:120] = 1
    arrows[34:53, 37:44] = 1                                        # стрелка поперёк стены посреди двери
    lab_g[40:49, 44:50] = 1                                         # разрыв только справа от стрелки
    wall[70:79, 0:30] = 1                                           # торец стены, дальше открыто
    arrows[70:79, 36:48] = 1                                        # стрелка «→» на открытом месте у торца
    lab_g[70:79, 30:36] = 2
    wall |= arrows
    gaps = [fc.Gap(1, 0, 0, 6, 9, 'door', 0.0, False, (0, 0, 0, 0)),
            fc.Gap(2, 0, 0, 6, 9, 'door', 0.0, False, (0, 0, 0, 0))]
    drop, merged, used = bench.arrow_doors(gaps, lab_g, arrows, t, wall)
    assert drop == {2} and used == {1} and len(merged) == 1
    cx, cy, L, ext = merged[0]
    assert abs(cx - 39.5) <= 1.5 and abs(cy - 44) <= 1.5 and abs(L - 20) <= 2 and not ext
    assert bench.arrow_doors(gaps, lab_g, arrows, t)[0] == {1, 2}    # без маски стен — как раньше
