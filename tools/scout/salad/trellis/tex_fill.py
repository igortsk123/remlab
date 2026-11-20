#!/usr/bin/env python3
"""ЗАЛИВКА НЕВИДИМОГО (T-20261120-164; план paint-photo-fill-01, шаги 4–5): текстура, где видимое с камеры фото осталось как есть, а невидимое залито ТОЙ ЖЕ ЧАСТЬЮ — программой, без нейросети и без платного.
Бесплатно, на процессоре, numpy + scipy + trimesh (+ PIL). Вход — GLB (форма, развёртка, текстура), маска «тексель известен» по каждой геометрии (видим с камеры фото, не вскользь, покрашен),
маски частей (по граням; нет частей — одна часть). Выход — новая текстура + отчёт-счётчики; форма и развёртка не меняются.

ПРАВИЛО (владелец, TG 101: «цвет и манера видимого бока — образец для всех невидимых граней»), порядок по каждому невидимому тексель-у:
  1. ЗЕРКАЛО. Если предмет симметричен (плоскость X или Z через центр габарита: большая доля точек поверхности имеет «двойника» с той же нормалью), тексель берёт цвет ЗЕРКАЛЬНОГО известного тексела
     ТОЙ ЖЕ части (диваны, кресла: второй подлокотник и бок). Только если зеркальная точка найдена в пределах `mirror_eps` и нормаль совпала.
  2. ГЕОДЕЗИЧЕСКАЯ ЗАЛИВКА. От известных текселей по ПОВЕРХНОСТИ (граф рёбер меша, дейкстра): цвет ближайшего известного места той же части, с затуханием `exp(−расстояние / geo_len)` к среднему цвету
     части (Lab). Путь идёт только по рёбрам граней ЭТОЙ части и ЭТОГО островка развёртки — вершины у швов развёртки не общие, граница части в граф не входит, поэтому цвет не «перетекает» через границу части
     и островка. Нет известного места в своём островке и части — среднее Lab части (нет и его — среднее по всем частям предмета: счётчик `fallback_global`).
  3. ФАКТУРА. К цвету добавляется бесшовный образец ВЫСОКОЙ частоты (остаток Lab над размытием) с «чистого» известного участка той же части (блок из текселей только этой части и одного островка, без швов,
     по типичной контрастности, не крайней). Копируется только статистика/текстура-остаток, не картинка: образец без среднего, размножен двумя разными по сдвигу и повороту плитками, амплитуда
     подогнана к разбросу известного остатка части (гейн в пределах `gain_min..gain_max`). Нет чистого блока — заливка гладкая (счётчик `no_patch`).
  Края: поле известного не меняется ни на единицу (кроме желоба вне островков — он дублирует ближайший цвет островка на `gutter` пикселей, чтобы билинейная выборка у шва не брала фон).

ПРОВЕРКА ПОКРЫТИЯ (шаг 5): после заливки `unpainted_after` — доля текселей островков с мерой `tex_coverage.UNPAINTED_SG` (ровный чёрный ≤3, магента) среди ВСЕХ текселей карты; должна быть 0.
Известное = видимое с камеры фото И не вскользь И покрашено: чёрные/магентовые тексели заливаются, даже если камера их видела (там краска не легла).
Все числа — `FILL` вверху файла. ID товаров в код не попадают.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tex_coverage as TC  # noqa: E402

FILL = {
    'photo_azimuths': (0.0, 45.0),   # камеры «фото»: азимут от лица предмета (0 = в лоб, +X вправо), градусы; подменяется камерой T-112 через `known` напрямую
    'photo_res': 1024,               # буфер глубины вида, пикселей
    'photo_ortho': 1.8,              # сторона ортографического кадра (наибольшая сторона габарита = 1; диагональ куба 1,73)
    'cos_min': 0.35,                 # ниже — «вскользь» (как COS_GRAZE меры охвата): тексель не образец
    'erode_known': 1,                # отступ известного от границы известного/неизвестного, пикселей карты
    'min_known': 200,                # меньше известных текселей у части — статистика части берётся по всему предмету
    'smooth_iter': 4,                # проходов сглаживания цвета вершин по графу части (низкие частоты; шумный цвет мелких граней)
    'hp_px': 5.0,                    # сигма размытия для остатка (высокие частоты — фактура)
    'feather_len': 0.04,             # длина растушёвки зеркального к видимому у стыка «фото → достройка», доли размера предмета (≈ несколько см для предмета в метр)
    'dL_max': 15.0,                  # потолок поправки яркости достроенного к видимому, L*
    'ao': 0.0,                       # сила затенения углублений по форме (0 — выключено)
    'step_de': 8.0,                  # скачок цвета между соседними гранями одной части, ΔE00, считается «ступенью»
    'cross_islands': True,           # геодезическая заливка идёт по поверхности через шов развёртки (шов — разрез, не граница материала); False — шов преграда (только внутри островка)
    'geo_len': 0.12,                 # длина затухания геодезической заливки, доли размера предмета
    'mirror_min_score': 0.80,        # доля точек поверхности с «двойником» через плоскость, с которой предмет считается симметричным
    'mirror_eps': 0.012,             # допуск «двойника» по расстоянию, доли размера предмета
    'mirror_cos': 0.7,               # нормаль двойника (после отражения): |cos| не меньше
    'patch': 64,                     # сторона блока образца фактуры, пикселей карты
    'patch_known_min': 0.98,         # доля известных текселей в блоке, чтобы он годился (блок 64 и 32)
    'patch_known_min2': 0.90,        # то же для запасного блока 16 (известное дробное — большой блок не нашёлся)
    'gain_min': 0.5, 'gain_max': 2.0,
    'gutter': 8,                     # пикселей желоба вокруг островков
    'sample': 20000,                 # точек для оценки симметрии
}
BLACK_MAX = TC.UNPAINTED_SG['black_max']


# ---------------------------------------------------------------- цвет -----------------------------------------
def rgb2lab(rgb):
    return TC.rgb2lab(rgb)


def lab2rgb(lab):
    """Lab (N,3), D65 → sRGB uint8 (N,3); обратное к `rgb2lab`."""
    lab = np.asarray(lab, np.float64)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    d = 6 / 29

    def inv(f):
        return np.where(f > d, f ** 3, 3 * d * d * (f - 4 / 29))
    xyz = np.stack([inv(fx), inv(fy), inv(fz)], 1) * np.array([0.95047, 1.0, 1.08883])
    M = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ M.T, 0.0, 1.0)
    c = np.where(c > 0.0031308, 1.055 * np.power(c, 1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255.0), 0, 255).astype(np.uint8)


def unpainted_mask(rgb):
    """Мера «не закрашено» сторожа покрытия (StableGen): ровный чёрный или магента — одна и та же, что в `tex_coverage.analyze(rig=…)`."""
    u = TC.UNPAINTED_SG
    rgb = np.asarray(rgb)
    return (rgb.max(axis=-1) <= u['black_max']) | ((rgb[..., 0] >= u['r_min']) & (rgb[..., 1] <= u['g_max']) & (rgb[..., 2] >= u['b_min']))


# ---------------------------------------------------------------- видимость с камеры фото ----------------------
def photo_views(azimuths=None) -> list:
    """Камеры фото как виды (на_камеру, вправо, вверх) в кадре GLB (лицом +Z, Y вверх): азимут 0 — в лоб, 90 — справа (+X), 180 — сзади."""
    az = FILL['photo_azimuths'] if azimuths is None else azimuths
    out = []
    for a in az:
        r = np.radians(a)
        c = np.array([np.sin(r), 0.0, np.cos(r)])
        right = np.cross([0.0, 1.0, 0.0], c)
        right /= np.linalg.norm(right)
        out.append((c, right, np.cross(c, right)))
    return out


def frame_of(geoms: list):
    """Центр и наибольшая сторона габарита всех геометрий вместе → точки куба P (как у меры охвата без поворота)."""
    V = np.concatenate([np.asarray(g['V'], np.float64) for g in geoms])
    lo, hi = V.min(axis=0), V.max(axis=0)
    ctr, size = (lo + hi) / 2.0, float(max((hi - lo).max(), 1e-9))
    return ctr, size


def _weld(key):
    """Номера склеенных вершин: строки `key` (N,k) с одинаковым значением — одна вершина."""
    _u, inv = np.unique(np.asarray(key), axis=0, return_inverse=True)
    return np.asarray(inv).reshape(-1)


def _islands(F, uvw):
    """Номер островка развёртки у каждой грани: грани, связанные общими вершинами, склеенными по UV (в GLB вершины не слиты: на каждый угол грани своя вершина)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nf = len(F)
    rows = np.repeat(np.arange(nf), 3)
    cols = nf + np.asarray(uvw)[np.asarray(F)].reshape(-1)
    n = nf + int(np.max(uvw)) + 1
    _n, lab = connected_components(coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)), directed=False)
    return lab[:nf]


