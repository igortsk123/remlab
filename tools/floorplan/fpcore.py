"""Стенд «картинка планировки → стены → серое 3D» (T-20261109-02, план floorplan-raster-bench-01): чистые функции.

Путь OpenCV без нейросети: маска стен (цвет или тёмное + открытие) → панели → закрытие разрывов стен по строкам/столбцам
(с проверкой «торца стены» и стекла окна) → комнаты как связные области свободного места → подписи → масштаб RANSAC →
выпрямление контуров по семействам углов → полосы стен для выдавливания. Без внешних моделей; тесты — tests/floorplan/.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# --- маски ------------------------------------------------------------------------------------------------------------

def remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[lab].astype(np.uint8)


def wall_mask_blue(img: np.ndarray, min_area: int = 40) -> np.ndarray:
    """Синие стены (план A): тон 95–135 (OpenCV 0–180), насыщенность и яркость не малые."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 50)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return remove_small(m, min_area)


def wall_mask_dark(img: np.ndarray, thr: int, open_px: int, min_area: int = 60) -> np.ndarray:
    """Тёмные стены: порог серого + открытие квадратом `open_px` (тонкие линии, текст, дуги дверей уходят)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    m = (g < thr).astype(np.uint8)
    if open_px > 1:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (open_px, open_px)))
    return remove_small(m, min_area)


def stroke_thickness(mask: np.ndarray) -> float:
    """Медианная толщина штриха маски, px: 2·dt на осевых пикселях (локальные максимумы distance transform)."""
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    mx = cv2.dilate(dt, np.ones((3, 3), np.uint8))
    ridge = (dt > 0.9) & (dt >= mx - 1e-6)
    v = dt[ridge]
    return float(2 * np.median(v)) if v.size else 0.0


# --- разрывы стен (двери, окна) ------------------------------------------------------------------------------------------

def _runs(row: np.ndarray):
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def perp_reach(wall: np.ndarray):
    """Для каждого пикселя — расстояние до ближайшей стены вверх и вниз по столбцу (inf, если стены нет)."""
    H = wall.shape[0]
    ar = np.arange(H)[:, None].repeat(wall.shape[1], 1)
    up = np.maximum.accumulate(np.where(wall > 0, ar, -1), axis=0)
    dn = np.minimum.accumulate(np.where(wall > 0, ar, H + 10)[::-1], axis=0)[::-1]
    du = np.where(up >= 0, ar - up, np.inf)
    dd = np.where(dn <= H, dn - ar, np.inf)
    return du, dd


def bridge_lines(wall: np.ndarray, max_gap: int, min_flank: int, both_flanks: bool = False,
                 reach: float | None = None) -> np.ndarray:
    """Закрыть разрывы ≤ max_gap ВДОЛЬ СТРОК: пиксели между двумя кусками стены на одной строке, если хотя бы один
    (или оба — `both_flanks`) кусок длиннее `min_flank` — то есть это торец стены, идущей вдоль строки, а не поперечная
    стена коридора. `reach`: поперёк разрыва хотя бы в одну сторону должна быть стена ближе reach px — иначе это
    пустота между отдельными панелями/постройками (с обеих сторон наружа), а не проём. Для столбцов — на `wall.T`."""
    add = np.zeros_like(wall, dtype=np.uint8)
    du = dd = None
    if reach is not None:
        du, dd = perp_reach(wall)
    for y in range(wall.shape[0]):
        row = wall[y]
        if not row.any():
            continue
        s, e = _runs(row)
        L = e - s
        longs = np.flatnonzero(L >= min_flank)
        for i in range(len(s) - 1):
            gap = s[i + 1] - e[i]
            if gap <= 0 or gap > max_gap:
                continue
            lf, rf = L[i], L[i + 1]
            if both_flanks:
                ok = min(lf, rf) >= min_flank
            else:
                ok = max(lf, rf) >= min_flank
                if not ok and len(longs):
                    # дверь между двумя короткими кусками (угол, Т-стык), но линия стены рядом есть: длинный кусок
                    # на этой же строке не дальше max_gap от разрыва — это стена вдоль строки, а не коридор поперёк
                    d = np.where(e[longs] <= e[i], e[i] - e[longs], s[longs] - s[i + 1])
                    ok = bool((d <= max_gap).any())
            if ok and du is not None:
                mid = (e[i] + s[i + 1]) // 2
                ok = min(du[y, mid], dd[y, mid]) <= reach
            if ok:
                add[y, e[i]:s[i + 1]] = 1
    return add


def extend_corners(wall: np.ndarray, reach: int, min_flank: int) -> np.ndarray:
    """Достроить угол, у которого нет вершины (угол спрятан под элементом интерфейса, как у A слева сверху, или
    окно в самом углу): висячий конец длинного куска стены продлевается вдоль строки (столбца) на ≤ reach, и
    продление остаётся только до самого дальнего пересечения с продлением перпендикулярной стены."""
    H, W = wall.shape

    def segs(m):
        out = []
        for y in range(m.shape[0]):
            row = m[y]
            if not row.any():
                continue
            s, e = _runs(row)
            for i in range(len(s)):
                if e[i] - s[i] < min_flank:
                    continue
                nxt = s[i + 1] if i + 1 < len(s) else None
                prv = e[i - 1] if i > 0 else None
                if nxt is None or nxt - e[i] > reach:
                    out.append((y, e[i], min(m.shape[1], e[i] + reach), +1))
                if prv is None or s[i] - prv > reach:
                    out.append((y, max(0, s[i] - reach), s[i], -1))
        return out

    sh, sv = segs(wall), segs(wall.T)
    eh = np.zeros((H, W), np.uint8)
    ev = np.zeros((W, H), np.uint8)
    for y, a, b, _ in sh:
        eh[y, a:b] = 1
    for x, a, b, _ in sv:
        ev[x, a:b] = 1
    cross = eh & ev.T
    add = np.zeros((H, W), np.uint8)
    for y, a, b, d in sh:
        c = np.flatnonzero(cross[y, a:b])
        if c.size:
            if d > 0:
                add[y, a:a + c.max() + 1] = 1
            else:
                add[y, a + c.min():b] = 1
    addT = np.zeros((W, H), np.uint8)
    crossT = cross.T
    for x, a, b, d in sv:
        c = np.flatnonzero(crossT[x, a:b])
        if c.size:
            if d > 0:
                addT[x, a:a + c.max() + 1] = 1
            else:
                addT[x, a + c.min():b] = 1
    return ((add | addT.T) & (wall == 0)).astype(np.uint8)


def xy_cut(mask: np.ndarray, min_gap: int, box=None, depth: int = 0) -> list[tuple]:
    """Рекурсивная нарезка листа по пустым полосам (нет ни одного пикселя стены) шириной ≥ min_gap → рамки
    (x0, y0, x1, y1). Проёмы и окна полосы через всю панель не дают — режутся только отдельные планы."""
    if box is None:
        box = (0, 0, mask.shape[1], mask.shape[0])
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    if not sub.any():
        return []
    ys, xs = np.nonzero(sub)
    x0, x1, y0, y1 = x0 + xs.min(), x0 + xs.max() + 1, y0 + ys.min(), y0 + ys.max() + 1
    sub = mask[y0:y1, x0:x1]
    if depth > 12:
        return [(x0, y0, x1, y1)]
    for axis in (0, 1):
        prof = sub.any(axis=axis)            # axis=0 → по столбцам
        s, e = _runs(~prof)
        cuts = [(a, b) for a, b in zip(s, e) if b - a >= min_gap and a > 0 and b < len(prof)]
        if cuts:
            out, prev = [], 0
            for a, b in cuts + [(len(prof), len(prof))]:
                nb = (x0 + prev, y0, x0 + a, y1) if axis == 0 else (x0, y0 + prev, x1, y0 + a)
                out += xy_cut(mask, min_gap, nb, depth + 1)
                prev = b
            return out
    return [(x0, y0, x1, y1)]


def rotate_mask(m: np.ndarray, angle_deg: float, shape=None, inverse_of=None):
    """Поворот маски вокруг центра с расширением холста; возвращает (маска, матрица). Обратный — `unrotate_mask`."""
    h, w = m.shape
    c = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(c, angle_deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    M[0, 2] += nw / 2 - c[0]
    M[1, 2] += nh / 2 - c[1]
    r = cv2.warpAffine(m.astype(np.uint8), M, (nw, nh), flags=cv2.INTER_NEAREST)
    return r, M


def unrotate_mask(r: np.ndarray, M: np.ndarray, shape) -> np.ndarray:
    Mi = cv2.invertAffineTransform(M)
    return cv2.warpAffine(r.astype(np.uint8), Mi, (shape[1], shape[0]), flags=cv2.INTER_NEAREST)


def bridge_parts(wall: np.ndarray, max_gap: int, min_flank: int, angles=(0.0,), both_flanks=False,
                 reach: float | None = None) -> list[np.ndarray]:
    """Разрывы вдоль строк и вдоль столбцов для каждого семейства углов (0 — оси картинки; диагональ C — свой угол)
    — ОТДЕЛЬНЫМИ масками: две соседние двери из разных проходов не должны слиться в одно пятно до проверки."""
    parts = []
    for a in angles:
        if abs(a) < 0.5:
            parts.append(bridge_lines(wall, max_gap, min_flank, both_flanks, reach))
            parts.append(bridge_lines(wall.T, max_gap, min_flank, both_flanks, reach).T.copy())
        else:
            r, M = rotate_mask(wall, a)
            parts.append(unrotate_mask(bridge_lines(r, max_gap, min_flank, both_flanks, reach), M, wall.shape))
            parts.append(unrotate_mask(bridge_lines(r.T, max_gap, min_flank, both_flanks, reach).T.copy(), M, wall.shape))
    return [(p & (wall == 0)).astype(np.uint8) for p in parts]


def bridge_all(wall: np.ndarray, max_gap: int, min_flank: int, angles=(0.0,), both_flanks=False,
               reach: float | None = None) -> np.ndarray:
    add = np.zeros_like(wall, dtype=np.uint8)
    for p in bridge_parts(wall, max_gap, min_flank, angles, both_flanks, reach):
        add |= p
    return add


@dataclass
class Gap:
    id: int
    cx: float
    cy: float
    length: float          # px вдоль стены
    depth: float           # px поперёк (≈ толщина стены)
    kind: str              # door | window | opening
    glaze: float           # доля «не белого» внутри разрыва (стекло окна)
    exterior: bool
    bbox: tuple


def thin_lines(gray: np.ndarray, wall: np.ndarray, delta: int = 15, k: int = 7) -> np.ndarray:
    """Тонкая графика (рамы окон, дуги дверей, мебель, текст): «чёрная шляпа» — линия темнее своего фона на delta
    и уже k px; мягкие тени у стен и заливки комнат сюда не попадают. Минус стены."""
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    return ((bh >= delta) & (wall == 0)).astype(np.uint8)


def gap_components(add: np.ndarray, dark: np.ndarray, outside: np.ndarray | None):
    """Добавленные пиксели → разрывы: длина/глубина по minAreaRect, «стекло» — доля тонких линий внутри разрыва
    (окно нарисовано рамой внутри толщины стены, проём двери пуст)."""
    n, lab, st, cen = cv2.connectedComponentsWithStats(add.astype(np.uint8), connectivity=8)
    out = []
    near_out = cv2.dilate(outside.astype(np.uint8), np.ones((5, 5), np.uint8)) if outside is not None else None
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < 3:
            continue
        (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        length, depth = max(w, h) + 1, min(w, h) + 1
        glaze = frame_coverage(ys, xs, dark)
        ext = bool(near_out[ys, xs].any()) if near_out is not None else False
        out.append(Gap(i, float(cx), float(cy), float(length), float(depth), '', glaze, ext,
                       tuple(int(v) for v in st[i, :4])))
    return lab, out


def frame_coverage(ys: np.ndarray, xs: np.ndarray, line: np.ndarray) -> float:
    """Рама окна: есть ли внутри разрыва линия ВДОЛЬ него. Пиксели разрыва — по слоям поперёк (шаг 1 px); у слоя —
    доля длины, покрытая линией; ответ — лучший слой (0..1). Пустой проём двери ≈ 0, окно с рамой ≈ 1."""
    if len(xs) < 3:
        return 0.0
    c, u, n, L, d = gap_axes(ys, xs)
    P = np.column_stack([xs, ys]).astype(float) - c
    a = np.round(P @ u).astype(int)
    b = np.round(P @ n).astype(int)
    hit = line[ys, xs] > 0
    best = 0.0
    for k in np.unique(b):
        sel = b == k
        tot = np.unique(a[sel]).size
        if tot < max(3, 0.5 * L):
            continue
        best = max(best, np.unique(a[sel & hit]).size / tot)
    return float(best)


def gap_axes(ys: np.ndarray, xs: np.ndarray):
    """Пиксели разрыва → центр, единичный вектор вдоль разрыва (главная ось), нормаль, длина, глубина."""
    P = np.column_stack([xs, ys]).astype(float)
    c = P.mean(axis=0)
    if len(P) < 3:
        return c, np.array([1.0, 0.0]), np.array([0.0, 1.0]), 1.0, 1.0
    w, v = np.linalg.eigh(np.cov((P - c).T))
    u = v[:, 1]
    n = np.array([-u[1], u[0]])
    a, b = (P - c) @ u, (P - c) @ n
    c = c + u * (a.max() + a.min()) / 2 + n * (b.max() + b.min()) / 2
    return c, u, n, float(a.max() - a.min() + 1), float(b.max() - b.min() + 1)


def door_evidence(thin: np.ndarray, c, u, n, L: float, depth: float, step_deg: int = 5) -> float:
    """Есть ли у разрыва дуга двери: доля углов 0–90°, где на радиусе створки от петли (конец разрыва, грань стены)
    лежит тонкая линия. Створка одна (радиус L) или две (по L/2 от каждого конца, обе дуги). → лучшая доля 0..1."""
    H, W = thin.shape
    th = np.radians(np.arange(0, 91, step_deg))

    def cov(h, d, s, R):
        pts = h[None, :] + R * (np.cos(th)[:, None] * d[None, :] + np.sin(th)[:, None] * s[None, :])
        hit = 0
        for x, y in pts:
            xi, yi = int(round(x)), int(round(y))
            y0, y1, x0, x1 = max(0, yi - 2), min(H, yi + 3), max(0, xi - 2), min(W, xi + 3)
            if y1 > y0 and x1 > x0 and thin[y0:y1, x0:x1].any():
                hit += 1
        return hit / len(pts)

    best = 0.0
    for s in (n, -n):
        face = c + s * depth / 2
        for j in (0.0, 0.1, 0.2, 0.3):               # петля чуть внутри разрыва (торец рисуют с наличником)
            e1, e2 = face - u * L * (0.5 - j), face + u * L * (0.5 - j)
            for f in np.arange(0.5, 1.06, 0.05):
                R = f * L
                single = max(cov(e1, u, s, R), cov(e2, -u, s, R))
                double = min(cov(e1, u, s, R / 2), cov(e2, -u, s, R / 2))
                best = max(best, single, double)
    return best


def free_components(wall: np.ndarray):
    """Свободные области: метки (4-связность), наружная область = всё, что касается края картинки."""
    free = (wall == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(free, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
    outside = np.isin(lab, list(border)) & (free > 0)
    return n, lab, outside


# --- углы: семейства направлений ------------------------------------------------------------------------------------------

def angle_families(wall: np.ndarray, min_share: float = 0.06, merge_deg: float = 4.0) -> list[float]:
    """Направления стен (mod 180, градусы): гистограмма направлений рёбер контуров с весом длины → пики.
    Всегда есть 0 и 90; диагональ добавляется, если её доля ≥ min_share."""
    cnts, _ = cv2.findContours(wall.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    hist = np.zeros(180)
    for c in cnts:
        if len(c) < 20:
            continue
        ap = cv2.approxPolyDP(c, 1.5, True).reshape(-1, 2).astype(float)
        for p, q in zip(ap, np.roll(ap, -1, axis=0)):
            d = q - p
            L = math.hypot(*d)
            if L < 12:
                continue
            a = math.degrees(math.atan2(d[1], d[0])) % 180
            hist[int(round(a)) % 180] += L
    sm = np.convolve(np.concatenate([hist[-3:], hist, hist[:3]]), np.ones(3) / 3, 'valid')[2:-2]
    tot = sm.sum() or 1
    fams = []
    for a in np.argsort(-sm):
        if sm[a] / tot * 3 < min_share:
            break
        if all(min(abs(a - f), 180 - abs(a - f)) > merge_deg for f in fams):
            fams.append(float(a))
    for base in (0.0, 90.0):
        if all(min(abs(base - f), 180 - abs(base - f)) > merge_deg for f in fams):
            fams.append(base)
    # уточнить пик взвешенным средним в ±2°
    ref = []
    for f in fams:
        idx = [(int(f) + k) % 180 for k in range(-2, 3)]
        w = hist[idx]
        if w.sum() > 0:
            offs = np.array(range(-2, 3))
            ref.append((f + float((offs * w).sum() / w.sum())) % 180)
        else:
            ref.append(f)
    return ref


def angdiff(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


# --- размеры комнаты ----------------------------------------------------------------------------------------------------

def _max_runs(m: np.ndarray, axis: int) -> np.ndarray:
    """Длина самого длинного непрерывного куска в каждой строке (axis=1) или столбце (axis=0)."""
    mm = m if axis == 1 else m.T
    out = []
    for row in mm:
        if not row.any():
            continue
        s, e = _runs(row)
        out.append(int((e - s).max()))
    return np.array(out, float)


def room_extents(room: np.ndarray, angle_deg: float = 0.0) -> dict:
    """Кандидаты размеров комнаты, px вдоль осей комнаты (угол — семейство стен): P95 хорды, медиана хорд, габарит."""
    ys, xs = np.nonzero(room)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = room[y0:y1, x0:x1].astype(np.uint8)
    m = np.pad(m, 4)
    if abs(angle_deg) > 0.5:
        m, _ = rotate_mask(m, angle_deg)
    hx, vy = _max_runs(m, 1), _max_runs(m, 0)
    ys2, xs2 = np.nonzero(m)
    return {'p95': (float(np.percentile(hx, 95)), float(np.percentile(vy, 95))),
            'med': (float(np.median(hx)), float(np.median(vy))),
            'bbox': (float(xs2.max() - xs2.min() + 1), float(ys2.max() - ys2.min() + 1))}


# --- масштаб: RANSAC по подписям ------------------------------------------------------------------------------------------

CANDS = ('p95', 'med', 'bbox')


def _pred(ext: dict, cand: str, perm: int, s: float):
    wx, wy = ext[cand]
    return (s * wx, s * wy) if perm == 0 else (s * wy, s * wx)   # perm 0: первое число подписи — по горизонтали


def _err(o: dict, s: float, cand: str, perm: int):
    pa, pb = _pred(o['ext'], cand, perm, s)
    a, b = o['dims']
    return max(abs(pa - a), abs(pb - b)), (pa, pb)


def _tol(dims, tol_abs, tol_rel):
    return max(tol_abs, tol_rel * max(dims))


def fit_scale(obs: list[dict], tol_abs: float = 0.12, tol_rel: float = 0.04, cands=CANDS) -> dict | None:
    """obs: [{'id', 'dims': (a, b) м, 'ext': room_extents(...)}] → масштаб м/px RANSAC (гипотеза — одна сторона одной
    комнаты; инлаер — комната, у которой какой-то кандидат и перестановка дают обе стороны в допуске); итог — медиана
    отношений по инлаерам (их выбранные кандидат/перестановка). Также sx/sy — отдельно по горизонтали/вертикали."""
    if not obs:
        return None
    hyps = set()
    for o in obs:
        for c in cands:
            wx, wy = o['ext'][c]
            for v in o['dims']:
                for w in (wx, wy):
                    if w > 0:
                        hyps.add(v / w)
    best = None
    for s in sorted(hyps):
        inl = []
        for o in obs:
            tol = _tol(o['dims'], tol_abs, tol_rel)
            opts = [(_err(o, s, c, p)[0], ci, p, c) for ci, c in enumerate(cands) for p in (0, 1)]
            e, _, p, c = min(opts)
            if e <= tol:
                inl.append((o, c, p, e))
        score = (len(inl), -sum(x[3] for x in inl))
        if best is None or score > best[0]:
            best = (score, s, inl)
    _, s0, inl = best
    if not inl:
        return None
    rx, ry = [], []
    for o, c, p, _ in inl:
        wx, wy = o['ext'][c]
        a, b = o['dims']
        if p == 0:
            rx.append(a / wx); ry.append(b / wy)
        else:
            rx.append(b / wx); ry.append(a / wy)
    s = float(np.median(rx + ry))
    return {'s': s, 's0': s0, 'sx': float(np.median(rx)), 'sy': float(np.median(ry)),
            'inliers': [(o['id'], c, p) for o, c, p, _ in inl], 'n': len(obs)}


def convention(fit: dict) -> tuple[str, int, float]:
    """Принятая на панели манера подписи: самый частый (кандидат, перестановка) среди инлаеров и его доля."""
    from collections import Counter
    cnt = Counter((c, p) for _, c, p in fit['inliers'])
    (c, p), n = cnt.most_common(1)[0]
    return c, p, n / max(1, len(fit['inliers']))


def leave_one_out(obs: list[dict], **kw) -> list[dict]:
    """Каждую комнату с подписью убираем из калибровки, масштаб и манеру — по остальным, затем предсказываем её
    стороны (кандидат и перестановка — манера остальных, НЕ подгонка под ответ)."""
    res = []
    for i, o in enumerate(obs):
        rest = obs[:i] + obs[i + 1:]
        f = fit_scale(rest, **kw)
        if f is None or len(rest) < 2:
            res.append({'id': o['id'], 'ok': False, 'why': 'мало комнат для калибровки'})
            continue
        c, p, share = convention(f)
        _, (pa, pb) = _err(o, f['s'], c, p)
        a, b = o['dims']
        res.append({'id': o['id'], 'ok': True, 's': f['s'], 'cand': c, 'perm': p, 'share': share,
                    'pred': (round(pa, 3), round(pb, 3)), 'gold': (a, b),
                    'err': (round(abs(pa - a), 3), round(abs(pb - b), 3)),
                    'rel': (abs(pa - a) / a, abs(pb - b) / b)})
    return res


def loo_summary(rows: list[dict]) -> dict:
    e = [x for r in rows if r.get('ok') for x in r['err']]
    rel = [x for r in rows if r.get('ok') for x in r['rel']]
    if not e:
        return {'n_dims': 0}
    return {'n_dims': len(e), 'mae': float(np.mean(e)), 'p95': float(np.percentile(e, 95)), 'max': float(max(e)),
            'mean_rel': float(np.mean(rel))}


# --- подписи: метры ↔ футы ------------------------------------------------------------------------------------------------

def feet_to_m(s: str) -> float:
    """«13'6"» → метры."""
    s = s.replace('’', "'").replace('”', '"').replace('″', '"').replace('′', "'").strip()
    ft, _, rest = s.partition("'")
    inch = rest.replace('"', '').strip() or '0'
    return (int(ft) * 12 + float(inch)) * 0.0254


