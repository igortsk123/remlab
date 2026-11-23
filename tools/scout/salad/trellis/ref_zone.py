"""Ш8м (ADR-0459 + методика «как брать суть», plans/paint-photo-fill-01.md, T-187/4): UltraTex-меш — ОБРАЗЕЦ «сути» зоны; пиксели/оттенок/яркость образца в товар не идут. ВХОЛОСТУЮ: решения пишет `compare` в ref_zone.json,
07 они не меняют, пока в rules/ref-zone.json `apply_to_fill` = false (по умолчанию).
Что делает (М1–М4, общим правилом, без ID):
  М1 зоны — по НАШЕМУ фото: сегменты цвета (Lab, k-means, слив близких) → через камеру 04 на грани (голос только внутренних пикселей с хорошим углом, ≥70 % за одну зону) → невидимые грани получают зону продолжением той же детали
     (граф смежности граней: та же геометрическая часть, излом ≤ `max_dihedral_deg`); смешанное/спорное — -1 (`unknown`). 03 при наличии — главный: `zone_override` (метка на грань) вместо сегментов.
  М2 мерим на поверхности: unlit-рендеры образца на НАШЕЙ геометрии (форма одна — проверка `same_mesh` внутри `compare`) в камере фото 04 и в видах «зад / право / лево / верх» при том же масштабе; окна `win` px целиком внутри одной зоны, на ровной грани
     (нормаль, шов UV, угол), без силуэта; единицы — пиксели кадра при фиксированном масштабе (нормированные единицы меша), «в см» не заявляем.
  М3 свойства раздельно, с правом воздержаться: texture (тонкая фактура), pattern (макромотив есть/нет), scale (период макромотива; not_applicable без мотива), direction (ориентация мотива к вертикали детали, период 180°; not_applicable без
     направленности), uniform (разброс яркости окон); класс материала — `unknown` (VLM не вводим). Решение — только при ≥ `min_windows` окон с каждой стороны, иначе `unknown`.
  М4 голос по свойству: образец на виде фото против самого ФОТО в тех же окнах (только настоящие фото-пиксели: маска фото, угол, не край) тем же тестом; провал выключает только это свойство.
Выход `compare`: {'zones': {z: {'sides': {сторона: {свойство: {decision, ...}}}, 'symmetry': {...}}}, 'map': {z: {сторона: {свойство: решение}}}, 'face_zone': [..], 'coverage': {...}}.
Пороги — гипотезы (калибруются на известных 3D-моделях Ш8′ и наших ~40, P-061).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
SCOUT = os.path.dirname(SALAD)
sys.path[:0] = [HERE, SALAD, SCOUT]


class SameMeshRequired(Exception):
    pass


def _rules() -> dict:
    try:
        return json.load(open(os.path.join(SCOUT, 'rules', 'ref-zone.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


R = _rules()
APPLY = bool(R.get('apply_to_fill', False))
PANEL_DEG = float(R.get('panel_deg', 15.0))                  # излом ребра внутри панели, градусы
PANEL_SIDE_COS = float(R.get('panel_side_cos', 0.6))         # нормаль грани к оси стороны не меньше — иначе «косая»
PANEL_OUTER = float(R.get('panel_outer', 0.75))               # грань — сторона предмета, только если лежит дальше этой доли полуразмера габарита по оси стороны (иначе стенка рельефа/полка внутри → «косая»)
PANEL_PURITY = float(R.get('panel_purity', 0.9))             # доля одной зоны среди боковых панелей / голосов двойников
SYM_EPS = float(R.get('sym_eps', 0.015))                      # двойник через плоскость: расстояние центров, доли диагонали
SYM_MIN = float(R.get('sym_min', 0.8))                       # форма считается симметричной при доле граней с двойником не меньше
WIN = int(R.get('win', 48))
STRIDE = int(R.get('stride', 24))
MIN_WIN = int(R.get('min_windows', 6))
COS_MIN = float(R.get('cos_min', 0.6))
NORM_STD = float(R.get('normal_std_max', 0.12))
UV_JUMP = float(R.get('uv_jump_max', 0.02))
EDGE_PX = int(R.get('silhouette_px', 10))
HF_FLOOR = float(R.get('hf_floor', 0.8))
HF_SAME = tuple(R.get('hf_same_ratio', (0.67, 1.5)))
HF_DIFF = tuple(R.get('hf_diff_ratio', (0.4, 2.5)))
PAT_FLOOR = float(R.get('macro_floor', 1.2))
PAT_FRAC = float(R.get('pattern_window_share', 0.5))
AC_PEAK = float(R.get('autocorr_peak', 0.35))
SC_SAME = tuple(R.get('scale_same_ratio', (0.75, 1.33)))
SC_DIFF = tuple(R.get('scale_diff_ratio', (0.5, 2.0)))
DIR_COH = float(R.get('coherence_min', 0.4))
DIR_SAME = float(R.get('direction_same_deg', 20.0))
DIR_DIFF = float(R.get('direction_diff_deg', 45.0))
UN_SAME = float(R.get('uniform_same_dL', 2.5))
UN_DIFF = float(R.get('uniform_diff_dL', 6.0))
G_TEX = tuple(R.get('photo_texture_ratio', (0.5, 2.0)))
G_SC = tuple(R.get('photo_scale_ratio', (0.6, 1.7)))
G_DIR = float(R.get('photo_direction_deg', 25.0))
G_UN = float(R.get('photo_uniform_dL', 4.0))
SEG_K = int(R.get('seg_k_max', 4))
SEG_MERGE_DE = float(R.get('seg_merge_dE', 10.0))
SEG_MIN_SHARE = float(R.get('seg_min_share', 0.02))
VOTE_MIN_PX = int(R.get('face_vote_min_px', 8))
VOTE_AGREE = float(R.get('face_vote_agree', 0.7))
MAX_DIH = float(R.get('max_dihedral_deg', 100.0))
CONFLICT = float(R.get('conflict_ratio', 1.5))
GOOD_SHARE = float(R.get('win_good_share', 0.85))
ZONE_SHARE = float(R.get('win_zone_share', 0.9))
WELD = float(R.get('weld_eps', 1e-5))
PROPS = ('texture', 'pattern', 'scale', 'direction', 'uniform')
WIN_DEBUG: list = []                                                              # по вызову collect_windows: сколько окон отказано и почему


# ── геометрия: тот же меш? ──────────────────────────────────────────────────────────────────────────────────────────
def same_mesh(a: list, b: list, eps: float = 1e-5) -> dict:
    """Образец = наш меш? Вершины, грани, UV поэлементно. → {'same': bool, ...}."""
    if len(a) != len(b):
        return {'same': False, 'why': 'число геометрий'}
    out = {'same': True}
    for i, (x, y) in enumerate(zip(a, b)):
        if x['V'].shape != y['V'].shape or x['F'].shape != y['F'].shape:
            return {'same': False, 'why': f'геометрия {i}: число вершин/граней'}
        dv, du, sf = float(np.abs(x['V'] - y['V']).max()), float(np.abs(x['UV'] - y['UV']).max()), bool((x['F'] == y['F']).all())
        out[f'g{i}'] = {'dV': dv, 'dUV': du, 'faces_equal': sf}
        if dv > eps or du > eps or not sf:
            out['same'] = False
    return out


# ── яркость и полосы ────────────────────────────────────────────────────────────────────────────────────────────────
def _L(rgb8: np.ndarray) -> np.ndarray:
    import recolor_lp as LP
    return LP.lab_f(rgb8)[..., 0].astype(np.float32)


def _nconv(x: np.ndarray, m: np.ndarray, s: float) -> np.ndarray:
    """Гауссово сглаживание только по маске (границы без чёрной каймы)."""
    import cv2
    mf = m.astype(np.float32)
    num = cv2.GaussianBlur(x * mf, (0, 0), s)
    den = cv2.GaussianBlur(mf, (0, 0), s)
    return np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0.0).astype(np.float32)


def band_maps(L: np.ndarray, m: np.ndarray) -> dict:
    g = {s: _nconv(L, m, s) for s in (0.8, 2.5, 3.0, 12.0)}
    return {'fine': g[0.8] - g[2.5], 'macro': g[3.0] - g[12.0], 'smooth': _nconv(L, m, 1.5)}


def window_features(bm: dict, L: np.ndarray, y0: int, x0: int, w: int) -> dict:
    sl = (slice(y0, y0 + w), slice(x0, x0 + w))
    fine, macro = bm['fine'][sl], bm['macro'][sl]
    hf = float(np.sqrt((fine ** 2).mean()))
    mc = float(np.sqrt((macro ** 2).mean()))
    # период макромотива — автокорреляция полосы (первый пик после спада)
    a = macro - macro.mean()
    F = np.fft.fft2(a, s=(2 * w, 2 * w))
    ac = np.fft.ifft2(np.abs(F) ** 2).real
    ac = ac / max(ac[0, 0], 1e-9)
    prof = [float(np.mean([ac[k, 0], ac[0, k], ac[-k, 0], ac[0, -k]])) for k in range(1, w // 2 + 1)]
    period = None
    if mc >= PAT_FLOOR:
        for k in range(2, len(prof) - 1):
            if prof[k] > prof[k - 1] and prof[k] >= prof[k + 1] and prof[k] >= AC_PEAK and min(prof[:k]) < prof[k] - 0.05:
                period = k + 1
                break
    gy, gx = np.gradient(bm['smooth'][sl])
    jxx, jyy, jxy = (gx * gx).mean(), (gy * gy).mean(), (gx * gy).mean()
    coh = float(np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / max(jxx + jyy, 1e-9))
    theta = float(0.5 * np.degrees(np.arctan2(2 * jxy, jxx - jyy)))        # направление градиента от оси x; направление мотива — перпендикуляр; к вертикали кадра
    ang_vert = (theta - 90.0 + 90.0) % 180.0                               # ориентация линий мотива относительно вертикали кадра (0 = вертикальные линии)
    return {'hf': hf, 'macro': mc, 'period': period, 'coh': coh, 'ang': ang_vert, 'L': float(L[sl].mean())}


def aggregate(wins: list) -> dict | None:
    if len(wins) < MIN_WIN:
        return None
    hf = np.array([w['hf'] for w in wins])
    mc = np.array([w['macro'] for w in wins])
    per = [w['period'] for w in wins if w['period']]
    coh_w = [w for w in wins if w['coh'] >= DIR_COH and w['macro'] >= PAT_FLOOR]
    ang = None
    if len(coh_w) >= max(3, MIN_WIN // 2):
        z = np.mean([np.exp(2j * np.radians(w['ang'])) for w in coh_w])
        ang = float((np.degrees(np.angle(z)) / 2.0) % 180.0)
    return {'n': len(wins), 'hf': float(np.median(hf)), 'macro': float(np.median(mc)), 'pat_share': float(len(per) / len(wins)), 'period': float(np.median(per)) if per else None,
            'dir_share': float(len(coh_w) / len(wins)), 'ang': ang, 'uniform': float(np.std([w['L'] for w in wins])), 'meanL': float(np.mean([w['L'] for w in wins]))}


# ── решения по свойствам ────────────────────────────────────────────────────────────────────────────────────────────
def _d(decision: str, why: str = '', **kw) -> dict:
    return dict({'decision': decision, 'why': why}, **kw)


def decide(a: dict | None, b: dict | None) -> dict:
    """Свойства пары «видимое a | другая сторона b» (агрегаты окон зоны). → {свойство: {'decision': same|different|unknown|not_applicable, ...}}."""
    if a is None or b is None:
        return {p: _d('unknown', 'мало окон (< %d) с %s' % (MIN_WIN, 'видимой' if a is None else 'проверяемой') + ' стороны') for p in PROPS}
    out = {}
    plain = a['hf'] < HF_FLOOR and b['hf'] < HF_FLOOR
    r = None if plain else b['hf'] / max(a['hf'], 1e-6)
    out['texture'] = _d('same', 'гладко с обеих сторон') if plain else _d('same' if HF_SAME[0] <= r <= HF_SAME[1] else ('different' if (r < HF_DIFF[0] or r > HF_DIFF[1]) else 'unknown'), 'отношение силы фактуры %.2f' % r, ratio=round(r, 3))
    pa, pb = a['pat_share'] >= PAT_FRAC, b['pat_share'] >= PAT_FRAC
    if not pa and not pb:
        out['pattern'] = _d('same', 'мотива нет с обеих сторон')
    elif pa != pb:
        out['pattern'] = _d('different', 'мотив есть только с одной стороны (%s)' % ('видимой' if pa else 'проверяемой'))
    else:
        out['pattern'] = _d('same', 'мотив есть с обеих сторон')
    if not (pa and pb):
        out['scale'] = _d('not_applicable', 'нет мотива с обеих сторон')
    elif not (a['period'] and b['period']):
        out['scale'] = _d('unknown', 'период не найден')
    else:
        rs = b['period'] / a['period']
        out['scale'] = _d('same' if SC_SAME[0] <= rs <= SC_SAME[1] else ('different' if (rs < SC_DIFF[0] or rs > SC_DIFF[1]) else 'unknown'), 'отношение периодов %.2f' % rs, ratio=round(rs, 3))
    if not (pa and pb) or a['ang'] is None or b['ang'] is None:
        out['direction'] = _d('not_applicable' if not (pa and pb) or (a['dir_share'] < PAT_FRAC and b['dir_share'] < PAT_FRAC) else 'unknown', 'нет мотива/направленности' if not (pa and pb) or (a['dir_share'] < PAT_FRAC and b['dir_share'] < PAT_FRAC) else 'направленность только с одной стороны')
    else:
        dd = abs((b['ang'] - a['ang'] + 90.0) % 180.0 - 90.0)
        out['direction'] = _d('same' if dd <= DIR_SAME else ('different' if dd >= DIR_DIFF else 'unknown'), 'угол между направлениями %.0f°' % dd, deg=round(dd, 1))
    du = abs(b['uniform'] - a['uniform'])
    out['uniform'] = _d('same' if du < UN_SAME else ('different' if du > UN_DIFF else 'unknown'), 'разность разброса яркости окон %.1f' % du, dL=round(du, 2))
    return out


def gate(ref_vis: dict | None, photo: dict | None) -> dict:
    """Голос образца по каждому свойству: образец на виде фото против фото в ТЕХ ЖЕ окнах. → {свойство: (ok, пояснение)}."""
    if ref_vis is None or photo is None:
        return {p: (False, 'мало окон для сверки с фото') for p in PROPS}
    g = {}
    plain = ref_vis['hf'] < HF_FLOOR and photo['hf'] < HF_FLOOR
    r = photo['hf'] / max(ref_vis['hf'], 1e-6)
    g['texture'] = (plain or G_TEX[0] <= r <= G_TEX[1], 'фото/образец силы фактуры %.2f' % r)
    pa, pb = ref_vis['pat_share'] >= PAT_FRAC, photo['pat_share'] >= PAT_FRAC
    g['pattern'] = (pa == pb, 'мотив у образца %s, на фото %s' % ('есть' if pa else 'нет', 'есть' if pb else 'нет'))
    if pa and pb and ref_vis['period'] and photo['period']:
        rs = photo['period'] / ref_vis['period']
        g['scale'] = (G_SC[0] <= rs <= G_SC[1], 'период фото/образец %.2f' % rs)
    else:
        g['scale'] = (pa == pb, 'периода нет у одной из сторон' if pa and pb else 'мотива нет')
    if ref_vis['ang'] is not None and photo['ang'] is not None:
        dd = abs((photo['ang'] - ref_vis['ang'] + 90.0) % 180.0 - 90.0)
        g['direction'] = (dd <= G_DIR, 'угол фото/образец %.0f°' % dd)
    else:
        g['direction'] = (True, 'направленности нет — нечем сверять')
    du = abs(photo['uniform'] - ref_vis['uniform'])
    g['uniform'] = (du < G_UN, 'разность разброса яркости фото/образец %.1f' % du)
    return g


# ── зоны по нашему фото (М1) ───────────────────────────────────────────────────────────────────────────────────────
def segment_photo(prgb: np.ndarray, valid: np.ndarray) -> tuple:
    """k-means по Lab на пикселях `valid`, слив близких центров; → (метки px×px, -1 вне valid; центры Lab)."""
    import cv2
    import recolor_lp as LP
    lab = LP.lab_f(prgb).astype(np.float32)
    x = lab[valid].astype(np.float64)
    if len(x) < 2000:
        return np.full(valid.shape, -1, np.int32), np.zeros((0, 3))
    rng = np.random.default_rng(0)
    xs = x if len(x) <= 120000 else x[rng.choice(len(x), 120000, replace=False)]
    c = [xs[int(np.argmin(xs[:, 0]))]]
    for _ in range(1, SEG_K):
        d = np.min([((xs - cc) ** 2).sum(1) for cc in c], axis=0)
        c.append(xs[int(np.argmax(d))])
    c = np.array(c)
    for _ in range(12):
        lb = np.argmin(((xs[:, None, :] - c[None]) ** 2).sum(2), axis=1)
        for j in range(len(c)):
            if (lb == j).any():
                c[j] = xs[lb == j].mean(0)
    while True:                                                           # слив: близкие центры и малые доли
        lb = np.argmin(((xs[:, None, :] - c[None]) ** 2).sum(2), axis=1)
        sh = np.bincount(lb, minlength=len(c)) / len(xs)
        if len(c) > 1 and sh.min() < SEG_MIN_SHARE:
            c = np.delete(c, int(np.argmin(sh)), 0)
            continue
        dm = [(float(LP.de2000(c[i][None], c[j][None])[0]), i, j) for i in range(len(c)) for j in range(i + 1, len(c))]
        if dm and min(dm)[0] < SEG_MERGE_DE:
            _, i, j = min(dm)
            c[i] = (c[i] * sh[i] + c[j] * sh[j]) / max(sh[i] + sh[j], 1e-9)
            c = np.delete(c, j, 0)
            continue
        break
    lbl = np.full(valid.shape, -1, np.int32)
    ys, xx = np.nonzero(valid)
    pts = lab[ys, xx].astype(np.float64)
    lbl[ys, xx] = np.argmin(((pts[:, None, :] - c[None]) ** 2).sum(2), axis=1)
    sm = cv2.medianBlur((lbl + 1).astype(np.uint8), 5).astype(np.int32) - 1                 # сглаживание шума границ
    sm[~valid] = -1
    return sm, c


def label_faces(nF: int, st: dict, seg: np.ndarray, good: np.ndarray, offs=None) -> tuple:
    """Голоса пикселей `good` (внутри, хороший угол) → зона грани (≥ VOTE_MIN_PX и ≥ VOTE_AGREE за одну). → (face_zone int32 nF, -1 без зоны; face_votes)."""
    ids = st['ids']
    ys, xs = np.nonzero(good & (ids >= 0) & (seg >= 0))
    f, z = ids[ys, xs].astype(np.int64), seg[ys, xs].astype(np.int64)
    K = int(seg.max()) + 1 if seg.max() >= 0 else 1
    cnt = np.zeros((nF, K), np.int32)
    np.add.at(cnt, (f, z), 1)
    tot = cnt.sum(1)
    top = cnt.argmax(1)
    ok = (tot >= VOTE_MIN_PX) & (cnt[np.arange(nF), top] >= VOTE_AGREE * np.maximum(tot, 1))
    fz = np.where(ok, top, -1).astype(np.int32)
    return fz, tot


def face_graph(V: np.ndarray, F: np.ndarray):
    """Смежность граней по общему ребру сварённых вершин: (i, j, вес = расстояние центров, двугранный угол в градусах, нормали граней)."""
    F_orig = np.asarray(F, np.int64)
    Vw = np.round(np.asarray(V, np.float64) / WELD).astype(np.int64)                  # сварка вершин по положению: острова UV одного тела — одна поверхность
    _u, inv = np.unique(Vw, axis=0, return_inverse=True)
    F = np.asarray(inv, np.int64).reshape(-1)[np.asarray(F, np.int64)]
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fi = np.tile(np.arange(len(F)), 3)
    key = np.sort(e, axis=1)
    kk = key[:, 0].astype(np.int64) * (int(F.max()) + 1) + key[:, 1]
    o = np.argsort(kk, kind='stable')
    kk, fi = kk[o], fi[o]
    same = kk[1:] == kk[:-1]
    i, j = fi[:-1][same], fi[1:][same]
    keep = i != j
    i, j = i[keep], j[keep]
    Vc = np.asarray(V, np.float64)
    cen = Vc[F_orig].mean(1)
    n = np.cross(Vc[F_orig[:, 1]] - Vc[F_orig[:, 0]], Vc[F_orig[:, 2]] - Vc[F_orig[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    dih = np.degrees(np.arccos(np.clip(np.abs((n[i] * n[j]).sum(1)), 0, 1)))      # без знака: обмотка мешей TRELLIS не согласована (≈50 % нормалей внутрь)
    return i, j, np.linalg.norm(cen[i] - cen[j], axis=1) + 1e-9, dih, n


def propagate_zones(V, F, fz: np.ndarray, parts, return_info: bool = False):
    """Невидимым граням — зона по графу смежности: та же геометрическая часть, излом ребра ≤ MAX_DIH. Кратчайшие расстояния считаются ОТДЕЛЬНО до каждого ярлыка; зона = ближайший ярлык.
    Спорная грань (второй ярлык ближе CONFLICT × первого) берёт зону с БОЛЬШЕЙ площадью видимого (размеченного по фото) — тон двух зон никогда не смешивается. Не достали (другая часть, остров) — -1.
    return_info → (карта, {'disputed', 'unreachable', 'todo'})."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    i, j, w, dih, _n = face_graph(V, F)
    ok = dih <= MAX_DIH
    if parts is not None:
        pa = np.asarray(parts)
        ok &= pa[i] == pa[j]
    i, j, w = i[ok], j[ok], w[ok]
    nF = len(F)
    g = coo_matrix((np.concatenate([w, w]), (np.concatenate([i, j]), np.concatenate([j, i]))), shape=(nF, nF)).tocsr()
    labels = [int(z) for z in np.unique(fz[fz >= 0])]
    out = fz.copy()
    info = {'disputed': 0, 'unreachable': 0, 'todo': int((fz < 0).sum())}
    if not labels:
        return (out, info) if return_info else out
    Vv = np.asarray(V, np.float64)
    ar = 0.5 * np.linalg.norm(np.cross(Vv[np.asarray(F)[:, 1]] - Vv[np.asarray(F)[:, 0]], Vv[np.asarray(F)[:, 2]] - Vv[np.asarray(F)[:, 0]]), axis=1)
    area = np.array([float(ar[fz == z].sum()) for z in labels])
    D = np.full((len(labels), nF), np.inf)
    for k, z in enumerate(labels):
        src = np.flatnonzero(fz == z)
        D[k] = dijkstra(g, directed=False, indices=src, min_only=True)
    srt = np.sort(D, axis=0)
    best = D.argmin(0)
    d1, d2 = srt[0], (srt[1] if len(labels) > 1 else np.full(nF, np.inf))
    lab = np.array(labels, np.int32)[best]
    disputed = np.isfinite(d2) & (d2 < CONFLICT * np.maximum(d1, 1e-9))
    close = np.argsort(D, axis=0)[:2]                                                  # две ближайшие зоны
    big = np.where(area[close[0]] >= area[close[1]], close[0], close[1]) if len(labels) > 1 else close[0]
    lab = np.where(disputed, np.array(labels, np.int32)[big], lab)
    reach = np.isfinite(d1)
    todo = fz < 0
    out[todo & reach] = lab[todo & reach]
    info['disputed'] = int((todo & reach & disputed).sum())
    info['unreachable'] = int((todo & ~reach).sum())
    return (out, info) if return_info else out


