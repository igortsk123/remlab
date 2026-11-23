#!/usr/bin/env python3
"""ОДИН свидетель «перёда» для 06, 07 и автооценки листа (T-20261123-21/2 ↔ T-43; директор 23.11).

`front_axis_resolved(...)` — «перёд» товара для 07 (директор 23.11 по листам: фото товара — фронтальное/3-4 спереди, поэтому камера 04 = сторона фото
законный источник «перёда», пока фото фронтальное; ошибается лишь перёд↔зад). Порядок: (1) решение orient (решённое, не `symmetric`; сиденье `confident`
при seat_conflict поправляет поворот orienter'а: θ = yaw + seat − 180) → (2) камера 04 при `photo_frontal` (камера смотрит на длинную грань габарита,
`photo_frontal_of`) с поправкой долями известного (развёрнуто → az+180) → (3) квадратные в плане (`photo_frontal=None`) — по долям известного → (4) unknown
(фото с торца, нет данных). Симметричным по роли — всегда unknown. Расхождение θ с камерой: ≥ `camera_conflict_deg` — `front_camera_opposite`,
между `photo_side_deg` и ним — `photo_side` (оба — пометки, не замена). θ — азимут «перёда» в системе меша: 0 = +Z, сторона листа на θ смотрится камерой
(sinθ, 0, cosθ); yaw orient (`legacy_front_yaw`) = θ.

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


def photo_frontal_of(V, cam_az, R=None):
    """True — камера смотрит на ДЛИННУЮ грань габарита в плане (угол к нормали длинной стороны ≤ frontal_max_deg; перёд это или зад — решают доли);
    False — на торец; None — квадратные/круглые в плане (длинная/короткая < square_ratio) или нет данных. Габарит — главные оси вершин в плане (x, z)."""
    rules = json.load(open(AXIS_RULES, encoding='utf-8'))
    if V is None or cam_az is None:
        return None
    P = np.asarray(V, float)[:, [0, 2]]
    P = P - P.mean(axis=0)
    if len(P) < 3:
        return None
    w, E = np.linalg.eigh(np.cov(P.T))
    ext = [float(np.ptp(P @ E[:, i])) for i in (1, 0)]            # длинная, короткая
    if ext[1] <= 0 or ext[0] / ext[1] < rules['square_ratio']:
        return None
    n = E[:, 1]                                                     # длинная ось плана; нормаль длинной грани — вторая ось
    nl = np.array([-n[1], n[0]])
    cam = np.array([np.sin(np.radians(float(cam_az))), np.cos(np.radians(float(cam_az)))])
    c = abs(float(cam @ nl))
    return bool(np.degrees(np.arccos(min(1.0, c))) <= rules['frontal_max_deg'])


def front_axis_resolved(orient=None, shares=None, photo_frontal=None, cam_az=None, R=None, V=None) -> dict:
    """{'theta': θ|None, 'front_yaw': то же, 'axis': (ось, знак)|None, 'source': orient|orient_seat|camera04|camera04_flipped|known_share|None, 'flags': [...]}.
    orient — запись orient (`status`, `source`, `legacy_front_yaw`/`yaw`, `evidence.seat`); shares — `front_shares(...)` для камеры cam_az;
    photo_frontal — True/False/None (если None и есть V — считается `photo_frontal_of`). Флаги: front_unknown(:причина), front_camera_opposite, photo_side."""
    rules = json.load(open(AXIS_RULES, encoding='utf-8'))
    g = load_guard(R)
    if photo_frontal is None and V is not None:
        photo_frontal = photo_frontal_of(V, cam_az, R)
    flags, theta, src = [], None, None
    o = orient or {}
    osrc = str(o.get('source') or o.get('orient') or '')
    yaw = o.get('legacy_front_yaw', o.get('yaw'))
    seat = ((o.get('evidence') or {}).get('seat')) or {}
    if 'symmetric' in osrc:
        flags.append('front_unknown:symmetric_by_role')
    else:
        if o.get('status') in RESOLVED and yaw is not None:
            theta, src = float(yaw) % 360.0, 'orient'
        elif osrc == 'seat_conflict' and yaw is not None and seat.get('status') == 'confident' and seat.get('front_yaw') is not None:
            theta, src = (float(yaw) + float(seat['front_yaw']) - rules['canon_front_yaw']) % 360.0, 'orient_seat'     # сиденье поправляет поворот orienter'а
        elif photo_frontal is True and cam_az is not None:
            theta, src = float(cam_az) % 360.0, 'camera04'
            if shares and front_flipped(shares, g):
                theta, src = (theta + 180.0) % 360.0, 'camera04_flipped'
        elif photo_frontal is None and shares and cam_az is not None:
            vals = sorted(((shares.get(n), d) for n, d in zip(SIDES, (0, 90, 180, 270)) if shares.get(n) is not None), reverse=True)
            if vals and (len(vals) == 1 or vals[0][0] > vals[1][0] + g['margin']):
                theta, src = (float(cam_az) + vals[0][1]) % 360.0, 'known_share'
        if theta is None:
            flags.append('front_unknown' + (':photo_side' if photo_frontal is False else ''))
    if theta is not None and cam_az is not None and src not in ('camera04', 'camera04_flipped'):
        d = _ad(theta, cam_az)
        if d >= rules['camera_conflict_deg']:
            flags.append('front_camera_opposite')
        elif d >= rules['photo_side_deg']:
            flags.append('photo_side')
    th = None if theta is None else round(theta, 1)
    return {'theta': th, 'front_yaw': th, 'axis': axis_of_theta(theta), 'source': src, 'flags': flags}


def resolve_from_files(glb, check06, orient_path=None, R=None) -> dict:
    """front_axis_resolved по файлам прогона: GLB (меш со своей UV), 06-visible/check.json (az камеры 04; known.png лежит рядом), orient.json (необязателен).
    Нет файлов/azимута — {'theta': None, ..., 'flags': ['front_unknown:no_inputs']} (молча не падает: лист строится по камере 04)."""
    try:
        import trimesh
        from PIL import Image
        az = float(json.load(open(check06, encoding='utf-8'))['extra']['camera']['az'])
        sc = trimesh.load(glb, force='scene')
        gs = list(sc.geometry.values())
        V = np.concatenate([g.vertices for g in gs])
        off, F, UV = 0, [], []
        for g in gs:
            F.append(g.faces + off)
            off += len(g.vertices)
            UV.append(np.asarray(g.visual.uv))
        F, UV = np.concatenate(F), np.concatenate(UV)
        known = np.asarray(Image.open(os.path.join(os.path.dirname(check06), 'known.png')).convert('L'))
        orient = json.load(open(orient_path, encoding='utf-8')) if orient_path and os.path.isfile(orient_path) else None
        sh = front_shares(V, F, UV, known, az, R)
        r = front_axis_resolved(orient, sh, None, az, R, V)
        r['cam_az'] = az
        return r
    except Exception as e:  # noqa: BLE001 — нет GLB/known/az: ракурс не решаем, причина в флаге
        return {'theta': None, 'front_yaw': None, 'axis': None, 'source': None, 'flags': ['front_unknown:no_inputs'], 'error': f'{type(e).__name__}: {e}'[:160]}


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
    flip = {'перед': 0.1, 'бок': 0.2, 'зад': 0.9, 'др. бок': 0.0}
    okr = {'перед': 0.9, 'бок': 0.2, 'зад': 0.1, 'др. бок': 0.0}
    a = res(orient={'status': 'auto_resolved', 'source': 'orienter+seat_agree', 'legacy_front_yaw': 359}, cam_az=171, shares=flip, photo_frontal=True)
    b = res(orient={'status': 'vlm_pending'}, cam_az=154, shares=okr, photo_frontal=True)
    c = res(orient={'status': 'vlm_pending'}, cam_az=171, shares=flip, photo_frontal=True)
    d = res(orient={'status': 'vlm_pending'}, cam_az=10, shares=okr, photo_frontal=False)
    e = res(orient={'status': 'auto_resolved', 'source': 'symmetric_by_role', 'legacy_front_yaw': 90}, cam_az=0, photo_frontal=True)
    f = res(orient={'status': 'review_pending', 'source': 'seat_conflict', 'legacy_front_yaw': 271, 'evidence': {'seat': {'status': 'confident', 'front_yaw': 270}}}, cam_az=358, photo_frontal=True)
    f2 = res(orient={'status': 'review_pending', 'source': 'seat_conflict', 'legacy_front_yaw': 271, 'evidence': {'seat': {'status': 'ambiguous', 'front_yaw': 270}}}, cam_az=358, photo_frontal=False)
    g2 = res(orient={'status': 'vlm_pending'}, shares=flip, photo_frontal=None, cam_az=10)
    g3 = res(orient={'status': 'vlm_pending'}, shares={'перед': 0.5, 'бок': 0.5, 'зад': 0.5, 'др. бок': 0.5}, photo_frontal=None, cam_az=10)
    for ok, name in ((a['source'] == 'orient' and a['theta'] == 359 and 'front_camera_opposite' in a['flags'], 'orient решён → θ из orient (13994: 359, камера 171 напротив — флаг, не замена)'),
                     (b['source'] == 'camera04' and b['theta'] == 154 and b['flags'] == [], 'нет orient, фото фронтальное, доли не против → θ = камера 04 (7736: 154)'),
                     (c['source'] == 'camera04_flipped' and c['theta'] == 351 and c['axis'] == (2, 1), 'фото фронтальное, но доли «зад» → развёрнуто: az+180 (13994: 351)'),
                     (d['theta'] is None and d['flags'] == ['front_unknown:photo_side'] and d['axis'] is None, 'камера на торец (photo_frontal=False) → unknown'),
                     (e['theta'] is None and e['flags'] == ['front_unknown:symmetric_by_role'], 'симметричная по роли → unknown, камера не подменяет'),
                     (f['source'] == 'orient_seat' and f['theta'] == 1.0, 'seat_conflict, сиденье confident → θ = yaw + seat − 180 (16411: 271+270−180 = 1)'),
                     (f2['theta'] is None and 'front_unknown' in f2['flags'][0], 'seat_conflict, сиденье не confident → не берём'),
                     (g2['source'] == 'known_share' and g2['theta'] == 190.0, 'квадратная в плане → по долям известного'),
                     (g3['theta'] is None and g3['flags'] == ['front_unknown'], 'квадратная и доли равны → unknown'),
                     (axis_of_theta(0) == (2, 1) and axis_of_theta(90) == (0, 1) and axis_of_theta(180) == (2, -1) and axis_of_theta(270) == (0, -1) and axis_of_theta(None) is None, 'axis_of_theta: 0→+Z, 90→+X, 180→−Z, 270→−X')):
        print(('  ✓ ' if ok else '  ✗ ') + name)
        bad += 0 if ok else 1
    # photo_frontal_of: брус 4×1 по x (длинная грань смотрит на ±Z): камера az 0/180/30 — фронт, 90/270/60 — торец; куб — None
    Vb = np.array([(x, y, z) for x in (-2, 2) for y in (0, 1) for z in (-0.5, 0.5)], float)
    Vc = np.array([(x, y, z) for x in (-1, 1) for y in (0, 1) for z in (-1, 1)], float)
    pf = lambda V, az: photo_frontal_of(V, az)
    for ok, name in ((pf(Vb, 0) is True and pf(Vb, 180) is True and pf(Vb, 30) is True, 'габарит: камера на длинную грань (0°, 180°, 30°) → фронтально'),
                     (pf(Vb, 90) is False and pf(Vb, 270) is False and pf(Vb, 60) is False, 'габарит: камера на торец (90°, 270°, 60°) → не фронтально'),
                     (pf(Vc, 0) is None and pf(None, 0) is None, 'квадрат в плане / нет вершин → None'),
                     (pf(Vb, 45) is True, 'габарит: ровно 45° → фронтально (порог ≤ frontal_max_deg)')):
        print(('  ✓ ' if ok else '  ✗ ') + name)
        bad += 0 if ok else 1
    print('FAIL' if bad else 'OK', bad)
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(selftest() if '--selftest' in sys.argv else 0)
