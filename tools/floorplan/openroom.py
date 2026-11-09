"""Открытые комнаты (T-20261109-16; план floorplan-raster-bench-01 § Этап 5): подпись с размером не попала ни в одну
комнату, потому что стена вокруг неё не сплошная — проём без двери, двустворчатые/складные двери, арка, открытая
планировка, открытая сторона навеса. Гипотезы замыкания контура вокруг подписи (общие правила, без настройки под лист):

  lines — «линии и продолжение стен»: граница — стены + любые видимые линии окна (рама, складные двери, остекление)
          + край заливки пола (пол залит цветом, лист белый); оставшиеся разрывы — продолжением стены вдоль её оси
          (`fpcore.bridge_parts`) с растущим пределом 0 → 1,0 → 1,8 → 3,0 м; берётся первый предел, при котором
          область подписи замкнулась, в ней одна подпись с размером и площадь в [OPEN_MIN; 1 + OPEN_TOL] от подписи.
  box   — «рамка по мерке подписи»: прямоугольник a×b подписи (масштаб панели), положение — где его стороны больше
          всего лежат на стенах/линиях/краю заливки и внутри нет стен и чужих комнат; стороны уточняются по ближней
          линии; комната — свободное внутри рамки, связное с подписью. Неподдержанная сторона — виртуальная граница.

Протечка в соседнюю комнату невозможна по построению (чужие комнаты — граница), в соседнюю открытую — ловит проверка
площади против подписи и «в области одна подпись с размером». Граница, проведённая не по стене, — виртуальная
(`State.cut`): в 3D стены там нет, пол есть. Приёмку делает круг починки (`repair.accept`).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

import fpcore as fc

OPEN_TOL = 0.15          # площадь области не больше подписи +15 % (иначе — протечка)
OPEN_MIN = 0.55          # и не меньше 55 % (Г-комната «max» меньше прямоугольника подписи; меньше — отрезано мебелью)
FAINT_DELTA = 40         # видимая линия: темнее фона окна на 40 (рама, складные двери, остекление, мебель)
LMAX_M = (0.0, 1.0, 1.8, 3.0)   # продолжение стены вдоль оси: до двери → двустворчатой → арки/открытой планировки
FLANK_M = 0.5            # продолжается стена от 0,5 м (не торец мебели)
SEED_M = 0.6             # область подписи — та, что занимает больше всего круга 0,6 м вокруг точки (текст — не она)
TINT_MIN = 8             # пол «залит», если темнее листа на 8+ уровней серого
POCKET_SHARE = 0.25      # карман за линией мебели (столешница, ванна) — часть комнаты, если он меньше 25 % подписи
BOX_SUPPORT = 0.5        # рамка: доля периметра на стенах/линиях не меньше 0,5
BOX_EDGE_OK = 0.6        # и хотя бы две стороны поддержаны на 0,6+
BOX_INTERIOR = 0.03      # внутри рамки стен и чужих комнат не больше 3 %
BOX_INTERIOR_MAX = 0.06  # у мерки «max»/«into bay» — до 6 %: это габарит, а в комнате бывают выступы стен, ниша, камин
BOX_OUTSIDE = 0.15      # за оболочкой здания — не больше 15 % рамки (углы мимо эркера у мерки «max»; пол по оболочке обрезается)
ATTACH_M = 0.3           # линия «связана со стеной», если подходит к ней ближе 0,3 м (эркер, рама; не остров, не текст)


def faint_lines(gray: np.ndarray, wall: np.ndarray, delta: int = FAINT_DELTA) -> np.ndarray:
    """Любая видимая линия окна (темнее фона окна на delta), кроме стен."""
    bg = float(np.percentile(gray, 75))
    return (gray < bg - delta) & ~(wall > 0)


def attached_lines(faint: np.ndarray, wall: np.ndarray, gap: int = 3) -> np.ndarray:
    """Линии, связанные со стенами (рама, складные двери, остекление, эркер): отдельно стоящие — текст подписи,
    остров кухни, стол, кровать, пунктир фонаря — границей комнаты не бывают. Связность — по линиям с зазором 1 px
    (светлая сглаженная дуга эркера рвётся на куски)."""
    f8 = faint.astype(np.uint8)
    n, lab = cv2.connectedComponents(cv2.dilate(f8, np.ones((3, 3), np.uint8)), connectivity=8)
    if n <= 1:
        return faint.copy()
    near = cv2.dilate((wall > 0).astype(np.uint8), np.ones((2 * gap + 1, 2 * gap + 1), np.uint8)) > 0
    keep = np.zeros(n, bool)
    keep[np.unique(lab[near & faint])] = True
    keep[0] = False
    return keep[lab] & faint


def hull_mask(final: np.ndarray, gray: np.ndarray | None = None, ppm: float = 10.0) -> np.ndarray | None:
    """Выпуклая оболочка стен панели (и линий, связанных со стенами: эркер, остекление — gray): комната здания за неё
    не выходит (открытая сторона — по краю здания)."""
    m0 = final > 0
    if gray is not None:
        m0 = m0 | attached_lines(faint_lines(gray, m0), m0, max(3, int(round(ATTACH_M * ppm))))
    ys, xs = np.nonzero(m0)
    if len(xs) < 3:
        return None
    hull = cv2.convexHull(np.column_stack([xs, ys]).astype(np.int32))
    m = np.zeros(final.shape, np.uint8)
    cv2.fillConvexPoly(m, hull, 1)
    return m > 0


def tint_barrier(gray: np.ndarray, pt, r: int, bg_sheet: float, min_tint: float = TINT_MIN, tol: float = 3.0,
                 floor: float | None = None):
    """Пол залит цветом (F: ~218 на листе 255) → «цвет листа» вокруг — граница комнаты и без линии (открытая сторона
    навеса); пол не залит (E) → None. Заливка — медиана светлого (не текст) в круге r вокруг подписи; floor — медиана
    найденных комнат панели: если и она не темнее листа, заливки нет (серый водяной знак или сглаженный текст у подписи
    заливкой не считаются)."""
    if floor is not None and bg_sheet - floor < min_tint:
        return None
    H, W = gray.shape
    disk = np.zeros((H, W), np.uint8)
    cv2.circle(disk, (int(round(pt[0])), int(round(pt[1]))), max(2, r), 1, -1)
    v = gray[(disk > 0) & (gray > bg_sheet - 60)]
    if v.size < 10:
        return None
    if bg_sheet - float(np.median(v)) < min_tint:
        return None
    return gray >= bg_sheet - tol


def seed_component(free: np.ndarray, pt, r: int):
    """Связная (4) область свободного, занимающая больше всего круга r вокруг подписи → маска или None."""
    n, lab = cv2.connectedComponents(free.astype(np.uint8), connectivity=4)
    H, W = free.shape
    disk = np.zeros((H, W), np.uint8)
    cv2.circle(disk, (int(round(pt[0])), int(round(pt[1]))), max(2, r), 1, -1)
    v = lab[(disk > 0) & (free > 0)]
    v = v[v > 0]
    if v.size == 0:
        return None, lab
    ids, cnt = np.unique(v, return_counts=True)
    return lab == ids[int(np.argmax(cnt))], lab


def touches_border(m: np.ndarray) -> bool:
    return bool(m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any())


def fill_holes(m: np.ndarray) -> np.ndarray:
    cnt = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    f = np.zeros(m.shape, np.uint8)
    cv2.drawContours(f, cnt, -1, 1, -1)
    return f > 0


def absorb_pockets(comp: np.ndarray, lab: np.ndarray, free: np.ndarray, max_px: float, forbid_pts) -> np.ndarray:
    """Карманы за тонкой линией внутри комнаты (столешница, ванна, ковёр у стены): свободные области, касающиеся
    только этой комнаты (кольцо 3 px — комната, стены, линии), не у края окна, без подписей, меньше max_px."""
    ring = cv2.dilate(comp.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    out = comp.copy()
    for q in np.unique(lab[ring & free & ~comp]):
        if q == 0:
            continue
        m = lab == q
        if m.sum() > max_px or touches_border(m):
            continue
        if any(m[int(y), int(x)] for x, y in forbid_pts if 0 <= int(y) < m.shape[0] and 0 <= int(x) < m.shape[1]):
            continue
        rq = (cv2.dilate(m.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) & free & ~m
        others = np.unique(lab[rq & ~comp])
        if (others > 0).any():
            continue                                   # касается другой свободной области — не карман
        out |= m
    # линии между комнатой и её карманами — тоже комната (закрытие 3 px внутри свободного от стен)
    return out


def _labels_in(m: np.ndarray, pts) -> list:
    H, W = m.shape
    return [k for k, (x, y) in enumerate(pts) if 0 <= int(y) < H and 0 <= int(x) < W and m[int(y), int(x)]]


def window(pt, dims, ppm, shape, k: float = 0.75, pad_m: float = 1.0):
    H, W = shape
    half = int((k * max(dims) + pad_m) * ppm)
    x, y = int(pt[0]), int(pt[1])
    return (max(0, x - half), max(0, y - half), min(W, x + half + 1), min(H, y + half + 1))


def enclose_lines(final, lab, rooms, gray, pt, dims, ppm, fams, bg_sheet, other_pts, other_areas_px, floor=None,
                  inside=None):
    """Подход «линии и продолжение стен» в окне (координаты окна). → (маска комнаты, сведения) или (None, причина).
    inside — выпуклая оболочка здания (вне её — граница)."""
    Wm = final > 0
    R = np.isin(lab, list(rooms)) if len(rooms) else np.zeros(lab.shape, bool)
    faint = attached_lines(faint_lines(gray, Wm), Wm, max(3, int(round(ATTACH_M * ppm))))
    r = max(4, int(SEED_M * ppm))
    tint = tint_barrier(gray, pt, r, bg_sheet, floor=floor)
    out = ~inside if inside is not None else np.zeros(Wm.shape, bool)
    base = Wm | R | faint | out
    if tint is not None:
        base |= tint
    A = dims[0] * dims[1] * ppm * ppm
    ang = _rot_angles(fams)
    why = 'не замкнулась'
    for L in LMAX_M:
        br = np.zeros(Wm.shape, bool)
        if L > 0:
            for p in fc.bridge_parts(Wm.astype(np.uint8), int(L * ppm), max(3, int(FLANK_M * ppm)), ang):
                br |= p > 0
        B = base | br
        comp, clab = seed_component(~B, pt, r)
        if comp is None:
            why = 'подпись на стене'
            continue
        if touches_border(comp):
            why = f'не замкнулась ({L} м)'
            continue
        inside = _labels_in(comp, other_pts)
        a = float(comp.sum())
        if inside:
            why = f'в области ещё подпись ({L} м)'
            continue
        if a > (1 + OPEN_TOL) * A:
            why = f'велика {a / A:.2f} ({L} м)'
            continue
        # без линий мебели (если так тоже замкнуто, одна подпись и площадь в допуске) — комната целиком
        B2 = Wm | R | br | out | (tint if tint is not None else False)
        comp2, _ = seed_component(~B2, pt, r)
        if comp2 is not None and not touches_border(comp2) and not _labels_in(comp2, other_pts) \
                and comp2.sum() <= (1 + OPEN_TOL) * A and (comp2 & comp).sum() >= 0.9 * comp.sum():
            comp = comp2
        else:
            comp = absorb_pockets(comp, clab, ~B, POCKET_SHARE * A, other_pts)
        comp = fill_holes(comp) & ~Wm & ~R & ~out
        a = float(comp.sum())
        if a < OPEN_MIN * A:
            why = f'мала {a / A:.2f} ({L} м)'
            continue
        if a > (1 + OPEN_TOL) * A:
            why = f'велика {a / A:.2f} ({L} м)'
            continue
        return comp, {'L_m': L, 'tint': tint is not None, 'share': round(a / A, 2)}
    return None, why


def _rot_angles(fams):
    out = [0.0]
    for f in fams or []:
        a = ((f + 45) % 90) - 45
        if abs(a) > 1.5 and all(abs(a - b) > 1.5 for b in out):
            out.append(a)
    return out


def _main_rot(fams) -> float:
    """Поворот окна к осям: семейство панели, ближайшее к 0/90, приведённое к (-45, 45]."""
    if not fams:
        return 0.0
    a = [((f + 45) % 90) - 45 for f in fams]
    return float(min(a, key=abs))


def is_max_note(note) -> bool:
    """Заметка подписи говорит, что размер — наибольший габарит комнаты («max», «into bay»), а не прямоугольник."""
    s = str(note or '').lower()
    return 'max' in s or 'bay' in s


def enclose_box(final, lab, rooms, gray, pt, dims, ppm, fams, bg_sheet, other_pts, t_int, floor=None, inside=None,
                max_extent: bool = False):
    """Подход «рамка по мерке подписи» в окне. → (маска комнаты, сведения) или (None, причина).
    inside — выпуклая оболочка здания: пол за неё не выходит, рамка заходит не больше BOX_OUTSIDE (углы мимо эркера).
    max_extent — мерка «max»/«into bay»: габарит, поэтому внутри рамки допускается больше выступов стен."""
    Wm = final > 0
    R = np.isin(lab, list(rooms)) if len(rooms) else np.zeros(lab.shape, bool)
    out = ~inside if inside is not None else np.zeros(Wm.shape, bool)
    faint = faint_lines(gray, Wm)
    r = max(4, int(SEED_M * ppm))
    tint = tint_barrier(gray, pt, r, bg_sheet, floor=floor)
    sup = Wm | faint
    if tint is not None:
        sup |= tint
    rot = _main_rot(fams)
    shape = Wm.shape
    M = None
    hard = Wm | R
    if abs(rot) > 0.5:
        sup_r, M = fc.rotate_mask(sup.astype(np.uint8), rot)
        hard_r, _ = fc.rotate_mask(hard.astype(np.uint8), rot)
        out_r, _ = fc.rotate_mask(out.astype(np.uint8), rot)
        P = M @ np.array([pt[0], pt[1], 1.0])
        px, py = float(P[0]), float(P[1])
        opts = [tuple(M @ np.array([x, y, 1.0])) for x, y in other_pts]
    else:
        sup_r, hard_r, out_r = sup.astype(np.uint8), hard.astype(np.uint8), out.astype(np.uint8)
        px, py = float(pt[0]), float(pt[1])
        opts = list(other_pts)
    tol = max(2, int(round(t_int)))
    S = (cv2.dilate(sup_r, np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)) > 0).astype(np.int32)
    Hh, Ww = S.shape
    rowc = np.zeros((Hh, Ww + 1), np.int32)
    rowc[:, 1:] = np.cumsum(S, axis=1)
    colc = np.zeros((Hh + 1, Ww), np.int32)
    colc[1:, :] = np.cumsum(S, axis=0)
    ii = np.zeros((Hh + 1, Ww + 1), np.int64)
    ii[1:, 1:] = np.cumsum(np.cumsum(hard_r.astype(np.int64), 0), 1)
    io = np.zeros((Hh + 1, Ww + 1), np.int64)
    io[1:, 1:] = np.cumsum(np.cumsum(out_r.astype(np.int64), 0), 1)
    m = max(2, int(0.2 * ppm))
    best = None
    for (da, db) in ((dims[0], dims[1]), (dims[1], dims[0])):
        w, h = int(round(da * ppm)), int(round(db * ppm))
        if w < 3 or h < 3:
            continue
        x0s = np.arange(max(1, int(px) - w + m), min(Ww - w - 1, int(px) - m) + 1)
        y0s = np.arange(max(1, int(py) - h + m), min(Hh - h - 1, int(py) - m) + 1)
        if not len(x0s) or not len(y0s):
            continue
        X0, Y0 = np.meshgrid(x0s, y0s)
        top = (rowc[Y0 - 1, X0 + w] - rowc[Y0 - 1, X0]) / w
        bot = (rowc[Y0 + h, X0 + w] - rowc[Y0 + h, X0]) / w
        lef = (colc[Y0 + h, X0 - 1] - colc[Y0, X0 - 1]) / h
        rig = (colc[Y0 + h, X0 + w] - colc[Y0, X0 + w]) / h
        sup_v = (w * (top + bot) + h * (lef + rig)) / (2.0 * (w + h))
        a0, b0, a1, b1 = X0 + tol, Y0 + tol, X0 + w - tol, Y0 + h - tol
        cells = max(1, (w - 2 * tol) * (h - 2 * tol))
        inner = (ii[b1, a1] - ii[b0, a1] - ii[b1, a0] + ii[b0, a0]) / cells
        beyond = (io[b1, a1] - io[b0, a1] - io[b1, a0] + io[b0, a0]) / cells
        sc = sup_v - 4.0 * (inner + beyond)
        for (ox, oy) in opts:                           # рамка не накрывает другую подпись с размером
            inside = (X0 + m <= ox) & (ox < X0 + w - m) & (Y0 + m <= oy) & (oy < Y0 + h - m)
            sc = np.where(inside, -9.0, sc)
        k = int(np.argmax(sc))
        j, i = np.unravel_index(k, sc.shape)
        cand = (float(sc[j, i]), int(X0[j, i]), int(Y0[j, i]), w, h, float(sup_v[j, i]), float(inner[j, i]),
                [float(top[j, i]), float(bot[j, i]), float(lef[j, i]), float(rig[j, i])], float(beyond[j, i]))
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return None, 'рамка не помещается'
    _, x0, y0, w, h, sv, inner, edges, beyond = best
    lim_in = BOX_INTERIOR_MAX if max_extent else BOX_INTERIOR
    if sv < BOX_SUPPORT or sum(e >= BOX_EDGE_OK for e in edges) < 2 or inner > lim_in or beyond > BOX_OUTSIDE:
        return None, (f'рамка не легла: опора {sv:.2f}, стороны {[round(e, 2) for e in edges]}, внутри {inner:.3f}, '
                      f'за оболочкой {beyond:.3f}')
    # стороны — к ближней линии (±6 % или 3 px): мерка подписи с допуском манеры
    def refine(pos, length, horiz, lo, sign):
        d = max(3, int(0.06 * length))
        bestp, bv = pos, -1.0
        for p in range(pos - d, pos + d + 1):
            if horiz:
                if not (0 <= p < Hh):
                    continue
                v = (rowc[p, lo + length] - rowc[p, lo]) / length
            else:
                if not (0 <= p < Ww):
                    continue
                v = (colc[lo + length, p] - colc[lo, p]) / length
            if v > bv + 1e-6 or (abs(v - bv) <= 1e-6 and abs(p - pos) < abs(bestp - pos)):
                bestp, bv = p, v
        return bestp
    t_ = refine(y0 - 1, w, True, x0, -1) + 1
    b_ = refine(y0 + h, w, True, x0, +1)
    l_ = refine(x0 - 1, h, False, y0, -1) + 1
    r_ = refine(x0 + w, h, False, y0, +1)
    rect = np.zeros(S.shape, np.uint8)
    if b_ - t_ < 3 or r_ - l_ < 3:
        return None, 'рамка выродилась'
    rect[t_:b_, l_:r_] = 1
    if M is not None:
        rect = fc.unrotate_mask(rect, M, shape) > 0
    else:
        rect = rect > 0
    free = rect & ~Wm & ~R & ~out
    comp, _ = seed_component(free, pt, r)
    if comp is None:
        return None, 'подпись на стене'
    comp = fill_holes(comp) & ~Wm & ~R & ~out & rect
    A = dims[0] * dims[1] * ppm * ppm
    if comp.sum() < OPEN_MIN * A:
        return None, f'мала {comp.sum() / A:.2f}'
    return comp, {'support': round(sv, 2), 'edges': [round(e, 2) for e in edges], 'inner': round(inner, 3),
                  'beyond': round(beyond, 3), 'tint': tint is not None, 'share': round(float(comp.sum()) / A, 2), 'rot': round(rot, 1)}


def virtual_boundary(comp: np.ndarray, final: np.ndarray, t: float) -> np.ndarray:
    """Граница новой комнаты, проведённая не по стене (линия, край заливки, продолжение стены) → маска (виртуальная)."""
    ring = (cv2.dilate(comp.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~comp
    k = max(3, int(t) + 2) | 1
    near_wall = cv2.dilate((final > 0).astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    return ring & ~near_wall & ~(final > 0)