class Tex:
    """Растр развёртки одной геометрии: у каждого занятого тексела — грань, точка и нормаль в 3D, часть, островок."""

    def __init__(self, g, P, T: int, part_of_face=None, cross_islands: bool = True):
        self.T = T
        F = np.asarray(g['F'], np.int64)
        UV = np.asarray(g['UV'], np.float64)
        xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
        ids, _ = TC.raster(xy, F, T)
        self.ids = ids
        ti = np.nonzero(ids >= 0)[0]
        self.ti = ti
        f = ids[ti].astype(np.int64)
        self.f = f
        a_, b_, c_ = F[f, 0], F[f, 1], F[f, 2]
        px, py = (ti % T) + 0.5, (ti // T) + 0.5
        A, B, C = xy[a_], xy[b_], xy[c_]
        ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
        wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
        wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
        self.bary = np.stack([wa, wb, 1.0 - wa - wb], 1)
        self.F = F
        self.UV = UV
        self.P = P
        self.Q = self.bary[:, :1] * P[a_] + self.bary[:, 1:2] * P[b_] + self.bary[:, 2:3] * P[c_]
        n3 = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        self.fnorm = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
        self.N = self.fnorm[f]
        self.part_f = np.zeros(len(F), np.int32) if part_of_face is None else np.asarray(part_of_face, np.int32)
        self.part = self.part_f[f]
        uvw = _weld(np.round(UV * 1e5).astype(np.int64))
        self.island_f = _islands(F, uvw)
        # вершины склеены по 3D-позиции (шов развёртки — разрез, не разрыв поверхности): граф геодезической заливки; cross_islands=False — ещё и по UV (шов — преграда)
        key = np.round(P * 1e6).astype(np.int64)
        if not cross_islands:
            key = np.hstack([key, uvw[:, None]])
        self.W = _weld(key)
        self.FW = self.W[F]
        self.PW = np.zeros((int(self.W.max()) + 1, 3))
        self.PW[self.W] = P
        self.island = self.island_f[f]


# ---------------------------------------------------------------- известное: видимость с камер фото ------------
def known_from_photo(geoms: list, azimuths=None, res: int | None = None, cos_min: float | None = None, parts=None) -> list:
    """Маски «тексель виден с камер фото» по каждой геометрии (T×T bool): глубина вида — первая грань вдоль луча, угол к камере лучше `cos_min`, тексель покрашен (не чёрный/магента).
    Это ТОЛЬКО видимость; отступ от границы — в `fill`. Камеру T-112 подставляют готовой маской вместо этой функции."""
    res = int(res or FILL['photo_res'])
    cos_min = FILL['cos_min'] if cos_min is None else cos_min
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    Fall = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    cams = []
    ortho = FILL['photo_ortho']
    for v in photo_views(azimuths):
        x, y, d = TC.project(P, v, ortho)
        cams.append((v, TC.raster(np.stack([x * res, y * res], 1), Fall, res, d)[1]))
    out = []
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, P[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi])
        seen = np.zeros(len(tx.ti), bool)
        for v, zb in cams:
            x, y, d = TC.project(tx.Q, v, ortho)
            cs = np.abs(tx.N @ v[0])
            ix = np.clip(np.floor(x * res).astype(np.int64), 0, res - 1)
            iy = np.clip(np.floor(y * res).astype(np.int64), 0, res - 1)
            eps = TC.DEPTH_EPS + (ortho / res) * np.sqrt(np.maximum(1.0 - cs * cs, 0.0)) / np.maximum(cs, TC.COS_SEEN)
            seen |= (zb[iy * res + ix] <= d + eps) & (cs > cos_min)
        m = np.zeros(T * T, bool)
        m[tx.ti] = seen
        out.append(m.reshape(T, T))
    return out


