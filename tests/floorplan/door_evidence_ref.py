"""Эталон: door_evidence до векторизации (T-20261126-169/2, копия fpcore.py main 27e1714a4). Только для побайтной сверки в tests/floorplan/test_door_evidence_fast.py; не менять."""
from __future__ import annotations

import cv2
import numpy as np

from fpcore import *  # noqa: F401,F403
from fpcore import (_tangent_evidence, _evidence_px, arc_pure, FLOOR_HATCH, PURE_MIN_PX, LEAF_PURE, LEAF_WALL, HALF_ARC_MIN, HALF_ANGLES, LEAF_MIN, LEAF_ARC_MIN, LEAF_SCORE)  # noqa: F401


def door_evidence_ref(thin: np.ndarray, c, u, n, L: float, depth: float, step_deg: int = 5, tangent_only: bool = False,
                  want_px: bool = False, wall: np.ndarray | None = None, pure_check: bool = True, want_how: bool = False):
    """Есть ли у разрыва дуга двери: доля углов 0–90°, где на радиусе створки от петли (конец разрыва, грань стены)
    лежит тонкая линия. Створка одна (радиус L) или две (по L/2 от каждого конца, обе дуги). → лучшая доля 0..1.
    `tangent_only` — только «вогнутая» дуга створки, нарисованной закрытой в линии стены (T-20261110-11): касается грани
    у торца, центр в комнате на глубине R; её первые ~35° (у самой грани, где лежат линии рамы окна) не считаются.
    `want_px` → (доля, пиксели рисунка `_evidence_px`) — для «одна дуга — одна дверь» (T-20261111-11).
    `wall` (маска стен) — створка вплотную к грани стены (ближе LEAF_WALL·R) не засчитывается: это обвод стены или
    тетива лестницы у неё, а «разрыв» упирается в стену поперёк (T-20261111-11, bs30: площадка у санузла, верх лестницы).
    `pure_check=False` — прежнее правило без «чистоты» (запасная дверь комнаты без дверей, `bench.doorless_doors`, T-11/3).
    `want_how` → (доля, рисунок лучшего: 'arc' | 'double' | 'leaf' | None) — число створок наружной двери (T-20261112-48);
    'double' — только при проверке «чистоты» (на заштрихованном полу и при `pure_check=False` — None)."""
    if tangent_only:
        v = _tangent_evidence(thin, c, u, n, L, depth, step_deg)
        return (v, frozenset()) if want_px else v
    H, W = thin.shape
    th = np.radians(np.arange(0, 91, step_deg))
    c = np.asarray(c, float)
    # T-20261111-11: один вырез вокруг разрыва, расширенный на окно 5×5 (точка «у линии» — линия в её окне; за краем листа
    # пусто) — как у `_tangent_evidence`; точки дальше выреза — за краем листа
    m = int(2.5 * L + depth) + 8
    cx, cy = int(round(float(c[0]))), int(round(float(c[1])))
    ox, oy = max(0, cx - m), max(0, cy - m)
    crop = np.pad((thin[oy:min(H, cy + m + 1), ox:min(W, cx + m + 1)] > 0).astype(np.uint8), 2)
    dil = cv2.dilate(crop, np.ones((5, 5), np.uint8)) > 0
    hh, ww = dil.shape
    pure = arc_pure() if pure_check else None
    wcrop = None
    if wall is not None and pure:
        wcrop = np.pad(wall[oy:min(H, cy + m + 1), ox:min(W, cx + m + 1)] > 0, 2)
    # T-11/2: пол заштрихован целиком (паркет «ёлочкой», лист aOv8kT: пунктирная дуга тонет в штриховке) — линии на 0,8R/1,2R
    # и по бокам створки есть везде, «чистота» гасит любую дверь: прежнее правило. Ступени и надписи (bs30) — пятно, не весь пол
    if pure and (dil[~wcrop] if wcrop is not None else dil).mean() >= FLOOR_HATCH:
        pure, wcrop = None, None

    def on(P, src=None):
        src = dil if src is None else src
        xi = np.rint(P[..., 0]).astype(int) - ox + 2
        yi = np.rint(P[..., 1]).astype(int) - oy + 2
        ok = (xi >= 0) & (xi < ww) & (yi >= 0) & (yi < hh)
        r = np.zeros(xi.shape, bool)
        r[ok] = src[yi[ok], xi[ok]]
        return r

    def arc_pts(h, d, s, R):
        return h[None, :] + R * (np.cos(th)[:, None] * d[None, :] + np.sin(th)[:, None] * s[None, :])

    def cov_mask(h, d, s, R):
        """Засчитанные точки дуги. T-20261111-11: «чистая дуга» — на том же луче от петли на 0,8R и 1,2R линий нет вместе
        (`ARC_PURE`): текст подписи и ступени лестницы — сплошная штриховка, задевают все три радиуса (bs30: «двери» площадки
        по надписи Landing и по ступеням)."""
        hit = on(arc_pts(h, d, s, R))
        if pure:
            # у малой дуги (дверца 0,4 м, R ~ 15 px) 0,2R внутри окна 5×5 самой линии — сдвиг не меньше PURE_MIN_PX
            k = max(PURE_MIN_PX, (1 - pure[0]) * R)
            hit &= ~(on(arc_pts(h, d, s, R - k)) & on(arc_pts(h, d, s, R + k)))
        return hit

    def cov(h, d, s, R):
        return float(cov_mask(h, d, s, R).mean())

    def leaf_pts(h, s, R):
        return h[None, :] + s[None, :] * np.linspace(0.15 * R, 0.95 * R, 12)[:, None]

    def leaf_mask(h, s, R, w):
        """Засчитанные точки створки. T-20261111-11: «чистая» — сбоку (вдоль стены, ±LEAF_PURE·R) линий нет вместе: текст и
        ступени лестницы — сплошные, их «створка» задевает обе стороны."""
        Q = leaf_pts(h, s, R)
        hit = on(Q)
        if pure:
            k = max(PURE_MIN_PX, LEAF_PURE * R)
            hit &= ~(on(Q + w[None, :] * k) & on(Q - w[None, :] * k))
        if wcrop is not None:
            for t in (0.5, 1.0):
                for sg in (1, -1):
                    hit &= ~on(Q + sg * t * LEAF_WALL * R * w[None, :], wcrop)
        return hit

    def leaf(h, s, R, w):
        """Створка: прямая тонкая линия от петли поперёк стены длиной ~R (доля покрытых точек)."""
        return float(leaf_mask(h, s, R, w).mean())

    best, how = 0.0, None
    for s in (n, -n):
        face = c + s * depth / 2
        for j in (0.0, 0.1, 0.2, 0.3):               # петля чуть внутри разрыва (торец рисуют с наличником)
            e1, e2 = face - u * L * (0.5 - j), face + u * L * (0.5 - j)
            for f in np.arange(0.5, 1.06, 0.05):
                R = f * L
                m1, m2 = cov_mask(e1, u, s, R), cov_mask(e2, -u, s, R)
                a1, a2 = float(m1.mean()), float(m2.mean())
                d1, d2 = cov(e1, u, s, R / 2), cov(e2, -u, s, R / 2)
                for v, w in ((a1, ('arc', e1, u, s, R)), (a2, ('arc', e2, -u, s, R)),
                             (min(d1, d2), ('double', e1, e2, u, s, R / 2))):
                    if v > best:
                        best, how = v, w
                # второй признак: створка у петли + дуга хотя бы частично (её конец бывает срезан стеной)
                if best < LEAF_SCORE:
                    for a, e, d in ((a1, e1, u), (a2, e2, -u)):
                        if a >= LEAF_ARC_MIN and leaf(e, s, R, u) >= LEAF_MIN:
                            best, how = LEAF_SCORE, ('leaf', e, d, s, R, s, u)
                # T-20261111-11: створка приоткрыта (дверцы шкафов, bs30: шкаф у площадки — на ~37°) — дуга 0–φ почти целиком
                # и прямая створка под углом φ (HALF_ANGLES)
                if best < LEAF_SCORE and pure:
                    for m_, e, d in ((m1, e1, u), (m2, e2, -u)):
                        for phi in HALF_ANGLES:
                            k = phi // step_deg + 1
                            if k > len(m_) or m_[:k].mean() < HALF_ARC_MIN:
                                continue
                            a_ = np.radians(phi)
                            q = np.cos(a_) * d + np.sin(a_) * s
                            wq = np.sin(a_) * d - np.cos(a_) * s
                            if leaf(e, q, R, wq) >= LEAF_MIN:
                                best, how = LEAF_SCORE, ('leaf', e, d, s, R, q, wq)
                                break
    if want_px:
        return best, _evidence_px(thin, how, cov_mask, arc_pts, leaf_mask, leaf_pts)
    if want_how:
        kind = how[0] if how else None
        if kind == 'double' and not pure:
            # пол заштрихован (паркет «ёлочкой», aOv8 вход: одна створка наружу) — без «чистоты» пару малых дуг даёт сама
            # штриховка (1,0 у любой пары): число створок по ней не читаем
            kind = None
        return best, kind
    return best
