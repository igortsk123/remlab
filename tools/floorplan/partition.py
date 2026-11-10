"""Обрыв нарисованной перегородки (T-20261109-38): две комнаты слиты в одну область через белый зазор у конца стены.

Схема — советник `.memory_bank/_intake/codex/false-doors-merged-rooms-2026-11-09-answer.md`: подписи двух РАЗНЫХ
самостоятельных комнат в одной области — только повод искать стену. Режем, лишь когда:
  * внутри области есть сырая нарисованная линия-перегородка (тёмное на листе И наша стена; область — по обе её стороны),
    одним концом прикреплённая к другой стене, а другим висящая в области;
  * от висящего конца вдоль её оси до стены/закрытия проёма — короткий зазор: ≤ GAP_T толщин И уже прохода
    (< fpcore.DOOR_MIN_M по масштабу панели — норма T-36). Только толщины мало: при толстом рисунке стены (25 см)
    дверной проём между двумя косяками — те же «3 толщины» (слепой G, гараж/мастерская, 0,89 м);
  * линией подтверждено ≥ SUPPORT_MIN всей перегородки (линия + зазор);
  * продолжение по зазору делит область ровно на две связные части достаточного размера, подписи A и B — в разных
    (если части сообщаются ещё где-то — область не делится, разреза нет).
Пороги — в пикселях от толщины стены; метры — только диагностика (масштаб без подписей размеров угадан по толщине).
Направления — оси и диагональные семейства стен панели (поворот окна)."""
from __future__ import annotations

import math

import cv2
import numpy as np

GAP_T = 4.0             # зазор ≤ 4 толщин стены
SUPPORT_MIN = 0.75      # линией подтверждено ≥ 75 % перегородки (линия + зазор)
STUB_W_T = 2.5          # перегородка — линия: её ширина ≤ 2,5 толщин
STUB_MIN_T = 3.0        # и длина ≥ 3 толщин (точка/торец — не линия)
PART_REL, PART_T = 0.15, 8.0   # каждая часть ≥ 15 % области и ≥ квадрата 8 толщин
CRUMB_T2 = 4.0          # обрезки без подписи < 4·t² (между полосой и стеной) — к части A


def _rot(mask: np.ndarray, a: float):
    """Поворот маски на a° (против часовой на экране) на расширенном холсте → (маска, обратная матрица, исходный размер)."""
    h, w = mask.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(math.ceil(h * sin + w * cos)) + 2, int(math.ceil(h * cos + w * sin)) + 2
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    r = cv2.warpAffine(mask.astype(np.uint8), M, (nw, nh), flags=cv2.INTER_NEAREST, borderValue=0) > 0
    return r, cv2.invertAffineTransform(M), (h, w)


def _unrot(mask: np.ndarray, Minv, hw) -> np.ndarray:
    h, w = hw
    return cv2.warpAffine(mask.astype(np.uint8), Minv, (w, h), flags=cv2.INTER_NEAREST, borderValue=0) > 0