def _grid(g, cap: int = 2048) -> int:
    H, W = np.asarray(g['tex']).shape[:2]
    if H != W:
        raise ValueError('текстура не квадратная: заливка работает по квадратной карте')
    return int(min(H, cap)) if H <= cap else int(H)


# ---------------------------------------------------------------- вспомогательные --------------------------------
def _blur_norm(img, known, sigma: float):
    """Размытие известного с нормировкой по весу (неизвестное не вносит чёрного): img (T,T,3) float, known (T,T) bool → (T,T,3), вес (T,T)."""
    from scipy.ndimage import gaussian_filter
    w = known.astype(np.float64)
    num = np.stack([gaussian_filter(img[..., k] * w, sigma, mode='nearest') for k in range(3)], -1)
    den = gaussian_filter(w, sigma, mode='nearest')
    return num / np.maximum(den, 1e-9)[..., None], den


def symmetry(txs: list, known_flat: list, size_eps: float, sample: int, cos_min: float) -> dict:
    """Оценка симметрии: доля точек поверхности, у которых через плоскость X (или Z) через центр есть «двойник» (ближе `size_eps`, нормаль после отражения совпала). → {axis, score, planes}."""
    from scipy.spatial import cKDTree
    Q = np.concatenate([t.Q for t in txs])
    N = np.concatenate([t.N for t in txs])
    rng = np.random.RandomState(11)
    sel = rng.choice(len(Q), min(sample, len(Q)), replace=False) if len(Q) else np.zeros(0, int)
    tree = cKDTree(Q)
    best = {'axis': None, 'score': 0.0, 'planes': {}}
    for axis in (0, 2):
        R = np.ones(3)
        R[axis] = -1
        d, j = tree.query(Q[sel] * R, k=1, distance_upper_bound=size_eps)
        okj = np.isfinite(d)
        cs = np.abs((N[sel] * R * N[np.where(okj, j, 0)]).sum(axis=1))
        score = float((okj & (cs > cos_min)).mean()) if len(sel) else 0.0
        best['planes'][int(axis)] = round(score, 3)
        if score > best['score']:
            best['axis'], best['score'] = axis, score
    best['score'] = round(best['score'], 3)
    return best


