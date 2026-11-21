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
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import tex_coverage as TC  # noqa: E402

FILL = {
    'photo_azimuths': (0.0, 45.0),   # камеры «фото»: азимут от лица предмета (0 = в лоб, +X вправо), градусы; подменяется камерой T-112 через `known` напрямую
    'photo_res': 1024,               # буфер глубины вида, пикселей
    'photo_ortho': 1.8,              # сторона ортографического кадра (наибольшая сторона габарита = 1; диагональ куба 1,73)
    'cos_min': 0.35,                 # ниже — «вскользь» (как COS_GRAZE меры охвата): тексель не образец
    'erode_known': 3,                # отступ известного от границы известного/неизвестного и края островка, пикселей карты (у края — стыки, низкая уверенность)
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
    'diffuse_iter': 150,             # проходов диффузии цвета по поверхности части: границы между «зонами ближайшего источника» размываются (без «лоскутов»)
    'far_de': 8.0,                   # мера пятен: тексель «далёк» от цвета своей части, если ΔE00 > far_de
    'quilt_block': 16, 'quilt_known_min': 0.75, 'quilt_n': 4,   # запасной лоскут фактуры: сборка quilt_n×quilt_n из мелких блоков, где известного ≥ quilt_known_min
    'tone': 'mode',                  # тон части: mode — самый частый цвет (фон, узор поверх), без затенённых; median — как раньше
    'tone_shadow_q': 0.15,           # тон: тексели темнее этого квантиля L части (затенённые складки, щели) в моду не входят
    'tone_bin': (4.0, 3.0, 3.0),     # тон: размер ячейки Lab (L, a, b) для моды; мода = медиана точек в ячейке и её соседях
    'patch_mode': 'quilt',           # фактура: quilt — сборка из мелких блоков (вся статистика частей, узор не теряется); block — один «типичный» блок 64/32/16 (как было)
    'quilt_pixels': 16,              # размер мелкого блока квилта, пикселей карты
    'quilt_known': 0.9,              # доля известного в блоке квилта
    'quilt_cells': 6,                # квилт = cells×cells блоков (не меньше `quilt_side` пикселей стороны)
    'quilt_side': 96,                # минимальная сторона плитки квилта, пикселей
    'quilt_overlap': 0.25,           # перекрытие блоков Efros–Freeman, доля блока (1/6–1/4)
    'quilt_block_min': 16, 'quilt_block_max': 48,   # блок — от периода узора (автокорреляция известного), в этих пределах
    'quilt_pool': 600,               # блоков-кандидатов на часть (шаг полблока, только чистые по части и известные)
    'quilt_tries': 40,               # случайных кандидатов на каждое место квилта
    'quilt_gain': (0.75, 1.33),      # выравнивание разброса блока к типичному: границы множителя (узорная часть; прочие — 0,6–1,6)
    'tone_dominance': 0.4,           # мода тона берётся, только если ячейка моды (с соседями) — не менее этой доли точек части; иначе медиана (ворс, полосы)
    'draft_when': 'a_fails',         # trellis с откатом: Б считается только если А не прошёл все мерки (a_fails); always — считать оба всегда
    'pattern_chroma': 1.5,           # часть, у которой МЕЛКИЙ разброс хромы (σ остатка от размытия pattern_blur_px, sqrt(σa²+σb²)) больше — «узорная»: остаток берётся от тона части (цветы/прожилки целиком), иначе — от размытия
    'pattern_blur_px': 12.0,         # размытие для отделения мелкого узора от крупных зон цвета (две большие зоны — не узор)
    'draft_blur_px': 6.0,            # trellis: размытие черновика внутри части до переноса статистики (штрих и муар черновика не переносятся)
    'draft_fallback': True,          # trellis: считать и А; взять Б, только если мерки не хуже (число непрошедших, затем ΔE00 перёд↔зад)
    'gutter': 8,                     # пикселей желоба вокруг островков
    'sample': 20000,                 # точек для оценки симметрии
    'source': 'stat',                # источник «невидимого»: stat — цвет части + лоскут фактуры; trellis — цвет черновика TRELLIS.2 со сдвигом тона (нужен draft)
    'draft_scale_min': 0.3, 'draft_scale_max': 3.0,   # потолок растяжения разброса черновика к разбросу фото части (по каналам Lab)
    'draft_texture': False,          # trellis: класть поверх ещё и лоскут фактуры (детали черновика и так сохраняются)
    'draft_cos': 0.2,                # trellis: нормаль точки черновика к нормали текселя — не меньше (иначе перёд/зад тонкой вещи путаются)
    'draft_max_dist': 0.03,          # trellis: дальше от поверхности черновика (доли размера предмета) — черновика в тексele нет
}
BLACK_MAX = TC.UNPAINTED_SG['black_max']
VIEW_CLASSES = getattr(TC, 'VIEW_CLASSES', ('низ', 'верх', 'зад', 'перёд', 'бока', 'прочее'))   # как в сторожe T-152 (tex_coverage.view_class, ветка tex-guard-152); после слияния — только TC


def view_class(nout):
    """(n,3) наружные нормали (Y вверх, перёд +Z) → индексы в VIEW_CLASSES. Та же раскладка, что `tex_coverage.view_class` (ветка tex-guard-152, 8be604ff)."""
    if hasattr(TC, 'view_class'):
        return TC.view_class(nout)
    k = np.full(len(nout), 5, np.int8)
    k[np.abs(nout[:, 0]) > 0.5] = 4
    k[nout[:, 2] > 0.5] = 3
    k[nout[:, 2] < -0.5] = 2
    k[nout[:, 1] > 0.5] = 1
    k[nout[:, 1] < -0.5] = 0
    return k


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
def photo_views(azimuths=None, elevation: float = 0.0) -> list:
    """Камеры фото как виды (на_камеру, вправо, вверх) в кадре GLB (лицом +Z, Y вверх): азимут 0 — в лоб, 90 — справа (+X), 180 — сзади; elevation — угол над горизонтом (−90 — снизу, на дно)."""
    az = FILL['photo_azimuths'] if azimuths is None else azimuths
    out = []
    for a in az:
        r = np.radians(a)
        e = np.radians(elevation)
        c = np.array([np.sin(r) * np.cos(e), np.sin(e), np.cos(r) * np.cos(e)])
        right = np.cross([0.0, 1.0, 0.0], c) if abs(c[1]) < 0.999 else np.array([1.0, 0.0, 0.0])
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