# ── окна на рендерах образца (М2) ──────────────────────────────────────────────────────────────────────────────────
def render_view(geo: dict, tex2k: np.ndarray, cam: dict, n: int) -> dict:
    """unlit-рендер образца на нашей геометрии: цвет (текстура образца), id грани, нормаль, cos, UV, маска."""
    import cv2
    import pose_fit as PF
    r = PF.render_persp(geo, cam, n)
    m = r['mask']
    H, Wd = tex2k.shape[:2]
    mapx = (r['uv'][..., 0] % 1.0 * (Wd - 1)).astype(np.float32)
    mapy = (np.clip(r['uv'][..., 1], 0, 1) * (H - 1)).astype(np.float32)
    col = cv2.remap(tex2k, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    col = np.where(m[..., None], col, 0)
    return {'rgb': np.clip(col, 0, 255).astype(np.uint8), 'ids': r['ids'], 'mask': m, 'cos': r.get('cos'), 'normal': r.get('normal'), 'uv': r['uv']}


def fit_cam(geo: dict, az: float, el: float, f: float, d: float) -> dict:
    """Камера вида az/el с ТЕМ ЖЕ масштабом f, что у камеры фото (px на предмете одинаков для всех видов), центр — по габариту."""
    import pose_fit as PF
    cam = {'az': az, 'el': el, 'd': d, 'f': f, 'cx': 0.0, 'cy': 0.0}
    x, y, _z = PF.project(geo['V'], cam)
    cam['cx'] = 0.5 - f * (x.min() + x.max()) / 2.0
    cam['cy'] = 0.5 - f * (y.min() + y.max()) / 2.0
    return cam


def collect_windows(rv: dict, rgb: np.ndarray, face_zone: np.ndarray, extra_valid: np.ndarray | None, mask: np.ndarray, face_ok: np.ndarray | None = None) -> dict:
    """Окна по зонам: {зона: [признаки окна…]}. Окно целиком в маске, одна зона, ровная грань (σ нормали), без шва UV, угол ≥ COS_MIN, не у силуэта."""
    import cv2
    L = _L(rgb)
    bm = band_maps(L, mask)
    px = L.shape[0]
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    zmap = np.where(rv['ids'] >= 0, face_zone[np.maximum(rv['ids'], 0)], -1)
    cosm = rv['cos'] if rv.get('cos') is not None else np.ones_like(L)
    nrm = rv['normal'] if rv.get('normal') is not None else np.zeros(L.shape + (3,), np.float32)
    uv = rv['uv']
    ju = np.zeros(L.shape, bool)
    du = np.abs(np.diff(uv[:, :, 0], axis=1)) > UV_JUMP
    dv = np.abs(np.diff(uv[:, :, 1], axis=0)) > UV_JUMP
    ju[:, 1:] |= du
    ju[1:, :] |= dv
    good = mask & (dist > EDGE_PX) & (cosm >= COS_MIN) & ~ju
    if face_ok is not None:                                              # видимое/невидимое одной грани раздельно: берём только разрешённые грани
        good &= np.where(rv['ids'] >= 0, face_ok[np.maximum(rv['ids'], 0)], False)
    if extra_valid is not None:
        good &= extra_valid
    out: dict = {}
    dbg = {'px_mask': int(mask.sum()), 'px_good': int(good.sum()), 'px_not_edge': int((mask & (dist > EDGE_PX)).sum()), 'px_cos_ok': int((mask & (cosm >= COS_MIN)).sum()), 'px_no_uvjump': int((mask & ~ju).sum()),
           'px_face_ok': int(good.sum()), 'win_total': 0, 'win_not_good': 0, 'win_zone_mixed': 0, 'win_rough': 0, 'win_ok': 0}
    for y0 in range(0, px - WIN + 1, STRIDE):
        for x0 in range(0, px - WIN + 1, STRIDE):
            sl = (slice(y0, y0 + WIN), slice(x0, x0 + WIN))
            dbg['win_total'] += 1
            gm = good[sl]
            if gm.mean() < GOOD_SHARE:
                dbg['win_not_good'] += 1
                continue
            zw = zmap[sl][gm]
            zw = zw[zw >= 0]
            if zw.size < GOOD_SHARE * gm.size:
                dbg['win_zone_mixed'] += 1
                continue
            z = int(np.bincount(zw).argmax())
            if (zw == z).mean() < ZONE_SHARE:
                dbg['win_zone_mixed'] += 1
                continue
            if nrm[sl][gm].reshape(-1, 3).std(0).max() > NORM_STD:
                dbg['win_rough'] += 1
                continue
            dbg['win_ok'] += 1
            out.setdefault(z, []).append(window_features(bm, L, y0, x0, WIN))
    WIN_DEBUG.append(dbg)
    return out


# ── сборка ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def compare(form_geo: dict, ref_tex: np.ndarray, form_geoms: list, ref_geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, parts=None, zone_override=None, views=None, n: int | None = None) -> dict:
    """form_geo — наша геометрия в кубе (V,F,UV,N; как `R.load_model`), ref_tex — текстура образца (uint8), form_geoms/ref_geoms — геометрии для проверки «тот же меш» (load_shape),
    st — камера 04 (`TV.load_stage`), prgb/pmask — фото в кадре камеры, parts — геометрические части по граням (границы продолжения зон), zone_override — метки зон 03 по граням (главный источник).
    → словарь результата (см. заголовок модуля)."""
    import cv2
    del WIN_DEBUG[:]
    sm = same_mesh(form_geoms, ref_geoms)
    if not sm['same']:
        raise SameMeshRequired('образец и наша форма — разные меши: ' + json.dumps(sm, ensure_ascii=False)[:300] + ' — нужна привязка зон по рендерам одного ракурса')
    nF = len(form_geo['F'])
    px = int(n or st['px'])
    cam0 = dict(st['camera'])
    # М1: зоны
    inner = st['mask'] & pmask & (cv2.distanceTransform((st['mask'] & pmask).astype(np.uint8), cv2.DIST_L2, 3) > EDGE_PX) & (st['cos'] >= COS_MIN)
    seg, centres = segment_photo(prgb, inner)
    if zone_override is not None:
        fz = np.asarray(zone_override, np.int32)
        z_src = 'этап 03'
    else:
        fz, _tot = label_faces(nF, st, seg, inner)
        z_src = 'сегменты нашего фото'
    n_lab_photo = int((fz >= 0).sum())
    import pose_fit as PF
    _C, _rt, _up, _fw = PF.cam_basis(float(cam0['az']), 0.0, float(cam0['d']))
    basis = (_rt, _up, _fw)
    fz_all, pinfo = panel_zones(form_geo['V'], form_geo['F'], fz, parts, basis, return_info=True)
    fside = face_sides(form_geo['V'], form_geo['F'], object_basis(form_geo['V'], form_geo['F'], basis)[0])
    # М2: рендеры образца: вид фото (из камеры 04) и стороны при том же масштабе
    tex2k = ref_tex if max(ref_tex.shape[:2]) <= 2048 else cv2.resize(ref_tex, (2048, 2048), interpolation=cv2.INTER_AREA)
    tex2k = tex2k.astype(np.float32)
    az0, el0, f0 = float(cam0['az']), float(cam0['el']), float(cam0['f'])
    view_def = views or {'photo': (az0, el0), 'back': (az0 + 180.0, 12.0), 'right': (az0 + 90.0, 12.0), 'left': (az0 - 90.0, 12.0), 'top': (az0, 72.0)}
    wins: dict = {}
    for vn, (az, el) in view_def.items():
        cam = dict(cam0) if vn == 'photo' else fit_cam(form_geo, az, el, f0, float(cam0['d']))
        rv = render_view(form_geo, tex2k, cam, px)
        if vn == 'photo':
            ph_valid = pmask & st['mask']
            wins['photo_ref'] = collect_windows(rv, rv['rgb'], fz, ph_valid, rv['mask'] & st['mask'])
            wins['photo_photo'] = collect_windows(rv, prgb, fz, ph_valid, pmask & st['mask'])      # то же окно, цвет — фото
            # окна только с лицевыми гранями, размеченными по фото (настоящие фото-пиксели): зона грани из голосов фото, не из продолжения
        else:
            wins[vn] = collect_windows(rv, rv['rgb'], fz_all, None, rv['mask'], face_ok=(fz < 0))              # решения — только по граням, которых нет на фото
            wins[vn + '_all'] = collect_windows(rv, rv['rgb'], fz_all, None, rv['mask'])                        # для проверки зеркала бок↔бок: любые грани
    zones = {}
    present = sorted({z for v in wins.values() if isinstance(v, dict) for z in v})
    cover = {'decided': 0, 'applicable': 0, 'unknown': 0, 'not_applicable': 0}
    amap = {}
    for z in present:
        pr, pp = aggregate(wins['photo_ref'].get(z, [])), aggregate(wins['photo_photo'].get(z, []))
        gt = gate(pr, pp)
        entry = {'faces_total': int((fz_all == z).sum()), 'faces_from_photo': int((fz == z).sum()), 'photo_voice': {k: {'ok': bool(v[0]), 'why': v[1]} for k, v in gt.items()}, 'features': {'photo_ref': pr, 'photo_photo': pp}, 'sides': {}}
        amap[z] = {}
        for vn in ('back', 'right', 'left', 'top'):
            ag = aggregate(wins.get(vn, {}).get(z, []))
            entry['features'][vn] = ag
            dec = decide(pr, ag)
            for p in PROPS:
                if dec[p]['decision'] in ('same', 'different') and not gt[p][0]:
                    dec[p] = _d('unknown', 'голос образца выключен: ' + gt[p][1], raw=dec[p]['decision'])
            entry['sides'][vn] = dec
            amap[z][vn] = {p: dec[p]['decision'] for p in PROPS}
            for p in PROPS:
                d = dec[p]['decision']
                if d == 'not_applicable':
                    cover['not_applicable'] += 1
                else:
                    cover['applicable'] += 1
                    cover['decided' if d in ('same', 'different') else 'unknown'] += 1
        # проверка зеркала: левый бок против правого (должно быть same)
        al, ar = aggregate(wins.get('left_all', {}).get(z, [])), aggregate(wins.get('right_all', {}).get(z, []))
        sym = decide(al, ar)
        entry['symmetry_left_right'] = {p: sym[p]['decision'] for p in PROPS}
        zones[int(z)] = entry
    return {'window_debug': list(WIN_DEBUG), 'same_mesh': sm, 'zone_source': z_src, 'segment_centres_Lab': np.round(centres, 1).tolist(), 'faces_labelled_by_photo': n_lab_photo, 'faces_total': nF,
            'faces_with_zone_after_propagation': int((fz_all >= 0).sum()), 'propagation': pinfo, 'face_side': fside,
            'disputed_share': round(pinfo['disputed'] / max(pinfo['todo'], 1), 4), 'disputed_ok': bool(pinfo['disputed'] / max(pinfo['todo'], 1) <= float(R.get('disputed_max_share', 0.5))), 'zones': zones, 'map': {int(k): v for k, v in amap.items()}, 'coverage': cover, 'face_zone': fz_all.astype(np.int32)}


# ── Б (директор 22.11): зоны по ПАНЕЛЯМ; невидимое без меток — только по симметрии бока и по зоне боковых панелей ─────────────────────────────
def _face_area_cen_normal(V, F):
    V = np.asarray(V, np.float64)
    F = np.asarray(F)
    c = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    ar = 0.5 * np.linalg.norm(c, axis=1)
    return ar, V[F].mean(1), c / np.maximum(2 * ar[:, None], 1e-12)


def object_basis(V, F, basis) -> tuple:
    """Оси ПРЕДМЕТА в мире по горизонтальным нормалям граней: угол θ нормали в плоскости (right, fwd) камеры; прямоугольный предмет даёт пики через 90° → ψ = arg Σ w·e^{i4θ} / 4 (w — площадь × горизонтальность).
    Лицо — ось (из четырёх), ближайшая к направлению на камеру (−fwd). → (basis предмета (right, up, fwd), δ в градусах: поворот предмета от камеры; −45…45)."""
    right, up, fwd = (np.asarray(b, np.float64) for b in basis)
    ar, _c, n = _face_area_cen_normal(V, F)
    x, z = n @ right, n @ fwd
    hz = np.sqrt(np.maximum(1 - (n @ up) ** 2, 0.0))
    th = np.arctan2(z, x)
    w = ar * hz ** 2
    psi = np.angle((w * np.exp(4j * th)).sum()) / 4.0
    best = None
    for k in range(4):
        a = psi + k * np.pi / 2
        vec = np.cos(a) * right + np.sin(a) * fwd
        score = float(vec @ (-fwd))
        if best is None or score > best[0]:
            best = (score, vec)
    front = best[1]
    delta = float(np.arctan2(front @ right, front @ (-fwd)))
    cd, sd = np.cos(delta), np.sin(delta)
    return (cd * right + sd * fwd, up, cd * fwd - sd * right), float(np.degrees(delta))


def face_sides(V, F, basis) -> np.ndarray:
    """Сторона грани: ось по нормали БЕЗ знака (обмотка мешей не согласована), знак — по положению центра грани относительно центра габарита. -1 лицо (в сторону камеры), 0 зад, 1 правый, 2 левый,
    3 верх (крышка), 4 низ, -2 косая (нормаль к ближайшей оси < PANEL_SIDE_COS). basis = (right, up, fwd) предмета; fwd — от камеры к предмету."""
    right, up, fwd = (np.asarray(b, np.float64) for b in basis)
    Vv = np.asarray(V, np.float64)
    _a, cen, n = _face_area_cen_normal(Vv, F)
    rel = cen - 0.5 * (Vv.min(0) + Vv.max(0))
    axes = [-fwd, right, up]
    dots = np.stack([np.abs(n @ a_) for a_ in axes], 1)
    k = dots.argmax(1)
    pos = np.stack([rel @ a_ for a_ in axes], 1)[np.arange(len(k)), k]
    half = np.array([0.5 * np.ptp(Vv @ a_) for a_ in axes])
    sg = pos >= 0
    code = np.select([(k == 0) & sg, (k == 0) & ~sg, (k == 1) & sg, (k == 1) & ~sg, (k == 2) & sg], [-1, 0, 1, 2, 3], 4)
    code[dots.max(1) < PANEL_SIDE_COS] = -2
    code[np.abs(pos) < PANEL_OUTER * half[k]] = -2                 # внутри габарита (стенки рельефа на лице, полки): не сторона
    return code.astype(np.int32)


def mirror_score(V, F, right, eps_frac: float, n_samples: int = 60000, cos_min: float = 0.7) -> tuple:
    """Симметрия формы плоскостью, перпендикулярной `right` через середину габарита, по ТОЧКАМ поверхности (триангуляция лево/право не зеркальна): доля площади, у которой отражённая точка
    ближе eps·диагональ к поверхности с нормалью, отражённой с cos ≥ 0,7. → (доля, функция twin(грани) → (индекс грани-двойника, ok))."""
    from scipy.spatial import cKDTree
    Vv = np.asarray(V, np.float64)
    Ff = np.asarray(F)
    r = np.asarray(right, np.float64)
    r = r / np.linalg.norm(r)
    t = Vv @ r
    c0 = 0.5 * (t.min() + t.max())
    diag = float(np.linalg.norm(Vv.max(0) - Vv.min(0)))
    ar, cen, n = _face_area_cen_normal(Vv, Ff)
    rng = np.random.default_rng(0)
    fi = rng.choice(len(Ff), size=n_samples, p=ar / ar.sum())
    u = rng.random((n_samples, 2))
    flip = u.sum(1) > 1
    u[flip] = 1 - u[flip]
    tri = Vv[Ff[fi]]
    pts = tri[:, 0] + u[:, :1] * (tri[:, 1] - tri[:, 0]) + u[:, 1:] * (tri[:, 2] - tri[:, 0])
    tree = cKDTree(pts)

    def refl_pt(x):
        return x - 2 * ((x @ r) - c0)[:, None] * r[None, :]

    def refl_n(x):
        return x - 2 * (x @ r)[:, None] * r[None, :]

    def twin(faces):
        faces = np.asarray(faces)
        d, k = tree.query(refl_pt(cen[faces]), k=1)
        jf = fi[k]
        ok = (d <= eps_frac * diag) & (np.abs((refl_n(n[faces]) * n[jf]).sum(1)) >= cos_min)
        return jf, ok

    d, k = tree.query(refl_pt(pts), k=1)
    okp = (d <= eps_frac * diag) & (np.abs((refl_n(n[fi]) * n[fi[k]]).sum(1)) >= cos_min)
    return float(okp.mean()), twin


def panel_ids(V, F, parts) -> np.ndarray:
    """Панели: связные области граней с изломом ребра ≤ PANEL_DEG (и той же геометрической части)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    i, j, _w, dih, _n = face_graph(V, F)
    ok = dih <= PANEL_DEG
    if parts is not None:
        pa = np.asarray(parts)
        ok &= pa[i] == pa[j]
    nF = len(F)
    g = coo_matrix((np.ones(2 * int(ok.sum())), (np.concatenate([i[ok], j[ok]]), np.concatenate([j[ok], i[ok]]))), shape=(nF, nF)).tocsr()
    return connected_components(g, directed=False)[1].astype(np.int32)


def _dominant(zones: np.ndarray, area: np.ndarray, min_share: float):
    sel = zones >= 0
    if not sel.any():
        return None, 0.0
    zs = np.unique(zones[sel])
    ar = np.array([area[zones == z].sum() for z in zs])
    k = int(ar.argmax())
    return int(zs[k]), float(ar[k] / ar.sum())


def panel_zones(V, F, fz: np.ndarray, parts, basis, return_info: bool = False):
    """Зоны всех граней по правилу директора (Б, 22.11), одна зона на грань, смеси нет:
    (1) панель с видимой частью — зона по меткам фото внутри этой панели (продолжение по рёбрам ТОЛЬКО в панели);
    (2) невидимый бок без меток — зона видимого бока по симметрии формы (двойник через плоскость), иначе -1;
    (3) зад без меток — зона БОКОВЫХ панелей, только если обе стороны одной зоны (доля ≥ PANEL_PURITY), иначе -1;
    (4) крышка, низ, косые, всё прочее без меток — -1 (unknown → нейтральный тон, 07 решает сам). → карта (+ info)."""
    fz = np.asarray(fz, np.int32)
    nF = len(F)
    basis, delta_deg = object_basis(V, F, basis)                  # оси предмета, не камеры (фото под углом)
    pid = panel_ids(V, F, parts)
    out, info = propagate_zones(V, F, fz, pid, return_info=True)         # шаг 1: границы продолжения = панели
    ar, cen, nrm = _face_area_cen_normal(V, F)
    sd = face_sides(V, F, basis)
    right = np.asarray(basis[0], np.float64)
    info['object_yaw_deg'] = round(delta_deg, 1)
    info['steps'] = {'photo_panels': int((out >= 0).sum()), 'mirror': 0, 'back': 0}
    info['sym_score'] = None
    labelled = out >= 0
    # шаг 2: невидимый бок по симметрии
    sc, twin = mirror_score(V, F, right, SYM_EPS)
    info['sym_score'] = round(sc, 3)
    if sc >= SYM_MIN:
        sidef = np.isin(sd, (1, 2))
        for p in np.unique(pid[sidef]):
            m = (pid == p) & sidef                                    # грани БОКА этой панели (панель бок+днище не блокирует)
            if labelled[pid == p].any() or ar[m].sum() < 0.3 * ar[pid == p].sum():
                continue
            fm = np.flatnonzero(m)
            jf, okt = twin(fm)
            zt = out[jf[okt]]
            zt = zt[zt >= 0]
            if len(zt) == 0 or ar[fm][okt].sum() < 0.5 * ar[fm].sum():
                continue
            zs, shares = np.unique(zt, return_counts=True)
            if shares.max() / shares.sum() >= PANEL_PURITY:
                out[m] = int(zs[shares.argmax()])
                info['steps']['mirror'] += int(m.sum())
    # шаг 3: зад без меток — зона боковых панелей, если обе стороны одной зоны
    backf = sd == 0
    back = [p for p in np.unique(pid[backf]) if not (out[pid == p] >= 0).any() and ar[backf & (pid == p)].sum() >= 0.3 * ar[pid == p].sum()]
    if back:
        zr, pr = _dominant(np.where(sd == 1, out, -1), ar, PANEL_PURITY)
        zl, pl = _dominant(np.where(sd == 2, out, -1), ar, PANEL_PURITY)
        if zr is not None and zr == zl and pr >= PANEL_PURITY and pl >= PANEL_PURITY:
            for p in back:
                m = (pid == p) & backf
                out[m] = zr
                info['steps']['back'] += int(m.sum())
    info['unknown'] = int((out < 0).sum())
    info['side_zone'] = {'right': _dominant(np.where(sd == 1, out, -1), ar, 0)[0], 'left': _dominant(np.where(sd == 2, out, -1), ar, 0)[0]}
    return (out, info) if return_info else out


# ── «суть целиком» (владелец TG 1643: «UltraTex всегда что-то красит, берём как рисует»): без unknown, без голосов и гейта М4 ─────────────────────────────────────────────
def ultratex_full(geoms: list, tex_after: list, known: list, ut_geoms: list, parts: list) -> tuple:
    """На НЕвидимых текселях (не known) каждой части (зона по панелям) к цвету заливки добавляется ΔL = L_UltraTex − низкий пас L_UltraTex по этой части (σ `full.sigma` px карты: средние и высокие частоты,
    средний уровень части и относительная яркость перёд↔зад убраны), ограничено ±`full.clip`; a, b — наши. Тот же меш: тексель в тексель. Фото-тексели не меняются.
    Мерка риска (видимая сторона): σ того же ΔL на known-текселях части у UltraTex ÷ max(σ по фото, `full.photo_floor`) > `full.risk_ratio` → рябь там, где на фото гладко.
    → (текстуры, отчёт {'parts': {часть: {...}}, 'risky_parts', 'texels_changed'})."""
    import cv2
    import tex_coverage as TC
    F = dict({'sigma': 12.0, 'clip': 35.0, 'risk_ratio': 2.0, 'photo_floor': 0.8, 'min_visible': 500, 'edge_thr': 8.0, 'edge_share_max': 0.01}, **R.get('full', {}))
    out, rep = [], {'parts': {}, 'risky_parts': [], 'texels_changed': 0, 'sharp_parts': {}}
    for gi, g in enumerate(geoms):
        tex = np.asarray(tex_after[gi], np.uint8)
        T = int(tex.shape[0])
        ut = np.asarray(ut_geoms[gi]['tex'])[..., :3]
        ut = np.clip(ut, 0, 255).astype(np.uint8) if ut.dtype != np.uint8 else ut
        if ut.shape[0] != T:
            ut = cv2.resize(ut, (T, T), interpolation=cv2.INTER_AREA)
        xy = np.stack([g['UV'][:, 0] * T, (1.0 - g['UV'][:, 1]) * T], 1)
        fid, _ = TC.raster(xy, g['F'], T)
        fid = fid.reshape(T, T)
        occ = fid >= 0
        pm = np.where(occ, np.asarray(parts[gi])[np.maximum(fid, 0)], -1)
        kn = np.asarray(known[gi], bool)
        lab = cv2.cvtColor(tex.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
        Lu = cv2.cvtColor(ut.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0]
        L0 = lab[..., 0].copy()
        for pid in np.unique(pm[occ]):
            mp = pm == pid
            det = np.clip(Lu - _nconv(Lu, mp, F['sigma']), -F['clip'], F['clip'])
            unk = mp & ~kn
            lab[..., 0][unk] += det[unk]
            if unk.sum() >= F['min_visible']:                                    # резкие линии/прямоугольники на невидимом (ручки, швы ДВП): конструкция из «целиком» не вычитается — только отметка
                dsm = cv2.GaussianBlur(det.astype(np.float32), (0, 0), 1.5)
                gx, gy = cv2.Sobel(dsm, cv2.CV_32F, 1, 0, ksize=3) / 8.0, cv2.Sobel(dsm, cv2.CV_32F, 0, 1, ksize=3) / 8.0
                gm = np.sqrt(gx ** 2 + gy ** 2)[cv2.erode(unk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)]
                sh = float((gm > F['edge_thr']).mean()) if gm.size else 0.0
                rep['sharp_parts'][int(pid)] = {'edge_share': round(sh, 4), 'sharp': bool(sh > F['edge_share_max'])}
            rep['texels_changed'] += int(unk.sum())
            kv = mp & kn
            if int(kv.sum()) >= F['min_visible']:
                dp = (L0 - _nconv(L0, kv, F['sigma']))[kv]
                su, sp = float(det[kv].std()), float(dp.std())
                ratio = su / max(sp, F['photo_floor'])
                rep['parts'][int(pid)] = {'ut_hf_std_visible': round(su, 3), 'photo_hf_std_visible': round(sp, 3), 'ratio': round(ratio, 2), 'risk': bool(ratio > F['risk_ratio'])}
                if ratio > F['risk_ratio']:
                    rep['risky_parts'].append(int(pid))
        out.append(np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8))
    return out, rep


def _texel_points(g: dict, T: int) -> tuple:
    """Занятые тексели карты T×T: (плоские индексы, 3D-точки центров текселей по барицентрам грани)."""
    import tex_coverage as TC
    V, F, UV = np.asarray(g['V'], np.float64), np.asarray(g['F'], np.int64), np.asarray(g['UV'], np.float64)
    xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    fid, _ = TC.raster(xy, F, T)
    idx = np.flatnonzero(fid >= 0)
    f = fid[idx].astype(np.int64)
    px, py = (idx % T) + 0.5, (idx // T) + 0.5
    a, b, c = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    w0 = ((b[:, 1] - c[:, 1]) * (px - c[:, 0]) + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / den
    w1 = ((c[:, 1] - a[:, 1]) * (px - c[:, 0]) + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / den
    w2 = 1.0 - w0 - w1
    P = w0[:, None] * V[F[f, 0]] + w1[:, None] * V[F[f, 1]] + w2[:, None] * V[F[f, 2]]
    return idx, P


def _yaw_rotate(P: np.ndarray, center: np.ndarray, deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    x, z = P[:, 0] - center[0], P[:, 2] - center[2]
    out = P.copy()
    out[:, 0] = center[0] + c * x + s * z
    out[:, 2] = center[2] - s * x + c * z
    return out


def align_ut(geoms: list, tex_after: list, known: list, ut_geoms: list | None, yaw: int | None = None) -> tuple:
    """UltraTex → поза НАШЕГО фото (владелец TG 1744 п.①). UltraTex красит ту же форму, но «перёд» кладёт на ту сторону, которую считает фото-стороной, — она может не совпасть с нашей.
    Перебор поворота UltraTex вокруг вертикали (`align.cands`, град.): для каждого берётся цвет UltraTex в повёрнутой 3D-точке каждого нашего текселя (ближайший тексель UltraTex); оценка — корреляция
    детали L (L − маскированный низкий пас σ `full.sigma`, лёгкое размытие) UltraTex и ФОТО на известных текселях. Лучший поворот принят, если корреляция ≥ `align.min_corr` и лучше нулевого на ≥ `align.margin`
    (симметричный предмет — любой поворот одинаков, берётся 0); нет детали → 'uncertain' (UltraTex дальше не используется); несколько поворотов почти равны (отрыв < `align.margin`) → 'tied' + `ties` — выбор за
    вызывающим (07: по автопроверке front_on_back после заливки); `yaw` задан — без оценки, UltraTex сразу переносится в этот поворот. → (список {'V','F','UV','tex'} в НАШЕЙ раскладке | None, отчёт)."""
    import cv2
    from scipy.spatial import cKDTree
    A = dict({'cands': [0, 90, 180, 270], 'min_score': 0.3, 'margin': 0.10, 'samples': 40000, 'ut_points_max': 1500000, 'seed': 3, 'energy_sigma': 6.0, 'eps': 0.3}, **R.get('align', {}))
    FU = dict({'sigma': 12.0}, **R.get('full', {}))
    rep = {'status': 'no_ut', 'yaw_deg': None, 'corr': {}}
    if ut_geoms is None:
        return None, rep
    rng = np.random.RandomState(int(A['seed']))
    res = []
    scores = {int(d): [] for d in ([int(yaw)] if yaw is not None else A['cands'])}
    cache = []
    for gi, g in enumerate(geoms):
        tex = np.asarray(tex_after[gi], np.uint8)
        T = int(tex.shape[0])
        ug = ut_geoms[gi]
        ut = np.asarray(ug['tex'])[..., :3]
        ut = np.clip(ut, 0, 255).astype(np.uint8) if ut.dtype != np.uint8 else ut
        Tu = int(ut.shape[0])
        idx_o, Po = _texel_points(g, T)
        idx_u, Pu = _texel_points(ug, Tu)
        if len(idx_u) > A['ut_points_max']:
            keep = rng.choice(len(idx_u), int(A['ut_points_max']), replace=False)
            idx_u, Pu = idx_u[keep], Pu[keep]
        tree = cKDTree(Pu)
        kn = np.asarray(known[gi], bool).ravel()
        center = 0.5 * (np.asarray(g['V']).min(0) + np.asarray(g['V']).max(0))
        Lp = cv2.cvtColor(tex.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0]
        kmask = np.asarray(known[gi], bool)
        hp_raw = cv2.GaussianBlur((Lp - _nconv(Lp, kmask, FU['sigma'])).astype(np.float32), (0, 0), 1.0)
        hp_p = _nconv(np.abs(hp_raw) * kmask, kmask, float(A['energy_sigma'])).ravel()
        Lu = cv2.cvtColor(ut.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0]
        occu = np.zeros(Tu * Tu, bool)
        occu[_texel_points(ug, Tu)[0]] = True
        su = FU['sigma'] * Tu / T
        om = occu.reshape(Tu, Tu)
        hu_raw = cv2.GaussianBlur((Lu - _nconv(Lu, om, su)).astype(np.float32), (0, 0), 1.0 * Tu / T)
        hp_u = _nconv(np.abs(hu_raw) * om, om, float(A['energy_sigma']) * Tu / T).ravel()
        kn_idx = np.flatnonzero(kn[idx_o])
        if len(kn_idx) > A['samples']:
            kn_idx = rng.choice(kn_idx, int(A['samples']), replace=False)
        for d in scores:
            _dist, j = tree.query(_yaw_rotate(Po[kn_idx], center, d), workers=-1)
            a_, b_ = hp_p[idx_o[kn_idx]], hp_u[idx_u[j]]
            scores[d].append((a_, b_))
        cache.append((g, ug, ut, T, Tu, idx_o, Po, idx_u, tree, center))
    if yaw is not None:
        rep.update({'status': 'forced', 'yaw_deg': int(yaw)})
    else:
        corr = {}
        eps = float(A['eps'])
        for d, lst in scores.items():
            a_, b_ = np.concatenate([x[0] for x in lst]), np.concatenate([x[1] for x in lst])
            if len(a_) <= 200:
                corr[d] = None
                continue
            lvl = float(np.exp(-abs(np.log((b_.mean() + eps) / (a_.mean() + eps)))))        # уровень энергии детали: у фото и у UltraTex на тех же местах один порядок
            cc = float(np.corrcoef(a_, b_)[0, 1]) if a_.std() > 1e-6 and b_.std() > 1e-6 else 0.0
            corr[d] = round(lvl * (0.5 + 0.5 * max(cc, 0.0)), 3)
        rep['corr'] = {str(k): v for k, v in corr.items()}
        ok_ = {d: c for d, c in corr.items() if c is not None}
        best, c_best = (max(ok_.items(), key=lambda kv: kv[1]) if ok_ else (None, None))
        if best is None or c_best < A['min_score']:
            rep.update({'status': 'uncertain', 'yaw_deg': None, 'why': 'нет детали на фото/UltraTex для сверки'})
            return None, rep
        ties = sorted(d for d, c in ok_.items() if c >= c_best - A['margin'])
        if len(ties) > 1:                                                                   # несколько поворотов почти равны (№11: 90° и 270°) — выбор по front_on_back у вызывающего
            rep.update({'status': 'tied', 'yaw_deg': None, 'corr_best': c_best, 'ties': ties, 'why': f'повороты {ties} различаются меньше отрыва {A["margin"]}'})
            return None, rep
        yaw = int(best)
        rep.update({'status': 'aligned' if yaw else 'identity', 'yaw_deg': yaw, 'corr_best': c_best})
    for g, ug, ut, T, Tu, idx_o, Po, idx_u, tree, center in cache:
        flat = ut.reshape(Tu * Tu, 3)
        img = np.zeros((T * T, 3), np.uint8)
        st = 2 if int(T) // max(int(Tu), 1) >= 2 else 1                                      # тексель UltraTex крупнее нашего вдвое и больше: запрос по каждому 2-му, остальные — копия у опорного текселя блока (в 4 раза быстрее)
        if st > 1:
            x, y = idx_o % T, idx_o // T
            base = (y - y % st) * T + (x - x % st)
            isq = idx_o == base
            q = np.flatnonzero(isq)
            _dist, j = tree.query(_yaw_rotate(Po[q], center, yaw), workers=-1)
            img[idx_o[q]] = flat[idx_u[j]]
            occ = np.zeros(T * T, bool)
            occ[idx_o[q]] = True
            rest = np.flatnonzero(~isq)
            cp = occ[base[rest]]
            img[idx_o[rest[cp]]] = img[base[rest[cp]]]
            nq = rest[~cp]                                                                     # опорный тексель блока вне карты (край острова) — свой запрос
            if len(nq):
                _dist, j2 = tree.query(_yaw_rotate(Po[nq], center, yaw), workers=-1)
                img[idx_o[nq]] = flat[idx_u[j2]]
        else:
            _dist, j = tree.query(_yaw_rotate(Po, center, yaw), workers=-1)
            img[idx_o] = flat[idx_u[j]]
        res.append({'V': g['V'], 'F': g['F'], 'UV': g['UV'], 'tex': img.reshape(T, T, 3)})
    return res, rep


def sub_tone(geoms: list, tex_before: list, tex_after: list, known: list, parts: list | None) -> tuple:
    """Подчасть по цвету 06 (T-187/6 Б, 23.11; разбор независимого рецензента). Часть красится одним тоном (`stat[p]`), а внутри неё бывают мелкие НЕВИДИМЫЕ панели со своим цветом (ножки дивана чёрные,
    кронштейны стола, белые крошки): цвет 06 в их текселях (база, фото там не легло) — слабая подсказка. Абсолютный цвет 06 врёт (ΔE до 62 против фото), поэтому берётся ОТНОСИТЕЛЬНЫЙ контраст:
    панель (не видна: известных < `min_known`) ровная (≥ `uniform_share` текселей в пределах `uniform_de` от своей медианы 06) и её медиана 06 далека от доминанты 06 невидимой части (D_p)
    на ≥ `contrast_de` (оба нейтральные — ещё и |ΔL| ≥ `neutral_dL`) → «подчасть». Классы подчастей (медианы в `class_merge`) держатся, только если их площадь в пределах [`area_min`, `area_max`] площади
    невидимой части (иначе — «цвет базы вообще другой», это не подчасть). Перенос: a,b = наш + `ab_gain`·(медиана 06 − D_p), L = наша × clip(L06/L_D, `L_lo`, `L_hi`) — квилт сохраняется, контраст масштабируется.
    Известные (фото) тексели не меняются. → (текстуры, отчёт {'enabled', 'parts': {p: {...}}, 'texels_changed', 'subtone_share_pct', 'lost_contrast_pct'})."""
    import cv2
    import tex_coverage as TC
    import tex_fill as TF
    O = dict({'enabled': True, 'min_known': 0.05, 'min_texels': 150, 'uniform_share': 0.8, 'uniform_de': 10.0, 'contrast_de': 22.0, 'neutral_chroma': 8.0, 'neutral_dL': 30.0,
              'class_merge': 8.0, 'area_min': 0.003, 'area_max': 0.20, 'small_part_share': 0.05, 'dark_L': 55.0, 'ab_gain': 0.8, 'L_lo': 0.15, 'L_hi': 1.3, 'lost_ratio': 0.3}, **R.get('sub_tone', {}))
    rep = {'enabled': bool(O['enabled']), 'parts': {}, 'texels_changed': 0, 'subtone_share_pct': 0.0, 'lost_contrast_pct': 0.0}
    if not O['enabled']:
        return [np.asarray(t, np.uint8) for t in tex_after], rep

    def lab_of(rgb):
        return cv2.cvtColor(np.asarray(rgb, np.uint8).astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)

    def lab2rgb(lab):
        return np.clip(cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_Lab2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8)

    outs, hid_all, chg_all, lost_all = [], 0, 0, 0
    for gi, g in enumerate(geoms):
        tex = np.asarray(tex_after[gi], np.uint8)
        T = int(tex.shape[0])
        outs.append(tex)
        if parts is None:
            continue
        F = np.asarray(g['F'])
        pa = panel_ids(np.asarray(g['V'], np.float64), F, parts[gi])
        xy = np.stack([g['UV'][:, 0] * T, (1.0 - g['UV'][:, 1]) * T], 1)
        fid, _ = TC.raster(xy, F, T)
        fid = fid.reshape(-1)
        occ = fid >= 0
        pmap = np.where(occ, pa[np.maximum(fid, 0)], -1)
        part_f = np.asarray(parts[gi])
        pmap_part = np.where(occ, part_f[np.maximum(fid, 0)], -1)
        kn = np.asarray(known[gi], bool).ravel()
        bef = np.asarray(tex_before[gi], np.uint8)
        if bef.shape[0] != T:
            continue
        unp = TF.unpainted_mask(bef).reshape(-1)
        lb = lab_of(bef).reshape(-1, 3)
        la = lab_of(tex).reshape(-1, 3)
        use = occ & ~unp
        ids, inv = np.unique(pmap[use], return_inverse=True)
        pidx = np.flatnonzero(use)
        order = np.argsort(inv, kind='stable')
        splits = np.split(pidx[order], np.cumsum(np.bincount(inv, minlength=len(ids)))[:-1])
        panels = {int(i): sp for i, sp in zip(ids, splits)}
        res = tex.reshape(-1, 3).copy()
        hid_by = {}
        for p in sorted({int(x) for x in np.unique(pmap_part[use])}):
            pans = {k: v for k, v in panels.items() if int(pmap_part[v[0]]) == p}
            h = {k: v[~kn[v]] for k, v in pans.items() if kn[v].mean() < O['min_known']}
            h = {k: v for k, v in h.items() if len(v) >= O['min_texels']}
            if h:
                hid_by[p] = h
        tot = sum(len(v) for h in hid_by.values() for v in h.values())
        if tot < 4 * O['min_texels']:
            continue
        D_all = np.median(lb[np.concatenate([v for h in hid_by.values() for v in h.values()])], axis=0)
        groups, small = {}, {}
        for p, h in hid_by.items():
            n_p = sum(len(v) for v in h.values())
            if n_p >= O['small_part_share'] * tot:
                groups[f'{p}'] = (h, None)                                       # большая часть: ссылка — её собственная доминанта 06
            else:
                small.update({(p, k): v for k, v in h.items()})                  # мелкие части: общая группа, ссылка — доминанта 06 всего товара
        if small:
            groups['small'] = (small, D_all)
        for gname, (hid, Dref) in groups.items():
            allh = np.concatenate(list(hid.values()))
            Dp = np.median(lb[allh], axis=0) if Dref is None else Dref
            area_den = len(allh) if Dref is None else tot
            cls = []
            for k, v in hid.items():
                x = lb[v]
                m = np.median(x, axis=0)
                if float(np.mean(np.linalg.norm(x - m, axis=1) <= O['uniform_de'])) < O['uniform_share']:
                    continue
                dE = float(np.linalg.norm(m - Dp))
                neut = max(float(np.hypot(m[1], m[2])), float(np.hypot(Dp[1], Dp[2]))) < O['neutral_chroma']
                if dE < O['contrast_de'] or (neut and abs(float(m[0] - Dp[0])) < O['neutral_dL']):
                    continue
                if not (float(np.hypot(m[1], m[2])) < O['neutral_chroma'] and float(m[0]) < O['dark_L']):
                    continue                                                     # только тёмное нейтральное (ножки, кронштейны, металл): светлое/цветное против базы товара ненадёжно (база бывает белой при бежевом фото)
                for c in cls:
                    if float(np.linalg.norm(c['m'] - m)) < O['class_merge']:
                        c['panels'].append(k)
                        c['n'] += len(v)
                        break
                else:
                    cls.append({'m': m, 'panels': [k], 'n': len(v)})
            kept = [c for c in cls if O['area_min'] <= c['n'] / area_den <= O['area_max']]
            info = {'hidden_texels': int(len(allh)), 'ref': 'own' if Dref is None else 'product', 'D_ref': [round(float(x), 1) for x in Dp], 'classes': [], 'skipped_classes': len(cls) - len(kept)}
            hid_all += int(len(allh))
            for c in kept:
                idx = np.concatenate([hid[k] for k in c['panels']])
                la_i = la[idx]
                lost = float(np.linalg.norm(np.median(la_i, axis=0) - Dp))
                c_before = float(np.linalg.norm(c['m'] - Dp))
                new = la_i.copy()
                new[:, 1:] = la_i[:, 1:] + O['ab_gain'] * (c['m'][1:] - Dp[1:])
                new[:, 0] = la_i[:, 0] * float(np.clip(c['m'][0] / max(float(Dp[0]), 1.0), O['L_lo'], O['L_hi']))
                rgbn = lab2rgb(new.reshape(-1, 1, 3)).reshape(-1, 3)
                rgbn = np.where((rgbn.max(axis=1) <= TF.BLACK_MAX)[:, None], np.maximum(rgbn, TF.BLACK_MAX + 1), rgbn)
                if lost < O['lost_ratio'] * c_before:
                    lost_all += int(len(idx))
                res[idx] = rgbn
                chg_all += int(len(idx))
                info['classes'].append({'texels': int(len(idx)), 'panels': len(c['panels']), 'median_06': [round(float(x), 1) for x in c['m']], 'contrast_de': round(c_before, 1), 'our_contrast_de_before': round(lost, 1)})
            if info['classes'] or info['skipped_classes']:
                rep['parts'][f'{gi}:{gname}'] = info
        outs[gi] = res.reshape(tex.shape)
    rep['texels_changed'] = chg_all
    rep['subtone_share_pct'] = round(100.0 * chg_all / max(hid_all, 1), 2)
    rep['lost_contrast_pct'] = round(100.0 * lost_all / max(hid_all, 1), 2)
    return outs, rep


def own_panel_tone(geoms: list, tex_after: list, known: list, ut_geoms: list | None, parts: list | None) -> tuple:
    """Невидимые панели (T-187/6, владелец 22.11 TG 1737/1741/1744): зеркала и чужого квилта нет. Панель, у которой фото закрывает меньше `min_known` текселей, — «невидимая».
    Для неё среди ВИДИМЫХ панелей ищется донор по UltraTex (тот же меш, та же поза): тот же ОТТЕНОК (ΔE по a,b медиан UltraTex ≤ `donor_hue_de`) И та же ФАКТУРА (σ детали L−низкий пас σ `full.sigma`,
    отношение в пределах `donor_tex_ratio`, обе ниже `full.photo_floor` — «гладкое/гладкое»); светлота L не сравнивается (свой свет и тени UltraTex).
      • донор нашёлся → невидимые тексели = наш тон И наши куски (квилт из блоков ФОТО донора); разница светлоты UltraTex не переносится;
      • донора нет → тон своей зоны (медиана текущей заливки панели) + суть UltraTex (ΔL как в `ultratex_full`, нет UltraTex — плоский тон).
    Фото-тексели не меняются. → (текстуры, отчёт {'panels': {id: {...}}, 'texels_changed', 'hidden', 'with_donor'})."""
    import cv2
    import tex_coverage as TC
    import tex_fill as TF
    O = dict({'enabled': True, 'min_known': 0.05, 'min_visible_texels': 200, 'min_hidden_texels': 300, 'donor_hue_de': 6.0, 'donor_tex_ratio': 1.6, 'quilt_block': 16, 'quilt_cells': 6,
              'quilt_overlap': 4, 'quilt_pool': 300, 'quilt_tries': 40, 'ut_detail': True, 'max_panels': 80, 'seed': 7, 'edge_px': 4, 'wins_k': 2.5, 'quilt_min_sigma': 1.5, 'flat_photo_sigma': 2.0, 'neutral_chroma': 8.0, 'neutral_dL': 25.0}, **R.get('own_panel', {}))
    FU = dict({'sigma': 12.0, 'clip': 35.0, 'photo_floor': 0.8}, **R.get('full', {}))
    out, rep = [], {'panels': {}, 'texels_changed': 0, 'hidden': 0, 'with_donor': 0, 'flat_texels': 0, 'flat_rough_texels': 0}
    if not O['enabled']:
        return [np.asarray(t, np.uint8) for t in tex_after], dict(rep, off=True)

    def lab_of(rgb):
        return cv2.cvtColor(np.asarray(rgb, np.uint8).astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)

    def panel_map(geo, pa, T):
        xy = np.stack([geo['UV'][:, 0] * T, (1.0 - geo['UV'][:, 1]) * T], 1)
        fid, _ = TC.raster(xy, geo['F'], T)
        fid = fid.reshape(T, T)
        return np.where(fid >= 0, pa[np.maximum(fid, 0)], -1)

    def groups_of(pmap):
        flat = pmap.ravel()
        occ = np.flatnonzero(flat >= 0)
        order = occ[np.argsort(flat[occ], kind='stable')]
        ids, starts = np.unique(flat[order], return_index=True)
        return dict(zip(ids.tolist(), np.split(order, starts[1:])))

    def crop(idx, T, pad):
        r, c = idx // T, idx % T
        y0, y1, x0, x1 = max(int(r.min()) - pad, 0), min(int(r.max()) + pad + 1, T), max(int(c.min()) - pad, 0), min(int(c.max()) + pad + 1, T)
        m = np.zeros((y1 - y0, x1 - x0), bool)
        m[r - y0, c - x0] = True
        return y0, y1, x0, x1, m

    def detail(Lflat, idx, T, clean=False):
        """ΔL = L − маскированный низкий пас по панели (σ full.sigma) на текселях idx; → (det по idx, σ det). `clean` (применяемая ΔL, владелец 22.11): без края панели (плавно `edge_px`), без бликов выше p99 L панели,
        выбросы (кляксы, резкие пятна) режутся на ±`wins_k`·σ_устойчивая (MAD)."""
        y0, y1, x0, x1, m = crop(idx, T, int(3 * FU['sigma']))
        Lc = Lflat.reshape(T, T)[y0:y1, x0:x1].astype(np.float32)
        det = Lc - _nconv(Lc, m, FU['sigma'])
        r, c = idx // T, idx % T
        d = det[r - y0, c - x0]
        if clean and len(d):
            dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)[r - y0, c - x0]
            d = d * np.clip(dist / max(float(O['edge_px']), 1.0), 0.0, 1.0)
            lp = Lc[r - y0, c - x0]
            d = np.where(lp > np.percentile(lp, 99.0), 0.0, d)
            s = 1.4826 * float(np.median(np.abs(d - np.median(d)))) + 1e-6
            d = np.clip(d, -float(O['wins_k']) * s, float(O['wins_k']) * s)
        return d, float(d.std())

    for gi, g in enumerate(geoms):
        tex = np.asarray(tex_after[gi], np.uint8)
        T = int(tex.shape[0])
        pa = panel_ids(np.asarray(g['V'], np.float64), np.asarray(g['F']), None if parts is None else parts[gi])
        grp = groups_of(panel_map(g, pa, T))
        kn = np.asarray(known[gi], bool).ravel()
        lab = lab_of(tex).reshape(-1, 3)
        rgb = tex.reshape(-1, 3)
        lu, ugrp = None, {}
        if ut_geoms is not None:
            ut = np.asarray(ut_geoms[gi]['tex'])[..., :3]
            ut = np.clip(ut, 0, 255).astype(np.uint8) if ut.dtype != np.uint8 else ut
            if ut.shape[0] != T:
                ut = cv2.resize(ut, (T, T), interpolation=cv2.INTER_AREA)
            lu = lab_of(ut).reshape(-1, 3)
            ugrp = groups_of(panel_map(ut_geoms[gi], pa, T))
        big = sorted(grp, key=lambda k: -len(grp[k]))[: int(O['max_panels'])]
        vis, hid = [], []
        for k in big:
            idx = grp[k]
            nk = int(kn[idx].sum())
            if nk >= O['min_visible_texels'] and nk >= O['min_known'] * len(idx):
                vis.append(k)
            elif len(idx) >= O['min_hidden_texels']:
                hid.append(k)
        ustat = {}
        if lu is not None:
            for k in set(vis) | set(hid):
                if k in ugrp:
                    ustat[k] = (np.median(lu[ugrp[k]], axis=0), detail(lu[:, 0], ugrp[k], T, clean=True)[1])      # σ без края панели/бликов/выбросов: кромка и щель не считаются «фактурой»
        photo_med = {k: np.median(lab[grp[k][kn[grp[k]]]], axis=0) for k in vis}
        newlab, newrgb = lab.copy(), None
        painted_ = ~TF.unpainted_mask(rgb)                                       # свой L берём только с покрашенных текселей заливки (белое «незалитое» — не наша светлота)

        def own_L(sel):
            m_ = painted_[sel]
            return float(np.median(lab[sel][m_, 0])) if int(m_.sum()) >= 50 else None
        paint = {}
        rng = np.random.RandomState(int(O['seed']))
        for k in hid:
            idx = grp[k]
            sel = idx[~kn[idx]]
            if not len(sel):
                continue
            info = {'texels': int(len(sel)), 'tone_before': [round(float(x), 1) for x in np.median(lab[sel], axis=0)]}
            best = hue_only = None
            if k in ustat:
                uh, sh = ustat[k]
                for v in vis:
                    if v not in ustat:
                        continue
                    uv_, sv = ustat[v]
                    de = float(np.hypot(uh[1] - uv_[1], uh[2] - uv_[2]))
                    if de > O['donor_hue_de']:
                        continue
                    if max(float(np.hypot(uh[1], uh[2])), float(np.hypot(uv_[1], uv_[2]))) < O['neutral_chroma'] and abs(float(uh[0]) - float(uv_[0])) > O['neutral_dL']:
                        continue                                             # нейтральные (серое/чёрное/белое/беж): оттенок a,b почти один — светлота UltraTex различает чёрное и светлое
                    a_, b_ = max(sh, FU['photo_floor']), max(sv, FU['photo_floor'])
                    ratio = a_ / b_
                    same_tex = (sh < FU['photo_floor'] and sv < FU['photo_floor']) or (1.0 / O['donor_tex_ratio'] <= ratio <= O['donor_tex_ratio'])
                    if same_tex:
                        if best is None or de < best[1]:
                            best = (v, de, ratio, min(sh, sv) >= O['quilt_min_sigma'])
                    elif hue_only is None or de < hue_only[1]:
                        hue_only = (v, de, ratio)
            if best is not None:
                v = best[0]
                dm = np.zeros((T, T), bool)
                dm.ravel()[grp[v][kn[grp[v]]]] = True
                B = int(O['quilt_block'])
                frac = cv2.boxFilter(dm.astype(np.float32), -1, (B, B), normalize=True, borderType=cv2.BORDER_CONSTANT)
                ys, xs = np.nonzero(frac[B // 2:T - B // 2 + 1:B // 2, B // 2:T - B // 2 + 1:B // 2] > 0.999)
                pool = [tex[y * (B // 2):y * (B // 2) + B, x * (B // 2):x * (B // 2) + B] for y, x in zip(ys, xs)]
                info.update({'tone_from': 'donor', 'donor_panel': int(v), 'hue_dE_ab': round(best[1], 2), 'tex_ratio': round(best[2], 2), 'donor_blocks': len(pool), 'ut_sigma': [round(float(ustat[k][1]), 2), round(float(ustat[v][1]), 2)]})
                rep['with_donor'] += 1
                if len(pool) >= 4 and best[3]:                                   # куски фасада — только если у обеих панелей по UltraTex есть фактура; две гладкие → плоский тон донора (22.11)
                    if len(pool) > O['quilt_pool']:
                        pool = [pool[i] for i in rng.choice(len(pool), int(O['quilt_pool']), replace=False)]
                    q = TF.wrap_soften(TF.quilt_image(np.stack(pool).astype(np.float64), int(O['quilt_cells']), int(O['quilt_overlap']), rng, int(O['quilt_tries'])))
                    S = q.shape[0]
                    px = np.clip(q[(sel // T) % S, (sel % T) % S] + 0.5, 0, 255).astype(np.uint8)
                    oL = own_L(sel)
                    if oL is not None:                                           # светлота наша (ADR-0464): куски донора — оттенок и зерно, L сдвинута к медиане своей заливки панели
                        lq = lab_of(px.reshape(-1, 1, 3)).reshape(-1, 3)
                        lq[:, 0] = np.clip(lq[:, 0] + oL - float(np.median(lq[:, 0])), 0.0, 100.0)
                        px = np.clip(cv2.cvtColor(lq.reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_Lab2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8).reshape(-1, 3)
                    info['L_policy'] = 'наша' if oL is not None else 'донора (своей нет)'
                    paint[k] = (sel, px)
                    info['texture'] = 'куски донора (квилт)'
                else:
                    tone = np.array(photo_med[v], np.float32)
                    oL = own_L(sel)
                    if oL is not None:
                        tone[0] = oL                                             # светлота наша, оттенок a,b — донора (ADR-0464; раньше ровно весь Lab донора → скачок L)
                    newlab[sel] = tone
                    info['L_policy'] = 'наша' if oL is not None else 'донора (своей нет)'
                    info['texture'] = 'плоский тон донора (мало блоков)' if len(pool) < 4 else 'плоский тон донора (обе гладкие по UltraTex)'
                    kv = grp[v][kn[grp[v]]]
                    sph = detail(lab[:, 0], kv, T, clean=True)[1] if len(kv) >= 50 else 0.0     # σ L фото донора: ровно при фактурном фото — в отчёт (flat_share_pct)
                    info['photo_sigma_L'] = round(float(sph), 2)
                    rep['flat_texels'] += int(len(sel))
                    if sph >= O['flat_photo_sigma']:
                        rep['flat_rough_texels'] += int(len(sel))
            else:
                tone = np.median(lab[sel], axis=0)
                newlab[sel] = tone
                info.update({'tone_from': 'own', 'why': 'нет UltraTex' if k not in ustat else ('оттенок совпал, фактура нет' if hue_only else 'нет панели того же оттенка')})
                if hue_only:
                    info.update({'hue_only_panel': int(hue_only[0]), 'hue_dE_ab': round(hue_only[1], 2), 'tex_ratio': round(hue_only[2], 2), 'ut_sigma': [round(float(ustat[k][1]), 2), round(float(ustat[hue_only[0]][1]), 2)]})
                if O['ut_detail'] and lu is not None and k in ugrp:
                    d, _ = detail(lu[:, 0], ugrp[k], T, clean=True)              # суть UltraTex на месте: тот же шаг, что в каноне (тексель в тексель — тот же меш и раскладка)
                    dm_ = np.zeros(T * T, np.float32)
                    dm_[ugrp[k]] = np.clip(d, -FU['clip'], FU['clip'])
                    newlab[sel, 0] += dm_[sel]
                    info['texture'] = 'суть UltraTex (ΔL)'
                else:
                    info['texture'] = 'плоский'
            info['tone_after'] = [round(float(x), 1) for x in np.median(newlab[sel], axis=0)]
            rep['panels'][int(k)] = info
            rep['hidden'] += 1
            rep['texels_changed'] += int(len(sel))
        res = np.clip(cv2.cvtColor(newlab.reshape(T, T, 3).astype(np.float32), cv2.COLOR_Lab2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8).reshape(-1, 3)
        for k, (sel, px) in paint.items():
            res[sel] = px
        res[kn] = rgb[kn]
        out.append(res.reshape(T, T, 3))
    rep['flat_share_pct'] = round(100.0 * rep['flat_rough_texels'] / max(rep['texels_changed'], 1), 2)      # доля изменённого, залитая ровным тоном при фактурном фото донора
    return out, rep


# ── 07: карта зона×сторона×свойство (за флагом, по умолчанию выкл.) ───────────────────────────────────────────────────
def apply_to_fill(geoms: list, tex_after: list, known: list, face_zone: np.ndarray, face_side: np.ndarray, amap: dict, offs: list) -> tuple:
    """`texture = different` для (зона, сторона грани) → на НЕВИДИМЫХ текселях этой пары остаётся только тон: цвет заменяется маскированным низким пасом (σ 12 px карты). Идёт ПОСЛЕ любой заливки — зеркало и рельеф обойти не могут;
    фото-тексели (known) не меняются. → (новые текстуры, отчёт). Вызывать только при APPLY (rules/ref-zone.json: apply_to_fill)."""
    import cv2
    import tex_coverage as TC
    out, rep = [], {'texels_detextured': 0}
    for gi, g in enumerate(geoms):
        T = int(g['tex'].shape[0])
        tex = np.asarray(tex_after[gi], np.uint8).copy()
        xy = np.stack([g['UV'][:, 0] * T, (1.0 - g['UV'][:, 1]) * T], 1)
        fid, _ = TC.raster(xy, g['F'], T)
        fid = fid.reshape(T, T)
        occ = fid >= 0
        gf = np.maximum(fid, 0) + offs[gi]
        zt = np.where(occ, face_zone[gf], -1)
        sd = np.where(occ, face_side[gf], -1)
        kn = np.asarray(known[gi], bool)
        sel = np.zeros((T, T), bool)
        names = ('back', 'right', 'left', 'top')
        for z, sides in amap.items():
            for si, sn in enumerate(names):
                if sides.get(sn, {}).get('texture') == 'different':
                    sel |= (zt == int(z)) & (sd == si)
        sel &= occ & ~kn
        if sel.any():
            lowp = np.stack([_nconv(tex[..., c].astype(np.float32), occ & ~sel | (sel), 12.0) for c in range(3)], -1)
            tex[sel] = np.clip(lowp[sel] + 0.5, 0, 255).astype(np.uint8)
            rep['texels_detextured'] += int(sel.sum())
        out.append(tex)
    return out, rep
