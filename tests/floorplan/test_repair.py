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


# --- T-38: обрыв нарисованной перегородки между двумя комнатами (partition) --------------------------------------------------

def partition_room(stub_rows, names, transpose=False, island=False, size=(160, 120), door=False, ppm=50.0, jamb=0):
    """Комната size (px) в стенах T; из верхней стены вниз идёт нарисованная перегородка (4 px) на stub_rows строк, дальше
    до нижней стены — белый зазор (в маске одна область). island — вместо нижней стены у конца перегородки короткий
    кусок стены-«остров», под которым области сообщаются; jamb — из нижней стены навстречу идёт второй кусок той же
    перегородки (jamb строк): зазор между ними — проём между косяками. Подписи без размеров (как у VLM) — слева и
    справа. Масштаб ppm=50 — как у листа T (стена 6 px ≈ 12 см)."""
    w, h = size
    H, W = h + 2 * T + 20, w + 2 * T + 20
    x0 = y0 = 10 + T
    final = np.zeros((H, W), np.uint8)
    cv2.rectangle(final, (10, 10), (10 + w + 2 * T - 1, 10 + h + 2 * T - 1), 1, -1)
    final[y0:y0 + h, x0:x0 + w] = 0
    xp = x0 + w // 2 - 2
    final[y0:y0 + stub_rows, xp:xp + 4] = 1
    if jamb:
        final[y0 + h - jamb:y0 + h, xp:xp + 4] = 1
    if island:
        yi = y0 + stub_rows + 15
        final[yi:yi + T, xp - 20:xp + 24] = 1
    lab = np.zeros((H, W), np.int32)
    lab[y0:y0 + h, x0:x0 + w] = 1
    lab[final > 0] = 0
    gray = np.full((H, W), 255, np.uint8)
    gray[final > 0] = 0
    add = np.zeros((H, W), np.uint8)
    if door:                                          # общий проём в нижней стене под концом перегородки — закрыт
        add[y0 + h:y0 + h + T, xp - 30:xp + 34] = 1
        gray[add > 0] = 255
    pts = [(x0 + w // 4, y0 + h // 2), (x0 + 3 * w // 4, y0 + h // 2)]
    if transpose:
        final, lab, gray, add = final.T.copy(), lab.T.copy(), gray.T.copy(), add.T.copy()
        pts = [(y, x) for x, y in pts]
    st = rp.State(lab, final, [1], add)
    ctx = rp.Ctx(gray=gray, ev=final > 0, wp=rp.wall_prob(gray), ppm=ppm, t_int=T, fams=[0.0], conv=('p95', 0))
    labels = [rp.Label(n, p) for n, p in zip(names, pts)]
    return st, ctx, labels


def test_room_tokens_and_distinct_rooms():
    L = [rp.Label(n, (0, 0)) for n in ('Bedroom 2', 'Bedroom 3', 'Bedroom 2', 'Wardrobe', 'Kitchen/Diner', 'Diner',
                                        'Dining Area', 'En-suite', 'Ensuite', 'Bedroom')]
    assert rp.room_tokens('Kitchen/Diner') == ('diner', 'kitchen')
    assert rp.room_tokens('Built-in Wardrobe') is None and rp.room_tokens('Dining Area') is None
    names = lambda gs: [[L[i].name for i in g] for g in gs]  # noqa: E731
    assert names(rp.distinct_rooms([0, 1], L)) == [['Bedroom 2'], ['Bedroom 3']]           # разные комнаты
    assert len(rp.distinct_rooms([0, 2], L)) == 1                                          # дубль
    assert len(rp.distinct_rooms([0, 3], L)) == 1                                          # шкаф — не комната
    assert len(rp.distinct_rooms([4, 5, 6], L)) == 1                                       # составное имя ⊇ часть
    assert len(rp.distinct_rooms([7, 8], L)) == 1                                          # синонимы
    assert len(rp.distinct_rooms([9, 0], L)) == 1                                          # «Bedroom» ⊆ «Bedroom 2»: не резать


def test_partition_closes_short_gap_at_drawn_wall_end():
    for tr in (False, True):
        st, ctx, labels = partition_room(120 - 15, ('Bedroom 2', 'Bedroom 3'), transpose=tr)
        rp._SKIPS.clear()
        h = rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1))
        assert h is not None, rp._SKIPS
        assert h.note['gap_px'] == 15 and h.note['support'] >= partition_support_min()
        st2, journal = rp.run(st, labels, ctx, outside=np.zeros_like(st.final, bool))
        applied = [x for x in journal if x.get('applied')]
        assert [x['kind'] for x in applied] == ['partition']
        t1 = rp.topology(st2, labels, ctx.ppm)
        assert t1['merged'] == 0                          # спальни — разные комнаты
        g = st2.drawn if not tr else st2.drawn.T          # новая стена — ровно в зазоре, по оси перегородки
        ys, xs = np.nonzero(g)
        assert ys.min() == 10 + T + 105 and ys.max() == 10 + T + 119
        assert xs.min() >= 10 + T + 78 and xs.max() <= 10 + T + 81
        assert (st2.final == st.final).all()              # стены «по пикселям» не тронуты
        assert not (st2.lab[st2.drawn] > 0).any()         # полоса новой стены — не пол ни одной из комнат


