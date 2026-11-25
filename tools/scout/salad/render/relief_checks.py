"""Мерка «глубокие борозды стёжки на сиденье мягкой обивки» (T-20261124-57, П1.160; паспорт `plans/mesh-type-rules-01.md`, строка 20.11 «T-156/1 (р.6)»).

Это порт замера T-156 (`relieflib.py` + `bth156.py`, отчёт `~/remlab-logs/t156-1120/itog.md`) в код этапа 02 «форма» (`form_checks.py`, режим OBSERVE): только число и «сработало бы»,
выход шага (форма) не трогается.

Что меряем. Глубина борозды = «чёрная шапка» (закрытие поверхности по высоте радиусом `stitch_close_cm` минус сама высота), в см по габариту каталога, по зоне СИДЕНЬЯ:
верхние грани (нормаль опорной поверхности вверх > 0,5) в средней части высоты (0,25–0,75 H), без кромки `stitch_edge_cm`. Правило (калибровка T-156 на 17 мягких): p95 глубины
> `stitch_p95_cm` ИЛИ доля площади глубже 0,5 см > `stitch_share05_max` → «глубокие борозды». Пороги — `rules/form-checks.json`, ID товаров в коде нет; к типу привязывает только список ролей
`stitch_roles` (мягкая обивка), сам порог — по замеру.

Нужны numpy, scipy, trimesh. Вход — сетка `m` (trimesh, вершины склеены по положению) и высота каталога в см; вертикаль — Y.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse


def weld(m, tol: float = 1e-6):
    v = np.asarray(m.vertices, dtype=np.float64)
    key = np.round(v / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    f = inv[np.asarray(m.faces)]
    ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return v[first], f[ok]


def adjacency(n: int, f: np.ndarray):
    i = np.concatenate([f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]])
    j = np.concatenate([f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]])
    a = sparse.coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n)).tocsr()
    a.data[:] = 1.0
    d = np.asarray(a.sum(1)).reshape(-1)
    d[d == 0] = 1
    return sparse.diags(1.0 / d) @ a


def taubin(v: np.ndarray, w, iters: int, lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    x = v.copy()
    for _ in range(iters):
        x = x + lam * (w @ x - x)
        x = x + mu * (w @ x - x)
    return x


def vnormals(v: np.ndarray, f: np.ndarray):
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    area = np.linalg.norm(fn, axis=1) / 2
    vn = np.zeros_like(v)
    va = np.zeros(len(v))
    for k in range(3):
        np.add.at(vn, f[:, k], fn)
        np.add.at(va, f[:, k], area / 3)
    nrm = np.linalg.norm(vn, axis=1)
    nrm[nrm == 0] = 1
    return vn / nrm[:, None], va


def edge_len(v: np.ndarray, f: np.ndarray) -> float:
    e = np.concatenate([np.linalg.norm(v[f[:, a]] - v[f[:, b]], axis=1) for a, b in ((0, 1), (1, 2), (2, 0))])
    return float(np.median(e))


def erode(mask: np.ndarray, w, steps: int) -> np.ndarray:
    x = mask.astype(np.float64)
    for _ in range(steps):
        x = np.where((w @ x) > 0.999, x, 0.0)
    return x > 0.5


def dilate(mask: np.ndarray, w, steps: int) -> np.ndarray:
    x = mask.astype(np.float64)
    for _ in range(steps):
        x = np.where((w @ x) > 0.001, 1.0, x)
    return x > 0.5


def maxfilter(d: np.ndarray, w, steps: int) -> np.ndarray:
    """Максимум по соседям на `steps` шагов по поверхности."""
    ip, ix = w.indptr, w.indices
    x = d.copy()
    for _ in range(steps):
        nb = np.maximum.reduceat(x[ix], ip[:-1]) if len(ix) else x
        x = np.maximum(x, nb)
    return x


def seat_groove_stats(m, height_cm: float, p: dict, arrays: bool = False) -> dict:
    """`arrays=True` — ещё `_arrays` = (вершины в см, зона сиденья, глубина) для кадра. {'status': 'ok'|'na', 'why', 'p95', 'p50', 'max', 'share05', 'n', 'area_cm2', 'edge_cm'} — глубина борозд по зоне сиденья, см. `na` — зона сиденья не нашлась (мало вершин)."""
    v, f = weld(m)
    if len(f) == 0 or not height_cm > 0:
        return {'status': 'na', 'why': 'нет граней или высоты'}
    up = 1
    vol = float(np.einsum('ij,ij->', v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])) / 6)
    if vol < 0:                                   # грани смотрят внутрь — разворот: + = бугор, − = борозда
        f = f[:, ::-1].copy()
    ext = v.max(0) - v.min(0)
    v = (v - v.min(0)) * (height_cm / ext[up])
    e = edge_len(v, f)
    w = adjacency(len(v), f)
    _, area = vnormals(v, f)
    it = int(max(1, round((p['stitch_sigma_cm'] / e) ** 2 / 0.5)))
    ref = taubin(v, w, it)
    n_ref, _ = vnormals(ref, f)
    hgt = v[:, up]
    hh = float(hgt.max())
    ny = n_ref[:, up]
    cs = int(np.ceil(2.0 / e))
    steps = int(np.ceil(p['stitch_edge_cm'] / e))
    zone = erode(erode(dilate((ny > 0.5) & (hgt > 0.25 * hh) & (hgt < 0.75 * hh), w, cs), w, cs), w, steps)
    k = int(np.ceil(p['stitch_close_cm'] / e))
    clo = -maxfilter(-maxfilter(hgt, w, k), w, k)             # закрытие по высоте: макс, затем мин
    g = np.maximum(clo - hgt, 0.0)
    if int(zone.sum()) < int(p['stitch_min_verts']):
        return {'status': 'na', 'why': f'зона сиденья мала ({int(zone.sum())} вершин)', 'edge_cm': round(e, 3)}
    d, a = g[zone], area[zone]
    o = np.argsort(d)
    cum = np.cumsum(a[o]) / a.sum()
    q = lambda x: float(d[o][min(int(np.searchsorted(cum, x)), len(d) - 1)])
    out = {'status': 'ok', 'why': '', 'p50': round(q(0.5), 3), 'p95': round(q(0.95), 3), 'max': round(float(d.max()), 3), 'share05': round(float(a[d > 0.5].sum() / a.sum()), 4),
           'n': int(zone.sum()), 'area_cm2': round(float(a.sum())), 'edge_cm': round(e, 3)}
    if arrays:
        out['_arrays'] = (v, zone, g)
    return out