def tone_of(L, c) -> np.ndarray:
    """Тон части по Lab-точкам L (n,3): мода — самый частый цвет (фон; узор кладётся поверх остатком), без затенённых (L ниже квантиля `tone_shadow_q`). tone='median' — медиана."""
    if len(L) == 0:
        return np.array([50.0, 0.0, 0.0])
    if c['tone'] == 'median':
        return np.median(L, axis=0)
    if len(L) > 400000:
        L = L[np.random.RandomState(3).choice(len(L), 400000, replace=False)]
    M = L
    if c['tone_shadow_q'] > 0:
        keep = L[:, 0] >= np.quantile(L[:, 0], c['tone_shadow_q'])
        if keep.sum() >= max(50, 0.2 * len(L)):
            M = L[keep]
    q = np.floor(M / np.asarray(c['tone_bin'], np.float64)).astype(np.int64) + 512
    key = (q[:, 0] * 1024 + q[:, 1]) * 1024 + q[:, 2]
    u, cnt = np.unique(key, return_counts=True)
    b = int(u[int(np.argmax(cnt))])
    bq = np.array([b // (1024 * 1024), (b // 1024) % 1024, b % 1024])
    near = (np.abs(q - bq) <= 1).all(axis=1)
    if float(near.mean()) < c['tone_dominance']:             # единого фона нет (ворс, полосы, пёстрая ткань): мода случайна и тянет тон в сторону — берём медиану, как до моды
        return np.median(L, axis=0)
    return np.median(M[near], axis=0)


def _mincut_v(err: np.ndarray) -> np.ndarray:
    """Путь минимальной ошибки сверху вниз по зоне перекрытия err (H,W) → маска (H,W): True справа от пути (берём новый блок), слева — прежний."""
    H, W = err.shape
    E = err.astype(np.float64).copy()
    for i in range(1, H):
        up = E[i - 1]
        E[i] += np.minimum(np.minimum(np.r_[np.inf, up[:-1]], up), np.r_[up[1:], np.inf])
    path = np.zeros(H, np.int64)
    path[-1] = int(np.argmin(E[-1]))
    for i in range(H - 2, -1, -1):
        j = int(path[i + 1])
        lo, hi = max(0, j - 1), min(W, j + 2)
        path[i] = lo + int(np.argmin(E[i, lo:hi]))
    return np.arange(W)[None, :] >= path[:, None]


def quilt_image(pool: np.ndarray, cells: int, overlap: int, rng, tries: int = 40) -> np.ndarray:
    """Image quilting (Efros–Freeman) из блоков pool (N,B,B,3): блоки с перекрытием `overlap` пикселей, на каждом месте — лучший по ошибке перекрытия из `tries` случайных (из близких к лучшему — случайный), шов — путь минимальной ошибки.
    → (S,S,3), S = cells·(B−overlap)+overlap."""
    N, B = pool.shape[0], pool.shape[1]
    o = int(max(1, min(overlap, B // 2)))
    step = B - o
    S = cells * step + o
    out = np.zeros((S, S, 3))
    for i in range(cells):
        for j in range(cells):
            y, x = i * step, j * step
            idx = rng.choice(N, size=min(tries, N), replace=N < tries)
            cand = pool[idx]
            err = np.zeros(len(idx))
            if j > 0:
                err += ((cand[:, :, :o] - out[y:y + B, x:x + o][None]) ** 2).sum(axis=(1, 2, 3))
            if i > 0:
                err += ((cand[:, :o, :] - out[y:y + o, x:x + B][None]) ** 2).sum(axis=(1, 2, 3))
            if i > 0 or j > 0:
                good = np.nonzero(err <= err.min() * 1.1 + 1e-9)[0]
                k = int(good[rng.randint(len(good))])
            else:
                k = 0
            blk = cand[k]
            new = np.ones((B, B), bool)
            if j > 0:
                new[:, :o] &= _mincut_v(((out[y:y + B, x:x + o] - blk[:, :o]) ** 2).sum(axis=2))
            if i > 0:
                new[:o, :] &= _mincut_v(((out[y:y + o, x:x + B] - blk[:o, :]) ** 2).sum(axis=2).T).T
            cur = out[y:y + B, x:x + B]
            out[y:y + B, x:x + B] = np.where(new[..., None], blk, cur)
    return out


def wrap_soften(img: np.ndarray, sigma: float = 2.0, reach: int = 4) -> np.ndarray:
    """Плитка повторяется с периодом S: шов краёв (левый↔правый, верх↔низ) сглаживается — сдвиг на пол-периода, размытие узкой полосы по кресту, обратный сдвиг."""
    from scipy.ndimage import gaussian_filter
    S = img.shape[0]
    h = S // 2
    R = np.roll(img, (h, h), (0, 1))
    bl = np.stack([gaussian_filter(R[..., k], sigma, mode='nearest') for k in range(R.shape[2])], -1)
    d = np.minimum(np.abs(np.arange(S) - h)[:, None], np.abs(np.arange(S) - h)[None, :]).astype(np.float64)
    w = np.exp(-0.5 * (d / max(reach / 2.0, 1e-6)) ** 2)[..., None]
    return np.roll(R * (1.0 - w) + bl * w, (-h, -h), (0, 1))


def quilt_jump(patch: np.ndarray, step: int) -> float:
    """Межблочный скачок: средний |ΔL| между средними яркостями соседних клеток квилта (шахматка по яркости ↔ большое значение)."""
    S = patch.shape[0]
    n = max(1, S // max(step, 1))
    L = patch[:n * step, :n * step, 0].reshape(n, step, n, step).mean(axis=(1, 3))
    if n < 2:
        return 0.0
    return float(0.5 * (np.abs(np.diff(L, axis=0)).mean() + np.abs(np.diff(L, axis=1)).mean()))


def pattern_period(resL: np.ndarray, ok: np.ndarray, lo: int, hi: int) -> int:
    """Размер блока квилта по периоду узора: длина автокорреляции остатка яркости на известной части (первый лаг, где корреляция < 1/e, по осям), блок ≈ 3 длины, в [lo,hi], кратно 4."""
    from scipy.fft import rfft2, irfft2, next_fast_len
    T = resL.shape[0]
    s = next_fast_len(T + 2 * hi)
    m = ok.astype(np.float32)
    x = (resL.astype(np.float32) - float((resL * ok).sum() / max(float(m.sum()), 1.0))) * m
    Fx, Fm = rfft2(x, (s, s)), rfft2(m, (s, s))
    ac = irfft2(Fx * np.conj(Fx), (s, s))
    nm = np.maximum(irfft2(Fm * np.conj(Fm), (s, s)), 1.0)
    r = ac / nm
    if r[0, 0] <= 1e-9:
        return lo
    r = r / r[0, 0]
    lag = []
    for prof in (r[0, 1:hi + 1], r[1:hi + 1, 0]):
        below = np.nonzero(prof < 0.37)[0]
        lag.append(int(below[0]) + 1 if len(below) else hi)
    ell = float(min(lag))                                  # полосы вдоль одной оси: берём короткий период
    return int(np.clip(int(round(3.0 * ell / 4.0)) * 4, lo, hi))


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


def _gaussian_tile(patch, rng, keep_mean: bool = False):
    """Бесшовная плитка из блока остатка (B,B,3): смесь блока и его сдвига на пол-блока с весами, сохраняющими разброс (sin·sin и √(1−w²)) → периодична по обеим осям."""
    B = patch.shape[0]
    x = np.arange(B)
    w1 = (np.sin(np.pi * x / B)[:, None] * np.sin(np.pi * x / B)[None, :])[..., None]
    w2 = np.sqrt(np.maximum(1.0 - w1 * w1, 0.0))
    m = patch.mean(axis=(0, 1), keepdims=True)
    p = patch - m
    t = w1 * p + w2 * np.roll(p, (B // 2, B // 2), axis=(0, 1))
    return t + m if keep_mean else t


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
def fill(geoms: list, known: list, parts: list | None = None, cfg: dict | None = None, mirror: bool = True, draft: dict | None = None) -> dict:
    """geoms — `tex_coverage.load_geoms`; known — по геометрии (T×T bool), parts — по геометрии номера частей ГРАНЕЙ (None — одна часть).
    draft — черновик TRELLIS на ту же форму/развёртку (`draft_texels`): {'lab': [(T,T,3) Lab], 'ok': [(T,T) bool]}; нужен при cfg['source']=='trellis': невидимое берёт цвет черновика,
    сдвинутый переносом статистики Lab (медиана/разброс части: черновик → видимое фото), детали черновика сохраняются; стыки — та же растушёвка. 'stat' (по умолчанию) — цвет части + лоскут фактуры.
    → {'tex': [uint8 (T,T,3) по геометриям], 'report': {...}}. Форма и развёртка не меняются."""
    from scipy.ndimage import binary_erosion, distance_transform_edt
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    c = dict(FILL, **(cfg or {}))
    if c['source'] not in ('stat', 'trellis'):
        raise ValueError(f"source {c['source']!r}: ждём stat | trellis")
    if c['source'] == 'trellis' and draft is None:
        raise ValueError('source=trellis требует draft (draft_texels)')
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
    g_mean = tone_of(glob_l, c)
    g_std = glob_l.std(axis=0) if len(glob_l) else np.zeros(3)
    lowb = [_blur_norm(labs[gi], kn[gi], c['pattern_blur_px'])[0] for gi in range(len(txs))]
    pat_std = {}
    for p in part_ids:
        Hp = np.concatenate([(labs[gi] - lowb[gi]).reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        pat_std[p] = float(np.hypot(Hp[:, 1].std(), Hp[:, 2].std())) if len(Hp) else 0.0
    for p in part_ids:
        L = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        if len(L) >= c['min_known']:
            stat[p] = (tone_of(L, c), L.std(axis=0), len(L), False)
        else:
            stat[p] = (g_mean, g_std, len(L), True)
            rep['fallback_global'] += 1
        rep['parts'][p] = {'known_texels': int(len(L)), 'pattern': bool(pat_std[p] > c['pattern_chroma']), 'pattern_chroma_std': round(float(pat_std[p]), 2), 'mean_lab': [round(float(x), 2) for x in stat[p][0]], 'std_lab': [round(float(x), 2) for x in stat[p][1]], 'stats_from_global': stat[p][3]}
    dshift = None
    if c['source'] == 'trellis':                     # перенос статистики Lab: черновик части → видимое фото той же части (медиана и разброс по каналам)
        dshift = []
        rep['draft'] = {'parts': {}, 'ok_pct': 0.0}
        n_ok = n_all_t = 0
        dm = {}
        dlab = [draft['lab'][gi] for gi in range(len(txs))]
        plow = [None] * len(txs)
        if c['draft_blur_px'] > 0:                   # черновик и фото — в низких частотах: штрих/муар черновика не переносится, разброс сравнивается по тем же частотам
            dlab = [_blur_norm(draft['lab'][gi], draft['ok'][gi], c['draft_blur_px'])[0] for gi in range(len(txs))]
            plow = [_blur_norm(labs[gi], kn[gi], c['draft_blur_px'])[0] for gi in range(len(txs))]
        for p in part_ids:
            D = np.concatenate([dlab[gi].reshape(-1, 3)[tx.ti[draft['ok'][gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
            if len(D) >= c['min_known']:
                dmed, dstd = tone_of(D, c), D.std(axis=0)
                if plow[0] is not None:
                    K_ = np.concatenate([plow[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
                    ref_std = K_.std(axis=0) if len(K_) >= c['min_known'] else stat[p][1]
                else:
                    ref_std = stat[p][1]
                scale = np.clip(ref_std / np.maximum(dstd, 1e-3), c['draft_scale_min'], c['draft_scale_max'])
                dm[p] = (dmed, scale)
                rep['draft']['parts'][p] = {'texels': int(len(D)), 'draft_median_lab': [round(float(x), 2) for x in dmed], 'draft_std_lab': [round(float(x), 2) for x in dstd], 'scale': [round(float(x), 2) for x in scale]}
            else:
                rep['draft']['parts'][p] = {'texels': int(len(D)), 'no_draft': True}
        for gi, tx in enumerate(txs):
            T = tx.T
            sh = np.zeros((T * T, 3))
            okf = np.zeros(T * T, bool)
            dl = dlab[gi].reshape(-1, 3)
            for p in part_ids:
                if p not in dm:
                    continue
                idx = tx.ti[(tx.part == p) & draft['ok'][gi].reshape(-1)[tx.ti]]
                sh[idx] = (dl[idx] - dm[p][0]) * dm[p][1] + stat[p][0]
                okf[idx] = True
            n_ok += int(okf[tx.ti].sum())
            n_all_t += len(tx.ti)
            dshift.append((sh, okf))
        rep['draft']['ok_pct'] = round(100.0 * n_ok / max(n_all_t, 1), 2)
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
                    if c['diffuse_iter'] > 0:                  # неизвестные вершины — среднее соседей (известные зафиксированы): плавный переход вместо «зон источников»
                        deg = np.asarray(Wn.sum(axis=1)).ravel()
                        free = reach & ~vknown
                        cur = col.copy()
                        cur[vknown & used] = vcol[vknown & used]
                        for _ in range(int(c['diffuse_iter'])):
                            nxt = (Wn @ cur) / np.maximum(deg, 1.0)[:, None]
                            cur[free] = nxt[free]
                        col[free] = cur[free]
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
                flat_idx = tx.ti[gsel_t]
                if dshift is not None:                   # черновик со сдвигом тона вместо цвета части; нет черновика в тексele — цвет части
                    at, gc = at_texels(dist_a, col_a, c['feather_len'], gsel_t)
                    sh, okf = dshift[gi]
                    base = np.where(okf[flat_idx][:, None], sh[flat_idx], stat[p][0])
                else:
                    at, gc = at_texels(dist_a, col_a, c['geo_len'], gsel_t)
                    base = stat[p][0]
                lab_flat[flat_idx] = at[:, None] * gc + (1.0 - at[:, None]) * base
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
    for p in (part_ids if dshift is None else []):
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
    pat_parts = {p for p in part_ids if rep['parts'][p]['pattern']}
    raw_mean = {}
    shade_lo = {}
    for p in pat_parts:
        Lv = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)], 0] for gi, tx in enumerate(txs)])
        shade_lo[p] = float(np.quantile(Lv, c['tone_shadow_q'])) if len(Lv) and c['tone_shadow_q'] > 0 else -1e9
    if c['patch_mode'] == 'quilt' and (dshift is None or c['draft_texture']):
        qrng = np.random.RandomState(7)
        for p in part_ids:
            resg, okg = [], []
            for gi, tx in enumerate(txs):
                res_, pm, _im = blk[gi]
                if p in pat_parts:                               # узорная: остаток от тона части; затенённые тексели (складки) в узор не входят — нулевое отклонение
                    resq = (labs[gi] - stat[p][0]) * (labs[gi][..., 0] >= shade_lo[p])[..., None]
                else:
                    resq = res_
                resg.append(resq * kn[gi][..., None])
                okg.append(kn[gi] & (pm == p))
            cnt = [int(o.sum()) for o in okg]
            if sum(cnt) < 200:
                continue
            gbest = int(np.argmax(cnt))                           # период узора — по геометрии, где у части больше всего известного
            Bq = pattern_period(resg[gbest][..., 0], okg[gbest], int(c['quilt_block_min']), int(c['quilt_block_max']))
            oq = max(2, int(round(Bq * c['quilt_overlap'])))
            pool = []
            for gi, tx in enumerate(txs):
                T = tx.T
                pm = blk[gi][1]
                if T < Bq or cnt[gi] < Bq * Bq:
                    continue
                s = max(Bq // 2, 1)
                ys = np.arange(0, T - Bq + 1, s)
                I_ok = np.pad(okg[gi].astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                I_pm = np.pad((pm == p).astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                Y, X = np.meshgrid(ys, ys, indexing='ij')

                def bsum(I):
                    return I[Y + Bq, X + Bq] - I[Y, X + Bq] - I[Y + Bq, X] + I[Y, X]
                good = (bsum(I_pm) >= Bq * Bq - 0.5) & (bsum(I_ok) >= c['quilt_known'] * Bq * Bq)
                for by, bx in zip(*np.nonzero(good)):
                    pool.append(resg[gi][Y[by, bx]:Y[by, bx] + Bq, X[by, bx]:X[by, bx] + Bq])
            if len(pool) < 4:
                continue
            if len(pool) > int(c['quilt_pool']):
                pool = [pool[i] for i in qrng.choice(len(pool), int(c['quilt_pool']), replace=False)]
            P = np.stack(pool).astype(np.float64)
            # выравнивание блока к тону части: среднее (узорная — медиана: цветы не сдвигают фон) → 0; разброс → к типичному
            off = np.median(P.reshape(len(P), -1, 3), axis=1) if p in pat_parts else P.reshape(len(P), -1, 3).mean(axis=1)
            P = P - off[:, None, None, :]
            sd = P.reshape(len(P), -1).std(axis=1)
            glo, ghi = c['quilt_gain'] if p in pat_parts else (0.6, 1.6)
            P = P * np.clip(float(np.median(sd)) / np.maximum(sd, 1e-6), glo, ghi)[:, None, None, None]
            nq = int(max(c['quilt_cells'], np.ceil((c['quilt_side'] - oq) / (Bq - oq))))
            q = wrap_soften(quilt_image(P, nq, oq, qrng, int(c['quilt_tries'])))
            patches[p] = q
            patch_gain[p] = 1.0
            rep['quilt'] = rep.get('quilt', 0) + 1
            rep.setdefault('quilt_info', {})[int(p)] = {'block': Bq, 'overlap': oq, 'cells': nq, 'pool': len(pool), 'jump_L': round(quilt_jump(q, Bq - oq), 3)}
            if p in pat_parts:
                raw_mean[p] = q.mean(axis=(0, 1))                 # узорная: плитка без вычитания среднего и без смешения (фон = тон, цветы поверх)
    for p in (part_ids if (dshift is None or c['draft_texture']) else []):
        if p in patches:
            continue
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
            Bq, nq = int(c['quilt_block']), int(c['quilt_n'])
            cands = []
            for gi, tx in enumerate(txs):
                T = tx.T
                res_, pm, im = blk[gi]
                n = T // Bq
                if n < 1:
                    continue
                m = n * Bq
                res0 = res_ * kn[gi][..., None]                 # неизвестные пиксели в остаток не входят

                def tilesq(a):
                    ex = a.shape[2:]
                    return a[:m, :m].reshape(n, Bq, n, Bq, *ex).transpose(0, 2, 1, 3, *range(4, 4 + len(ex))).reshape(n, n, Bq * Bq, *ex)
                kf = tilesq(kn[gi]).mean(axis=2)
                pb = tilesq(pm)
                okb = (kf >= c['quilt_known_min']) & (pb.min(axis=2) == p) & (pb.max(axis=2) == p)
                rb = tilesq(res0)
                for by, bx in zip(*np.nonzero(okb)):
                    blkr = rb[by, bx].reshape(Bq, Bq, 3)
                    cands.append((float(blkr.std()), blkr.copy()))
            if len(cands) >= 2:
                ss = np.array([x[0] for x in cands])
                med = float(np.median(ss))
                near = np.argsort(np.abs(ss - med))[:max(2, min(len(cands), 32))]
                pick = rng.choice(near, size=nq * nq, replace=True)
                rows = [np.concatenate([cands[int(pick[r * nq + q])][1] for q in range(nq)], axis=1) for r in range(nq)]
                patches[p] = np.concatenate(rows, axis=0)
                patch_gain[p] = med / max(float(patches[p].std()), 1e-6)
                rep['quilt'] = rep.get('quilt', 0) + 1
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
            tile = patches[p] if p in raw_mean else _gaussian_tile(patches[p], rng)
            ox1, oy1 = rng.randint(0, Bp, 2)
            ox2, oy2 = rng.randint(0, Bp, 2)
            t2 = np.rot90(tile)
            r1 = tile[(py[sel] + oy1) % Bp, (px[sel] + ox1) % Bp]
            r2 = t2[(py[sel] * 3 // 2 + oy2) % Bp, (px[sel] * 3 // 2 + ox2) % Bp]
            gain = float(np.clip(patch_gain[p], c['gain_min'], c['gain_max']))
            add[sel] = gain * (r1 + r2) / np.sqrt(2.0) if p not in raw_mean else r1                  # узорная: узор из фото целиком (отклонение от тона), без смешения двух сдвигов
        out_lab[gi].reshape(-1, 3)[tx.ti[unk_flat]] += add
    rep['time_s']['texture'] = round(time.time() - t0, 2)
    # --- итог: RGB, желоб, проверка покрытия
    outs = []
    for gi, tx in enumerate(txs):
        T = tx.T
        rgb = tex_in[gi].copy()
        new = lab2rgb(out_lab[gi].reshape(-1, 3)[tx.ti])
        new = np.where((new.max(axis=1) <= BLACK_MAX)[:, None], np.maximum(new, BLACK_MAX + 1), new)    # тёмное — не «чёрное непокрашенное»: сторож охвата считает ≤ порога дырой
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
        vc = view_class(tx.N * np.where((tx.Q * tx.N).sum(axis=1) >= 0.0, 1.0, -1.0)[:, None])     # вид по наружной нормали (наружу — по знаку (точка − центр)·нормаль)
        ub, ua = unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti]), unpainted_mask(rgb.reshape(-1, 3)[tx.ti])
        rep['geoms'][gi]['by_view'] = [[int((vc == i).sum()), int((vc == i)[ub].sum()), int((vc == i)[ua].sum())] for i in range(len(VIEW_CLASSES))]
        nfc = np.bincount(tx.f, minlength=len(tx.F)).astype(np.float64)
        tx.unk_face = (np.bincount(tx.f, weights=(~kn[gi].reshape(-1)[tx.ti]).astype(np.float64), minlength=len(tx.F)) > 0.5 * np.maximum(nfc, 1.0)) & (nfc > 0)
        rep['geoms'][gi]['steps'] = {'before': step_stats(tx, tex_in[gi], c['step_de']), 'after': step_stats(tx, rgb, c['step_de'])}
    far = {'known': [], 'filled': []}
    rs = np.random.RandomState(11)
    for gi, tx in enumerate(txs):
        lab_o = rgb2lab(outs[gi].reshape(-1, 3)[tx.ti])
        kk = kn[gi].reshape(-1)[tx.ti]
        for p in part_ids:
            sel = tx.part == p
            for nm, m in (('known', sel & kk), ('filled', sel & ~kk)):
                idx = np.nonzero(m)[0]
                if len(idx) > 100000:
                    idx = rs.choice(idx, 100000, replace=False)
                if len(idx):
                    far[nm].append((TC.de2000_v(lab_o[idx], np.broadcast_to(stat[p][0], (len(idx), 3)).copy()) > c['far_de']))
    fk = float(np.concatenate(far['known']).mean()) * 100.0 if far['known'] else 0.0
    ff = float(np.concatenate(far['filled']).mean()) * 100.0 if far['filled'] else 0.0
    rep['far_pct'] = {'known': round(fk, 2), 'filled': round(ff, 2), 'excess': round(ff - fk, 2)}
    n_all = sum(r['texels'] for r in rep['geoms'])
    rep['texels'] = n_all
    bv = np.sum([r['by_view'] for r in rep['geoms']], axis=0)
    rep['unpainted_by_view'] = {nm: {'texels_pct': round(100.0 * int(bv[i, 0]) / max(n_all, 1), 2), 'before_of_all_pct': round(100.0 * int(bv[i, 1]) / max(n_all, 1), 3),
                                     'after_of_all_pct': round(100.0 * int(bv[i, 2]) / max(n_all, 1), 3)} for i, nm in enumerate(VIEW_CLASSES)}
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


# ---------------------------------------------------------------- черновик TRELLIS на нашу форму --------------------
def draft_texels(geoms: list, draft_geoms: list, cfg: dict | None = None) -> dict:
    """Цвет черновика (`tex_coverage.load_geoms` родного GLB TRELLIS.2 или его копии на упрощённую форму) в текселях НАШЕЙ развёртки: ближайшая точка поверхности черновика
    (по 3D-позиции в кадре нашего предмета; нормаль не против нашей) → её Lab. Черновик в другой системе координат не подгоняется: кадр сверяется отчётом (`frame_gap`), расхождение — `ok` ложно.
    → {'lab': [(T,T,3)], 'ok': [(T,T) bool], 'report': {...}}."""
    from scipy.spatial import cKDTree
    c = dict(FILL, **(cfg or {}))
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Pall = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    doffs = np.cumsum([0] + [len(g['V']) for g in draft_geoms])
    Dall = (np.concatenate([np.asarray(g['V'], np.float64) for g in draft_geoms]) - ctr) / size
    srcQ, srcN, srcL = [], [], []
    for gi, g in enumerate(draft_geoms):
        tx = Tex(g, Dall[doffs[gi]:doffs[gi + 1]], _grid(g), None, True)
        rgb = np.asarray(g['tex'])[..., :3]
        srcQ.append(tx.Q)
        srcN.append(tx.N)
        srcL.append(rgb2lab(rgb.reshape(-1, 3)[tx.ti]))
    srcQ, srcN, srcL = np.concatenate(srcQ), np.concatenate(srcN), np.concatenate(srcL)
    tree = cKDTree(srcQ)
    labs, oks, d_all, n_ok, n_tot = [], [], [], 0, 0
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, Pall[offs[gi]:offs[gi + 1]], T, None, True)
        K = 4
        d, j = tree.query(tx.Q, k=K, distance_upper_bound=c['draft_max_dist'])
        jj = np.where(np.isfinite(d), j, 0)
        cs = (srcN[jj] * tx.N[:, None, :]).sum(axis=2)
        good = np.isfinite(d) & (cs > c['draft_cos'])
        first = good.argmax(axis=1)
        has = good.any(axis=1)
        pick = jj[np.arange(len(jj)), first]
        lab = np.zeros((T * T, 3))
        ok = np.zeros(T * T, bool)
        lab[tx.ti[has]] = srcL[pick[has]]
        ok[tx.ti[has]] = True
        n_ok += int(has.sum())
        n_tot += len(tx.ti)
        labs.append(lab.reshape(T, T, 3))
        oks.append(ok.reshape(T, T))
        d_all.append(np.where(np.isfinite(d[:, 0]), d[:, 0], np.nan))
    dd = np.concatenate(d_all)
    A, B = (Pall.min(axis=0), Pall.max(axis=0)), (Dall.min(axis=0), Dall.max(axis=0))
    gap = float(np.abs(np.concatenate([A[0] - B[0], A[1] - B[1]])).max())
    return {'lab': labs, 'ok': oks, 'report': {'ok_pct': round(100.0 * n_ok / max(n_tot, 1), 2),
                                               'nearest_median': None if np.isnan(dd).all() else round(float(np.nanmedian(dd)), 4), 'frame_gap': round(gap, 3)}}


# ---------------------------------------------------------------- кадры «до | после» -------------------------------
def render_ortho(geoms: list, texs: list, azimuth: float = 180.0, res: int = 1024, ortho: float = 1.25, elevation: float = 0.0):
    """Ортографический кадр предмета с заданного азимута (0 — в лоб, 180 — сзади) с текстурами `texs` (по геометриям): цвет текстуры × освещение лоб-светом. Для проб, не для продукта."""
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    F = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    fg = np.concatenate([np.full(len(g['F']), i) for i, g in enumerate(geoms)])
    UV = np.concatenate([np.asarray(g['UV'], np.float64) for g in geoms])
    v = photo_views([azimuth], elevation)[0]
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


# ---------------------------------------------------------------- этап 07 пути покраски: выход, проверка, кадр ----
STAGE = '07-fill'
THRESHOLDS = {                                   # пороги этапа (check.json): плана R1 — ΔE00 перёд↔зад ≤ 5–6; «ступени» — предварительно, уточнить по прогонам
    'empty_pct': ('<=', 0.5),                    # ОБЩЕЕ «не закрашено» после заливки (все тексели, дно и зад тоже), % — решение директора 20.11, порог ≈0,5 %
    'dE00_front_back': ('<=', 6.0),              # перёд↔зад одной части: худшая из частей, у которых известного ≥ 1 % известного предмета
    'filled_faces_step_pct': ('<=', 10.0),       # доля достроенных граней со скачком цвета к соседу той же части (ΔE00 > FILL['step_de'])
    'far_excess_pct': ('<=', 10.0),              # мера пятен: доля достроенных текселей с ΔE00 > far_de от цвета части МИНУС та же доля у видимых (фактура фото не «пятно»)
    'time_s': ('<=', 120.0),                     # план R1: < 2 мин на товар
}


def parts_from_geometry(geoms: list):
    """Части граней по геометрии `tools/assets/material_parts.py`: 0 обивка/корпус, 1 ножки, 2 нейтральное (тонкое, полоса у ножек); нет уверенного деления — одна часть. → (список по геометриям | None, строка о способе)."""
    try:
        sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'assets'))
        import material_parts as MP
        rules = MP.load_rules()
    except Exception as e:  # noqa: BLE001 — частей нет, заливка идёт одной частью
        return None, f'частей нет ({type(e).__name__})'
    out, note = [], []
    for g in geoms:
        nf = len(g['F'])
        try:
            rec = MP.judge(MP.analyze(g['mesh'], rules), rules, None)
            if rec.get('status') == 'split' and rec.get('apply', rec.get('confidence', 0) >= rules['confidence']['apply']):
                leg = MP.legs_face_mask(g['mesh'], rec)
                neu = MP.neutral_face_mask(g['mesh'], rec) & ~leg
                p = np.zeros(nf, np.int32)
                p[leg] = 1
                p[neu] = 2
                out.append(p)
                note.append(f"split ножки {int(leg.sum())} нейтр. {int(neu.sum())} из {nf}")
                continue
            note.append(f"{rec.get('status')} → одна часть")
        except Exception as e:  # noqa: BLE001
            note.append(f'сбой частей {type(e).__name__}')
        out.append(np.zeros(nf, np.int32))
    return out, '; '.join(note)


def parts_from_npz(path: str, geoms: list):
    """Части граней этапа 3 пути покраски (`03-parts/parts.npz`, T-169): `part` int16 — ОДИН массив на все грани GLB в порядке геометрий; режется по числу граней каждой геометрии.
    −1 («нет части») получает отдельный номер. Число граней не совпало → ValueError (части другого меша — заливать нельзя). → (список по геометриям, строка о способе)."""
    z = np.load(path)
    part = np.asarray(z['part']).astype(np.int32)
    n = sum(len(g['F']) for g in geoms)
    if len(part) != n:
        raise ValueError(f'parts.npz: граней {len(part)}, а в GLB {n} — части другого меша')
    if (part < 0).any():
        part = np.where(part < 0, int(part.max()) + 1, part)
    out, o = [], 0
    for g in geoms:
        out.append(part[o:o + len(g['F'])])
        o += len(g['F'])
    return out, f'parts.npz: {int(part.max()) + 1} частей'


def part_deltas(geoms: list, parts, kfront: list, kback: list, tex_before: list, tex_after: list) -> dict:
    """ΔE00 перёд↔зад внутри одной части: средние Lab текселей, видимых спереди (kfront) и сзади (kback), до и после заливки. → {часть: {'before', 'after'}}."""
    res = {}
    ids = sorted({int(p) for pp in (parts or [np.zeros(len(g['F']), np.int32) for g in geoms]) for p in np.unique(pp)})
    txs = [Tex(g, np.asarray(g['V'], np.float64), _grid(g), None if parts is None else parts[gi]) for gi, g in enumerate(geoms)]
    for p in ids:
        sets = {'before': ([], []), 'after': ([], [])}
        for gi, tx in enumerate(txs):
            sel = tx.part == p
            for nm, tex in (('before', tex_before[gi]), ('after', tex_after[gi])):
                flat = np.asarray(tex).reshape(-1, 3)
                for k, kk in ((0, kfront[gi]), (1, kback[gi])):
                    m = kk.reshape(-1)[tx.ti] & sel
                    m &= ~unpainted_mask(flat[tx.ti])
                    if m.any():
                        sets[nm][k].append(rgb2lab(flat[tx.ti[m]]))
        r = {}
        for nm, (fr, bk) in sets.items():
            if fr and bk:
                a, b = np.concatenate(fr).mean(axis=0, keepdims=True), np.concatenate(bk).mean(axis=0, keepdims=True)
                r[nm] = round(float(TC.de2000_v(a, b)[0]), 2)
            else:
                r[nm] = None
        res[p] = r
    return res


def write_glb(geoms: list, texs: list, dst: str) -> None:
    """Та же форма и развёртка, текстура — заполненная (выход этапа для следующих)."""
    import trimesh
    from PIL import Image
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, t in zip(geoms, texs):
        mesh = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
        mesh.visual = TextureVisuals(uv=np.asarray(g['UV']), material=PBRMaterial(baseColorTexture=Image.fromarray(np.asarray(t)), metallicFactor=0.0, roughnessFactor=1.0))
        sc.add_geometry(mesh, geom_name=str(g.get('name') or 'mesh'))
    sc.export(dst)


def run_stage(run: str, sku: str, glb: str, known: list | None = None, parts=None, cfg: dict | None = None, thresholds: dict | None = None, mirror: bool = True, draft_glb: str | None = None, out_name: str | None = None, parts_npz: str | None = None) -> dict:
    """Этап 07 «докрасить невидимое»: GLB (текстура = фото на видимом) → `<run>/<sku>/07-fill/` {filled.glb, report.json, frame.png (az180 до | после), check.json}.
    `known` — маска «видно с камеры фото» по геометриям (нет — из `known_from_photo`: az0/az45); `parts` — части граней (нет — `parts_from_geometry`). Не прошёл (check.json passed=false) — товар дальше не идёт.
    → {'check', 'report', 'geoms', 'tex_before', 'tex_after', 'known', 'parts', 'dir'} (для проб и кадров)."""
    import json
    from PIL import Image
    import paint_stage as PS
    t0 = time.time()
    d = PS.stage_dir(run, sku, out_name or STAGE)
    th = dict(THRESHOLDS, **(thresholds or {}))
    geoms = TC.load_geoms(glb)
    tex_before = [np.asarray(g['tex']).copy() for g in geoms]
    if known is None:
        known = known_from_photo(geoms)
    parts_note = 'заданы'
    if parts is None and parts_npz:
        parts, parts_note = parts_from_npz(parts_npz, geoms)
    if parts is None:
        parts, parts_note = parts_from_geometry(geoms)
    draft = None
    if (cfg or {}).get('source') == 'trellis':
        draft = draft_texels(geoms, TC.load_geoms(draft_glb), cfg)
    kback = known_from_photo(geoms, azimuths=(180.0,))

    def one(cfg_, draft_):
        r_ = fill(geoms, known, parts, cfg_, mirror, draft_)
        rp, tx_ = r_['report'], r_['tex']
        de_ = part_deltas(geoms, parts, known, kback, tex_before, tx_)
        kt = max(sum(v['known_texels'] for v in rp['parts'].values()), 1)
        bg = [p for p, v in rp['parts'].items() if v['known_texels'] >= 0.01 * kt]
        da = {int(p): v['after'] for p, v in de_.items() if v['after'] is not None}
        dw = max([da[p] for p in bg if p in da] or [None]) if any(p in da for p in bg) else None
        vals = {'empty_pct': rp['unpainted_after_pct'], 'dE00_front_back': dw, 'filled_faces_step_pct': rp['steps']['after']['filled_faces_step_pct'], 'far_excess_pct': rp['far_pct']['excess']}
        nfail = sum(0 if PS.judge(vals[k], th[k][0], th[k][1]) else 1 for k in vals)
        return {'rep': rp, 'tex': tx_, 'de': de_, 'big': bg, 'de_worst': dw, 'vals': vals, 'nfail': nfail, 'key': (nfail, dw if dw is not None else 99.0, vals['far_excess_pct'] if vals['far_excess_pct'] is not None else 99.0)}
    tried = {}
    if draft is not None and dict(FILL, **(cfg or {}))['draft_fallback']:      # Б и А: Б берётся, только если мерки не хуже (число непрошедших, затем ΔE перёд↔зад, затем пятна)
        cA = one(dict(cfg or {}, source='stat'), None)
        tried = {'stat': {'nfail': cA['nfail'], **cA['vals']}}
        if cA['nfail'] == 0 and dict(FILL, **(cfg or {}))['draft_when'] == 'a_fails':    # А прошёл все мерки — Б не считаем (экономия времени этапа)
            pick, used = cA, 'stat'
        else:
            cB = one(cfg, draft)
            tried['trellis'] = {'nfail': cB['nfail'], **cB['vals']}
            pick, used = (cB, 'trellis') if cB['key'] <= cA['key'] else (cA, 'stat')
    else:
        pick, used = one(cfg, draft), ((cfg or {}).get('source') or 'stat')
    rep, tex_after, de, big, de_worst = pick['rep'], pick['tex'], pick['de'], pick['big'], pick['de_worst']
    rep['source_used'], rep['source_tried'] = used, tried
    write_glb(geoms, tex_after, os.path.join(d, 'filled.glb'))
    a = render_ortho(geoms, tex_before, 180.0)
    b = render_ortho(geoms, tex_after, 180.0)
    Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(d, PS.FRAME))
    secs = time.time() - t0
    metrics = {
        'empty_pct': {'value': rep['unpainted_after_pct'], 'threshold': th['empty_pct'][1], 'op': th['empty_pct'][0]},
        'dE00_front_back': {'value': de_worst, 'threshold': th['dE00_front_back'][1], 'op': th['dE00_front_back'][0]},
        'filled_faces_step_pct': {'value': rep['steps']['after']['filled_faces_step_pct'], 'threshold': th['filled_faces_step_pct'][1], 'op': th['filled_faces_step_pct'][0]},
        'far_excess_pct': {'value': rep['far_pct']['excess'], 'threshold': th['far_excess_pct'][1], 'op': th['far_excess_pct'][0]},
        'time_s': {'value': round(secs, 1), 'threshold': th['time_s'][1], 'op': th['time_s'][0]},
    }
    for m in metrics.values():
        m['ok'] = PS.judge(m['value'], m['op'], m['threshold'])
    if draft is not None:
        rep['draft_transfer'] = draft['report']
    report = {'report': rep, 'deltaE_by_part': de, 'big_parts': big, 'parts_note': parts_note, 'empty_before_pct': rep['unpainted_before_pct']}
    with open(os.path.join(d, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    check = PS.write_check(d, out_name or STAGE, sku, None, dict(metrics['empty_pct'], name='empty_pct'), '', metrics={k: v for k, v in metrics.items() if k != 'empty_pct'}, seconds=secs,
                           outputs=['filled.glb', 'report.json'], frame=PS.FRAME, known_pct=rep['known_pct'], mirrored_pct=rep['mirrored_pct'], empty_before_pct=rep['unpainted_before_pct'], empty_by_view=rep['unpainted_by_view'], steps=rep['steps'], parts=parts_note, source_used=used, source_tried=tried)
    return {'check': check, 'report': rep, 'geoms': geoms, 'tex_before': tex_before, 'tex_after': tex_after, 'known': known, 'parts': parts, 'dir': d, 'deltaE': de, 'kback': kback}