def partition_support_min():
    import partition
    return partition.SUPPORT_MIN


def test_partition_open_plan_half_wall_not_cut():
    # кухня/гостиная с полустенкой: перегородка на 40 % высоты, дальше широкое сообщение — это одна открытая зона
    st, ctx, labels = partition_room(48, ('Kitchen', 'Lounge'))
    rp._SKIPS.clear()
    assert rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1)) is None
    assert 'толщин' in rp._SKIPS[-1]
    st2, journal = rp.run(st, labels, ctx, outside=np.zeros_like(st.final, bool))
    assert not [x for x in journal if x.get('applied')]
    assert any(x.get('hyp') == 'partition' for x in journal if x.get('kind') == 'skip')   # причина — в журнале


def test_partition_two_labels_of_one_room_not_cut():
    # та же геометрия, что в положительном случае, но подписи одной комнаты (дубль от VLM) — не повод искать стену
    st, ctx, labels = partition_room(120 - 15, ('Bedroom 2', 'Bedroom 2'))
    assert not [h for h in rp.propose(st, labels, ctx, np.zeros_like(st.final, bool)) if h.kind == 'partition']


def test_partition_narrow_passage_without_wall_not_cut():
    # две комнаты 60×60, между ними узкий проход 10 px без висящей перегородки: резать нечего
    H, W = 100, 180
    final = np.ones((H, W), np.uint8)
    final[20:80, 10:70] = 0
    final[20:80, 110:170] = 0
    final[45:55, 70:110] = 0
    lab = np.where(final == 0, 1, 0).astype(np.int32)
    gray = np.where(final > 0, 0, 255).astype(np.uint8)
    st = rp.State(lab, final, [1], np.zeros((H, W), np.uint8))
    ctx = rp.Ctx(gray=gray, ev=final > 0, wp=rp.wall_prob(gray), ppm=PPM, t_int=T, fams=[0.0], conv=('p95', 0))
    labels = [rp.Label('Bedroom 1', (40, 50)), rp.Label('Study', (140, 50))]
    rp._SKIPS.clear()
    assert rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1)) is None


def test_partition_parts_still_connected_elsewhere_not_cut():
    # у конца перегородки короткий зазор до куска стены, но под ним части сообщаются широко — одна область, не две
    st, ctx, labels = partition_room(60, ('Bedroom 2', 'Bedroom 3'), island=True)
    rp._SKIPS.clear()
    assert rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1)) is None
    assert 'не развело' in rp._SKIPS[-1]


def test_partition_splits_shared_door_into_two():
    # зазор упёрся в закрытый общий проём двух спален: стена идёт сквозь закрытие, проём в модели — два
    import types
    import bench
    st, ctx, labels = partition_room(120 - 15, ('Bedroom 2', 'Bedroom 3'), door=True)
    st2, journal = rp.run(st, labels, ctx, outside=np.zeros_like(st.final, bool))
    rec = [x for x in journal if x.get('applied')]
    assert [x['kind'] for x in rec] == ['partition'] and rec[0]['close_px'] == T
    yb = 10 + T + 120                                 # нижняя стена: стена прошла сквозь закрытие проёма
    assert st2.drawn[yb:yb + T, 10 + T + 78:10 + T + 82].all()
    lab_g = (st.add > 0).astype(np.int32)
    ys, xs = np.nonzero(lab_g)
    g = types.SimpleNamespace(kind='door', id=1, cx=float(xs.mean()), cy=float(ys.mean()), length=64.0)
    parts = bench.split_by_drawn(g, lab_g, st2.drawn)
    assert len(parts) == 2 and all(20 <= L <= 34 for _, _, L in parts)
    assert len(bench.split_by_drawn(g, lab_g, None)) == 1


def test_partition_doorway_between_jambs_not_cut():
    # толстый рисунок стены (6 px при 22 px/м ≈ 27 см): проём 20 px между двумя кусками одной перегородки — 0,9 м,
    # в толщинах тот же «обрыв» (3,3 t), но по ширине — проход (≥ DOOR_MIN_M): не замуровывать (слепой G, гараж/мастерская)
    st, ctx, labels = partition_room(60, ('Garage', 'Workshop'), ppm=22.4, jamb=40)
    rp._SKIPS.clear()
    assert rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1)) is None
    assert 'проём' in rp._SKIPS[-1]
    st, ctx, labels = partition_room(60, ('Garage', 'Workshop'), ppm=50.0, jamb=40)   # тот же рисунок: 0,4 м — обрыв
    assert rp.hyp_partition(st, 1, [0], [1], labels, ctx, (0, 1)) is not None
