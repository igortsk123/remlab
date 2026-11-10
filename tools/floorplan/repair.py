"""Круг «построил → сверил → починил» (T-20261109-03; план floorplan-raster-bench-01 § Этап 2; схема — Codex
`_intake/codex/floorplan-selfrepair-2026-11-09-answer.md`).

Эвристики, которые раньше сразу меняли стены (`merge_false_splits`, разрез «по узкому месту»), здесь — ГИПОТЕЗЫ:
  remove   — удалить отрезок между куском без подписи и соседней комнатой (ложная стена: штрих мебели, наша перемычка);
  mincut   — binary min-cut (Boykov–Jolly) в области, где оказались две подписи: разрез идёт по тёмным пикселям
             СЫРОГО листа, а где их нет — по самому короткому месту;
  recompute— подпись не попала ни в одну комнату: локальный пересчёт окна (закрытие проёмов; маска по доминирующему
             тёмному цвету окна — для построек, нарисованных другим цветом; тонкие линии — виртуальная граница,
             только если сильные улики окно не замкнули);
  neck     — подпись «велика», у её комнаты отросток уже NECK_M (коридор, дверной карман): min-cut тела против отростка.
Каждая гипотеза пересчитывает общую цену и принимается только при жёстких условиях (лексикографически):
  1) топология подписей не хуже (пропавшие подписи, две подписи в одной комнате, необъяснённые куски);
  2) соответствие сырым пикселям не хуже (стены без тёмных пикселей под ними + тёмные толстые штрихи без стены);
  3) робастная ошибка размеров остальных подписей не хуже (подпись-триггер — та, что открыла окно, — НЕ участвует);
  4) правка минимальна. Иначе — откат. Близкие по цене разные гипотезы одного триггера — «неоднозначно» (человеку).
Масштаб панели заморожен; tabu по (гипотеза, состояние окна); ≤ 5 проходов, ≤ 45 с на панель. Журнал — список словарей.
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

import fpcore as fc
import openroom
import partition

# T-16: замыкание открытых комнат (openroom.py) — подходы по порядку, пока один не построит гипотезу;
# FP_OPEN=none — без замыкания (как до T-16), lines / box / box+lines — сравнение в отчёте T-16. Выбран box:
# рамка по мерке подписи с опорой на линии внутри оболочки здания не протекает; lines на E-1 протёк за эркер.
OPEN_MODES = 'box'


def open_modes() -> list:
    v = os.environ.get('FP_OPEN', OPEN_MODES)
    return [] if v in ('', 'none', '0') else v.split('+')

TOL_NORM_M, TOL_NORM_REL = 0.12, 0.03      # норма расхождения с подписью
TOL_BAD_M, TOL_BAD_REL = 0.25, 0.05        # выше — «не сошлось»: геометрию менять только с пиксельным свидетельством
TOL_PIX_M = 0.3                            # пиксели «не хуже»: допуск, м стены
HYST = 0.02                                # гистерезис улучшения размеров
EXPLAIN_M2 = 1.0                           # кусок без подписи от 1 м² — «необъяснённый»
W_MISSING, W_MERGED, W_UNEXPL = 3, 2, 1    # веса топологии (пропала подпись > две в одной > лишний кусок)
MAX_PASSES, BUDGET_S = 5, 45.0
MINCUT_MAX_PX = 400_000


@dataclass
class Label:
    name: str
    pt: tuple                       # px панели
    dims: tuple | None = None       # (a, b) м, как напечатано; None — помещение без размеров (имя от VLM)
    src: str = 'vlm'
    note: str | None = None         # заметка подписи («max», «into bay»): мерка по наибольшим сторонам


@dataclass
class State:
    lab: np.ndarray
    final: np.ndarray
    rooms: list
    add: np.ndarray                  # наши закрытия проёмов (стена «по построению», не по пикселям)
    cut: np.ndarray = None           # границы min-cut (виртуальные; drawn — вдоль нарисованной линии)
    drawn: np.ndarray = None

    def copy(self):
        return State(self.lab.copy(), self.final.copy(), list(self.rooms), self.add.copy(),
                     None if self.cut is None else self.cut.copy(), None if self.drawn is None else self.drawn.copy())


@dataclass
class Ctx:
    gray: np.ndarray
    ev: np.ndarray                   # толстые тёмные штрихи сырого листа (свидетельство стены)
    wp: np.ndarray                   # «вероятность стены» по сырому серому 0..1
    ppm: float
    t_int: float
    fams: list
    conv: tuple = ('p95', 0)         # манера подписи панели (кандидат, перестановка) — заморожена
    bay_in: np.ndarray | None = None
    dominant: np.ndarray | None = None   # маска по доминирующему тёмному цвету (для recompute)
    bg: float | None = None              # фон листа (P90 серого) — для «пол залит цветом» (openroom)
    floor: float | None = None           # медиана серого найденных комнат панели (пол залит, если темнее листа)
    hull: np.ndarray | None = None       # выпуклая оболочка стен панели: комната не выходит за здание (openroom)
    hull_walls: np.ndarray | None = None  # оболочка только стен (без линий): подпись вне её — выноска, не открытая комната


# --- свидетельства из сырого листа -------------------------------------------------------------------------------------

def inner_thickness(final: np.ndarray, wall: np.ndarray) -> float:
    """Толщина внутренних стен (осевые пиксели нарисованных стен не у наружи), px."""
    _, _, outside = fc.free_components(final)
    dto = cv2.distanceTransform((~outside).astype(np.uint8), cv2.DIST_L2, 5)
    dtw = cv2.distanceTransform((wall > 0).astype(np.uint8), cv2.DIST_L2, 5)
    ridge = (dtw > 0.9) & (dtw >= cv2.dilate(dtw, np.ones((3, 3), np.uint8)) - 1e-6)
    inner = ridge & (dto > dtw + 2)
    return float(2 * np.median(dtw[inner])) if inner.sum() > 20 else fc.stroke_thickness(wall)


def evidence(dark_raw: np.ndarray, t_int: float, k_thin: float = 0.75) -> np.ndarray:
    """Свидетельство стены на сыром листе: тёмные пиксели штрихов толщиной ≥ k_thin·t_int (две грани с заливкой между);
    тонкая графика (мебель, дуги, рамки, текст) — не стена."""
    d = dark_raw.astype(np.uint8)
    dt = cv2.distanceTransform(d, cv2.DIST_L2, 3)
    ridge = (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8)) - 1e-6) & (2 * dt >= k_thin * t_int)
    r = int(math.ceil(t_int / 2)) + 1
    grown = cv2.dilate(ridge.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    return (grown > 0) & (d > 0)


DRAWN_WP = 0.5                      # граница разреза «нарисована», если wp ≥ этого вдоль ≥ 60 % её длины


def wall_prob(gray: np.ndarray, bg: float | None = None, dark: float = 60.0, local_px: int = 15,
              local_delta: float = 40.0) -> np.ndarray:
    """0..1: насколько пиксель темнее фона (для цены разреза; сырой серый, без маски) — максимум из глобального
    (темнее фона листа) и локального контраста (темнее закрытия окном local_px: светло-серая перегородка
    на белом — тоже линия, хотя до чёрного далеко)."""
    if bg is None:
        bg = float(np.percentile(gray, 90))
    g = gray.astype(float)
    glob = np.clip((bg - g) / max(1.0, bg - dark), 0.0, 1.0)
    if not local_px:
        return glob
    cl = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((local_px, local_px), np.uint8)).astype(float)
    loc = np.clip((cl - g) / local_delta, 0.0, 1.0)
    return np.maximum(glob, loc)


def dominant_dark_mask(gray: np.ndarray, open_px: int = 2, delta: int = 28) -> np.ndarray | None:
    """Маска стен по доминирующему тёмному цвету окна: мода серого среди пикселей заметно темнее фона, переживших
    открытие (штрихи ≥ open_px) → |серый − мода| ≤ delta. Для построек, обведённых не чёрным. None — нет тёмного."""
    bg = float(np.percentile(gray, 75))
    cand = (gray < bg - 25).astype(np.uint8)
    if open_px > 1:
        cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((open_px, open_px), np.uint8))
    v = gray[cand > 0]
    if v.size < 50:
        return None
    hist = np.bincount(v.ravel(), minlength=256)
    mode = int(np.argmax(np.convolve(hist, np.ones(9), 'same')))
    m = (np.abs(gray.astype(int) - mode) <= delta).astype(np.uint8)
    if open_px > 1:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((open_px, open_px), np.uint8))
    return m


# --- цена -----------------------------------------------------------------------------------------------------------------

def snap(lab: np.ndarray, rooms, pt, r: int) -> int | None:
    """Комната под точкой подписи (ближайшая в радиусе r: подпись жирным лежит на маске)."""
    x, y = int(round(pt[0])), int(round(pt[1]))
    H, W = lab.shape
    y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
    if y1 <= y0 or x1 <= x0:
        return None
    win = lab[y0:y1, x0:x1]
    rs = set(rooms)
    ok = np.isin(win, list(rs)) if rs else np.zeros(win.shape, bool)
    if not ok.any():
        return None
    yy, xx = np.nonzero(ok)
    k = int(np.argmin((yy + y0 - y) ** 2 + (xx + x0 - x) ** 2))
    return int(win[yy[k], xx[k]])


def assign(st: State, labels: list, ppm: float) -> list:
    r = max(6, int(0.25 * ppm))
    rs = max(8, int(0.5 * ppm))                       # точка помещения без размеров от VLM — грубее (лестница в штрихах)
    return [snap(st.lab, st.rooms, l.pt, r if l.dims is not None else rs) for l in labels]


def topology(st: State, labels: list, ppm: float, areas=None) -> dict:
    """Топология по ВСЕМ подписям (место подписи — не число, его подгонкой не испортишь)."""
    own = assign(st, labels, ppm)
    if areas is None:
        areas = np.bincount(st.lab.ravel(), minlength=int(st.lab.max()) + 1)
    by = {}
    for i, rid in enumerate(own):
        if rid is not None:
            by.setdefault(rid, []).append(i)
    missing = [i for i, rid in enumerate(own) if rid is None and labels[i].dims is not None]
    # доверенные — подписи с размерами (напечатаны на листе); помещения без размеров от VLM — слабее (точка грубее,
    # бывает выдумано): их слияния и необъяснённые куски — отдельный слабый член X
    merged_t = sum(max(0, sum(1 for i in v if labels[i].dims is not None) - 1) for v in by.values())
    merged = sum(len(v) - 1 for v in by.values())
    unexpl = [rid for rid in st.rooms if rid not in by and areas[rid] >= EXPLAIN_M2 * ppm * ppm]
    cost = W_MISSING * len(missing) + W_MERGED * merged_t
    x = W_MERGED * (merged - merged_t) + W_UNEXPL * len(unexpl)
    return {'cost': cost, 'x': x, 'missing': missing, 'merged': merged, 'merged_t': merged_t, 'unexplained': unexpl,
            'own': own, 'by': by}


def pixel_cost(st: State, ctx: Ctx, roi=None) -> float:
    """Расхождение с сырым листом, м стены: (наша стена без тёмного под ней, кроме закрытий проёмов) +
    (толстый тёмный штрих без нашей стены рядом). Считается в окне roi (x0, y0, x1, y1) или по всей панели."""
    sl = np.s_[:, :] if roi is None else np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    f = st.final[sl] > 0
    if fc.empty_img(f):
        return 0.0                                   # пустое окно: расхождения нет (dilate на нём — cv2.error)
    k = np.ones((3, 3), np.uint8)
    evd = cv2.dilate(ctx.ev[sl].astype(np.uint8), k, iterations=1) > 0
    fd = cv2.dilate(f.astype(np.uint8), k, iterations=1) > 0
    unsup = f & ~(st.add[sl] > 0) & ~evd
    miss = ctx.ev[sl] & ~fd
    return float(unsup.sum() + miss.sum()) / max(1.0, ctx.t_int) / ctx.ppm


def residual(dims, ext, ppm, conv) -> tuple[float, tuple]:
    """Ошибка подписи при замороженном масштабе и манере панели: max по сторонам, м (+ предсказание)."""
    c, _p = conv
    o = {'ext': ext, 'dims': tuple(dims)}
    # порядок чисел подписи, прочитанной VLM, не надёжен (повёрнутый текст, «длина × ширина») — без порядка
    e, pred = min((fc._err(o, 1.0 / ppm, c if c in ext else 'p95', p) for p in (0, 1)), key=lambda t: t[0])
    return float(e), pred


def bad_tol(dims) -> float:
    return max(TOL_BAD_M, TOL_BAD_REL * max(dims))


def norm_tol(dims) -> float:
    return max(TOL_NORM_M, TOL_NORM_REL * max(dims))


def room_angle(mask, fams):
    """Ось комнаты: семейство, ближайшее к углу minAreaRect; приведение к (-45, 45] (как bench.room_angle)."""
    ys, xs = np.nonzero(mask)
    (_, _), (_, _), a = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
    a = a % 180
    f = min(fams, key=lambda q: fc.angdiff(q, a)) if fams else 0.0
    return ((f + 45) % 90) - 45


_EXT_CACHE: dict = {}


def room_ext(st: State, rid: int, ctx: Ctx) -> dict:
    m = st.lab == rid
    if ctx.bay_in is not None and (m & ~ctx.bay_in).any():
        m = m & ~ctx.bay_in
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    key = hashlib.sha1(np.packbits(m[y0:y1, x0:x1]).tobytes() + repr((y1 - y0, x1 - x0, tuple(ctx.fams))).encode()).hexdigest()
    if key not in _EXT_CACHE:
        if len(_EXT_CACHE) > 4000:
            _EXT_CACHE.clear()
        ang = room_angle(m, ctx.fams)
        _EXT_CACHE[key] = fc.room_extents(m, -ang, core=True)
    return _EXT_CACHE[key]


def dims_errors(st: State, labels: list, ctx: Ctx, topo: dict) -> dict:
    """Ошибка каждой подписи с размерами, которая одна в своей комнате → {индекс подписи: (ошибка м, предсказание)}."""
    out = {}
    for i, l in enumerate(labels):
        rid = topo['own'][i]
        if l.dims is None or rid is None:
            continue
        if sum(1 for j in topo['by'][rid] if labels[j].dims is not None) > 1:
            continue
        out[i] = residual(l.dims, room_ext(st, rid, ctx), ctx.ppm, ctx.conv)
    return out


def dims_cost(errs: dict, exclude: set) -> float:
    """Робастная ошибка размеров: среднее ошибок, обрезанных на 1 м, без подписей-триггеров."""
    v = [min(1.0, e) for i, (e, _) in errs.items() if i not in exclude]
    return float(np.mean(v)) if v else 0.0


# --- min-cut --------------------------------------------------------------------------------------------------------------

def mincut_split(region: np.ndarray, seeds_a: np.ndarray, seeds_b: np.ndarray, wp: np.ndarray,
                 eps: float = 0.05, k: float = 1.0, scale: int = 100):
    """Binary min-cut на 4-связной сетке пикселей области (Boykov–Jolly 2001): семена A/B — жёстко к истоку/стоку;
    цена ребра p–q = eps + k·(1 − max(wp_p, wp_q)): разрез вдоль тёмной линии сырого листа дёшев, по белому — дорог,
    поэтому без линии он идёт по самому короткому месту. → (маска стороны A, цена разреза в «белых px», число рёбер)."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order, maximum_flow
    ys, xs = np.nonzero(region)
    n = len(ys)
    if n == 0 or not (seeds_a & region).any() or not (seeds_b & region).any():
        return None
    idx = -np.ones(region.shape, np.int64)
    idx[ys, xs] = np.arange(n)
    rows, cols, caps = [], [], []
    for dy, dx in ((0, 1), (1, 0)):
        a = idx[:region.shape[0] - dy, :region.shape[1] - dx]
        b = idx[dy:, dx:]
        ok = (a >= 0) & (b >= 0)
        pa, pb = a[ok], b[ok]
        w = np.maximum(wp[:region.shape[0] - dy, :region.shape[1] - dx][ok], wp[dy:, dx:][ok])
        c = np.maximum(1, np.round(scale * (eps + k * (1.0 - w)))).astype(np.int64)
        rows += [pa, pb]; cols += [pb, pa]; caps += [c, c]
    s, t = n, n + 1
    big = int(sum(int(c.sum()) for c in caps) + 1)
    big = min(big, 2 ** 30)
    sa = idx[seeds_a & region]
    sb = idx[seeds_b & region]
    rows += [np.full(len(sa), s), sb]
    cols += [sa, np.full(len(sb), t)]
    caps += [np.full(len(sa), big), np.full(len(sb), big)]
    R = np.concatenate(rows); C = np.concatenate(cols); V = np.concatenate(caps)
    G = csr_matrix((V.astype(np.int32), (R, C)), shape=(n + 2, n + 2))
    G.sum_duplicates()
    res = maximum_flow(G, s, t, method='dinic')
    F = res.flow if hasattr(res, 'flow') else res.residual
    Rg = (G - F).tocsr()
    Rg.data[Rg.data < 0] = 0
    Rg.eliminate_zeros()
    order = breadth_first_order(Rg, s, directed=True, return_predecessors=False)
    side = np.zeros(n + 2, bool)
    side[order] = True
    A = np.zeros(region.shape, bool)
    A[ys, xs] = side[:n]
    return A, int(res.flow_value), n