def _gaussian_tile(patch, rng):
    """Бесшовная плитка из блока остатка (B,B,3): смесь блока и его сдвига на пол-блока с весами, сохраняющими разброс (sin·sin и √(1−w²)) → периодична по обеим осям."""
    B = patch.shape[0]
    x = np.arange(B)
    w1 = (np.sin(np.pi * x / B)[:, None] * np.sin(np.pi * x / B)[None, :])[..., None]
    w2 = np.sqrt(np.maximum(1.0 - w1 * w1, 0.0))
    p = patch - patch.mean(axis=(0, 1), keepdims=True)
    return w1 * p + w2 * np.roll(p, (B // 2, B // 2), axis=(0, 1))


def concavity(tx, smooth: int = 2):
    """Вогнутость по склеенным вершинам: (среднее соседей − вершина)·нормаль / средняя длина ребра, сглажено; >0 — впадина (нормали наружу, грани против часовой). → (nW,) float."""
    from scipy.sparse import coo_matrix
    FW, PW = tx.FW, tx.PW
    nW = len(PW)
    nrm = np.zeros((nW, 3))
    for i in range(3):
        for k in range(3):
            nrm[:, k] += np.bincount(FW[:, i], weights=tx.fnorm[:, k], minlength=nW)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]
    e = np.unique(np.sort(np.concatenate([FW[:, [0, 1]], FW[:, [1, 2]], FW[:, [2, 0]]]), axis=1), axis=0)
    e = e[e[:, 0] != e[:, 1]]
    A = coo_matrix((np.ones(2 * len(e)), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(nW, nW)).tocsr()
    deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1.0)
    lap = (A @ PW) / deg[:, None] - PW
    el = float(np.linalg.norm(PW[e[:, 0]] - PW[e[:, 1]], axis=1).mean()) if len(e) else 1.0
    cv = (lap * nrm).sum(axis=1) / max(el, 1e-9)
    for _ in range(smooth):
        cv = (A @ cv + cv) / (deg + 1.0)
    return cv


def step_stats(tx, rgb, thr: float) -> dict:
    """«Ступени» внутри части: резкий скачок цвета (ΔE00 > thr) между соседними гранями ОДНОЙ части вдоль поверхности (соседство — по склеенным вершинам). → доля граней со ступенью, доля пар,
    то же среди «достроенных» граней (больше половины их текселей неизвестны — передаётся в tx.unk_face)."""
    F, UV = tx.F, np.asarray(tx.UV)
    T = tx.T
    cu = UV[F].mean(axis=1)
    px = np.clip(np.floor(cu[:, 0] * T).astype(np.int64), 0, T - 1)
    py = np.clip(np.floor((1.0 - cu[:, 1]) * T).astype(np.int64), 0, T - 1)
    lab = rgb2lab(np.asarray(rgb)[py, px][:, :3])
    nf = len(F)
    ew = np.concatenate([tx.FW[:, [0, 1]], tx.FW[:, [1, 2]], tx.FW[:, [2, 0]]])
    ew = np.sort(ew, axis=1)
    fi = np.concatenate([np.arange(nf)] * 3)
    ok = ew[:, 0] != ew[:, 1]
    ew, fi = ew[ok], fi[ok]
    key = ew[:, 0].astype(np.int64) * (int(tx.FW.max()) + 1) + ew[:, 1]
    o = np.argsort(key, kind='stable')
    key, fi = key[o], fi[o]
    same = key[1:] == key[:-1]
    a, b = fi[:-1][same], fi[1:][same]
    keep = (a != b) & (tx.part_f[a] == tx.part_f[b])
    a, b = a[keep], b[keep]
    if len(a) == 0:
        return {'pairs': 0, 'faces_step_pct': 0.0, 'pairs_step_pct': 0.0, 'filled_faces_step_pct': None}
    de = TC.de2000_v(lab[a], lab[b])
    st = de > thr
    faces = np.zeros(nf, bool)
    faces[a[st]] = True
    faces[b[st]] = True
    inpair = np.zeros(nf, bool)
    inpair[a] = True
    inpair[b] = True
    uf = getattr(tx, 'unk_face', None)
    fl = None
    if uf is not None and (inpair & uf).any():
        fl = round(100.0 * float((faces & uf).sum()) / float((inpair & uf).sum()), 2)
    return {'pairs': int(len(a)), 'faces_step_pct': round(100.0 * float(faces.sum()) / max(int(inpair.sum()), 1), 2),
            'pairs_step_pct': round(100.0 * float(st.mean()), 2), 'filled_faces_step_pct': fl}


# ---------------------------------------------------------------- заливка ---------------------------------------
def fill(geoms: list, known: list, parts: list | None = None, cfg: dict | None = None, mirror: bool = True) -> dict:
    """geoms — `tex_coverage.load_geoms`; known — по геометрии (T×T bool), parts — по геометрии номера частей ГРАНЕЙ (None — одна часть).
    → {'tex': [uint8 (T,T,3) по геометриям], 'report': {...}}. Форма и развёртка не меняются."""
    from scipy.ndimage import binary_erosion, distance_transform_edt
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    c = dict(FILL, **(cfg or {}))
    t0 = time.time()
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Pall = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    txs, labs, kn, tex_in = [], [], [], []
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, Pall[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi], c['cross_islands'])
        rgb = np.asarray(g['tex'])[..., :3]
        if rgb.shape[0] != T:
            raise ValueError('текстура больше сетки карты (cap) — загрузите с её размером')
        k = np.asarray(known[gi], bool).copy()
        if c['erode_known'] > 0:
            k = binary_erosion(k, iterations=int(c['erode_known']))
        k &= ~unpainted_mask(rgb)
        txs.append(tx)
        kn.append(k)
        tex_in.append(rgb)
        labs.append(rgb2lab(rgb.reshape(-1, 3)).reshape(T, T, 3))
    rep = {'geoms': [], 'parts': {}, 'mirror': None, 'fallback_global': 0, 'no_patch': 0, 'time_s': {}}
    # --- статистика частей (Lab среднее и разброс), по известным
    part_ids = sorted({int(p) for t in txs for p in np.unique(t.part)})
    stat, glob_l = {}, []
    for gi, tx in enumerate(txs):
        glob_l.append(labs[gi].reshape(-1, 3)[kn[gi].reshape(-1)])
    glob_l = np.concatenate(glob_l) if glob_l else np.zeros((0, 3))
    g_mean = np.median(glob_l, axis=0) if len(glob_l) else np.array([50.0, 0.0, 0.0])
    g_std = glob_l.std(axis=0) if len(glob_l) else np.zeros(3)
    for p in part_ids:
        L = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        if len(L) >= c['min_known']:
            stat[p] = (np.median(L, axis=0), L.std(axis=0), len(L), False)
        else:
            stat[p] = (g_mean, g_std, len(L), True)
            rep['fallback_global'] += 1
        rep['parts'][p] = {'known_texels': int(len(L)), 'mean_lab': [round(float(x), 2) for x in stat[p][0]], 'std_lab': [round(float(x), 2) for x in stat[p][1]], 'stats_from_global': stat[p][3]}
    rep['time_s']['prepare'] = round(time.time() - t0, 2)
    # --- шаг 1: зеркало
    out_lab = [lb.copy() for lb in labs]
    done = [k.copy() for k in kn]                  # известное или уже залитое зеркалом/геодезией (источник дальнейших шагов)
    mirrored = [np.zeros_like(k) for k in kn]
    sym = symmetry(txs, kn, c['mirror_eps'], c['sample'], c['mirror_cos']) if mirror else {'axis': None, 'score': 0.0, 'planes': {}}
    rep['mirror'] = {'axis': sym['axis'], 'score': sym['score'], 'planes': sym['planes'], 'applied': False, 'texels': 0}
    if mirror and sym['axis'] is not None and sym['score'] >= c['mirror_min_score']:
        R = np.ones(3)
        R[sym['axis']] = -1
        rep['mirror']['applied'] = True
        for p in part_ids:
            srcQ, srcN, srcL = [], [], []
            for gi, tx in enumerate(txs):
                kk = kn[gi].reshape(-1)[tx.ti] & (tx.part == p)
                srcQ.append(tx.Q[kk])
                srcN.append(tx.N[kk])
                srcL.append(labs[gi].reshape(-1, 3)[tx.ti[kk]])
            srcQ, srcN, srcL = np.concatenate(srcQ), np.concatenate(srcN), np.concatenate(srcL)
            if len(srcQ) == 0:
                continue
            tree = cKDTree(srcQ)
            for gi, tx in enumerate(txs):
                unk = (~done[gi].reshape(-1)[tx.ti]) & (tx.part == p)
                if not unk.any():
                    continue
                d, j = tree.query(tx.Q[unk] * R, k=1, distance_upper_bound=c['mirror_eps'] * 1.5)
                okj = np.isfinite(d)
                jj = np.where(okj, j, 0)
                cs = np.abs((tx.N[unk] * R * srcN[jj]).sum(axis=1))
                use = okj & (cs > c['mirror_cos'])
                idx = tx.ti[np.nonzero(unk)[0][use]]
                flat = out_lab[gi].reshape(-1, 3)
                flat[idx] = srcL[jj[use]]
                done[gi].reshape(-1)[idx] = True
                mirrored[gi].reshape(-1)[idx] = True
                rep['mirror']['texels'] += int(use.sum())
    rep['time_s']['mirror'] = round(time.time() - t0, 2)
    # --- шаг 2: геодезическая заливка (низкие частоты) по поверхности ТОЙ ЖЕ части; зеркальное достраивается растушёвкой от известного
    lam_all, unk_all = [], []
    for gi, g in enumerate(geoms):
        tx = txs[gi]
        nvw = len(tx.PW)
        kflat = kn[gi].reshape(-1)[tx.ti]
        mflat = mirrored[gi].reshape(-1)[tx.ti]
        unk = ~kflat
        lab_flat = out_lab[gi].reshape(-1, 3)
        lam_t = np.zeros(len(tx.ti))
        for p in sorted({int(x) for x in np.unique(tx.part_f)}):
            Fp = tx.FW[tx.part_f == p]
            tsel = unk & (tx.part == p)
            if len(Fp) == 0 or not tsel.any():
                continue
            e = np.unique(np.sort(np.concatenate([Fp[:, [0, 1]], Fp[:, [1, 2]], Fp[:, [2, 0]]]), axis=1), axis=0)
            e = e[e[:, 0] != e[:, 1]]
            ln = np.linalg.norm(tx.PW[e[:, 0]] - tx.PW[e[:, 1]], axis=1) + 1e-9
            gr = coo_matrix((np.concatenate([ln, ln]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(nvw, nvw)).tocsr()
            used = np.zeros(nvw, bool)
            used[Fp.reshape(-1)] = True
            Wn = gr.copy()
            Wn.data = np.ones_like(Wn.data)

            def field(src_tex):
                """Источник — тексели `src_tex` (bool по занятым) этой части → расстояние по поверхности до ближайшего источника и его (сглаженный по графу) цвет, по склеенным вершинам."""
                vw = np.zeros(nvw)
                vc = np.zeros((nvw, 3))
                sm = src_tex & (tx.part == p)
                fk, bk, lk = tx.f[sm], tx.bary[sm], lab_flat[tx.ti[sm]]
                for i in range(3):
                    vi = tx.FW[fk, i]
                    vw += np.bincount(vi, weights=bk[:, i], minlength=nvw)
                    for ch in range(3):
                        vc[:, ch] += np.bincount(vi, weights=bk[:, i] * lk[:, ch], minlength=nvw)
                vknown = vw > 1e-6
                wk = vknown.astype(np.float64)
                vcol = np.where(vknown[:, None], vc / np.maximum(vw, 1e-12)[:, None], 0.0)
                for _ in range(int(c['smooth_iter'])):
                    num = Wn @ (vcol * wk[:, None]) + vcol * wk[:, None]
                    den = Wn @ wk + wk
                    vcol = np.where((den > 0)[:, None], num / np.maximum(den, 1e-12)[:, None], 0.0)
                src = np.nonzero(vknown & used)[0]
                dist = np.full(nvw, np.inf)
                col = np.zeros((nvw, 3))
                if len(src):
                    d, _pred, srcs = dijkstra(gr, directed=False, indices=src, min_only=True, return_predecessors=True)
                    reach = np.isfinite(d) & used & (srcs >= 0)
                    dist[reach] = d[reach]
                    col[reach] = vcol[srcs[reach]]
                return dist, col

            def at_texels(dist, col, length, sel):
                """Вес стороны источника exp(−d/length) и её цвет на текселях `sel` (барицентрическая интерполяция весов и цвет·вес)."""
                lv = np.where(np.isfinite(dist), np.exp(-np.where(np.isfinite(dist), dist, 0.0) / length), 0.0)
                ff, wv = tx.f[sel], tx.bary[sel]
                av = lv[tx.FW[ff]]
                at = (wv * av).sum(axis=1)
                ct = (wv[..., None] * (av[..., None] * col[tx.FW[ff]])).sum(axis=1)
                return at, ct / np.maximum(at, 1e-9)[:, None]

            msel_t = tsel & mflat                        # зеркальные: растушёвка к известному у стыка «фото → достройка»
            gsel_t = tsel & ~mflat                       # прочие: затухание от известного и зеркального к цвету части
            if gsel_t.any():
                dist_a, col_a = field(kflat | mflat)
                at, gc = at_texels(dist_a, col_a, c['geo_len'], gsel_t)
                flat_idx = tx.ti[gsel_t]
                lab_flat[flat_idx] = at[:, None] * gc + (1.0 - at[:, None]) * stat[p][0]
                lam_t[gsel_t] = at
            if msel_t.any():
                dist_k, col_k = field(kflat)
                at, gc = at_texels(dist_k, col_k, c['feather_len'], msel_t)
                flat_idx = tx.ti[msel_t]
                lab_flat[flat_idx] = at[:, None] * gc + (1.0 - at[:, None]) * lab_flat[flat_idx]
                lam_t[msel_t] = at
        lam_all.append(lam_t)
        unk_all.append(unk)
        rep['geoms'].append({'texels': int(len(tx.ti)), 'known': int(kflat.sum()), 'mirrored': int(mflat.sum()),
                             'geodesic': int((unk & ~mflat & (lam_t >= 0.5)).sum()), 'part_mean': int((unk & ~mflat & (lam_t < 0.5)).sum())})
    rep['time_s']['geodesic'] = round(time.time() - t0, 2)
    # --- выравнивание яркости достроенного к видимому той же части (медиана L; поправка гаснет к стыку, зеркальное не трогаем)
    rep['brightness'] = {}
    for p in part_ids:
        vals = [out_lab[gi].reshape(-1, 3)[tx.ti[unk_all[gi] & ~mirrored[gi].reshape(-1)[tx.ti] & (tx.part == p) & (lam_all[gi] < 0.2)]][:, 0] for gi, tx in enumerate(txs)]
        vals = np.concatenate(vals)
        if len(vals) < 50:
            continue
        shift = float(np.clip(stat[p][0][0] - np.median(vals), -c['dL_max'], c['dL_max']))
        rep['brightness'][p] = {'dL_before': round(float(np.median(vals) - stat[p][0][0]), 2), 'applied': 0.0}
        if abs(shift) < 0.5:
            continue
        for gi, tx in enumerate(txs):
            sel = unk_all[gi] & ~mirrored[gi].reshape(-1)[tx.ti] & (tx.part == p)
            out_lab[gi].reshape(-1, 3)[tx.ti[sel], 0] += shift * (1.0 - lam_all[gi][sel])
        rep['brightness'][p]['applied'] = round(shift, 2)
    # --- лёгкое затенение углублений по форме (AO-подобно, опция `ao` > 0): L *= 1 − ao·вогнутость
    if c['ao'] > 0:
        for gi, tx in enumerate(txs):
            cv = concavity(tx)
            ff, wv = tx.f, tx.bary
            ct = (wv * cv[tx.FW[ff]]).sum(axis=1)
            sel = unk_all[gi]
            out_lab[gi].reshape(-1, 3)[tx.ti[sel], 0] *= 1.0 - c['ao'] * np.clip(ct[sel], 0.0, 1.0)
        rep['ao'] = c['ao']
    # --- шаг 3: фактура (остаток высоких частот известного участка той же части), только на залитое не зеркалом
    rng = np.random.RandomState(5)
    patches, patch_gain = {}, {}
    blk = {}                                                  # по геометрии: остаток, номер части и островка (пиксель карты)
    for gi, tx in enumerate(txs):
        T = tx.T
        pm = np.zeros((T, T), np.int32) - 1
        pm.reshape(-1)[tx.ti] = tx.part
        im = np.zeros((T, T), np.int64) - 1
        im.reshape(-1)[tx.ti] = tx.island
        blur, _ = _blur_norm(labs[gi], kn[gi], c['hp_px'])
        blk[gi] = (labs[gi] - blur, pm, im)
    for p in part_ids:
        for B, thr in ((int(c['patch']), c['patch_known_min']), (int(c['patch']) // 2, c['patch_known_min']), (int(c['patch']) // 4, c['patch_known_min2'])):
            cands = []
            for gi, tx in enumerate(txs):
                T = tx.T
                res_, pm, im = blk[gi]
                n = T // B
                if n < 1:
                    continue
                m = n * B

                def tiles(a):
                    ex = a.shape[2:]
                    return a[:m, :m].reshape(n, B, n, B, *ex).transpose(0, 2, 1, 3, *range(4, 4 + len(ex))).reshape(n, n, B * B, *ex)
                kf = tiles(kn[gi]).mean(axis=2)
                pb, ib = tiles(pm), tiles(im)
                okb = (kf >= thr) & (pb.min(axis=2) == p) & (pb.max(axis=2) == p) & (ib.min(axis=2) == ib.max(axis=2))
                rb = tiles(res_)
                for by, bx in zip(*np.nonzero(okb)):
                    blkr = rb[by, bx].reshape(B, B, 3)
                    cands.append((float(blkr.std()), blkr.copy()))
            if cands:
                ss = np.array([x[0] for x in cands])
                med = float(np.median(ss))
                pick = cands[int(np.argmin(np.abs(ss - med)))]
                patches[p] = pick[1]
                patch_gain[p] = med / max(pick[0], 1e-6)       # типичный блок по контрастности; амплитуда подгоняется к медиане разброса известного
                break
        else:
            rep['no_patch'] += 1
    for gi, tx in enumerate(txs):
        T = tx.T
        unk_flat = (~kn[gi].reshape(-1)[tx.ti]) & (~mirrored[gi].reshape(-1)[tx.ti])
        if not unk_flat.any():
            continue
        px, py = tx.ti[unk_flat] % T, tx.ti[unk_flat] // T
        add = np.zeros((len(px), 3))
        for p in part_ids:
            if p not in patches:
                continue
            sel = tx.part[unk_flat] == p
            if not sel.any():
                continue
            Bp = patches[p].shape[0]
            tile = _gaussian_tile(patches[p], rng)
            ox1, oy1 = rng.randint(0, Bp, 2)
            ox2, oy2 = rng.randint(0, Bp, 2)
            t2 = np.rot90(tile)
            r1 = tile[(py[sel] + oy1) % Bp, (px[sel] + ox1) % Bp]
            r2 = t2[(py[sel] * 3 // 2 + oy2) % Bp, (px[sel] * 3 // 2 + ox2) % Bp]
            gain = float(np.clip(patch_gain[p], c['gain_min'], c['gain_max']))
            add[sel] = gain * (r1 + r2) / np.sqrt(2.0)
        out_lab[gi].reshape(-1, 3)[tx.ti[unk_flat]] += add
    rep['time_s']['texture'] = round(time.time() - t0, 2)
    # --- итог: RGB, желоб, проверка покрытия
    outs = []
    for gi, tx in enumerate(txs):
        T = tx.T
        rgb = tex_in[gi].copy()
        new = lab2rgb(out_lab[gi].reshape(-1, 3)[tx.ti])
        keepk = kn[gi].reshape(-1)[tx.ti]
        rgb.reshape(-1, 3)[tx.ti[~keepk]] = new[~keepk]
        occ = np.zeros((T, T), bool)
        occ.reshape(-1)[tx.ti] = True
        if c['gutter'] > 0:
            dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
            g_ = (~occ) & (dist <= c['gutter'])
            rgb[g_] = rgb[iy[g_], ix[g_]]
        outs.append(rgb)
        bad_before = int((unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti])).sum())
        bad_after = int((unpainted_mask(rgb.reshape(-1, 3)[tx.ti])).sum())
        rep['geoms'][gi].update({'unpainted_before': bad_before, 'unpainted_after': bad_after})
        nfc = np.bincount(tx.f, minlength=len(tx.F)).astype(np.float64)
        tx.unk_face = (np.bincount(tx.f, weights=(~kn[gi].reshape(-1)[tx.ti]).astype(np.float64), minlength=len(tx.F)) > 0.5 * np.maximum(nfc, 1.0)) & (nfc > 0)
        rep['geoms'][gi]['steps'] = {'before': step_stats(tx, tex_in[gi], c['step_de']), 'after': step_stats(tx, rgb, c['step_de'])}
    n_all = sum(r['texels'] for r in rep['geoms'])
    rep['texels'] = n_all
    rep['known_pct'] = round(100.0 * sum(r['known'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['mirrored_pct'] = round(100.0 * sum(r['mirrored'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['geodesic_pct'] = round(100.0 * sum(r['geodesic'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['part_mean_pct'] = round(100.0 * sum(r['part_mean'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['unpainted_before_pct'] = round(100.0 * sum(r['unpainted_before'] for r in rep['geoms']) / max(n_all, 1), 3)
    rep['unpainted_after_pct'] = round(100.0 * sum(r['unpainted_after'] for r in rep['geoms']) / max(n_all, 1), 3)
    rep['steps'] = {}
    for k in ('before', 'after'):
        ss = [r['steps'][k] for r in rep['geoms']]
        n = max(sum(x['pairs'] for x in ss), 1)
        rep['steps'][k] = {'faces_step_pct': round(sum(x['faces_step_pct'] * x['pairs'] for x in ss) / n, 2),
                           'pairs_step_pct': round(sum(x['pairs_step_pct'] * x['pairs'] for x in ss) / n, 2),
                           'filled_faces_step_pct': (round(sum((x['filled_faces_step_pct'] or 0.0) * x['pairs'] for x in ss) / n, 2) if any(x['filled_faces_step_pct'] is not None for x in ss) else None)}
    rep['time_s']['all'] = round(time.time() - t0, 2)
    return {'tex': outs, 'report': rep}


# ---------------------------------------------------------------- кадры «до | после» -------------------------------
def render_ortho(geoms: list, texs: list, azimuth: float = 180.0, res: int = 1024, ortho: float = 1.25):
    """Ортографический кадр предмета с заданного азимута (0 — в лоб, 180 — сзади) с текстурами `texs` (по геометриям): цвет текстуры × освещение лоб-светом. Для проб, не для продукта."""
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    F = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    fg = np.concatenate([np.full(len(g['F']), i) for i, g in enumerate(geoms)])
    UV = np.concatenate([np.asarray(g['UV'], np.float64) for g in geoms])
    v = photo_views([azimuth])[0]
    x, y, d = TC.project(P, v, ortho)
    xy = np.stack([x * res, y * res], 1)
    ids, _zb = TC.raster(xy, F, res, d)
    hit = np.nonzero(ids >= 0)[0]
    f = ids[hit].astype(np.int64)
    px, py = (hit % res) + 0.5, (hit // res) + 0.5
    A, B, C = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
    wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
    uv = wa[:, None] * UV[F[f, 0]] + wb[:, None] * UV[F[f, 1]] + (1.0 - wa - wb)[:, None] * UV[F[f, 2]]
    n3 = np.cross(P[F[f, 1]] - P[F[f, 0]], P[F[f, 2]] - P[F[f, 0]])
    n3 /= np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    col = np.zeros((len(hit), 3))
    for gi in range(len(geoms)):
        s = fg[f] == gi
        if not s.any():
            continue
        tex = np.asarray(texs[gi])
        H, W = tex.shape[:2]
        tx_ = np.clip(np.floor(uv[s, 0] * W).astype(np.int64), 0, W - 1)
        ty_ = np.clip(np.floor((1.0 - uv[s, 1]) * H).astype(np.int64), 0, H - 1)
        col[s] = tex[ty_, tx_][:, :3]
    img = np.full((res * res, 3), 245.0)
    img[hit] = col * (0.40 + 0.60 * np.abs(n3 @ v[0]))[:, None]
    return img.reshape(res, res, 3).astype(np.uint8)
