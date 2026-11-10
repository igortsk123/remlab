"""Обрывки за нашими закрытиями (T-20261110-19): мелкий безымянный кусок, отрезанный от соседа достроенным разрывом (не стеной
листа), вливается в соседа; кладовка в стенах листа и кусок с подписью — остаются; мерка соседа с подписью не портится."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402
import repair as rp  # noqa: E402

PPM = 20.0          # px на метр
T = 6               # толщина стены, px
O = 10 + T          # начало пола холла


def hall(piece='closure', piece_label=None, hall_dims=None, outside_piece=False, right_rows=30, hall_rows=30, outer_add=False):
    """Холл 4×4 м (80×80 px) в стенах. В правом верхнем углу — кусок 1,0×0,8 м (20×16 px), отделённый:
    'closure' — нашими закрытиями слева и снизу (add); 'cupboard' — стенами листа, снизу дверь 0,6 м (закрытие).
    outside_piece — кусок 0,9×1,5 м между холлом и комнатой 3 (3×4 м) справа; стенки к обоим — наши закрытия."""
    xe = O + 80
    x0 = xe + T                                           # кусок (outside_piece)
    x3 = x0 + 18 + T                                      # комната 3
    W = (x3 + 60 + T + 10) if outside_piece else (80 + 2 * T + 20)
    H = 80 + 2 * T + 20
    final = np.zeros((H, W), np.uint8)
    final[10:O + 80 + T, 10:(x3 + 60 + T if outside_piece else xe + T)] = 1
    final[O:O + 80, O:O + 80] = 0
    add = np.zeros((H, W), np.uint8)
    lab = np.zeros((H, W), np.int32)
    lab[O:O + 80, O:O + 80] = 1
    if outside_piece:
        final[O:O + 30, x0:x0 + 18] = 0
        lab[O:O + 30, x0:x0 + 18] = 2
        final[O:O + 80, x3:x3 + 60] = 0
        lab[O:O + 80, x3:x3 + 60] = 3
        add[O:O + hall_rows, xe:xe + T] = 1              # стенка к холлу — наше закрытие
        if outer_add:                                     # верх и низ куска — тоже наши (к соседу не ведут)
            add[O - T:O, x0 + T:x0 + 18] = 1
            add[O + 30:O + 30 + T, x0 + T:x0 + 18] = 1
        add[O:O + right_rows, x0 + 18:x3] = 1            # стенка к комнате 3 — тоже (right_rows — какая её часть)
    else:
        px0, py1 = xe - 20, O + 16
        lab[O:py1, px0:xe] = 2
        final[O:py1 + T, px0 - T:px0] = 1                 # левая сторона куска
        final[py1:py1 + T, px0 - T:xe] = 1                # нижняя
        lab[final > 0] = 0
        if piece == 'closure':
            add[O:py1 + T, px0 - T:px0] = 1
            add[py1:py1 + T, px0 - T:xe] = 1
        else:                                             # кладовка: стены листа, снизу дверь 12 px
            add[py1:py1 + T, px0 + 4:px0 + 16] = 1
    gray = np.full((H, W), 255, np.uint8)
    gray[(final > 0) & (add == 0)] = 0
    st = rp.State(lab, final, [1, 2, 3] if outside_piece else [1, 2], add)
    ctx = rp.Ctx(gray=gray, ev=(final > 0) & (add == 0), wp=rp.wall_prob(gray), ppm=PPM, t_int=T, fams=[0.0], conv=('p95', 0))
    labels = [rp.Label('Hall', (O + 30, O + 50), hall_dims)]
    if piece_label:
        labels.append(rp.Label(piece_label, (xe - 10, O + 8), None, 'vlm-space'))
    return st, ctx, labels


def test_fragment_behind_our_closure_joins_neighbour():
    st, ctx, labels = hall('closure')
    st2, jr, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [{'into': 1, 'piece': 2, 'm2': 0.8}]
    assert st2.rooms == [1] and not (st2.lab == 2).any()
    assert not (st2.add > 0).any() and (st2.final[st.add > 0] == 0).all()   # закрытия между ними сняты
    assert (st2.final[10:O, :] > 0).any()                                    # стена листа — на месте
    rec = [e for e in jr if e.get('applied')]
    assert rec and rec[0]['ours'] >= rp.FRAG_OURS_MIN


def test_cupboard_in_drawn_walls_stays():
    st, ctx, labels = hall('cupboard')
    st2, jr, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [] and 2 in st2.rooms
    assert any(e.get('why') == 'замкнут стенами листа' and e['ours'] < rp.FRAG_OURS_MIN for e in jr)


def test_named_piece_stays():
    st, ctx, labels = hall('closure', piece_label='Cupboard')
    st2, _, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [] and 2 in st2.rooms


def test_neighbour_dims_not_spoiled():
    # закрытий к холлу и к комнате 3 поровну — первым пробуется холл (с подписью); его мерка 4×4 м сходится, с куском
    # он стал бы 5,2 м — не в него, а в комнату 3
    st, ctx, labels = hall(outside_piece=True, hall_dims=(4.0, 4.0))
    st2, jr, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [{'into': 3, 'piece': 2, 'm2': 1.35}] and st2.rooms == [1, 3]
    assert any(e.get('into') == 1 and str(e.get('why', '')).startswith('мерка Hall хуже') for e in jr)
    # без размера в подписи — в холл
    st, ctx, labels = hall(outside_piece=True)
    _, _, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [{'into': 1, 'piece': 2, 'm2': 1.35}]
    # к комнате 3 закрытие лишь на треть стенки — слабый касатель не запасной сосед: кусок остаётся
    st, ctx, labels = hall(outside_piece=True, hall_dims=(4.0, 4.0), right_rows=10)
    st2, jr, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [] and 2 in st2.rooms
    assert not any(e.get('into') == 3 for e in jr)


def test_short_contact_not_merged(monkeypatch):
    # закрытий у куска хватает (порог доли снижен, чтобы дойти до проверки касания), но к холлу — лишь 0,3 м
    # (короче CONTACT_MIN_M): не вливается — вошёл бы в холл островом
    monkeypatch.setattr(rp, 'FRAG_OURS_MIN', 0.2)
    st, ctx, labels = hall(outside_piece=True, right_rows=0, hall_rows=6, outer_add=True)
    st2, jr, done = rp.absorb_fragments(st, labels, ctx, bench.is_fragment)
    assert done == [] and 2 in st2.rooms
    assert any(e.get('why') == 'касается соседа коротко' for e in jr)


def test_shrink_gaps_drops_and_trims():
    lab_g = np.zeros((40, 60), np.int32)
    lab_g[10:14, 5:25] = 1                                # снят целиком
    lab_g[20:24, 5:45] = 2                                # снят наполовину
    lab_g[30:34, 5:25] = 3                                # не тронут
    gaps = [fc.Gap(i, 0.0, 0.0, 0.0, 0.0, 'door', 0.0, False, (0, 0, 0, 0)) for i in (1, 2, 3)]
    removed = np.zeros_like(lab_g, bool)
    removed[10:14, 5:25] = True
    removed[20:24, 25:45] = True
    lg, out = bench.shrink_gaps(lab_g, gaps, removed)
    assert [g.id for g in out] == [2, 3]
    g2 = out[0]
    assert abs(g2.length - 20) <= 1.5 and abs(g2.cx - 14.5) <= 1 and g2.bbox == (5, 20, 20, 4)
    assert out[1] is gaps[2] and not (lg == 1).any() and (lg[20:24, 25:45] == 0).all()
