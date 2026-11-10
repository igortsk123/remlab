#!/usr/bin/env python3
"""Изголовье кровати по геометрии меша — свидетель разворота (T-20261110-20/3).

Канон orient-v1: верх +Y, перед −Z (MR-yaw 180) → у кровати изголовье СЗАДИ, у края +Z; X — ширина, Z — длина.
Изголовье = сторона, у которой верх кромки (98-й перцентиль высоты в полосе у края) выше всего над спальным местом
(95-й перцентиль высоты в середине). Уверенно — только с отрывом от трёх других сторон (`MARGIN`): изножье почти с
изголовье, низкая спинка или «подиум» без спинки — `ambiguous`, право честно не знать (как `mesh_front` у сидячих).

Ошибка, которую ловим: каскад (orienter + VLM «перед/зад») не видит разворот на 90° — VLM-свидетель отвечает «перед»
почти всегда (`domain/viz-fidelity-playbook.md` § «Ориентация мешей»), и кровать встаёт боком (Лория/Кейла 120, T-20/2).

Сторона — в той же конвенции, что `mesh_front.back_side`: 0 = +Z, 180 = −Z, 90 = +X, 270 = −X. Поправка `fix_deg` —
поворот вокруг +Y, после которого изголовье у +Z: R' = ry(fix)·R (`rotate_R`).

    python tools/scout/bed_headboard.py --selftest
    python tools/scout/bed_headboard.py <model.glb> '<R как JSON>'     # одна модель
"""
import json
import math
import sys

BAND = 0.12          # толщина полосы у края — доля длины меша вдоль этой оси
MIN_RISE = 0.12      # изголовье выше спального места хотя бы на 12 % высоты меша
MARGIN = 0.10        # и выше любой другой стороны хотя бы на 10 % высоты меша
CORNER = 0.2         # полоса стороны — без 20 % у каждого угла (по другой оси)
# ширина/длина «почти квадрат»: рамы 180×200 ≈ 0,88, 200×200 ≈ 0,95 — у них торец формой не определить; 160×200 ≈ 0,79 — уже вытянута
SQUARE = (0.86, 1.16)
VERSION = 1
SIDES = {0: (2, +1), 180: (2, -1), 90: (0, +1), 270: (0, -1)}     # сторона → (ось, знак края)


def side_tops(V) -> dict:
    """V — вершины в каноне (N×3, numpy). → {rise: {сторона: подъём над спальным местом}, bed: уровень места} в долях высоты."""
    import numpy as np
    V = np.asarray(V, np.float64)
    lo, hi = V.min(0), V.max(0)
    ext = np.maximum(hi - lo, 1e-9)
    n = (V - lo) / ext
    mid = (np.abs(n[:, 0] - 0.5) < 0.25) & (np.abs(n[:, 2] - 0.5) < 0.25)
    bed = float(np.percentile(n[mid, 1], 95)) if mid.any() else 0.0
    rise = {}
    for side, (ax, sgn) in SIDES.items():
        other = 2 if ax == 0 else 0
        # без углов: у боковой полосы угол — это край изголовья во всю ширину, он поднял бы бок до высоты спинки
        band = (n[:, ax] > 1 - BAND if sgn > 0 else n[:, ax] < BAND) & (np.abs(n[:, other] - 0.5) < 0.5 - CORNER)
        rise[side] = float(np.percentile(n[band, 1], 98)) - bed if band.sum() >= 20 else -1.0
    return {'rise': rise, 'bed': bed, 'xz': float(ext[0] / ext[2])}


def infer_headboard(V) -> dict:
    """→ {status confident|ambiguous|sideways, head_side, fix_deg, rise, margin, xz, ends, version}. fix_deg = 0 — изголовье у +Z.

    Два признака. (1) Форма: изголовье — на КОРОТКОМ торце. Кровать вытянута (ширина/длина `xz` вне `SQUARE`) — кандидаты
    только два торца длинной оси; без этого тахта (спинка вдоль длинной стороны + изголовье — Лория, Кейла) даёт две высокие
    стороны рядом и не различается. Почти квадратная (180–200 × 200) — все четыре стороны. (2) Высота: из кандидатов —
    самый высокий над спальным местом с отрывом. Вытянута поперёк канона (`xz` > 1), а торцы не различить — `sideways`:
    известно, что стоит боком, но не куда смотрит изголовье — чинить нечем, это блок, а не догадка."""
    t = side_tops(V)
    rise, xz = t['rise'], t['xz']
    if xz < SQUARE[0]:
        ends = (0, 180)
    elif xz > SQUARE[1]:
        ends = (90, 270)
    else:
        ends = (0, 180, 90, 270)
    order = sorted(ends, key=rise.get, reverse=True)
    best, second = order[0], order[1]
    margin = rise[best] - rise[second]
    out = {'rise': {k: round(v, 3) for k, v in rise.items()}, 'bed': round(t['bed'], 3), 'margin': round(margin, 3),
           'xz': round(xz, 3), 'ends': list(ends), 'version': VERSION}
    if rise[best] < MIN_RISE or margin < MARGIN:
        return {**out, 'status': 'sideways' if xz > SQUARE[1] else 'ambiguous'}
    return {**out, 'status': 'confident', 'head_side': best, 'fix_deg': (360 - best) % 360}


