#!/usr/bin/env python3
"""ОДИН свидетель «перёда» для 06, 07 и автооценки листа (T-20261123-21/2 ↔ T-43; директор 23.11).

Порядок «перёд» (канон `paint-photo-fill-01.md`): решение orient (`orient_policy`) → доли известного с фото (`front_shares`,
эта функция) → камера 04 только сверка. Сам выбор камеры az/az+180 этапом 04 (`pose_rank.flip_pick`) — способ ВЫБРАТЬ камеру,
не источник «перёда».

`front_shares(V, F, UV, known, az, R)` — доля текселей, известных с фото (known.png этапа 06), по сторонам «перед/бок/зад/др. бок»
(камера az, az+90, +180, +270; θ=0 — со стороны +Z). Чистый numpy; пороги (cos_min, margin, min_front_share) — только из
`data/flat3d/sides-eval.json: front_guard` (R — всё правило или сам блок front_guard; None — прочитать файл).

    python tools/scout/front_axis.py --selftest
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'data', 'flat3d', 'sides-eval.json')
AXIS_RULES = os.path.join(HERE, '..', '..', 'data', 'flat3d', 'front-axis.json')
RESOLVED = ('auto_resolved', 'human_resolved')            # = orient_policy.RESOLVED (модуль чистый, без импорта scout)
SIDES = ('перед', 'бок', 'зад', 'др. бок')


def load_guard(R: dict | None = None) -> dict:
    """Блок front_guard: из переданных правил (целиком или сам блок) либо из data/flat3d/sides-eval.json."""
    if R is None:
        R = json.load(open(RULES, encoding='utf-8'))
    return R.get('front_guard', R)


def front_shares(V, F, UV, known, az_deg, R=None, names=None) -> dict:
    """Доля известных текселей по сторонам листа (камера az, az+90, +180, +270). V, F — меш; UV — на вершину (n,2), v вверх;
    known — 2D-маска (>0 известно), строки сверху вниз. Грани — нормаль наружу, n·cam ≥ cos_min; вес — площадь.
    Нет граней, смотрящих на сторону, — None."""
    g = load_guard(R)
    V, F = np.asarray(V, float), np.asarray(F, int)
    tri = V[F]
    nn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(nn, axis=1) * 0.5
    nn = nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
    cen = tri.mean(axis=1)
    nn = nn * np.where(((cen - V.mean(axis=0)) * nn).sum(axis=1) >= 0, 1.0, -1.0)[:, None]
    uv = np.asarray(UV, float)[F].mean(axis=1)
    h, w = known.shape[:2]
    ix = np.clip((uv[:, 0] % 1.0 * w).astype(int), 0, w - 1)
    iy = np.clip(((1.0 - uv[:, 1] % 1.0) * h).astype(int), 0, h - 1)
    kn = (np.asarray(known)[iy, ix] > 0).astype(float)
    out = {}
    for name, d in zip(names or SIDES, (0, 90, 180, 270)):
        t = np.deg2rad(float(az_deg) + d)
        cam = np.array([np.sin(t), 0.0, np.cos(t)])
        sel = (nn @ cam) >= g['cos_min']
        a = area[sel]
        out[name] = round(float((kn[sel] * a).sum() / a.sum()), 4) if a.sum() > 0 else None
    return out


def front_flipped(shares: dict, R=None) -> bool:
    """«Зад» известен больше «перёда» на margin и больше (и не меньше min_front_share): фото легло на сторону, противоположную камере."""
    g = load_guard(R)
    f, b = shares.get('перед'), shares.get('зад')
    return bool(f is not None and b is not None and b > f + g['margin'] and b >= g['min_front_share'])


def _ad(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def axis_of_theta(theta) -> tuple | None:
    """(ось 0|2, знак) «перёда» с азимута θ — как `tex_fill.front_axis_of_check` (x = sinθ, z = cosθ)."""
    if theta is None:
        return None
    a = np.radians(float(theta))
    sx, cz = float(np.sin(a)), float(np.cos(a))
    return (0, 1 if sx >= 0 else -1) if abs(sx) > abs(cz) else (2, 1 if cz >= 0 else -1)


def front_axis_resolved(orient=None, geom=None, shares=None, photo_frontal=None, cam_az=None, R=None) -> dict:
    """{'theta': θ|None, 'front_yaw': то же, 'axis': (ось, знак)|None, 'source': orient|geometry|known_share|None, 'flags': [...]}.
    orient — запись orient (`status`, `source`, `legacy_front_yaw`/`yaw`); geom — {'theta', 'source'}; shares — `front_shares(...)` для камеры cam_az;
    photo_frontal — True только когда фото фронтальное (доли берутся лишь так). Флаги: front_unknown(:причина), front_camera_opposite, photo_side."""
    rules = json.load(open(AXIS_RULES, encoding='utf-8'))
    g = load_guard(R)
    flags, theta, src = [], None, None
    o = orient or {}
    osrc = str(o.get('source') or o.get('orient') or '')
    yaw = o.get('legacy_front_yaw', o.get('yaw'))
    if 'symmetric' in osrc:
        flags.append('front_unknown:symmetric_by_role')
    else:
        if o.get('status') in RESOLVED and yaw is not None:
            theta, src = float(yaw) % 360.0, 'orient'
        elif geom and geom.get('theta') is not None:
            theta, src = float(geom['theta']) % 360.0, 'geometry:' + str(geom.get('source') or '')
        elif photo_frontal is True and shares and cam_az is not None:
            vals = [(shares.get(n), d) for n, d in zip(SIDES, (0, 90, 180, 270)) if shares.get(n) is not None]
            vals.sort(reverse=True)
            if vals and (len(vals) == 1 or vals[0][0] > vals[1][0] + g['margin']):
                theta, src = (float(cam_az) + vals[0][1]) % 360.0, 'known_share'
        if theta is None:
            flags.append('front_unknown')
    if theta is not None and cam_az is not None:
        d = _ad(theta, cam_az)
        if d >= rules['camera_conflict_deg']:
            flags.append('front_camera_opposite')
        elif d >= rules['photo_side_deg']:
            flags.append('photo_side')
    th = None if theta is None else round(theta, 1)
    return {'theta': th, 'front_yaw': th, 'axis': axis_of_theta(theta), 'source': src, 'flags': flags}


def _box4():
    V, F, UV = [], [], []
    quads = [((-1, 0, 1), (1, 0, 1)), ((1, 0, 1), (1, 0, -1)), ((1, 0, -1), (-1, 0, -1)), ((-1, 0, -1), (-1, 0, 1))]   # +Z, +X, -Z, -X
    for i, (a, b) in enumerate(quads):
        o = len(V)
        for (x, y, z), (u, v) in ((a, (0, 0)), (b, (1, 0)), (b, (1, 1)), (a, (0, 1))):
            V.append((x, -1.0 if v == 0 else 1.0, z))
            UV.append((i / 4 + u / 4, v))
        F += [(o, o + 1, o + 2), (o, o + 2, o + 3)]
    return np.array(V, float), np.array(F), np.array(UV, float)


def selftest() -> int:
    bad = 0
    V, F, UV = _box4()
    kn = np.zeros((100, 400), np.uint8)
    kn[:, 200:300] = 255                                    # известна грань −Z
    s0, s180 = front_shares(V, F, UV, kn, 0.0), front_shares(V, F, UV, kn, 180.0)
    for ok, name in ((s0['зад'] == 1.0 and s0['перед'] == 0.0 and front_flipped(s0), 'камера на +Z, известно на −Z → развёрнут'),
                     (s180['перед'] == 1.0 and not front_flipped(s180), 'камера на −Z → не развёрнут'),
                     (not front_flipped({'перед': 0.30, 'зад': 0.32}) and not front_flipped({'перед': None, 'зад': 0.5}), 'разница меньше margin / нет данных → молчит'),
                     (front_shares(V, F, UV, kn, 0.0, load_guard())['зад'] == 1.0, 'R = сам блок front_guard')):
        print(('  ✓ ' if ok else '  ✗ ') + name)
        bad += 0 if ok else 1
    G = load_guard()
    res = lambda **k: front_axis_resolved(R=G, **k)
    sh = {'перед': 0.1, 'бок': 0.2, 'зад': 0.9, 'др. бок': 0.0}
    a = res(orient={'status': 'auto_resolved', 'source': 'orienter+seat_agree', 'legacy_front_yaw': 359}, cam_az=171, shares=sh, photo_frontal=True)
    b = res(orient={'status': 'vlm_pending'}, geom={'theta': 270, 'source': 'm3'}, cam_az=154)
    c = res(orient={'status': 'vlm_pending'}, shares=sh, photo_frontal=True, cam_az=10)
    d = res(orient={'status': 'vlm_pending'}, shares=sh, photo_frontal=None, cam_az=10)
    e = res(orient={'status': 'auto_resolved', 'source': 'symmetric_by_role', 'legacy_front_yaw': 90}, geom={'theta': 90}, cam_az=0)
    f = res(orient={'status': 'review_pending', 'source': 'seat_conflict', 'legacy_front_yaw': 271}, cam_az=358)
    g2 = res(orient={'status': 'auto_resolved', 'source': 'orienter+seat_agree', 'legacy_front_yaw': 0}, cam_az=315)
    for ok, name in ((a['source'] == 'orient' and a['theta'] == 359 and 'front_camera_opposite' in a['flags'], 'orient решён → θ из orient; камера напротив (171 против 359) — флаг, не замена'),
                     (b['source'] == 'geometry:m3' and b['theta'] == 270 and 'photo_side' in b['flags'] and 'front_camera_opposite' not in b['flags'], 'нет orient → геометрия; камера сбоку (116°) — «фото сбоку», не конфликт'),
                     (c['source'] == 'known_share' and c['theta'] == 190.0 and c['axis'] == (2, -1), 'фото фронтальное → перёд по долям известного (зад 0,9 → θ = az+180)'),
                     (d['theta'] is None and d['flags'] == ['front_unknown'] and d['axis'] is None, 'фото не фронтальное/неизвестно → доли не берём → unknown (камера перёд не решает)'),
                     (e['theta'] is None and e['flags'] == ['front_unknown:symmetric_by_role'], 'симметричная по роли → unknown, геометрия не подменяет'),
                     (f['theta'] is None and 'front_unknown' in f['flags'], 'orient не решён (seat_conflict) и нет геометрии → unknown'),
                     (g2['flags'] == ['photo_side'] or g2['flags'] == [], 'камера 45° от перёда — не ошибка'),
                     (axis_of_theta(0) == (2, 1) and axis_of_theta(90) == (0, 1) and axis_of_theta(180) == (2, -1) and axis_of_theta(270) == (0, -1) and axis_of_theta(None) is None, 'axis_of_theta: 0→+Z, 90→+X, 180→−Z, 270→−X')):
        print(('  ✓ ' if ok else '  ✗ ') + name)
        bad += 0 if ok else 1
    print('FAIL' if bad else 'OK', bad)
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(selftest() if '--selftest' in sys.argv else 0)
