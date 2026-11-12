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

Боковая спинка (T-20261112-31, `infer_side_back`): тот же подъём сторон по ДЛИННЫМ бокам — угловая модель («Кейси-Б», тахта)
ставится только в угол спинкой к стене; признак — в evidence.headboard.side_back и кэше сторожа (`load_side_backs`).

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


# БОКОВАЯ СПИНКА (T-20261112-31): угловая модель («Кейси-Б», кровать-софа, тахта) — вторая высокая сторона вдоль ДЛИННОГО
# бока. Тот же замер подъёма сторон (`side_tops`), только по двум длинным бокам. Порог — от высоты изголовья: спинка бока
# у угловых моделей почти с изголовье (Кейси-Б), у обычной рамы бок ниже матраса (подъём ≤ 0).
SIDE_MIN_RISE = 0.12      # бок выше спального места хотя бы на 12 % высоты меша (как изголовье)
SIDE_OF_HEAD = 0.5        # и не ниже половины подъёма изголовья
SIDE_MARGIN = 0.10        # и выше другого длинного бока на 10 % высоты: высокие ОБА бока — не угловая (бортики, короб)
SIDE_VERSION = 1


def long_sides(t: dict, hb: dict | None = None) -> tuple:
    """Стороны длинных боков в конвенции `SIDES`: изголовье известно — перпендикуляр к нему; нет — по вытянутости меша."""
    h = (hb or {}).get('head_side')
    if h is not None:
        return (90, 270) if h in (0, 180) else (0, 180)
    if t['xz'] < SQUARE[0]:
        return (90, 270)
    if t['xz'] > SQUARE[1]:
        return (0, 180)
    return ()


def infer_side_back(V, hb: dict | None = None) -> dict:
    """V — вершины в каноне решения, hb — `infer_headboard(V)` (None — посчитать). → {status yes|no|both|unknown, side,
    side_canon, rise, version}. side — бок КРОВАТИ в осях солвера (`planner/bedroom_checks.bed_zones`): 'left' — −x,
    'right' — +x при изголовье у стены и лице к изножью. Канон: изголовье +Z, перед −Z; сцена и солвер ставят меш
    передом к +Z (`scene_mesh.world_vertices`: ry(−front_yaw)), т. е. канон повёрнут на 180° — его +X (сторона 90) у
    солвера −x ('left'), −X (270) — +x ('right'). Изголовье не у +Z (поправка решения ещё не применена) — бок по сторонам
    относительно изголовья, тот же счёт."""
    t = side_tops(V)
    hb = hb if hb is not None else infer_headboard(V)
    sides = long_sides(t, hb if hb.get('status') == 'confident' else None)
    out = {'rise': {s: round(t['rise'][s], 3) for s in sides}, 'version': SIDE_VERSION}
    if not sides:
        return {**out, 'status': 'unknown', 'why': 'почти квадратная, изголовье не найдено'}
    head = hb.get('head_side') if hb.get('status') == 'confident' else None
    hr = t['rise'][head] if head is not None else max(t['rise'][s] for s in (0, 180, 90, 270) if s not in sides)
    a, b = sorted(sides, key=lambda s: t['rise'][s], reverse=True)
    ra, rb = t['rise'][a], t['rise'][b]
    need = max(SIDE_MIN_RISE, SIDE_OF_HEAD * hr)
    if ra < need:
        return {**out, 'status': 'no'}
    if ra - rb < SIDE_MARGIN:
        # оба бока высокие — короб/бортики (не угловая); один чуть выше порога без отрыва — обычная рама
        return {**out, 'status': 'both' if rb >= need else 'no'}
    # сторона относительно изголовья: при изголовье у +Z (0) бок +X (90) → солвер 'left'; поворот изголовья поворачивает и бок
    rel = (a - (head if head is not None else 0)) % 360
    return {**out, 'status': 'yes', 'side_canon': a, 'side': 'left' if rel == 90 else 'right'}


def side_back_brief(sb: dict) -> dict:
    """Кратко для хранения рядом с изголовьем (evidence.headboard.side_back, кэш сторожа): статус, сторона, версия."""
    return {k: sb[k] for k in ('status', 'side', 'version') if k in sb}


# Где лежит признак: сторож изголовья (`orient_worker.py --bed-guard --apply`, ночной шаг `orient_bed_guard`) пишет в свой кэш
# {revision_key: {sig, hb: {…, side_back}}}; `BED_SHAPE_FILE` — тот же формат из другого места (проба в worktree до ночи).
def load_side_backs(path: str | None = None) -> dict:
    """{sku: {status, side, version}} по кэшу сторожа изголовья. Нет файла — {} (признака нет — по названию)."""
    import os
    path = path or os.environ.get('BED_SHAPE_FILE') or os.path.join(
        os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes')), 'orientation', 'bed-guard-cache.json')
    try:
        cache = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    out = {}
    for rk in sorted(cache):
        sb = ((cache[rk] or {}).get('hb') or {}).get('side_back')
        if sb and sb.get('status'):
            out[rk.split('|')[0]] = sb
    return out


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
    # боковая спинка (T-20261112-31): тахта — спинка у −X канона (270) → у солвера правый бок (+x); зеркально — левый
    r = infer_side_back(T)
    ok('тахта: боковая спинка у −X канона → солвер «right»', r['status'] == 'yes' and r['side'] == 'right')
    r = infer_side_back(np.vstack([_bed('+z'), _box(1.2, 1.3, 0, 0.95, 0, 2.1, 10)]))
    ok('спинка у +X канона → «left»', r['status'] == 'yes' and r['side'] == 'left')
    ok('обычная кровать — боковой спинки нет', infer_side_back(V)['status'] == 'no')
    B2 = np.vstack([_bed('+z'), _box(0, 0.1, 0, 0.95, 0, 2.1, 10), _box(1.2, 1.3, 0, 0.95, 0, 2.1, 10)])
    ok('высокие оба бока (короб) — не угловая', infer_side_back(B2)['status'] == 'both')
    Rm = np.asarray(ry(90))
    ok('тахта повёрнута на 90° (решение без поправки) — бок тот же относительно изголовья',
       infer_side_back(T @ Rm.T)['side'] == 'right')
    Rq = rotate_R([[-1, 0, 0], [0, 1, 0], [0, 0, -1]], 90)
    q = quat_wxyz(Rq)
    ok('кватернион: w ≥ 0 и единичный', q[0] >= 0 and abs(sum(v * v for v in q) - 1) < 1e-5)
    ok('кватернион единичной = (1,0,0,0)', quat_wxyz([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) == [1.0, 0.0, 0.0, 0.0])
    print('итог:', 'чисто' if not fails else f'провалов {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        sys.exit(selftest())
    _V = canonical_vertices(sys.argv[1], json.loads(sys.argv[2]))
    _hb = infer_headboard(_V)
    print(json.dumps({**_hb, 'side_back': infer_side_back(_V, _hb)}, ensure_ascii=False))
