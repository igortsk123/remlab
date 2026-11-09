"""Круг самопочинки стен (T-20261109-03): гипотеза → цена → принять/откатить, min-cut на синтетике, табу."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import repair as rp  # noqa: E402

PPM = 20.0          # px на метр в синтетике
T = 6               # толщина стены, px


def two_rooms_merged(line_gray=150):
    """Прямоугольник 8×4 м (160×80 px) в стенах; посередине — нарисованная светло-серая перегородка, которую маска
    стен не взяла (в маске — одна комната). → (State, Ctx, labels)."""
    H, W = 80 + 2 * T + 20, 160 + 2 * T + 20
    final = np.zeros((H, W), np.uint8)
    cv2.rectangle(final, (10, 10), (10 + 160 + 2 * T - 1, 10 + 80 + 2 * T - 1), 1, -1)
    final[10 + T:10 + T + 80, 10 + T:10 + T + 160] = 0
    lab = np.zeros((H, W), np.int32)
    lab[10 + T:10 + T + 80, 10 + T:10 + T + 160] = 1
    gray = np.full((H, W), 255, np.uint8)
    gray[final > 0] = 0
    xm = 10 + T + 80
    gray[10 + T:10 + T + 80, xm - 1:xm + 1] = line_gray
    st = rp.State(lab, final, [1], np.zeros((H, W), np.uint8))
    ctx = rp.Ctx(gray=gray, ev=final > 0, wp=rp.wall_prob(gray), ppm=PPM, t_int=T, fams=[0.0], conv=('p95', 0))
    labels = [rp.Label('A', (10 + T + 40, 10 + T + 40), (4.0, 4.0)), rp.Label('B', (10 + T + 120, 10 + T + 40), (4.0, 4.0))]
    return st, ctx, labels


# --- min-cut ----------------------------------------------------------------------------------------------------------------

def test_mincut_follows_drawn_line():
    st, ctx, labels = two_rooms_merged()
    region = st.lab == 1
    a = np.zeros_like(region); b = np.zeros_like(region)
    a[50, 30] = True; b[50, 170] = True
    A, flow, n = rp.mincut_split(region, a, b, ctx.wp)
    xm = 10 + T + 80
    cols = np.nonzero(A.any(axis=0))[0]
    assert abs(int(cols.max()) - xm) <= 2            # разрез — по нарисованной линии, не у семени
    assert not (A & (np.arange(A.shape[1])[None, :] > xm + 2)).any()


def test_mincut_without_line_takes_narrow_neck():
    # две комнаты 60×60, соединённые проходом 10 px: разрез — поперёк прохода (дёшево), а не по комнате
    region = np.zeros((80, 160), bool)
    region[10:70, 5:65] = True
    region[10:70, 95:155] = True
    region[35:45, 65:95] = True
    wp = np.zeros(region.shape)
    # семена — круги по телу комнаты (как seed_disk): от точечного семени разрез «усаживается» вокруг него
    dt = cv2.distanceTransform(region.astype(np.uint8), cv2.DIST_L2, 5)
    a = rp.seed_disk(region, (35, 40), 3, dt)
    b = rp.seed_disk(region, (125, 40), 3, dt)
    A, flow, n = rp.mincut_split(region, a, b, wp, eps=0.05, k=1.0)
    assert A[10:70, 5:65].all() and not A[10:70, 95:155].any()
    assert flow <= 100 * 1.05 * 10 + 5                # ≈ ширина прохода × цена ребра


def test_mincut_without_seeds_returns_none():
    region = np.ones((10, 10), bool)
    assert rp.mincut_split(region, np.zeros_like(region), region, np.zeros(region.shape)) is None


# --- гипотеза → цена → принять/откатить ---------------------------------------------------------------------------------------

def test_mincut_hypothesis_accepted_and_journaled():
    st, ctx, labels = two_rooms_merged()
    t0 = rp.topology(st, labels, PPM)
    assert t0['merged_t'] == 1 and t0['cost'] == rp.W_MERGED
    st2, journal = rp.run(st, labels, ctx, outside=np.zeros_like(st.final, bool))
    t1 = rp.topology(st2, labels, PPM)
    assert t1['cost'] == 0                            # подписи разошлись по комнатам
    applied = [x for x in journal if x.get('applied')]
    assert applied and applied[0]['kind'] == 'mincut' and applied[0]['why'] == 'топология лучше'
    assert applied[0]['drawn'] >= 0.6                 # граница — по нарисованной линии
    errs = rp.dims_errors(st2, labels, ctx, t1)
    assert all(e < 0.15 for e, _ in errs.values())    # обе половины 4×4 м
    assert journal[-1]['kind'] == 'stop'
    assert (st.lab == 1).sum() == 160 * 80            # исходное состояние не тронуто (правки — на копии)


def test_accept_lexicographic_order():
    S = rp.Score
    base = S(topo=2, pix=10.0, dims=0.10, edit=0.0)
    assert rp.accept(base, S(3, 9.0, 0.0, 0.0)) == (False, 'топология хуже')
    assert rp.accept(base, S(2, 10.0 + rp.TOL_PIX_M + 0.1, 0.0, 0.0))[0] is False          # пиксели хуже
    assert rp.accept(base, S(0, 10.0, 0.10, 0.0)) == (True, 'топология лучше')
    assert rp.accept(base, S(0, 10.0, 0.20, 0.0)) == (False, 'размеры остальных хуже')     # топология не покупает размеры
    assert rp.accept(base, S(2, 10.0, 0.05, 0.0)) == (True, 'размеры лучше')
    assert rp.accept(base, S(2, 10.0, 0.1 + 0.001, 0.0)) == (False, 'нет улучшения')       # в гистерезисе
    assert rp.accept(base, S(2, 10.0, 0.10, 0.0, x=0, prot=0.0)) == (False, 'нет улучшения')
    assert rp.accept(S(2, 10.0, 0.1, 0.0, x=0, prot=3.0), S(2, 10.0, 0.1, 0.0, x=0, prot=1.0)) == (True, 'форма лучше')


def test_rejected_hypothesis_is_rolled_back():
    # подписи 2×4 м в половинах 4×4 м: разрез топологию чинит, но его же подпись-триггер не судит; а вот лишняя
    # «стена», которой нет на листе, пиксели ухудшает — откат
    st, ctx, labels = two_rooms_merged()
    bad = st.copy()

    def apply(s):
        s = s.copy()
        s.final[20:90, 60:66] = 1                    # стена по белому — нет тёмных пикселей под ней
        return s
    roi = (0, 0, st.lab.shape[1], st.lab.shape[0])
    h = rp.Hyp('remove', (), roi, apply, {'piece': 1}, 'bad')
    b, _ = rp.score(bad, labels, ctx, set(), roi)
    a, _ = rp.score(h.apply(bad), labels, ctx, set(), roi)
    ok, why = rp.accept(b, a)
    assert not ok and why == 'пиксели хуже'


# --- табу: отвергнутая гипотеза не пересчитывается в том же состоянии окна -----------------------------------------------------

def test_tabu_skips_rejected_hypothesis_in_same_window(monkeypatch):
    st, ctx, labels = two_rooms_merged()
    H, W = st.lab.shape
    calls = {'bad': 0, 'pass': 0}

    def fake_score(s, labels, ctx, exclude, roi=None):  # цена = минус число стен в левой полосе (больше стен — лучше)
        return rp.Score(-int(s.final[:, :12].sum()), 0.0, 0.0, 0.0), {}

    def bad_apply(s):
        calls['bad'] += 1
        s = s.copy()
        s.final[:, :12] = 0                          # ухудшает цену → откат
        s.lab[0, W - 1] = 7                          # и что-то меняет в своём окне
        return s

    def make_good(k):
        def ap(s):
            s = s.copy()
            s.final[2 + k, 2] = 1
            return s
        return ap

    def fake_propose(s, labels, ctx, outside):
        k = calls['pass']; calls['pass'] += 1
        return [rp.Hyp('remove', (), (W - 20, 0, W, 20), bad_apply, {'piece': 99}, 'bad'),
                rp.Hyp('remove', (), (0, 0, 12, H), make_good(k), {'piece': k}, f'good{k}')]

    monkeypatch.setattr(rp, 'score', fake_score)
    monkeypatch.setattr(rp, 'propose', fake_propose)
    st2, journal = rp.run(st, labels, ctx, outside=np.zeros((H, W), bool), max_passes=4)
    assert calls['pass'] == 4                         # каждый проход что-то принял
    assert calls['bad'] == 1                          # плохая — один раз: дальше табу (её окно не менялось)
    assert sum(1 for x in journal if x.get('applied')) == 4
    assert all(not x.get('applied') for x in journal if x.get('piece') == 99)


def test_ambiguous_close_alternatives_go_to_human(monkeypatch):
    st, ctx, labels = two_rooms_merged()
    H, W = st.lab.shape

    def fake_score(s, labels, ctx, exclude, roi=None):
        return rp.Score(-int((s.lab == 5).any()), 0.0, 0.0, 0.0), {}

    def part(x0, x1):
        def ap(s):
            s = s.copy()
            s.lab[20:90, x0:x1] = 5
            return s
        return ap

    def fake_propose(s, labels, ctx, outside):
        roi = (0, 0, W, H)
        return [rp.Hyp('mincut', (0,), roi, part(20, 60), {'room': 1}, 'm1'),
                rp.Hyp('mincut', (0,), roi, part(120, 170), {'room': 1}, 'm2')]

    monkeypatch.setattr(rp, 'score', fake_score)
    monkeypatch.setattr(rp, 'propose', fake_propose)
    st2, journal = rp.run(st, labels, ctx, outside=np.zeros((H, W), bool))
    assert any(x['kind'] == 'ambiguous' for x in journal)
    assert not any(x.get('applied') for x in journal)
    assert (st2.lab == st.lab).all()                  # не применили — человеку


# --- свидетельства и форма ------------------------------------------------------------------------------------------------------

def test_wall_prob_local_contrast_sees_light_partition():
    g = np.full((40, 40), 236, np.uint8)
    g[:, 20] = 191                                    # светло-серая линия на белом: до чёрного далеко
    wp = rp.wall_prob(g)
    assert wp[10, 20] >= rp.DRAWN_WP and wp[10, 5] < 0.1


def test_protrusion_finds_corridor_strip():
    m = np.zeros((140, 200), bool)
    m[10:130, 10:130] = True                          # тело 6×6 м
    m[10:30, 130:190] = True                          # коридор 1×3 м
    area, body, thin = rp.protrusion(m, PPM)
    assert 2.0 <= area <= 3.5
    assert thin[20, 170] and not thin[70, 70]


def test_recompute_closes_missing_room():
    # комната 3×3 м с проёмом 0,6 м в стене, к ней не пришла комната из маски: окно закрывает проём → комната
    H, W = 120, 120
    final = np.zeros((H, W), np.uint8)
    cv2.rectangle(final, (20, 20), (20 + 60 + 2 * T - 1, 20 + 60 + 2 * T - 1), 1, -1)
    final[20 + T:20 + T + 60, 20 + T:20 + T + 60] = 0
    final[20 + T + 24:20 + T + 36, 20:20 + T] = 0     # проём 12 px = 0,6 м
    lab = np.zeros((H, W), np.int32)
    gray = np.full((H, W), 255, np.uint8); gray[final > 0] = 0
    st = rp.State(lab, final, [], np.zeros((H, W), np.uint8))
    ctx = rp.Ctx(gray=gray, ev=final > 0, wp=rp.wall_prob(gray), ppm=PPM, t_int=T, fams=[0.0], conv=('p95', 0))
    l = rp.Label('Room', (20 + T + 30, 20 + T + 30), (3.0, 3.0))
    h = rp.hyp_recompute(st, 0, [l], ctx, np.zeros((H, W), bool), 1.0, False)
    assert h is not None and h.kind == 'recompute'
    s2 = h.apply(st)
    t = rp.topology(s2, [l], PPM)
    assert t['missing'] == [] and t['cost'] == 0
    assert s2.add.sum() > 0                           # закрытие проёма — «по построению», не по пикселям