def vertical_stubs(R: np.ndarray, raw: np.ndarray, wall: np.ndarray, t: float, why: list, close=None,
                   gap_max_px: float | None = None):
    """Вертикальные перегородки внутри области R с висящим концом → [(полоса-продолжение, сведения)].
    close — закрытия проёмов: если зазор упёрся в закрытие (дверной проём, общий на две комнаты), продолжение идёт и
    сквозь него (≤ 2 толщин) — проём делится стеной на два. gap_max_px — физический потолок зазора (уже прохода),
    действует вместе с порогом в толщинах: толстый рисунок стены (t ≈ 25 см) делает дверной проём «3 толщинами»."""
    H, W = R.shape
    k = int(math.ceil(STUB_W_T * t))
    left = np.zeros_like(R)
    right = np.zeros_like(R)
    for j in range(1, k + 1):
        left[:, j:] |= R[:, :-j]
        right[:, :-j] |= R[:, j:]
    part = raw & left & right & ~R
    n, cl, stt, _ = cv2.connectedComponentsWithStats(part.astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h = stt[i, :4]
        if h < STUB_MIN_T * t:
            continue
        ys, xs = np.nonzero(cl[y:y + h, x:x + w] == i)
        t_loc = float(np.median(np.bincount(ys)[np.bincount(ys) > 0]))
        if t_loc > STUB_W_T * t:
            continue
        xc = x + float(np.median(xs))
        b0 = max(0, int(math.floor(xc - t_loc / 2 + 0.5)))
        b1 = min(W, b0 + max(1, int(round(t_loc))))
        tt = max(t, t_loc)
        ends = []
        for end, d in ((y, -1), (y + h - 1, 1)):
            gap, s = None, 1
            while True:
                yy = end + d * s
                if not (0 <= yy < H):
                    break
                if wall[yy, b0:b1].mean() >= 0.5:
                    gap = s - 1
                    break
                if R[yy, b0:b1].mean() < 0.5:
                    break                                    # вышли из области не в стену (наружа/другая комната)
                if s - 1 > GAP_T * tt:
                    break
                s += 1
            ends.append((end, d, gap, s - 1))
        # один конец прикреплён (стена сразу за ним), другой висит в области с коротким зазором
        att = [e for e in ends if e[2] is not None and e[2] <= 2]
        hang = [e for e in ends if e[2] is not None and e[2] > 2]
        if len(att) != 1:
            if not hang and any(e[2] is None and e[3] > GAP_T * tt for e in ends):
                why.append(f'зазор у конца линии > {GAP_T:g} толщин')
            elif len(att) == 0:
                why.append('линия не прикреплена к стене (висит с обоих концов)')
            continue
        if not hang:
            far = [e for e in ends if e not in att][0]
            why.append(f'зазор у конца линии > {GAP_T:g} толщин' if far[2] is None and far[3] > GAP_T * tt
                       else 'конец линии не упирается в стену')
            continue
        end, d, gap, _ = hang[0]
        if gap_max_px is not None and gap >= gap_max_px:
            why.append(f'зазор {gap} px не уже прохода ({gap_max_px:.0f} px) — это проём, не обрыв рисунка')
            continue
        # подтверждённая длина: сырая линия от висящего конца назад (до стены, к которой она прикреплена, включительно)
        Ls, miss, yy = 0, 0, end
        xi = int(round(xc))
        while 0 <= yy < H:
            if raw[yy, max(0, xi - 1):xi + 2].any():
                Ls, miss = abs(yy - end) + 1, 0
            else:
                miss += 1
                if miss > 2:
                    break
            yy -= d
        support = Ls / (Ls + gap)
        info = {'gap_px': int(gap), 'stub_px': int(Ls), 't_loc_px': round(t_loc, 1), 'support': round(float(support), 2)}
        if support < SUPPORT_MIN:
            why.append(f'перегородка подтверждена на {support:.0%} (< {SUPPORT_MIN:.0%})')
            continue
        ext = np.zeros_like(R)
        if gap:
            ya, yb = sorted((end + d, end + d * gap))
            ext[ya:yb + 1, b0:b1] = True
        ext &= R
        if close is not None:                                # сквозь закрытие проёма, в которое упёрся зазор
            nc, yy = 0, end + d * (gap + 1)
            while 0 <= yy < H and close[yy, b0:b1].mean() >= 0.5 and nc <= 2 * tt:
                nc, yy = nc + 1, yy + d
            if 0 < nc <= 2 * tt:
                ya, yb = sorted((end + d * (gap + 1), end + d * (gap + nc)))
                ext[ya:yb + 1, b0:b1] |= close[ya:yb + 1, b0:b1]
                info['close_px'] = int(nc)
        out.append((ext, info))
    return out


def _comp_at(cl: np.ndarray, pt, r: int) -> int:
    x, y = int(round(pt[0])), int(round(pt[1]))
    H, W = cl.shape
    y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
    win = cl[y0:y1, x0:x1]
    yy, xx = np.nonzero(win > 0)
    if not len(yy):
        return 0
    k = int(np.argmin((yy + y0 - y) ** 2 + (xx + x0 - x) ** 2))
    return int(win[yy[k], xx[k]])


def find_partition(R: np.ndarray, raw: np.ndarray, wall: np.ndarray, t: float, angles, pa: list, pb: list,
                   close=None, gap_max_px: float | None = None):
    """R — область (окно), raw — сырая нарисованная стена, wall — вся стена (с закрытиями проёмов), t — толщина стены,
    angles — повороты (0 + диагональные семейства), pa/pb — точки подписей комнат A и B (в координатах окна),
    close — закрытия проёмов (часть wall; продолжение идёт сквозь них — см. vertical_stubs), gap_max_px — зазор не
    уже прохода (норма двери в px) — проём, не обрыв.
    → (стена-продолжение, маска части B, сведения) или (None, None, {'why': причина})."""
    why: list = []          # отказы по геометрии линии
    why_c: list = []        # отказы найденной перегородки (важнее: линия есть, но разрез не годится)
    t = max(2.0, float(t))
    best = None
    area = int(R.sum())
    r_lab = max(6, int(2 * t))
    for a in angles:
        if abs(a) > 0.5:
            Rr, Minv, hw = _rot(R, a)
            rawr, wallr = _rot(raw, a)[0], _rot(wall, a)[0]
            closer = _rot(close, a)[0] if close is not None else None
        else:
            Rr, rawr, wallr, closer, Minv, hw = R, raw, wall, close, None, None
        for tr in (False, True):                      # вертикальные, затем горизонтальные (транспонированием)
            Rw, raww, wallw = (Rr.T, rawr.T, wallr.T) if tr else (Rr, rawr, wallr)
            closew = None if closer is None else (closer.T if tr else closer)
            for ext_w, info in vertical_stubs(Rw, raww, wallw, t, why, closew, gap_max_px):
                ext = ext_w.T if tr else ext_w
                if Minv is not None:
                    ext = _unrot(ext, Minv, hw)
                ext &= R | (close if close is not None else False)
                n, cl, stt, _ = cv2.connectedComponentsWithStats((R & ~ext).astype(np.uint8), connectivity=4)
                ca = {_comp_at(cl, p, r_lab) for p in pa}
                cb = {_comp_at(cl, p, r_lab) for p in pb}
                if len(ca) != 1 or len(cb) != 1 or 0 in ca | cb or ca == cb:
                    why_c.append('продолжение не развело подписи по двум частям')
                    continue
                A, B = ca.pop(), cb.pop()
                rest = [j for j in range(1, n) if j not in (A, B)]
                if any(stt[j, cv2.CC_STAT_AREA] >= CRUMB_T2 * t * t for j in rest):
                    why_c.append('после продолжения — лишняя часть без подписи')
                    continue
                amin = min(int(stt[A, cv2.CC_STAT_AREA]), int(stt[B, cv2.CC_STAT_AREA]))
                info = dict(info, angle=round(float(a), 1), axis='h' if tr else 'v', part_rel=round(amin / area, 2))
                if amin < PART_REL * area or amin < (PART_T * t) ** 2:
                    why_c.append('часть после разреза мала')
                    continue
                if best is None or info['gap_px'] < best[2]['gap_px']:
                    best = (ext, cl == B, info)
    if best is None:
        w = why_c or why
        return None, None, {'why': w[-1] if w else 'нет висящей перегородки в области'}
    return best