def ry(deg: float):
    a = math.radians(deg)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def rotate_R(R, fix_deg: float):
    """R' = ry(fix)·R: канон, повёрнутый вокруг вертикали так, что сторона `head_side` уходит к +Z.
    ry(θ)·(x,0,z) = (x·cos+z·sin, 0, −x·sin+z·cos): +X (90) при θ=270 → (0,0,+1) — верно."""
    A = ry(fix_deg)
    return [[sum(A[i][k] * R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def quat_wxyz(R) -> list:
    """Кватернион матрицы поворота (det=+1), w ≥ 0 — как `raw_to_canonical_quat_wxyz` каскада."""
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    return [round(v, 6) for v in (w, x, y, z)]


def canonical_vertices(glb: str, R):
    """Вершины модели в каноне (R·v) — без склейки и рендера: для свидетеля хватает облака точек."""
    import numpy as np
    import trimesh
    tm = trimesh.load(glb, force='mesh')
    return np.asarray(tm.vertices, np.float64) @ np.asarray(R, np.float64).T


def _box(x0, x1, y0, y1, z0, z1, n=6):
    import numpy as np
    g = np.linspace(0, 1, n)
    return np.array([[x0 + (x1 - x0) * a, y0 + (y1 - y0) * b, z0 + (z1 - z0) * c] for a in g for b in g for c in g])


def _bed(head: str = '+z', foot_h: float = 0.0):
    """Синтетика: основание 1.3×0.4×2.1, изголовье высотой 1.0 у края head, изножье высотой foot_h у противоположного."""
    import numpy as np
    parts = [_box(0, 1.3, 0, 0.4, 0, 2.1, 10)]
    hb = {'+z': (0, 1.3, 2.0, 2.1), '-z': (0, 1.3, 0, 0.1)}
    x0, x1, z0, z1 = hb['+z' if head == '+z' else '-z']
    parts.append(_box(x0, x1, 0, 1.0, z0, z1, 8))
    if foot_h:
        fx0, fx1, fz0, fz1 = hb['-z' if head == '+z' else '+z']
        parts.append(_box(fx0, fx1, 0, foot_h, fz0, fz1, 8))
    return np.vstack(parts)


def selftest() -> int:
    import numpy as np
    fails = 0

    def ok(name, cond):
        nonlocal fails
        print(('ok   ' if cond else 'FAIL ') + name)
        fails += not cond
    V = _bed('+z')
    r = infer_headboard(V)
    ok('изголовье у +Z → сторона 0, поправка 0', r['status'] == 'confident' and r['head_side'] == 0 and r['fix_deg'] == 0)
    r = infer_headboard(_bed('-z'))
    ok('изголовье у −Z → 180, поправка 180', r.get('head_side') == 180 and r['fix_deg'] == 180)
    for deg, side in ((90, 90), (270, 270)):          # ry(90)·(+Z) = +X
        Rm = np.asarray(ry(deg))
        r = infer_headboard(V @ Rm.T)
        ok(f'кровать повёрнута на {deg}° → сторона {side}', r.get('head_side') == side)
        # поправка возвращает изголовье к +Z
        R2 = np.asarray(rotate_R(Rm.tolist(), r['fix_deg']))
        ok(f'  поправка {r["fix_deg"]}° → изголовье у +Z', infer_headboard(V @ R2.T).get('head_side') == 0)
    # тахта: изголовье у +Z и спинка во всю длину у −X почти той же высоты (Лория/Кейла 120)
    T = np.vstack([_bed('+z'), _box(0, 0.1, 0, 0.95, 0, 2.1, 10)])
    r = infer_headboard(T)
    ok('тахта стоит верно → 0', r.get('head_side') == 0 and r['fix_deg'] == 0)
    for deg in (90, 270):
        Rm = np.asarray(ry(deg))
        r = infer_headboard(T @ Rm.T)
        R2 = np.asarray(rotate_R(Rm.tolist(), r.get('fix_deg', 0)))
        ok(f'тахта боком ({deg}°) → поправка {(360 - deg) % 360}, изголовье у +Z',
           r.get('fix_deg') == (360 - deg) % 360 and infer_headboard(T @ R2.T).get('head_side') == 0)
    r = infer_headboard(_bed('+z', foot_h=0.95) @ np.asarray(ry(90)).T)
    ok('боком, торцы одинаковые → sideways (блок)', r['status'] == 'sideways')
    r = infer_headboard(_bed('+z', foot_h=0.95))
    ok('изножье почти как изголовье → ambiguous', r['status'] == 'ambiguous')
    r = infer_headboard(_box(0, 1.3, 0, 0.4, 0, 2.1, 10))
    ok('подиум без спинки → ambiguous', r['status'] == 'ambiguous')
    Rq = rotate_R([[-1, 0, 0], [0, 1, 0], [0, 0, -1]], 90)
    q = quat_wxyz(Rq)
    ok('кватернион: w ≥ 0 и единичный', q[0] >= 0 and abs(sum(v * v for v in q) - 1) < 1e-5)
    ok('кватернион единичной = (1,0,0,0)', quat_wxyz([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) == [1.0, 0.0, 0.0, 0.0])
    print('итог:', 'чисто' if not fails else f'провалов {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        sys.exit(selftest())
    print(json.dumps(infer_headboard(canonical_vertices(sys.argv[1], json.loads(sys.argv[2]))), ensure_ascii=False))
