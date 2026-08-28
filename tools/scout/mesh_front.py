#!/usr/bin/env python3
"""Детерминированный ФРОНТ «сидячих» ролей по геометрии меша (гибрид владельца + Codex q23).

Алгоритм: посадочная поверхность = грани с нормалью вверх на высоте 0.25H–0.65H достаточной
площади; вокруг четырёх направлений ищется «спинка» — масса ВЫШЕ сиденья, прилегающая к его
краю (перекрытие по ширине, близость к кромке, высота). Фронт = противоположно лучшей спинке.
Право честно вернуть ambiguous обязательно: порог отрыва (best−opp)/best ≥ 0.25 — иначе тихий
разворот на 180°. Масса меша — только слабый тай-брейк (подлокотники/юбки её обращают).
Краевые случаи: качалка — всё ниже сиденья исключается; банкетка без спинки —
front_equivalence [0,180]; недостаточно данных — abstain.

Статусы: confident | ambiguous | no_seat. Результат — front_yaw в конвенции MR
(«фронт виден при yaw Yf» ⟺ фронт меша = ry(Yf)·Z; выравнивание в сцене ry(−Yf) —
замер mr-yaw-test 28.08, НЕ выводить на бумаге).
"""
import math
import sys

import numpy as np

FRONT_VERSION = 2
SEAT_ROLES = ('стул', 'кресло', 'диван', 'банкетка', 'кресло-качалка')
# РОЛИ БЕЗ ЯВНОГО ПЕРЕДА (владелец 28.08): у пуфа направления нет вообще, у банкетки перед и
# зад эквивалентны (важна только ось «вдоль») — им фронт не ищем и в фоллбэк не шлём.
NONDIRECTIONAL = {'пуф': [0, 90, 180, 270], 'банкетка': [0, 180], 'кашпо': [0, 90, 180, 270],
                  'торшер': [0, 90, 180, 270]}


def _faces_world(parts):
    """Все грани всех частей: центры, нормали, площади (в нормализованных координатах частей)."""
    C, N, A = [], [], []
    for m in parts:
        v = np.asarray(m.vertices, np.float32)
        f = np.asarray(m.faces, np.int32)
        tri = v[f]
        c = tri.mean(axis=1)
        n = np.asarray(m.face_normals, np.float32)
        a = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        C.append(c)
        N.append(n)
        A.append(a)
    return np.vstack(C), np.vstack(N), np.concatenate(A)


def infer_seat_front(parts, role: str = 'стул', has_back: bool | None = None) -> dict:
    """→ {status, front_yaw, equivalence, seat_h, scores, version}.

    `has_back` — знание вызывающего о ПРИЗНАКЕ спинки (q25: банкетка со спинкой направлена,
    без — нет; решает подтип/название, а не роль целиком). True — искать фронт даже у роли
    из NONDIRECTIONAL; None/False — прежнее правило роли."""
    if role in NONDIRECTIONAL and not has_back:
        return {'status': 'symmetric_by_role', 'front_yaw': 0,
                'front_equivalence': NONDIRECTIONAL[role], 'version': FRONT_VERSION}
    C, N, A = _faces_world(parts)
    y0, y1 = C[:, 1].min(), C[:, 1].max()
    H = max(y1 - y0, 1e-6)
    up = N[:, 1] > 0.9
    band = (C[:, 1] > y0 + 0.22 * H) & (C[:, 1] < y0 + 0.68 * H)
    seat = up & band
    if A[seat].sum() < 0.02 * A.sum():
        return {'status': 'no_seat', 'version': FRONT_VERSION}
    # уровень сиденья — медиана по площади
    order = np.argsort(C[seat][:, 1])
    cum = np.cumsum(A[seat][order])
    seat_h = float(C[seat][order][np.searchsorted(cum, cum[-1] / 2), 1])
    sx0, sx1 = C[seat][:, 0].min(), C[seat][:, 0].max()
    sz0, sz1 = C[seat][:, 2].min(), C[seat][:, 2].max()
    above = C[:, 1] > seat_h + 0.06 * H                     # масса выше сиденья
    scores = {}
    for yaw, (dx, dz, lo, hi, px, pz) in {
        0:   (0, 1,  sz1, None, (sx0, sx1), None),          # спинка у дальнего края +Z → фронт −Z?
        180: (0, -1, None, sz0, (sx0, sx1), None),
        90:  (1, 0,  sx1, None, None, (sz0, sz1)),
        270: (-1, 0, None, sx0, None, (sz0, sz1)),
    }.items():
        m = above.copy()
        if dx == 0:                                          # спинка вдоль оси Z
            edge = sz1 if dz > 0 else sz0
            near = np.abs(C[:, 2] - edge) < 0.18 * max(sz1 - sz0, 1e-6) + 0.05 * H
            width_ok = (C[:, 0] > sx0 - 0.05) & (C[:, 0] < sx1 + 0.05)
            m &= near & width_ok
        else:
            edge = sx1 if dx > 0 else sx0
            near = np.abs(C[:, 0] - edge) < 0.18 * max(sx1 - sx0, 1e-6) + 0.05 * H
            depth_ok = (C[:, 2] > sz0 - 0.05) & (C[:, 2] < sz1 + 0.05)
            m &= near & depth_ok
        h_gain = np.clip((C[:, 1] - seat_h) / H, 0, 1)
        scores[yaw] = float((A[m] * h_gain[m]).sum())
    # спинка у стороны S ⇒ фронт — противоположная сторона. Сторона задаётся направлением
    # НАРУЖУ от сиденья: спинка при яв-стороне «+Z» значит фронт «−Z» = виден при MR yaw 180.
    back_side = max(scores, key=scores.get)
    best = scores[back_side]
    opp = scores[(back_side + 180) % 360]
    others = sorted(scores.values(), reverse=True)
    margin = (best - opp) / max(best, 1e-6)
    front_yaw = (back_side + 180) % 360
    if best <= 0 or margin < 0.25:
        # спинки нет или неотличима: банкетка/пуф → эквивалентность по оси наибольшей ширины
        eq = [0, 180] if (sx1 - sx0) >= (sz1 - sz0) else [90, 270]
        return {'status': 'ambiguous', 'front_equivalence': eq, 'seat_h': round(seat_h, 3),
                'scores': {k: round(v, 4) for k, v in scores.items()},
                'version': FRONT_VERSION}
    return {'status': 'confident', 'front_yaw': front_yaw,
            'back_side': back_side, 'margin': round(margin, 2),
            'seat_h': round(seat_h, 3),
            'scores': {k: round(v, 4) for k, v in scores.items()},
            'version': FRONT_VERSION}


if __name__ == '__main__':
    sys.path.insert(0, __file__.rsplit('/', 1)[0])
    import json

    import mesh_render as MR
    parts = MR.load_parts(sys.argv[1])
    print(json.dumps(infer_seat_front(parts, sys.argv[2] if len(sys.argv) > 2 else 'стул'),
                     ensure_ascii=False, indent=1))