def check_feet(dims_m, dims_ft, tol_in: float = 2.0) -> list[float]:
    """Расхождение метров и футов подписи, дюймы (UK-листы округляют дюймы вниз — допуск 2")."""
    return [round((m - feet_to_m(f)) / 0.0254, 2) for m, f in zip(dims_m, dims_ft)]


# --- выпрямление контуров -------------------------------------------------------------------------------------------------

def _line_isect(p1, d1, p2, d2):
    A = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]], float)
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t = np.linalg.solve(A, np.array(p2, float) - np.array(p1, float))
    return np.array(p1, float) + t[0] * np.array(d1, float)


def regularize_contour(cnt: np.ndarray, fams: list[float], tol_deg: float = 3.0, eps: float = 1.2,
                       max_shift: float = 4.0):
    """Контур (N×2, px) → выпрямленный многоугольник + рёбра для метрики углов.
    Ребро approxPolyDP → прямая МНК по исходным пикселям участка; если её угол в tol_deg от семейства — поворот
    к семейству вокруг центра участка; соседние коллинеарные — слияние; вершины — пересечения соседних прямых."""
    c = cnt.reshape(-1, 2)
    if len(c) < 4:
        return c.astype(float), []
    ap = cv2.approxPolyDP(c.reshape(-1, 1, 2), eps, True).reshape(-1, 2)
    if len(ap) < 3:
        return c.astype(float), []
    idx_of = {}
    for i, p in enumerate(c):
        idx_of.setdefault((int(p[0]), int(p[1])), i)
    idx = [idx_of[(int(p[0]), int(p[1]))] for p in ap]
    n = len(c)
    segs = []
    for k in range(len(idx)):
        i0, i1 = idx[k], idx[(k + 1) % len(idx)]
        span = c[i0:i1 + 1] if i1 >= i0 else np.vstack([c[i0:], c[:i1 + 1]])
        if len(span) < 2:
            continue
        pts = span.astype(np.float32)
        L = float(np.hypot(*(span[-1] - span[0])))
        if len(pts) >= 3 and L >= 3:
            vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        else:
            d = span[-1] - span[0]
            nrm = math.hypot(*d) or 1
            vx, vy = d / nrm
            x0, y0 = span.mean(axis=0)
        raw = math.degrees(math.atan2(vy, vx)) % 180
        fam = min(fams, key=lambda f: angdiff(f, raw)) if fams else raw
        ang = fam if angdiff(fam, raw) <= tol_deg else raw
        segs.append({'p': (float(x0), float(y0)), 'ang': ang, 'raw': raw, 'len': L, 'a': span[0], 'b': span[-1]})
    # слияние соседних коллинеарных
    merged = []
    for s in segs:
        if merged:
            m = merged[-1]
            if angdiff(m['ang'], s['ang']) < 0.5:
                d = (math.cos(math.radians(m['ang'])), math.sin(math.radians(m['ang'])))
                off = abs((s['p'][0] - m['p'][0]) * d[1] - (s['p'][1] - m['p'][1]) * d[0])
                if off < 1.5:
                    w1, w2 = m['len'], s['len']
                    m['p'] = ((m['p'][0] * w1 + s['p'][0] * w2) / (w1 + w2 or 1), (m['p'][1] * w1 + s['p'][1] * w2) / (w1 + w2 or 1))
                    m['b'] = s['b']
                    m['len'] = float(np.hypot(*(m['b'] - m['a'])))
                    continue
        merged.append(dict(s))
    if len(merged) < 3:
        return ap.astype(float), segs
    verts = []
    for k in range(len(merged)):
        s1, s2 = merged[k - 1], merged[k]
        d1 = (math.cos(math.radians(s1['ang'])), math.sin(math.radians(s1['ang'])))
        d2 = (math.cos(math.radians(s2['ang'])), math.sin(math.radians(s2['ang'])))
        q = _line_isect(s1['p'], d1, s2['p'], d2) if angdiff(s1['ang'], s2['ang']) > 10 else None
        orig = s2['a'].astype(float)
        if q is None or np.hypot(*(q - orig)) > max_shift:
            # почти параллельны или далеко — проекция исходной вершины на прямую s2
            p = np.array(s2['p']); dd = np.array(d2)
            q = p + dd * float(np.dot(orig - p, dd))
            if np.hypot(*(q - orig)) > max_shift:
                q = orig
        verts.append(q)
    return np.array(verts), merged


def mask_polygons(mask: np.ndarray, fams: list[float], min_area: float = 8.0, **kw):
    """Маска → список (внешний контур, [дыры]) выпрямленных многоугольников, px; плюс все рёбра (для метрики углов)."""
    cnts, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys, edges = [], []
    if hier is None:
        return polys, edges
    hier = hier[0]
    for i, c in enumerate(cnts):
        if hier[i][3] != -1 or cv2.contourArea(c) < min_area:
            continue
        outer, e = regularize_contour(c, fams, **kw)
        edges += e
        holes = []
        j = hier[i][2]
        while j != -1:
            if cv2.contourArea(cnts[j]) >= min_area:
                h, e2 = regularize_contour(cnts[j], fams, **kw)
                holes.append(h)
                edges += e2
            j = hier[j][0]
        polys.append((outer, holes))
    return polys, edges
