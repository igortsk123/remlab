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
    print('FAIL' if bad else 'OK', bad)
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(selftest() if '--selftest' in sys.argv else 0)