def seed_disk(region: np.ndarray, pt, r: int, dt: np.ndarray | None = None, k_dt: float = 0.8,
              r_max: int | None = None) -> np.ndarray:
    """Семя подписи: круг вокруг ближайшего к подписи пикселя области; радиус — 0,8 расстояния до ближайшей стены
    в этой точке (вписанный круг тела комнаты), не меньше r. Маленькое семя даёт «усадку» разреза (min-cut
    дешевле обвести вокруг семени, чем пересечь широкий проём) — поэтому семя по телу комнаты."""
    ys, xs = np.nonzero(region)
    k = int(np.argmin((ys - pt[1]) ** 2 + (xs - pt[0]) ** 2))
    cy, cx = int(ys[k]), int(xs[k])
    rr = r
    if dt is not None:
        # ближайший к подписи гребень: максимум dt в окне r (подпись может стоять у стены ниши)
        y0, y1, x0, x1 = max(0, cy - r), min(region.shape[0], cy + r + 1), max(0, cx - r), min(region.shape[1], cx + r + 1)
        w = dt[y0:y1, x0:x1]
        j = np.unravel_index(int(np.argmax(w)), w.shape)
        cy, cx = y0 + int(j[0]), x0 + int(j[1])
        rr = max(r, int(k_dt * float(dt[cy, cx])))
    if r_max is not None:
        rr = min(rr, r_max)
    m = np.zeros(region.shape, np.uint8)
    cv2.circle(m, (cx, cy), max(2, rr), 1, -1)
    er = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8))
    s = (m > 0) & (er > 0)
    if not s.any():
        s = np.zeros(region.shape, bool)
        s[cy, cx] = True
    return s


