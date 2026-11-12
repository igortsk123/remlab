"""T-20261111-11 (bs30, Ferndale Avenue): площадка 2-го этажа резалась ложными «дверями», гараж делился пополам.
Синтетика под каждое правило: полоса-проём `xy_cut`, «чистая» дуга и створка `door_evidence` (штриховка, текст, створка вдоль
грани стены), приоткрытая створка, край марша `stair_edge`, «одна дуга — одна дверь» `bench.own_arcs`."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402


def garage(t=6):
    """Узкая постройка 200×330 px: окно сверху (x 80..140) и ворота снизу (x 70..150) — напротив друг друга."""
    m = np.zeros((360, 240), np.uint8)
    cv2.rectangle(m, (10, 10), (10 + 200 + 2 * t - 1, 10 + 330 + 2 * t - 1), 1, -1)
    m[10 + t:10 + t + 330, 10 + t:10 + t + 200] = 0
    m[10:10 + t, 80:140] = 0
    m[10 + 330 + t:10 + 330 + 2 * t, 70:150] = 0
    return m


def test_xy_cut_keeps_narrow_building_with_opposite_openings():
    m = garage()
    assert len(fc.xy_cut(m, min_gap=40)) == 2                       # прежнее правило: пустая полоса через окно и ворота
    assert len(fc.xy_cut(m, min_gap=40, max_open=120)) == 1         # полоса-проём — одна постройка
    assert len(fc.xy_cut(m, min_gap=40, max_open=40)) == 2          # шире предела — режем, как прежде


def test_xy_cut_still_splits_two_plans_with_open_band_rule():
    m = np.zeros((200, 500), np.uint8)
    a = np.zeros((152, 182), np.uint8)
    cv2.rectangle(a, (10, 10), (171, 141), 1, -1)
    a[16:136, 16:166] = 0
    m[20:172, 10:192] |= a
    m[20:172, 300:482] |= a
    assert len(fc.xy_cut(m, min_gap=40, max_open=200)) == 2         # боковые стены вдоль полосы — два плана


def gap_h(x0=60, x1=120, y=100):
    ys, xs = np.mgrid[y - 3:y + 4, x0:x1 + 1]
    return fc.gap_axes(ys.ravel(), xs.ravel())


def test_door_evidence_ignores_hatch_and_text(monkeypatch):
    """Сплошная штриховка (текст подписи, ступени) задевает все радиусы — не дуга и не створка; без правила — «дверь» 1,0."""
    thin = np.zeros((220, 220), np.uint8)
    for y in range(104, 200, 4):
        cv2.line(thin, (30, y), (190, y), 1, 1)
    for x in range(30, 190, 4):
        cv2.line(thin, (x, 104), (x, 200), 1, 1)
    c, u, n, L, d = gap_h()
    assert fc.door_evidence(thin, c, u, n, L, d) < 0.75
    assert fc.door_evidence(thin, c, u, n, L, d, pure_check=False) >= 0.75    # прежнее правило (запасная дверь, T-11/3)
    monkeypatch.setenv('FP_ARC_PURE', '0')
    assert fc.door_evidence(thin, c, u, n, L, d) >= 0.75


def test_door_evidence_hatched_floor_keeps_old_rule():
    """T-11/2, лист aOv8kT: пол заштрихован целиком (паркет), дуга двери пунктиром тонет в штриховке. Штриховка — по всему полу у
    разрыва, а не пятном: «чистота» не различает, действует прежнее правило (дверь есть, как в main)."""
    thin = np.zeros((220, 220), np.uint8)
    for k in range(-220, 440, 7):
        cv2.line(thin, (k, 0), (k + 220, 220), 1, 1)
        cv2.line(thin, (k, 220), (k + 220, 0), 1, 1)
    wall = np.zeros_like(thin)
    wall[96:104, :60] = 1
    wall[96:104, 121:] = 1
    thin[wall > 0] = 0
    thin[96:104, 60:121] = 0
    c, u, n, L, d = gap_h()
    assert fc.door_evidence(thin, c, u, n, L, d, wall=wall) >= 0.75


def test_door_evidence_leaf_along_wall_face_is_not_a_leaf():
    """Половина дуги + прямая у петли: дверь (`LEAF_SCORE`). Та же прямая вплотную к грани стены (тетива лестницы, обвод стены
    поперёк разрыва) — не створка."""
    thin = np.zeros((220, 220), np.uint8)
    cv2.ellipse(thin, (60, 100), (60, 60), 0, 50, 90, 1, 1)
    cv2.line(thin, (60, 100), (60, 160), 1, 1)
    c, u, n, L, d = gap_h()
    assert fc.door_evidence(thin, c, u, n, L, d) >= fc.LEAF_SCORE
    wall = np.zeros_like(thin)
    wall[100:220, 40:58] = 1                                        # стена слева от «створки», грань в 2 px
    assert fc.door_evidence(thin, c, u, n, L, d, wall=wall) < 0.75
    far = np.zeros_like(thin)
    far[100:220, 0:30] = 1                                          # стена далеко — створка засчитана
    assert fc.door_evidence(thin, c, u, n, L, d, wall=far) >= fc.LEAF_SCORE


def test_door_evidence_sees_half_open_leaf():
    """Дверца шкафа приоткрыта на ~37°: дуга 0–37° и прямая створка под тем же углом — дверь."""
    thin = np.zeros((220, 220), np.uint8)
    a = np.radians(37)
    cv2.line(thin, (60, 100), (int(round(60 + 60 * np.cos(a))), int(round(100 + 60 * np.sin(a)))), 1, 1)
    cv2.ellipse(thin, (60, 100), (60, 60), 0, 0, 37, 1, 1)
    c, u, n, L, d = gap_h()
    assert fc.door_evidence(thin, c, u, n, L, d) >= fc.LEAF_SCORE
    arc_only = np.zeros_like(thin)
    cv2.ellipse(arc_only, (60, 100), (60, 60), 0, 0, 37, 1, 1)
    assert fc.door_evidence(arc_only, c, u, n, L, d) < 0.75


def test_door_evidence_want_px_returns_drawing_pixels():
    thin = np.zeros((220, 220), np.uint8)
    cv2.ellipse(thin, (60, 100), (60, 60), 0, 0, 90, 1, 1)
    c, u, n, L, d = gap_h()
    ev, px = fc.door_evidence(thin, c, u, n, L, d, want_px=True)
    assert ev >= 0.75 and len(px) > 50
    ys, xs = np.divmod(np.array(sorted(px)), thin.shape[1])
    assert thin[ys, xs].all()


def test_stair_edge_treads_vs_window_frame():
    ppm = 63.0
    c, u, n, L, d = gap_h()
    stairs = np.zeros((220, 220), np.uint8)
    for y in (112, 126, 140, 154):                                  # ступени через ~0,22 м
        cv2.line(stairs, (55, y), (125, y), 1, 1)
    assert fc.stair_edge(stairs, c, u, n, L, d, ppm)
    frame = np.zeros_like(stairs)
    for y in (106, 109, 112):                                       # рама: линии через 3 px — одна
        cv2.line(frame, (55, y), (125, y), 1, 1)
    assert not fc.stair_edge(frame, c, u, n, L, d, ppm)
    bay = np.zeros_like(stairs)
    for y in (112, 122, 132):                                       # эркер: линии частично (~60 % разрыва)
        cv2.line(bay, (76, y), (104, y), 1, 1)
    assert not fc.stair_edge(bay, c, u, n, L, d, ppm)


def test_own_arcs_one_arc_one_door():
    """Заявка, чей рисунок уже забрала более сильная дверь, снимается; своя дуга — остаётся; закрытия не по дуге — не трогаем."""
    H, W = 50, 50
    pa, pb, pc = frozenset(range(0, 100)), frozenset(range(0, 80)) | frozenset(range(200, 210)), frozenset(range(300, 400))
    A = (np.array([1, 1]), np.array([1, 2]), 1.0, pa)
    B = (np.array([5, 5, 1]), np.array([5, 6, 2]), 0.8, pb)        # пиксель (1,2) — общий с A
    C = (np.array([9]), np.array([9]), 0.8, pc)
    other = np.zeros((H, W), np.uint8)
    other[5, 6] = 1
    drop = bench.own_arcs([A, B, C], other)
    assert drop is not None and drop[5, 5] and not drop[5, 6] and not drop[1, 2] and not drop[9, 9]
    assert bench.own_arcs([A, C], other) is None


def doorless_case(c0=140):
    """Три комнаты в ряд (ppm 30, допуск 9 px): у A дверь (разрыв 1), у B и C дверей нет. У B — две кандидатки прежнего правила
    (0,8 и 0,95; вторая — у C, если C начинается ближе 9 px), у C — наружный разрыв 2, ставший окном только по «чистоте»."""
    lab = np.zeros((60, 200), np.int32)
    lab[10:50, 10:60], lab[10:50, 70:120], lab[10:50, c0:190] = 1, 2, 3
    lab_g = np.zeros_like(lab)
    lab_g[20:30, 6:8] = 1
    lab_g[50:52, 150:170] = 2
    gaps = [fc.regap(fc.Gap(1, 0, 0, 0, 0, 'door', 0.0, False, (0, 0, 0, 0)), *np.nonzero(lab_g == 1)),
            fc.regap(fc.Gap(2, 0, 0, 0, 0, 'window', 0.0, True, (0, 0, 0, 0)), *np.nonzero(lab_g == 2))]
    ya, xa = np.nonzero(np.pad(np.ones((2, 20), bool), ((50, 8), (80, 100))))
    yb, xb = np.nonzero(np.pad(np.ones((20, 2), bool), ((20, 20), (120, 78))))
    return {'lab': lab, 'lab_g': lab_g, 'gaps': gaps, 'rooms': [1, 2, 3], 'outside': np.zeros(lab.shape, np.uint8),
            'alts': [(ya, xa, 0.8), (yb, xb, 0.95)], 'retype': [(2, 0.9)]}


def test_doorless_room_gets_best_old_rule_door(monkeypatch):
    """T-11/3 (rgK5f3: кухня, кладовые, WC без единой двери): комнате без дверей — лучшая кандидатка прежнего правила у неё;
    комнату с дверью не трогаем; наружное «окно» по одной «чистоте» — снова дверь. Без флага — ничего не меняется."""
    r = doorless_case()
    monkeypatch.setattr(bench, 'DOORLESS', False)
    assert bench.doorless_doors(r, 30.0) == [] and len(r['gaps']) == 2
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert [a[0] for a in added] == [2, 3]
    assert len(r['gaps']) == 3 and r['gaps'][2].kind == 'door'
    assert r['lab_g'][30, 120] == r['gaps'][2].id                    # B: кандидатка 0,95 (между B и C), не 0,8
    assert r['gaps'][1].kind == 'door'                               # C: окно → дверь
    assert r['lab_g'][50, 85] == 0                                   # вторая кандидатка B не добавлена


def test_doorless_room_glazed_window_with_arc_becomes_door(monkeypatch):
    """T-11/4 (rgK5f3 Tool store: проём залит серым — «рама», дуга открывания наружу): у комнаты без дверей и без кандидаток
    прежнего правила окно с дугой (`glazed`) — дверь; окно соседней комнаты у угла (меньше половины у пола) — нет; кандидатка
    прежнего правила важнее окна с дугой."""
    r = doorless_case()
    r['retype'] = []
    r['lab_g'][50:52, 120:136] = 3                                  # окно у угла B/C: у C — 5 столбцов из 16
    r['gaps'].append(fc.regap(fc.Gap(3, 0, 0, 0, 0, 'window', 1.0, True, (0, 0, 0, 0)), *np.nonzero(r['lab_g'] == 3)))
    r['glazed'] = [(3, 1.0)]
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert [a[0] for a in added] == [2] and r['gaps'][2].kind == 'window'   # C: окно у угла не её; B: прежнее правило 0,95
    assert r['gaps'][1].kind == 'window'
    r2 = doorless_case()
    r2['retype'], r2['glazed'] = [], [(2, 0.8)]
    added = bench.doorless_doors(r2, 30.0)
    assert [a[0] for a in added] == [2, 3] and r2['gaps'][1].kind == 'door'   # C: своё окно с дугой → дверь


def test_doorless_room_door_by_corner_does_not_count(monkeypatch):
    """T-11/4 (rgK5f3 Tool store): закрытие, лишь углом у пола комнаты (ближний пиксель в 6 px, но у пола — кусок меньше
    половины его ширины), комнате дверь не даёт — она получает свою (окно C с дугой → дверь)."""
    r = doorless_case()
    r['lab'][10:25, 140:190] = 0                                     # C — строки 25..49
    r['lab_g'][0:20, 190:200] = 4                                    # «дверь» над правым углом C
    r['gaps'].append(fc.regap(fc.Gap(4, 0, 0, 0, 0, 'door', 0.0, True, (0, 0, 0, 0)), *np.nonzero(r['lab_g'] == 4)))
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert 3 in [a[0] for a in added] and r['gaps'][1].kind == 'door'


def test_doorless_room_counts_deep_door_by_its_face(monkeypatch):
    """T-11/5 (rgK5f3 p1 Bathroom): глубокий проём 24×24 px лицом к полу комнаты — её дверь, хотя середина в 12 px (> допуска
    9): окно C с дугой остаётся окном, второй двери у C нет."""
    r = doorless_case()
    r['lab'][10:25, 140:190] = 0                                     # C — строки 25..49
    r['lab_g'][1:25, 150:174] = 4
    r['gaps'].append(fc.regap(fc.Gap(4, 0, 0, 0, 0, 'door', 0.0, False, (0, 0, 0, 0)), *np.nonzero(r['lab_g'] == 4)))
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert 3 not in [a[0] for a in added] and r['gaps'][1].kind == 'window'


def test_doorless_room_takes_next_candidate_when_first_occupied(monkeypatch):
    """T-11/4 (rgK5f3 Cupboard у кухни): лучшую кандидатку не поставить (её пиксели заняты другим разрывом) — берётся следующая,
    комната не остаётся без двери."""
    r = doorless_case()
    r['lab_g'][20:30, 190:192] = 5
    r['gaps'].append(fc.regap(fc.Gap(5, 0, 0, 0, 0, 'wall', 0.0, False, (0, 0, 0, 0)), *np.nonzero(r['lab_g'] == 5)))
    yo, xo = np.nonzero(r['lab_g'] == 5)
    r['alts'].append((yo, xo, 0.99))
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert (3, 0.9) in added and r['gaps'][1].kind == 'door'


def test_doorless_room_shared_candidate_serves_both(monkeypatch):
    """Кандидатка между двумя комнатами без дверей — одна дверь на обе (вторая комната её видит и не берёт ещё одну)."""
    r = doorless_case(c0=125)
    r['retype'] = []
    monkeypatch.setattr(bench, 'DOORLESS', True)
    added = bench.doorless_doors(r, 30.0)
    assert [a[0] for a in added] == [2] and r['gaps'][1].kind == 'window'


def test_window_with_arrow_becomes_door():
    """T-11/6 (rgK5f3 p4 Cellar): стрелка (вход, лестница) в «окне» или вплотную (2 px) — дверь; окно без стрелки и дальше
    2 px — окно; дверь не трогаем."""
    r = doorless_case()
    lab_g, gaps = r['lab_g'], r['gaps']
    lab_g[0:2, 20:40] = 3
    gaps.append(fc.regap(fc.Gap(3, 0, 0, 0, 0, 'window', 0.0, True, (0, 0, 0, 0)), *np.nonzero(lab_g == 3)))
    arr = np.zeros(lab_g.shape, np.uint8)
    arr[53:56, 158:162] = 1                                          # в 1 px под окном 2 (строки 50..51)
    lab_g[0:2, 100:110] = 4                                          # короткая (10 px ≤ 3 t) щель у стрелки — дело arrow_doors
    gaps.append(fc.regap(fc.Gap(4, 0, 0, 0, 0, 'window', 0.0, True, (0, 0, 0, 0)), *np.nonzero(lab_g == 4)))
    arr[2:4, 104:106] = 1
    assert bench.arrow_windows(gaps, lab_g, None, 4.0) == [] and gaps[1].kind == 'window'
    assert bench.arrow_windows(gaps, lab_g, arr, 4.0) == [2]
    assert [g.kind for g in gaps] == ['door', 'door', 'window', 'window']
