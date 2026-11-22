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
    dih = np.degrees(np.arccos(np.clip((n[i] * n[j]).sum(1), -1, 1)))
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
    fside = face_sides(form_geo['V'], form_geo['F'], basis)
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


def face_sides(V, F, basis) -> np.ndarray:
    """Сторона грани по нормали при камере фото: -1 лицо (в сторону камеры), 0 зад, 1 правый, 2 левый, 3 верх (крышка), 4 низ, -2 косая. basis = (right, up, fwd) мира; fwd — от камеры к предмету."""
    right, up, fwd = (np.asarray(b, np.float64) for b in basis)
    _a, _c, n = _face_area_cen_normal(V, F)
    d = {'front': -(n @ fwd), 'back': n @ fwd, 'right': n @ right, 'left': -(n @ right), 'top': n @ up, 'bottom': -(n @ up)}
    names = ['front', 'back', 'right', 'left', 'top', 'bottom']
    m = np.stack([d[k] for k in names], 1)
    best = m.argmax(1)
    code = np.array([-1, 0, 1, 2, 3, 4])[best]
    code[m.max(1) < PANEL_SIDE_COS] = -2
    return code.astype(np.int32)


def mirror_score(V, F, right, eps_frac: float, n_samples: int = 60000) -> tuple:
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
        ok = (d <= eps_frac * diag) & ((refl_n(n[faces]) * n[jf]).sum(1) >= 0.7)
        return jf, ok

    d, k = tree.query(refl_pt(pts), k=1)
    okp = (d <= eps_frac * diag) & ((refl_n(n[fi]) * n[fi[k]]).sum(1) >= 0.7)
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
    pid = panel_ids(V, F, parts)
    out, info = propagate_zones(V, F, fz, pid, return_info=True)         # шаг 1: границы продолжения = панели
    ar, cen, nrm = _face_area_cen_normal(V, F)
    sd = face_sides(V, F, basis)
    right = np.asarray(basis[0], np.float64)
    info['steps'] = {'photo_panels': int((out >= 0).sum()), 'mirror': 0, 'back': 0}
    info['sym_score'] = None
    labelled = out >= 0
    # шаг 2: невидимый бок по симметрии
    sc, twin = mirror_score(V, F, right, SYM_EPS)
    info['sym_score'] = round(sc, 3)
    if sc >= SYM_MIN:
        for p in np.unique(pid):
            m = pid == p
            if labelled[m].any() or not np.isin(sd[m], (1, 2)).all():
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
    back = [p for p in np.unique(pid) if not (out[pid == p] >= 0).any() and (sd[pid == p] == 0).all()]
    if back:
        zr, pr = _dominant(np.where(sd == 1, out, -1), ar, PANEL_PURITY)
        zl, pl = _dominant(np.where(sd == 2, out, -1), ar, PANEL_PURITY)
        if zr is not None and zr == zl and pr >= PANEL_PURITY and pl >= PANEL_PURITY:
            for p in back:
                m = pid == p
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
    F = dict({'sigma': 12.0, 'clip': 35.0, 'risk_ratio': 2.0, 'photo_floor': 0.8, 'min_visible': 500}, **R.get('full', {}))
    out, rep = [], {'parts': {}, 'risky_parts': [], 'texels_changed': 0}
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