# --- гипотезы ---------------------------------------------------------------------------------------------------------------

@dataclass
class Hyp:
    kind: str
    trigger: tuple                  # индексы подписей-триггеров (их размеры в приёмке не участвуют)
    roi: tuple
    apply: object                   # State → State
    note: dict = field(default_factory=dict)
    key: str = ''


def _roi_of(mask: np.ndarray, pad: int, shape) -> tuple:
    ys, xs = np.nonzero(mask)
    H, W = shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad), min(W, int(xs.max()) + pad + 1),
            min(H, int(ys.max()) + pad + 1))


def _state_hash(st: State, roi) -> str:
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    h = hashlib.sha1(st.lab[sl].tobytes())
    h.update(st.final[sl].tobytes())
    return h.hexdigest()[:16]


def hyp_mincut(st: State, rid: int, ia: list, ib: list, labels: list, ctx: Ctx, trigger: tuple, eps: float = 0.05):
    region = st.lab == rid
    if region.sum() > MINCUT_MAX_PX:
        return None
    rs = max(3, int(0.3 * ctx.ppm))
    roi = _roi_of(region, 2, region.shape)
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    dt = np.zeros(region.shape, np.float32)
    dt[sl] = cv2.distanceTransform(region[sl].astype(np.uint8), cv2.DIST_L2, 5)

    def dist(i, grp):
        return min(math.hypot(labels[i].pt[0] - labels[j].pt[0], labels[i].pt[1] - labels[j].pt[1]) for j in grp)
    A0 = np.zeros(region.shape, bool)
    B0 = np.zeros(region.shape, bool)
    for i in ia:                                       # семена не ближе друг к другу, чем 0,1 расстояния подписей
        A0 |= seed_disk(region, labels[i].pt, rs, dt, r_max=max(rs, int(0.45 * dist(i, ib))))
    for i in ib:
        B0 |= seed_disk(region, labels[i].pt, rs, dt, r_max=max(rs, int(0.45 * dist(i, ia))))
    B0 &= ~A0
    out = mincut_split(region[sl], A0[sl], B0[sl], ctx.wp[sl], eps=eps)
    if out is None:
        return None
    Aw, cut_val, n = out
    A = np.zeros(region.shape, bool)
    A[sl] = Aw
    B = region & ~A
    if B.sum() < 0.3 * ctx.ppm ** 2 or A.sum() < 0.3 * ctx.ppm ** 2:
        return None
    # граница разреза — пиксели B у A; «нарисована», если тёмная линия сырого листа идёт вдоль большей её части
    bnd = B & (cv2.dilate(A.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    wpb = ctx.wp[bnd]
    drawn_frac = float((wpb >= DRAWN_WP).mean()) if wpb.size else 0.0
    shape =float((1.0 - wpb).sum() + 0.25 * wpb.size) / ctx.ppm

    def apply(s: State, A=A, B=B, bnd=bnd, drawn_frac=drawn_frac):
        s = s.copy()
        nid = int(s.lab.max()) + 1
        s.lab[B] = nid
        s.rooms.append(nid)
        if s.cut is None:
            s.cut = np.zeros(s.lab.shape, bool)
            s.drawn = np.zeros(s.lab.shape, bool)
        s.cut |= bnd
        if drawn_frac >= 0.6:
            s.drawn |= bnd
        return s

    return Hyp('mincut', trigger, roi, apply,
               {'room': rid, 'a': [labels[i].name for i in ia], 'b': [labels[i].name for i in ib], 'eps': eps,
                'cut_m': round(int(bnd.sum()) / ctx.ppm, 2), 'drawn': round(drawn_frac, 2), 'shape': round(shape, 3),
                'cut_cost': cut_val}, f'mincut:{rid}:{ia}:{ib}:{eps}')


def _shared(st: State, p: int, q: int, ctx: Ctx):
    """Общий отрезок стены между комнатами p и q (как в fpcore.merge_false_splits) → (S, Sthin, окно, свойства)."""
    P = st.lab == p
    ys, xs = np.nonzero(P)
    H, W = P.shape
    m = int(2 * ctx.t_int + 4)
    y0, y1, x0, x1 = max(0, ys.min() - m), min(H, ys.max() + m + 1), max(0, xs.min() - m), min(W, xs.max() + m + 1)
    sl = (slice(y0, y1), slice(x0, x1))
    d = 1.2 * max(ctx.t_int, 2.0) + 1.5
    dP = cv2.distanceTransform((~P[sl]).astype(np.uint8), cv2.DIST_L2, 3)
    ring = (st.final[sl] > 0) & (dP <= d)
    dQ = cv2.distanceTransform((st.lab[sl] != q).astype(np.uint8), cv2.DIST_L2, 3)
    S = ring & (dQ <= d)
    if S.sum() < 4:
        return None
    dtf = cv2.distanceTransform((st.final[sl] > 0).astype(np.uint8), cv2.DIST_L2, 5)
    rS = S & (dtf >= cv2.dilate(dtf, np.ones((3, 3), np.uint8)) - 1e-6) & (dtf > 0.5)
    thick = 2 * float(np.median(dtf[rS])) if rS.any() else 2 * float(dtf[S].max())
    Sthin = S & (dP <= thick + 1) & (dQ <= thick + 1)
    sy, sx = np.nonzero(S)
    _, _, _, L, _ = fc.gap_axes(sy + y0, sx + x0)
    return S, Sthin, (x0, y0, x1, y1), {'L_m': round(L / ctx.ppm, 2), 'thick': round(thick, 1),
                                        'add': round(float(st.add[sl][S].mean()), 2)}


def neighbours(st: State, p: int, ctx: Ctx) -> list:
    P = st.lab == p
    k = int(2 * ctx.t_int + 5) | 1
    ring = cv2.dilate(P.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    return [int(q) for q in np.unique(st.lab[ring & ~P]) if q in st.rooms and q != p]


def hyp_remove(st: State, p: int, q: int, ctx: Ctx, trigger: tuple, outside: np.ndarray):
    """Удалить стену между p и q (p вливается в q). Наружный контур (якорь) не трогаем."""
    sh = _shared(st, p, q, ctx)
    if sh is None:
        return None
    S, Sthin, (x0, y0, x1, y1), props = sh
    if props['L_m'] > 6.0:
        return None
    Sg = np.zeros(st.lab.shape, bool)
    Sg[y0:y1, x0:x1] = Sthin
    if not Sg.any():
        return None
    if (cv2.dilate(Sg.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)[outside].any():
        return None                                   # якорь: стена у наружи
    if st.drawn is not None and (Sg & cv2.dilate(st.drawn.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)).any():
        return None                                   # tabu: не снимать то, что сами провели разрезом

    def apply(s: State, p=p, q=q, Sg=Sg):
        s = s.copy()
        s.lab[s.lab == p] = q
        s.final[Sg] = 0
        s.lab[Sg] = q
        s.rooms.remove(p)
        return s

    roi = _roi_of((st.lab == p) | Sg, int(2 * ctx.t_int) + 4, st.lab.shape)
    return Hyp('remove', trigger, roi, apply, {'piece': p, 'into': q, **props}, f'remove:{p}:{q}')


_SKIPS: list = []                   # почему гипотеза не построилась — в журнал (не молча)
SKIPLOG: list = []
TABU: set = set()                    # отвергнутые (ключ, состояние окна) текущего круга — propose их не считает (T-16)


def _no(why: str):
    _SKIPS.append(why)
    return None


def on_sheet(labels: list, shape) -> tuple[list, list]:
    """Подписи с точкой на листе панели → (они, записи журнала об остальных). Подпись отдаётся панели по ближайшему
    контуру VLM без предела расстояния, поэтому её точка бывает за краем листа панели — окно вокруг неё пусто, а OpenCV
    на пустом окне роняет процесс (лист C, T-20261110-06). Такие подписи в починке не участвуют."""
    H, W = shape
    keep, off = [], []
    for l in labels:
        x, y = float(l.pt[0]), float(l.pt[1])
        if 0 <= x < W and 0 <= y < H:
            keep.append(l)
        else:
            off.append({'kind': 'skip', 'hyp': 'label', 'label': l.name, 'pt': [round(x, 1), round(y, 1)],
                        'sheet': [W, H], 'why': 'точка подписи вне листа панели'})
    return keep, off


def hyp_recompute(st: State, i: int, labels: list, ctx: Ctx, outside: np.ndarray, close_m: float, use_dom: bool):
    """Подпись не в комнате: окно вокруг неё (по её размерам — только как размер окна), закрытие проёмов ≤ close_m
    (и маска по доминирующему тёмному цвету окна) → область подписи, замкнутая внутри окна, становится комнатой."""
    l = labels[i]
    H, W = st.lab.shape
    half = int((0.75 * max(l.dims or (4.0, 4.0)) + 1.0) * ctx.ppm)
    x, y = int(l.pt[0]), int(l.pt[1])
    if not (0 <= x < W and 0 <= y < H):
        return _no('точка подписи вне листа')
    roi = (max(0, x - half), max(0, y - half), min(W, x + half + 1), min(H, y + half + 1))
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    if fc.empty_img(st.final[sl]):
        return _no('пустое окно')                                   # OpenCV на пустом окне роняет процесс
    Wm = (st.final[sl] > 0).astype(np.uint8)
    faint = np.zeros(Wm.shape, bool)
    if use_dom == 'faint':
        # любая видимая линия окна (тонкая граница: открытая сторона навеса, светлая перегородка) — граница комнаты,
        # но не стена: в 3D остаётся проёмом (виртуальная граница)
        g = ctx.gray[sl]
        faint = (g < float(np.percentile(g, 75)) - 40) & (Wm == 0)
        Wm = (Wm | faint).astype(np.uint8)
    elif use_dom:
        dm = dominant_dark_mask(ctx.gray[sl])
        if dm is None:
            return _no("нет тёмного цвета")
        Wm = (Wm | dm).astype(np.uint8)
    k = int(close_m * ctx.ppm) | 1
    pad = cv2.copyMakeBorder(Wm, k, k, k, k, cv2.BORDER_CONSTANT, value=0)
    closed = cv2.morphologyEx(pad, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))[k:-k, k:-k]
    allowed = ~np.isin(st.lab[sl], st.rooms) | (Wm > 0)
    W2 = ((Wm > 0) | ((closed > 0) & allowed)).astype(np.uint8)
    n, labw = cv2.connectedComponents((W2 == 0).astype(np.uint8), connectivity=4)
    px, py = x - roi[0], y - roi[1]
    r = max(6, int(0.25 * ctx.ppm))
    win = labw[max(0, py - r):py + r + 1, max(0, px - r):px + r + 1]
    ids = [v for v in np.unique(win) if v > 0]
    if not ids:
        return _no("подпись на стене")
    comp = labw == ids[0]
    if comp[0].any() or comp[-1].any() or comp[:, 0].any() or comp[:, -1].any():
        return _no("не замкнулась")                                 # не замкнулась в окне
    if comp.sum() < 0.3 * ctx.ppm ** 2:
        return _no("мала")
    if np.isin(st.lab[sl][comp], st.rooms).mean() > 0.2:
        return _no("чужая комната")                                 # залезли в чужую комнату
    hull = cv2.convexHull(np.column_stack(np.nonzero(comp)[::-1]).astype(np.int32))
    solidity = comp.sum() / max(1.0, cv2.contourArea(hull))
    # дыры области (текст подписи, мебель внутри) — часть комнаты, стенами не становятся
    cnt = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    comp_f = np.zeros(comp.shape, np.uint8)
    cv2.drawContours(comp_f, cnt, -1, 1, -1)
    comp_f = (comp_f > 0) & ~((st.final[sl] > 0) & ~comp)
    newwall = (W2 > 0) & ~(st.final[sl] > 0)
    near = cv2.dilate(comp_f.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    nw = newwall & near & ~comp_f
    closures = nw & ~(Wm > 0)                        # закрытия проёмов (не по пикселям)
    virt = nw & faint                                # тонкая линия — граница без стены
    per = cv2.arcLength(max(cnt, key=cv2.contourArea), True)
    clos_frac = float(closures.sum()) / max(1.0, ctx.t_int) / max(1.0, per)
    # тонкая линия — только как одна-две открытые стороны (навес, перегородка); область, обведённая почти целиком
    # тонким (стол, ковёр, штриховка внутри комнаты) — не комната
    virt_frac = float((nw & faint).sum()) / max(1.0, per)
    if solidity < 0.6 or clos_frac > 0.4 or virt_frac > 0.8:
        return _no(f"форма: solidity {solidity:.2f}, закрытия {clos_frac:.2f}, тонкое {virt_frac:.2f}")

    def apply(s: State, comp=comp_f, nw=nw, closures=closures, virt=virt):
        s = s.copy()
        nid = int(s.lab.max()) + 1
        s.final[sl][nw & ~virt] = 1
        s.add[sl][closures] = 1
        s.lab[sl][nw] = 0
        s.lab[sl][comp] = nid
        s.rooms.append(nid)
        if virt.any():
            if s.cut is None:
                s.cut = np.zeros(s.lab.shape, bool)
                s.drawn = np.zeros(s.lab.shape, bool)
            s.cut[sl] |= virt
        return s

    return Hyp('recompute', (i,), roi, apply, {'label': l.name, 'close_m': close_m, 'dominant': use_dom,
                                               'solidity': round(float(solidity), 2), 'closures': round(clos_frac, 2),
                                               'virtual': round(virt_frac, 2),
                                               'area_m2': round(float(comp.sum()) / ctx.ppm ** 2, 2)},
               f'recompute:{i}:{close_m}:{use_dom}')


def hyp_enclose(st: State, i: int, labels: list, ctx: Ctx, mode: str):
    """Подпись с размером не в комнате и локальный пересчёт её не замкнул (стена не сплошная: проём, складные двери,
    открытая планировка, открытая сторона) → замкнуть контур вокруг подписи (`openroom`, подход mode). Новых стен нет:
    граница не по стене — виртуальная (`cut`), поэтому пиксельная цена не меняется; принимает топология."""
    l = labels[i]
    H, W = st.lab.shape
    roi = openroom.window(l.pt, l.dims, ctx.ppm, (H, W), k=0.75 if mode == 'lines' else 1.0)
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    if fc.empty_img(st.lab[sl]):
        return _no('пустое окно')                     # подпись за краем листа: OpenCV на пустом окне роняет процесс
    if ctx.bg is None:
        ctx.bg = float(np.percentile(ctx.gray, 90))
        rm = np.isin(st.lab, st.rooms)
        ctx.floor = float(np.median(ctx.gray[rm])) if rm.any() else ctx.bg
        ctx.hull = openroom.hull_mask(st.final, ctx.gray, ctx.ppm)
        ctx.hull_walls = openroom.hull_mask(st.final)
    if not openroom.point_inside(ctx.hull_walls, l.pt):
        return _no('подпись вне здания (выноска)')
    pt = (l.pt[0] - roi[0], l.pt[1] - roi[1])
    opts = [(q.pt[0] - roi[0], q.pt[1] - roi[1]) for j, q in enumerate(labels) if j != i and q.dims is not None]
    lab_w, final_w, gray_w = st.lab[sl], st.final[sl], ctx.gray[sl]
    hull_w = ctx.hull[sl] if ctx.hull is not None else None
    rs = set(st.rooms)
    rooms_in = [int(v) for v in np.unique(lab_w) if int(v) in rs]
    if mode == 'lines':
        comp, info = openroom.enclose_lines(final_w, lab_w, rooms_in, gray_w, pt, l.dims, ctx.ppm, ctx.fams, ctx.bg, opts,
                                            None, floor=ctx.floor, inside=hull_w)
    elif mode == 'box':
        comp, info = openroom.enclose_box(final_w, lab_w, rooms_in, gray_w, pt, l.dims, ctx.ppm, ctx.fams, ctx.bg, opts,
                                          ctx.t_int, floor=ctx.floor, inside=hull_w,
                                          max_extent=openroom.is_max_note(l.note))
    else:
        return _no(f'нет подхода {mode}')
    if comp is None:
        return _no(info)
    virt = openroom.virtual_boundary(comp, final_w, ctx.t_int)

    def apply(s: State, comp=comp, virt=virt):
        s = s.copy()
        nid = int(s.lab.max()) + 1
        s.lab[sl][comp] = nid
        s.rooms.append(nid)
        if virt.any():
            if s.cut is None:
                s.cut = np.zeros(s.lab.shape, bool)
                s.drawn = np.zeros(s.lab.shape, bool)
            s.cut[sl] |= virt
        return s

    return Hyp('enclose', (i,), roi, apply, {'label': l.name, 'mode': mode, **info,
                                            'area_m2': round(float(comp.sum()) / ctx.ppm ** 2, 2),
                                            'label_m2': round(float(l.dims[0] * l.dims[1]), 2),
                                            'virtual_m': round(float(virt.sum()) / ctx.ppm, 2)},
               f'enclose:{i}:{mode}')


def hyp_neck(st: State, i: int, labels: list, ctx: Ctx, eps: float = 0.05):
    """Подпись «велика», а у её комнаты есть отросток уже NECK_M (коридор/проход, прихваченный через проём без
    дуги двери) → min-cut между телом комнаты у подписи и отростком: разрез ляжет по самому узкому месту или по
    нарисованной линии. Гипотеза общая: ни плана, ни подписи кроме «наше больше подписи» не знает."""
    l = labels[i]
    rid = snap(st.lab, st.rooms, l.pt, max(6, int(0.25 * ctx.ppm)))
    if rid is None:
        return None
    region = st.lab == rid
    if region.sum() > MINCUT_MAX_PX:
        return None
    roi = _roi_of(region, 2, region.shape)
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    m, body, thin = protrusion(region[sl], ctx.ppm)
    if body is None or m < NECK_MIN_M2:
        return None
    nb, bl = cv2.connectedComponents(body.astype(np.uint8), connectivity=4)
    px, py = int(l.pt[0]) - roi[0], int(l.pt[1]) - roi[1]
    ys, xs = np.nonzero(bl > 0)
    k = int(np.argmin((ys - py) ** 2 + (xs - px) ** 2))
    core = bl == bl[ys[k], xs[k]]                     # тело комнаты под подписью
    n, tl, stt, _ = cv2.connectedComponentsWithStats(thin.astype(np.uint8), connectivity=4)
    big = [j for j in range(1, n) if stt[j, cv2.CC_STAT_AREA] >= NECK_MIN_M2 * ctx.ppm ** 2]
    if not big:
        return None
    g = max(2, int(0.25 * NECK_M * ctx.ppm))
    A0 = cv2.erode(core.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    farB = ~(cv2.dilate(core.astype(np.uint8), np.ones((2 * g + 1, 2 * g + 1), np.uint8)) > 0)
    B0 = np.isin(tl, big) & farB                      # дальняя часть отростков (и другие тела — не трогаем)
    if not B0.any():
        return None
    out = mincut_split(region[sl], A0, B0, ctx.wp[sl], eps=eps)
    if out is None:
        return None
    Aw = out[0]
    A = np.zeros(region.shape, bool)
    A[sl] = Aw
    B = region & ~A
    if B.sum() < NECK_MIN_M2 * ctx.ppm ** 2:
        return None
    # проверка по самой подписи (не цикл: подпись — только «стало ближе», а принимает форма и остальные размеры)
    e0, _ = residual(l.dims, room_ext(st, rid, ctx), ctx.ppm, ctx.conv)
    tmp = st.copy()
    tmp.lab[B] = int(tmp.lab.max()) + 1
    e1, _ = residual(l.dims, room_ext(tmp, rid, ctx), ctx.ppm, ctx.conv)
    if e1 > e0 - 0.1:
        return None
    bnd = B & (cv2.dilate(A.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    wpb = ctx.wp[bnd]
    drawn_frac = float((wpb >= DRAWN_WP).mean()) if wpb.size else 0.0

    def apply(s: State, B=B, bnd=bnd, drawn_frac=drawn_frac):
        s = s.copy()
        nid = int(s.lab.max()) + 1
        s.lab[B] = nid
        s.rooms.append(nid)
        if s.cut is None:
            s.cut = np.zeros(s.lab.shape, bool)
            s.drawn = np.zeros(s.lab.shape, bool)
        s.cut |= bnd
        if drawn_frac >= 0.6:
            s.drawn |= bnd
        return s

    return Hyp('neck', (i,), roi, apply, {'room': rid, 'label': l.name, 'prot_m2': round(m, 2),
                                          'piece_m2': round(float(B.sum()) / ctx.ppm ** 2, 2),
                                          'cut_m': round(int(bnd.sum()) / ctx.ppm, 2), 'drawn': round(drawn_frac, 2),
                                          'err_before': round(e0, 3), 'err_after': round(e1, 3)},
               f'neck:{i}:{eps}')


# --- T-38: обрыв нарисованной перегородки (две комнаты слиты через белый зазор у её конца) ------------------------------------
# Схема — советник `_intake/codex/false-doors-merged-rooms-2026-11-09-answer.md`: подписи двух РАЗНЫХ комнат в одной области —
# только повод искать стену; режем, лишь когда сырая линия перегородки есть и разрез закрывает её локальный обрыв.
# Геометрия и пороги — `partition.py`.

# не самостоятельная комната: часть комнаты или зона (шкаф, кладовка, «зона»)
_SUBSPACE = ('wardrobe', 'robe', 'cupboard', 'cpd', 'store', 'storage', 'airing', 'closet', 'walk', 'built', 'area',
             'bay', 'recess', 'shelf', 'cylinder')
_ALIAS = {'dining': 'diner', 'dine': 'diner', 'sitting': 'living', 'reception': 'living', 'lounge': 'living',
          'family': 'living', 'bed': 'bedroom', 'bath': 'bathroom', 'wc': 'cloakroom', 'cloaks': 'cloakroom',
          'shower': 'bathroom', 'ensuite': 'en-suite'}


def room_tokens(name: str) -> tuple | None:
    """Имя подписи → набор слов (синонимы сведены, номер — отдельным словом: {bedroom,2} ≠ {bedroom,3}).
    None — не самостоятельная комната (шкаф, кладовка, зона)."""
    s = (name or '').lower().replace('en suite', 'ensuite').replace('en-suite', 'ensuite')
    if any(w in s for w in _SUBSPACE):
        return None
    words = ''.join(ch if ch.isalnum() else ' ' for ch in s.replace(' and ', ' ')).split()
    return tuple(sorted({_ALIAS.get(w, w) for w in words})) or None


def distinct_rooms(ii: list, labels: list) -> list:
    """Подписи области → группы «одна комната»: дубли и вложенные имена (слова одной ⊆ слов другой: «Diner» ⊆
    «Kitchen/Diner», «Bedroom» ⊆ «Bedroom 1») — одна комната; части комнаты (шкаф, зона) — не комната.
    → список групп индексов (по группе на самостоятельную комнату). Сомнение — в пользу «одна комната» (не резать)."""
    groups = []                                       # [(набор слов, [индексы])]
    for i in ii:
        tk = room_tokens(labels[i].name)
        if tk is None:
            continue
        s = set(tk)
        for g in groups:
            if s <= g[0] or g[0] <= s:
                g[0].update(s)
                g[1].append(i)
                break
        else:
            groups.append((s, [i]))
    return [g[1] for g in groups]


def hyp_partition(st: State, rid: int, ia: list, ib: list, labels: list, ctx: Ctx, trigger: tuple):
    """Две самостоятельные комнаты (подписи ia | ib) в одной области → продолжить висящую нарисованную перегородку через
    короткий зазор до стены (`partition.find_partition`, жёсткие условия там). Новая стена — `drawn` (в 3D сплошная),
    стены «по пикселям» не меняются; принимает топология (подписи разошлись по двум комнатам)."""
    region = st.lab == rid
    if region.sum() > MINCUT_MAX_PX:
        return _no('область велика для разреза')
    t = max(2.0, float(ctx.t_int))
    roi = _roi_of(region, int(partition.GAP_T * t) + 4, region.shape)
    sl = np.s_[roi[1]:roi[3], roi[0]:roi[2]]
    raw = (st.final[sl] > 0) & ~(st.add[sl] > 0) & (ctx.wp[sl] >= DRAWN_WP)     # сырая линия: наша стена И тёмное листа
    angles = rot_angles(ctx.fams)

    def loc(i):
        return (labels[i].pt[0] - roi[0], labels[i].pt[1] - roi[1])
    ext_w, B_w, info = partition.find_partition(region[sl], raw, st.final[sl] > 0, t, angles,
                                                [loc(i) for i in ia], [loc(i) for i in ib], close=st.add[sl] > 0,
                                                gap_max_px=fc.DOOR_MIN_M * ctx.ppm)
    if ext_w is None:
        return _no(info['why'])
    ext = np.zeros(region.shape, bool)
    ext[sl] = ext_w
    B = np.zeros(region.shape, bool)
    B[sl] = B_w
    note = {'room': rid, 'a': [labels[i].name for i in ia], 'b': [labels[i].name for i in ib], **info,
            'gap_m': round(info['gap_px'] / ctx.ppm, 2), 't_px': round(t, 1),
            'part_m2': round(float(min(B.sum(), (region & ~B & ~ext).sum())) / ctx.ppm ** 2, 2)}

    def apply(s: State, B=B, ext=ext, rid=rid):
        s = s.copy()
        nid = int(s.lab.max()) + 1
        s.lab[B] = nid
        s.lab[ext & (s.lab == rid)] = 0              # полоса новой стены — не пол комнаты A (иначе её пол заходит в B)
        s.rooms.append(nid)
        if s.cut is None:
            s.cut = np.zeros(s.lab.shape, bool)
            s.drawn = np.zeros(s.lab.shape, bool)
        s.cut |= ext
        s.drawn |= ext
        return s

    return Hyp('partition', trigger, roi, apply, note, f'partition:{rid}:{ia}:{ib}')


def rot_angles(fams) -> list:
    """Повороты окна: 0 (оси) + диагональные семейства стен панели, приведённые к (-45, 45] (как bench.rot_angles)."""
    out = [0.0]
    for f in fams or []:
        a = ((f + 45) % 90) - 45
        if abs(a) > 1.5 and all(abs(a - b) > 1.5 for b in out):
            out.append(a)
    return out


# --- приёмка ----------------------------------------------------------------------------------------------------------------

@dataclass
class Score:
    topo: int                       # доверенные подписи: пропавшие, две с размерами в одной комнате
    pix: float                      # сырой лист, м стены
    dims: float                     # ошибка размеров остальных подписей, м
    edit: float                     # правка, м стены
    cut: float = 0.0                # цена разреза: м без нарисованной линии + 0,25·длина (только min-cut)
    x: int = 0                      # слабое: слияния с помещениями VLM без размеров + необъяснённые куски
    prot: float = 0.0               # форма: м² «отростков» уже NECK_M у комнат с подписью (коридор, прихваченный комнатой)


NECK_M = 1.3                        # отросток уже 1,3 м — коридор/проход, а не тело комнаты (Г-комнаты шире)
NECK_MIN_M2 = 0.4                   # отросток от 0,4 м² (дверной карман, проход; мельче — шум контура)
_PROT_CACHE: dict = {}


def protrusion(m: np.ndarray, ppm: float) -> tuple[float, np.ndarray | None, np.ndarray | None]:
    """Отростки области: что остаётся после открытия кругом диаметра NECK_M (тело комнаты) — куски ≥ 0,5 м².
    → (м², маска тела, маска отростков) в координатах m."""
    if fc.empty_img(m):
        return 0.0, None, None
    k = max(3, int(NECK_M * ppm)) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mm = cv2.copyMakeBorder(m.astype(np.uint8), k, k, k, k, cv2.BORDER_CONSTANT, value=0)
    body = cv2.morphologyEx(mm, cv2.MORPH_OPEN, se)[k:-k, k:-k] > 0
    if not body.any():
        return 0.0, None, None
    thin = m & ~(cv2.dilate(body.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(thin.astype(np.uint8), connectivity=4)
    keep = np.zeros(n, bool)
    keep[1:] = stt[1:, cv2.CC_STAT_AREA] >= NECK_MIN_M2 * ppm * ppm
    t = keep[lab]
    return float(t.sum()) / ppm / ppm, body, t


def prot_cost(st: State, labels: list, topo: dict, ppm: float) -> float:
    tot = 0.0
    for rid, ii in topo['by'].items():
        if not any(labels[i].dims is not None for i in ii):
            continue
        m = st.lab == rid
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        c = m[y0:y1, x0:x1]
        key = hashlib.sha1(np.packbits(c).tobytes() + repr(c.shape).encode()).hexdigest()
        if key not in _PROT_CACHE:
            if len(_PROT_CACHE) > 4000:
                _PROT_CACHE.clear()
            _PROT_CACHE[key] = protrusion(c, ppm)[0]
        tot += _PROT_CACHE[key]
    return tot


def score(st: State, labels: list, ctx: Ctx, exclude: set, roi=None) -> tuple[Score, dict]:
    topo = topology(st, labels, ctx.ppm)
    errs = dims_errors(st, labels, ctx, topo)
    return Score(topo['cost'], pixel_cost(st, ctx, roi), dims_cost(errs, exclude), 0.0, 0.0, topo['x'],
                 prot_cost(st, labels, topo, ctx.ppm)), topo


def accept(before: Score, after: Score) -> tuple[bool, str]:
    """Жёсткие условия по порядку (Codex п.1): топология доверенных подписей → пиксели → размеры остальных
    (с гистерезисом) → слабые (объяснение кусков, форма) → правка (выбор среди принятых)."""
    if after.topo > before.topo:
        return False, 'топология хуже'
    if after.pix > before.pix + TOL_PIX_M:
        return False, 'пиксели хуже'
    tol_d = max(HYST * before.dims, 0.005)
    if after.topo < before.topo:
        if after.dims > before.dims + max(tol_d, 0.02):
            return False, 'размеры остальных хуже'
        return True, 'топология лучше'
    if after.dims > before.dims + tol_d:
        return False, 'размеры остальных хуже'
    if after.dims < before.dims - tol_d:
        return True, 'размеры лучше'
    if after.pix < before.pix - TOL_PIX_M and after.x <= before.x:
        return True, 'пиксели лучше'
    if after.x < before.x and after.prot <= before.prot + 0.5:
        return True, 'куски объяснены'
    if after.prot < before.prot - NECK_MIN_M2 and after.x <= before.x + W_UNEXPL:
        return True, 'форма лучше'
    return False, 'нет улучшения'


def _key(sc: Score):
    return (sc.topo, round(sc.pix / TOL_PIX_M), round(sc.dims, 3), sc.x, round(sc.prot), sc.cut, sc.edit)


def propose(st: State, labels: list, ctx: Ctx, outside: np.ndarray) -> list:
    """Генератор гипотез по триггерам текущего состояния."""
    topo = topology(st, labels, ctx.ppm)
    errs = dims_errors(st, labels, ctx, topo)
    out = []
    # 1) две подписи с размерами в одной комнате (конфликт топологии) или подпись «велика» и в её комнате есть
    #    помещение без размеров (имя от VLM: холл, лестница) → min-cut: каждая против остальных
    for rid, ii in topo['by'].items():
        if len(ii) < 2:
            continue
        dl = [i for i in ii if labels[i].dims is not None]
        big = [i for i in dl if i in errs and errs[i][0] > bad_tol(labels[i].dims)
               and any(errs[i][1][k] > labels[i].dims[k] + bad_tol(labels[i].dims) for k in (0, 1))]
        if len(dl) >= 2:
            trig = tuple(dl)
        elif big:
            trig = tuple(big)
        else:
            continue
        for i in ii:
            rest = [j for j in ii if j != i]
            if len(dl) < 2 and i not in dl:
                continue                               # один «большой» против помещений без размеров
            for eps in (0.05, 0.3):
                h = hyp_mincut(st, rid, [i], rest, labels, ctx, trig, eps)
                if h:
                    out.append(h)
    # 1б) T-38: подписи двух РАЗНЫХ самостоятельных комнат в одной области (размеры не нужны) → разрез только по обрыву
    #     нарисованной перегородки (hyp_partition); каждая комната против остальных
    for rid, ii in topo['by'].items():
        groups = distinct_rooms(ii, labels) if len(ii) >= 2 else []
        if len(groups) < 2:
            continue
        for gi, ga in enumerate(groups):
            if len(groups) == 2 and gi == 1:
                break                                  # две комнаты: «A против B» = «B против A»
            gb = [j for gj, g in enumerate(groups) if gj != gi for j in g]
            _SKIPS.clear()
            h = hyp_partition(st, rid, ga, gb, labels, ctx, tuple(ga + gb))
            if h:
                out.append(h)
            elif _SKIPS:
                SKIPLOG.append({'kind': 'skip', 'hyp': 'partition', 'room': int(rid),
                                'a': [labels[i].name for i in ga], 'b': [labels[i].name for i in gb], 'why': _SKIPS[-1]})
    # 2) подпись «мала» (наше меньше подписи) → влить соседний кусок без подписи
    for i, (e, pred) in errs.items():
        l = labels[i]
        if e <= bad_tol(l.dims):
            continue
        rid = topo['own'][i]
        small = any(pred[k] < l.dims[k] - bad_tol(l.dims) for k in (0, 1))
        if small:
            for p in neighbours(st, rid, ctx):
                if p in topo['by']:
                    continue
                h = hyp_remove(st, p, rid, ctx, (i,), outside)
                if h:
                    out.append(h)
    # 3) необъяснённый кусок → влить в соседа (триггера-подписи нет; размеры соседа проверяют)
    for p in topo['unexplained']:
        for q in neighbours(st, p, ctx):
            h = hyp_remove(st, p, q, ctx, (), outside)
            if h:
                out.append(h)
    # 2б) подпись «велика», в комнате нет других подписей → отрезать узкий отросток (коридор) по узкому месту
    for i, (e, pred) in errs.items():
        l = labels[i]
        rid = topo['own'][i]
        if e <= bad_tol(l.dims) or len(topo['by'].get(rid, [])) > 1:
            continue
        if any(pred[k] > l.dims[k] + bad_tol(l.dims) for k in (0, 1)):
            h = hyp_neck(st, i, labels, ctx)
            if h:
                out.append(h)
    # 4) подпись не попала в комнату → локальный пересчёт окна
    #    лестница улик: сначала стены и доминирующий цвет; тонкие линии (виртуальная граница) — только если сильные
    #    улики окно не замкнули (иначе тонкий контур стола/ковра внутри комнаты выигрывает у самой комнаты)
    for i in topo['missing']:
        strong = 0
        made = 0
        for dom in (False, True, 'faint'):
            if dom == 'faint' and strong:
                SKIPLOG.append({'kind': 'skip', 'hyp': 'recompute', 'label': labels[i].name, 'dominant': dom,
                                'why': 'сильные улики уже замкнули окно'})
                continue
            for close_m in (1.0, 1.8):
                _SKIPS.clear()
                h = hyp_recompute(st, i, labels, ctx, outside, close_m, dom)
                if h:
                    out.append(h)
                    strong += dom != 'faint'
                    made += (h.key, _state_hash(st, h.roi)) not in TABU   # отвергнутый пересчёт — не замена замыканию
                elif _SKIPS:
                    SKIPLOG.append({'kind': 'skip', 'hyp': 'recompute', 'label': labels[i].name, 'close_m': close_m,
                                    'dominant': dom, 'why': _SKIPS[-1]})
        # 5) T-16: пересчёт окна не замкнул — открытая комната: замыкание контура вокруг подписи (по подходам)
        if made:
            continue
        for mode in open_modes():
            _SKIPS.clear()
            h = hyp_enclose(st, i, labels, ctx, mode)
            if h:
                out.append(h)
                break
            if _SKIPS:
                SKIPLOG.append({'kind': 'skip', 'hyp': 'enclose', 'label': labels[i].name, 'mode': mode,
                                'why': _SKIPS[-1]})
    return out


def run(st: State, labels: list, ctx: Ctx, outside: np.ndarray, budget_s: float = BUDGET_S,
        max_passes: int = MAX_PASSES) -> tuple[State, list]:
    t0 = time.time()
    journal, tabu = [], TABU
    tabu.clear()
    for ps in range(max_passes):
        SKIPLOG.clear()
        hyps = propose(st, labels, ctx, outside)
        journal += [{'pass': ps, **x} for x in SKIPLOG]
        cand = []
        for h in hyps:
            if time.time() - t0 > budget_s:
                break
            tk = (h.key, _state_hash(st, h.roi))
            if tk in tabu:
                continue
            # табу — отвергнутые в этом состоянии окна (принятые, но не применённые — пробуются снова)
            excl = set(h.trigger)
            b, _ = score(st, labels, ctx, excl, h.roi)
            try:
                s2 = h.apply(st)
            except Exception as e:  # noqa: BLE001 — гипотеза не применилась: в журнал, не молча
                journal.append({'pass': ps, 'kind': h.kind, **h.note, 'ok': False, 'why': f'сбой {type(e).__name__}'})
                continue
            a, topo2 = score(s2, labels, ctx, excl, h.roi)
            # правка = сколько метров стены добавлено/снято (переразметка площади правкой не считается)
            cd = 0 if s2.cut is None else int((s2.cut != (st.cut if st.cut is not None else np.zeros_like(s2.cut))).sum())
            a.edit = float((s2.final != st.final).sum() + cd) / max(1.0, ctx.t_int) / ctx.ppm
            a.cut = float(h.note.get('shape', 0.0))
            ok, why = accept(b, a)
            rec = {'pass': ps, 'kind': h.kind, **h.note, 'trigger': [labels[i].name for i in h.trigger],
                   'dT': a.topo - b.topo, 'dP_m': round(a.pix - b.pix, 2), 'dD_m': round(a.dims - b.dims, 3),
                   'dE_rel': round((a.dims - b.dims) / max(1e-6, b.dims), 3), 'dX': a.x - b.x,
                   'dS_m2': round(a.prot - b.prot, 2), 'edit_m': round(a.edit, 2),
                   'ok': ok, 'why': why}
            journal.append(rec)
            if ok:
                cand.append((_key(a), h, s2, rec, a, tk))
            else:
                tabu.add(tk)
        if not cand:
            break
        # по триггеру — лучшая; близкие разные — «неоднозначно» (не применяем)
        groups = {}
        for c in cand:
            groups.setdefault((c[1].trigger, c[1].note.get('room', c[1].note.get('piece', c[1].note.get('label')))), []).append(c)
        applied_roi = []
        changed = False
        for g in sorted(groups.values(), key=lambda g: min(c[0] for c in g)):
            g.sort(key=lambda c: c[0])
            best = g[0]
            alt = [c for c in g[1:] if c[0][:2] == best[0][:2] and abs(c[0][2] - best[0][2]) <= max(HYST * best[0][2], 0.01)
                   and c[0][3:5] == best[0][3:5] and abs(c[0][5] - best[0][5]) <= HYST * max(best[0][5], 0.5)
                   and _differs(c[2], best[2], st)]
            if alt:
                best[3]['ambiguous'] = True
                tabu.add(best[5])
                for c in alt:
                    c[3]['ambiguous'] = True
                    tabu.add(c[5])
                journal.append({'pass': ps, 'kind': 'ambiguous', 'trigger': best[3]['trigger'],
                                'options': [best[3].get('kind')] + [c[3].get('kind') for c in alt],
                                'ok': False, 'why': 'близкие гипотезы — человеку'})
                continue
            if _state_hash(st, best[1].roi) != best[5][1]:
                continue                               # окно гипотезы уже изменилось в этом проходе — в следующем
            st2 = best[1].apply(st)
            # переоценка на текущем состоянии (после других правок прохода)
            b, _ = score(st, labels, ctx, set(best[1].trigger), best[1].roi)
            a, _ = score(st2, labels, ctx, set(best[1].trigger), best[1].roi)
            ok, why = accept(b, a)
            if not ok:
                continue
            st = st2
            best[3]['applied'] = True
            applied_roi.append(best[1].roi)
            changed = True
        if not changed or time.time() - t0 > budget_s:
            break
    journal.append({'kind': 'stop', 'sec': round(time.time() - t0, 1)})
    return st, journal


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _differs(s1: State, s2: State, base: State) -> bool:
    """Разные ли разбиения: переразмеченные пиксели пересекаются мало (IoU < 0,5) — И не являются дополнением друг
    друга внутри затронутых комнат: разрез «A против B» и «B против A» — то же разбиение с переставленными номерами
    (переразмечена то одна сторона, то другая), это не «неоднозначно»."""
    d1 = s1.lab != base.lab
    d2 = s2.lab != base.lab

    def iou(a, b):
        u = (a | b).sum()
        return (a & b).sum() / u if u else 1.0
    if iou(d1, d2) >= 0.5:
        return False
    touched = [v for v in np.unique(base.lab[d1 | d2]) if v in base.rooms]
    if touched:
        R = np.isin(base.lab, touched)
        if iou(d1 & R, R & ~d2) >= 0.5:
            return False
    return True


# --- обрывки за нашими закрытиями (T-20261110-19) ------------------------------------------------------------------------
# Мелкий безымянный кусок (обрывок — `bench.is_fragment`: < 1,5 м² или уже 1 м) на шумном листе (штрихи лестницы, край ванны,
# тени, водяной знак) отрезан от соседа НАШИМ закрытием — достроенным разрывом стены, а не стеной листа. Комнату, даже кладовку,
# замыкают нарисованные стены: у кладовки 0,8×0,8 м с дверью 0,7 м закрытие — ~1/5 границы, остальное — стены листа (на 8
# листах T-19: WC и кладовки с подписью — 0–0,18). У обрывков — 0,31–0,67 (Wynne: марш лестницы разрезан закрытиями; QFfI:
# край ванны, тамбур спальни; Nethercote: вход в прихожую по линии коврика, очаг камина). Порог «необъяснённого» (EXPLAIN_M2 = 1 м²) такие
# куски в починку не пускает, а метрика обрывков (`bench.name_extras`) их лишь не считает, в выгрузке они — «Помещение».
# Правило: обрывок без подписи, у которого доля наших закрытий (кроме зазубрин) в границе ≥ FRAG_OURS_MIN, вливается в
# соседа, с которым делит больше всего закрытий; закрытия между ними снимаются. Не вливается, если сосед — с подписью размера и
# его мерка от этого выходит из допуска (bad_tol) заметно хуже прежней, или топология подписей хуже. Повтор, пока вливается
# (марш из трёх кусков — по одному). Журнал — 'absorb' (применено / почему нет).
FRAG_OURS_MIN = 0.3
CONTACT_MIN = 0.5           # запасной сосед: общее закрытие ≥ этой доли от главного
CONTACT_MIN_M = 0.4         # общее закрытие с соседом — не короче (м; проход уже 0,6 м не бывает)
ABSORB_MAX = 50


def _band(st: State, P: np.ndarray, ctx: Ctx):
    """Граница куска P: пиксели стен/закрытий не дальше толщины от него (как `_shared`) → (окно, кольцо, dP)."""
    ys, xs = np.nonzero(P)
    H, W = P.shape
    m = int(2 * ctx.t_int + 6)
    y0, y1, x0, x1 = max(0, ys.min() - m), min(H, ys.max() + m + 1), max(0, xs.min() - m), min(W, xs.max() + m + 1)
    sl = np.s_[y0:y1, x0:x1]
    d = 1.2 * max(ctx.t_int, 2.0) + 1.5
    dP = cv2.distanceTransform((~P[sl]).astype(np.uint8), cv2.DIST_L2, 3)
    return sl, (st.final[sl] > 0) & (dP <= d), d


def absorb_fragments(st: State, labels: list, ctx: Ctx, frag, notch: np.ndarray | None = None) -> tuple[State, list, list]:
    """Обрывки за нашими закрытиями — в соседа (см. выше). frag(м², ширина м) → обрывок ли (`bench.is_fragment`);
    notch — пиксели закрытий, которые не проход и не разрез: зазубрины (стена) и окна (наружная стена) — в долю не идут.
    Доля — все наши закрытия в границе куска (и к соседям, и наружу: вход с улицы у обрывка прихожей — тоже наш);
    снимаются только закрытия между куском и соседом, и не те, что у третьей комнаты (дверь соседа в неё — на месте).
    → (состояние, журнал, [{'into', 'piece', 'm2'}])."""
    jr, done = [], []
    ppm = ctx.ppm
    skip = set()
    diag = os.environ.get('FP_ABSORB_DIAG', '0') != '0'
    for _ in range(ABSORB_MAX):
        topo = topology(st, labels, ppm)
        areas = np.bincount(st.lab.ravel(), minlength=int(st.lab.max()) + 1)
        moved = False
        cands = []
        for p in st.rooms:
            if p in skip or (p in topo['by'] and not diag):
                continue
            P = st.lab == p
            a = float(areas[p]) / ppm / ppm
            w = 2.0 * float(cv2.distanceTransform(np.pad(P.astype(np.uint8), 1), cv2.DIST_L2, 5).max()) / ppm
            if not frag(a, w):
                continue
            sl, ring, d = _band(st, P, ctx)
            ours = ring & (st.add[sl] > 0)
            if notch is not None:
                ours &= ~(notch[sl] > 0)
            per = {}
            labw = st.lab[sl]
            for q in neighbours(st, p, ctx):
                dQ = cv2.distanceTransform((labw != q).astype(np.uint8), cv2.DIST_L2, 3)
                other = (labw > 0) & (labw != p) & (labw != q)
                dR = cv2.distanceTransform((~other).astype(np.uint8), cv2.DIST_L2, 3) if other.any() else None
                S = ours & (dQ <= d)
                if dR is not None:
                    S &= dR > d
                if S.sum() >= 3:
                    per[q] = S
            share = float(ours.sum()) / max(1, int(ring.sum())) if per else 0.0
            rec = {'kind': 'absorb', 'piece': int(p), 'm2': round(a, 2), 'w_m': round(w, 2), 'ours': round(share, 2),
                   'per': {int(q): int(S.sum()) for q, S in per.items()}}
            if p in topo['by']:                           # отладка (FP_ABSORB_DIAG): доля закрытий у кусков С подписью
                skip.add(p)
                jr.append(dict(rec, ok=False, why='с подписью: ' + ', '.join(labels[i].name for i in topo['by'][p])))
                continue
            if share < FRAG_OURS_MIN:
                skip.add(p)
                if per:                                   # кусок с закрытием, но замкнут стенами листа — кладовка: в журнал
                    jr.append(dict(rec, ok=False, why='замкнут стенами листа'))
                continue
            cands.append((share, p, P, a, sl, per, rec))
        # первым — самый явный обрывок (большая доля закрытий): иначе мелкий кусок марша влился бы в соседний кусок
        # и снял закрытие между ними — доля у слитого упала бы ниже порога, хотя оба — обрывки (Wynne)
        for share, p, P, a, sl, per, rec in sorted(cands, key=lambda c: (-c[0], c[1])):
            # сосед — с наибольшим общим закрытием (при равенстве — с подписью, затем больший)
            order = sorted(per, key=lambda q: (-int(per[q].sum()), q not in topo['by'], -int(areas[q])))
            # запасной сосед — только с сопоставимым общим закрытием: слабый касатель (угол закрытия у торца стены листа)
            # соединил бы кусок с соседом в обход стены (Nethercote: два шкафа в стене между спальнями — в один)
            # и само общее закрытие — не короче CONTACT_MIN_M: иначе кусок отрезан не нашим закрытием, а своими стенами,
            # и в соседа вошёл бы островом (Nethercote: очаг камина касается гостиной закрытием в 6 px)
            top = int(per[order[0]].sum())
            px_min = CONTACT_MIN_M * ppm * max(ctx.t_int, 2.0)
            order = [q for q in order if per[q].sum() >= max(CONTACT_MIN * top, px_min)]
            if not order:
                skip.add(p)
                jr.append(dict(rec, ok=False, why='касается соседа коротко'))
                continue
            applied = False
            for q in order:
                Sg = np.zeros(st.lab.shape, bool)
                Sg[sl] = per[q]
                s2 = st.copy()
                s2.lab[P] = q
                s2.final[Sg] = 0
                s2.add[Sg] = 0
                s2.lab[Sg] = q
                s2.rooms.remove(p)
                topo2 = topology(s2, labels, ppm)
                if topo2['cost'] > topo['cost'] or topo2['merged'] > topo['merged']:
                    jr.append(dict(rec, into=int(q), ok=False, why='топология хуже'))
                    continue
                # подписи остаются у своих комнат: снятое закрытие — пол соседа у чужой точки подписи (Wynne: «Cupboard»
                # на закрытии ушёл бы к маршу лестницы, а его комната стала бы «безымянной» и влилась бы следом)
                stolen = [labels[i].name for i, (o1, o2) in enumerate(zip(topo['own'], topo2['own']))
                          if o1 != o2 and o1 is not None and not (o1 == p and o2 == q)]
                if stolen:
                    jr.append(dict(rec, into=int(q), ok=False, why='подпись сменила комнату: ' + ', '.join(stolen)))
                    continue
                worse = None
                e1 = dims_errors(st, labels, ctx, topo)
                e2 = dims_errors(s2, labels, ctx, topo2)
                for i in topo2['by'].get(q, []):
                    if labels[i].dims is None or i not in e2:
                        continue
                    eb, ea = (e1[i][0] if i in e1 else 0.0), e2[i][0]
                    if ea > bad_tol(labels[i].dims) and ea > eb + norm_tol(labels[i].dims):
                        worse = (labels[i].name, round(eb, 2), round(ea, 2))
                        break
                if worse:
                    jr.append(dict(rec, into=int(q), ok=False, why=f'мерка {worse[0]} хуже: {worse[1]} → {worse[2]} м'))
                    continue
                st = s2
                jr.append(dict(rec, into=int(q), closure_px=int(Sg.sum()), ok=True, applied=True))
                done.append({'into': int(q), 'piece': int(p), 'm2': round(a, 2)})
                applied = moved = True
                break
            if not applied:
                skip.add(p)
            if moved:
                break                                      # состояние сменилось — доли и соседи заново
        if not moved:
            break
    # кусок, влитый в кусок, — итог в того, в кого влит последний
    final_of = {}
    for x in done:
        final_of[x['piece']] = x['into']
    for x in done:
        q = x['into']
        while q in final_of:
            q = final_of[q]
        x['into'] = q
    return st, jr, done


# --- итог по подписям (что не починилось — видно) ----------------------------------------------------------------------

def label_report(st: State, labels: list, ctx: Ctx) -> list:
    topo = topology(st, labels, ctx.ppm)
    errs = dims_errors(st, labels, ctx, topo)
    out = []
    for i, l in enumerate(labels):
        if l.dims is None:                            # помещение VLM без размеров — для разбора, без флага
            out.append({'name': l.name, 'pt': [round(l.pt[0], 1), round(l.pt[1], 1)], 'dims': None,
                        'room': topo['own'][i], 'space': True, 'flag': '', 'level': 0})
            continue
        rid = topo['own'][i]
        row = {'name': l.name, 'pt': [round(l.pt[0], 1), round(l.pt[1], 1)], 'dims': list(l.dims), 'room': rid}
        if rid is None:
            row.update(flag='не найдена', level=2)
        elif i not in errs:
            row.update(flag='слита с ' + ', '.join(labels[j].name for j in topo['by'][rid] if j != i), level=2)
        else:
            e, pred = errs[i]
            row['err_m'] = round(e, 3)
            row['pred'] = [round(pred[0], 2), round(pred[1], 2)]
            if e > bad_tol(l.dims):
                row.update(flag='не сошлось', level=2)
            elif e > norm_tol(l.dims):
                row.update(flag='ниша/манера?', level=1)
            else:
                row.update(flag='', level=0)
        out.append(row)
    return out
