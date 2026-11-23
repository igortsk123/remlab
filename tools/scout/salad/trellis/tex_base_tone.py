"""Этап 6, режим «основа = готовая текстура» (UltraTex и подобные; T-187/1): подгонка ТОНА основы под фото, до переноса фото поверх.

Зачем: основа (текстура, которую красит нейросеть) и фото одного товара различаются тоном (владелец TG 1516: графит у UltraTex почти чёрный против серого на фото). Фото — правда, основа должна лечь к нему.
Что делает (общее правило, без ID и ручных правок товара):
  1. Перекрытие = тексели, которые этап 6 взял с фото (`known`): там есть и фото, и основа.
  2. Группы: части по геометрии, если даны (`parts_map`) и их ≥ 2; иначе кластеры цвета основы на перекрытии (k-means в Lab, до `k_max`, малые доли сливаются). Остальные тексели (включая невидимые с фото) получают
     мягкий вес групп по расстоянию в Lab до центров кластеров (по частям — жёстко).
  3. Сдвиг Lab = медиана (фото − основа) по перекрытию группы; применяется ко ВСЕЙ текстуре группы (и к невидимому). Нет перекрытия у группы — берётся общий сдвиг.
  4. Остаток (фото − подогнанная основа) на перекрытии сглаживается и затухает от границы вглубь основы (`resid_decay` текселей): граница фото/основы не прыгает по тону.
  5. Граница мягкая: внутри взятой области вес фото растёт от 0 на границе до 1 за `feather` текселей (деталь фото ← деталь основы плавно).
Мерки (пишутся в отчёт): ΔE00 фото↔основа на перекрытии до/после; ΔE00 поперёк границы (пары соседних текселей «фото | основа») для сырой основы / только сдвиг / итог.
Числа — `rules/tex-visible.json` → `base_fit`.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
SCOUT = os.path.dirname(SALAD)
sys.path[:0] = [HERE, SALAD, SCOUT]

import recolor_lp as LP  # noqa: E402
import tex_coverage as TC  # noqa: E402


def _rules() -> dict:
    try:
        return json.load(open(os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8')).get('base_fit', {})
    except (OSError, ValueError):
        return {}


BF = _rules()
K_MAX = int(BF.get('k_max', 4))
MIN_SHARE = float(BF.get('min_share', 0.03))            # кластер меньше этой доли перекрытия сливается с ближайшим
MIN_OVERLAP = int(BF.get('min_overlap_texels', 2000))   # меньше перекрытия у группы — общий сдвиг
SOFT_SIGMA = float(BF.get('soft_sigma_dE', 7.0))        # мягкость весов кластеров, единиц Lab
RESID_SIGMA = float(BF.get('resid_sigma_tex', 6.0))     # сглаживание остатка на перекрытии, текселей
RESID_DECAY = float(BF.get('resid_decay_tex', 48.0))    # затухание остатка вглубь основы, текселей
RESID_CAP = float(BF.get('resid_cap_dE', 25.0))         # остаток по модулю не больше (Lab)
FEATHER = float(BF.get('feather_tex', 12.0))            # мягкая граница: ширина перехода внутри взятой области, текселей
SUBSAMPLE = int(BF.get('kmeans_subsample', 150000))
GUTTER = 6


def _lab(rgb8: np.ndarray) -> np.ndarray:
    return LP.lab_f(rgb8).astype(np.float32)


def _rgb8(lab: np.ndarray) -> np.ndarray:
    return LP.l2s8(LP.lab_to_lin(lab))


def _kmeans(x: np.ndarray, k: int, it: int = 12) -> np.ndarray:
    """Центры k-means (Lab), farthest-point старт; детерминировано."""
    c = [x[int(np.argmin(x[:, 0]))]]
    for _ in range(1, k):
        d = np.min([((x - cc) ** 2).sum(1) for cc in c], axis=0)
        c.append(x[int(np.argmax(d))])
    c = np.array(c, np.float64)
    for _ in range(it):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(2), axis=1)
        for j in range(len(c)):
            m = lab == j
            if m.any():
                c[j] = x[m].mean(0)
    return c


def cluster_centres(ut_lab_ov: np.ndarray) -> np.ndarray:
    """Центры кластеров цвета основы на перекрытии; малые доли сливаются с ближайшим."""
    rng = np.random.default_rng(0)
    x = ut_lab_ov if len(ut_lab_ov) <= SUBSAMPLE else ut_lab_ov[rng.choice(len(ut_lab_ov), SUBSAMPLE, replace=False)]
    x = x.astype(np.float64)
    c = _kmeans(x, min(K_MAX, max(1, len(x) // 500)))
    while len(c) > 1:
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(2), axis=1)
        sh = np.bincount(lab, minlength=len(c)) / len(x)
        j = int(np.argmin(sh))
        if sh[j] >= MIN_SHARE:
            break
        c = np.delete(c, j, axis=0)
    return c


def soft_weights(lab: np.ndarray, centres: np.ndarray, chunk: int = 1_000_000) -> np.ndarray:
    """Вес каждого центра для каждого тексела (строки в сумме 1); float32, размер N×k."""
    out = np.empty((len(lab), len(centres)), np.float32)
    for s in range(0, len(lab), chunk):
        d2 = ((lab[s:s + chunk, None, :].astype(np.float64) - centres[None]) ** 2).sum(2)
        w = np.exp(-(d2 - d2.min(1, keepdims=True)) / (2 * SOFT_SIGMA ** 2))
        out[s:s + chunk] = (w / w.sum(1, keepdims=True)).astype(np.float32)
    return out


def _pairs_de(a_lab: np.ndarray, b_lab: np.ndarray, kn: np.ndarray, occ: np.ndarray) -> dict:
    """ΔE00 поперёк границы: соседние (по 4) тексели «i взят с фото, j не взят», оба занятые; сравниваются a[i] и b[j]."""
    res = []
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        sy = slice(max(dy, 0), kn.shape[0] + min(dy, 0)), slice(max(dx, 0), kn.shape[1] + min(dx, 0))
        sj = slice(max(-dy, 0), kn.shape[0] + min(-dy, 0)), slice(max(-dx, 0), kn.shape[1] + min(-dx, 0))
        m = kn[sj] & ~kn[sy] & occ[sj] & occ[sy]
        if m.any():
            res.append(LP.de2000(a_lab[sj][m], b_lab[sy][m]))
    if not res:
        return {'n': 0}
    d = np.concatenate(res)
    return {'n': int(len(d)), 'med': round(float(np.median(d)), 2), 'p90': round(float(np.percentile(d, 90)), 2)}


def fit(geoms: list, tr: dict, parts: list | None = None) -> tuple:
    """geoms[gi]['tex'] — основа; tr['tex'][gi] — основа с фото поверх `known` (результат `transfer`). → (tr с новыми текстурами, отчёт). Маски `known` не меняются."""
    new_tex, rep_all = [], []
    for gi, g in enumerate(geoms):
        T = int(g['tex'].shape[0])
        base = np.asarray(g['tex'], np.uint8)
        full = np.asarray(tr['tex'][gi], np.uint8)
        kn = np.asarray(tr['known'][gi], bool)
        xy = np.stack([g['UV'][:, 0] * T, (1.0 - g['UV'][:, 1]) * T], 1)
        fid, _ = TC.raster(xy, g['F'], T)
        fid = fid.reshape(T, T)
        occ = fid >= 0
        ov = kn & occ
        rep = {'T': T, 'overlap_texels': int(ov.sum()), 'occupied_texels': int(occ.sum())}
        if ov.sum() < MIN_OVERLAP:
            rep['skipped'] = 'перекрытия мало — подгонка не делалась'
            new_tex.append(full)
            rep_all.append(rep)
            continue
        ut = _lab(base)
        ph = _lab(full)
        de0 = LP.de2000(ph[ov], ut[ov])
        rep['overlap_dE_before'] = {'med': round(float(np.median(de0)), 2), 'p90': round(float(np.percentile(de0, 90)), 2)}
        pm = None
        if parts is not None and parts[gi] is not None:
            pm = np.where(occ, np.asarray(parts[gi])[np.maximum(fid, 0)], -1)           # часть по тексельной карте граней
        adj = ut.copy()
        use_parts = pm is not None and len(np.unique(pm[occ])) >= 2
        if use_parts:
            glob = np.median(ph[ov] - ut[ov], 0)
            deltas = {}
            for p in np.unique(pm[occ]):
                mp = occ & (pm == p)
                mo = mp & ov
                d = np.median(ph[mo] - ut[mo], 0) if mo.sum() >= MIN_OVERLAP else glob
                deltas[int(p)] = d
                adj[mp] = ut[mp] + d.astype(np.float32)
            rep['groups'] = {'kind': 'части', 'deltas_Lab': {k: [round(float(x), 2) for x in v] for k, v in deltas.items()}}
        else:
            cen = cluster_centres(ut[ov])
            w_ov = soft_weights(ut[ov], cen)
            glob = np.median(ph[ov] - ut[ov], 0)
            d_k, share = [], []
            hard = np.argmax(w_ov, 1)
            for j in range(len(cen)):
                m = hard == j
                share.append(round(float(m.mean()), 3))
                d_k.append(np.median((ph[ov] - ut[ov])[m], 0) if m.sum() >= MIN_OVERLAP else glob)
            d_k = np.array(d_k, np.float32)
            idx = np.flatnonzero(occ.ravel())
            utf = ut.reshape(-1, 3)
            adjf = adj.reshape(-1, 3)
            for s in range(0, len(idx), 1_000_000):
                ii = idx[s:s + 1_000_000]
                w = soft_weights(utf[ii], cen)
                adjf[ii] = utf[ii] + w @ d_k
            adj = adjf.reshape(T, T, 3)
            rep['groups'] = {'kind': 'кластеры цвета основы', 'k': int(len(cen)), 'share_overlap': share, 'centres_Lab': np.round(cen, 1).tolist(), 'deltas_Lab': np.round(d_k, 2).tolist()}
        de1 = LP.de2000(ph[ov], adj[ov])
        rep['overlap_dE_after_shift'] = {'med': round(float(np.median(de1)), 2), 'p90': round(float(np.percentile(de1, 90)), 2)}
        # остаток → вглубь основы с затуханием
        r = np.clip(ph - adj, -RESID_CAP, RESID_CAP) * ov[..., None]
        den = gaussian_filter(ov.astype(np.float32), RESID_SIGMA)
        num = np.stack([gaussian_filter(r[..., c].astype(np.float32), RESID_SIGMA) for c in range(3)], -1)
        r_s = np.where((den > 1e-3)[..., None], num / np.maximum(den, 1e-3)[..., None], 0.0).astype(np.float32)
        dist, (iy, ix) = distance_transform_edt(~ov, return_distances=True, return_indices=True)
        decay = np.exp(-dist / RESID_DECAY).astype(np.float32)
        r_ext = r_s[iy, ix] * decay[..., None]
        base2 = adj + r_ext                                   # основа у границы ≈ фото по тону, вдали — как после сдвига
        # мягкая граница внутри взятой области
        dk = distance_transform_edt(ov).astype(np.float32)
        wph = np.clip(dk / max(FEATHER, 1e-6), 0.0, 1.0)[..., None]
        fin = np.where(ov[..., None], wph * ph + (1 - wph) * base2, base2)
        rep['boundary_dE'] = {'сырая_основа|фото': _pairs_de(ph, ut, kn, occ), 'сдвиг_без_остатка': _pairs_de(ph, adj, kn, occ), 'итог': _pairs_de(fin, fin, kn, occ)}
        # итог: не занятые тексели — желоб от занятых
        out = np.where(occ[..., None], _rgb8(fin.astype(np.float32)), full)
        gd, (gy, gx) = distance_transform_edt(~occ, return_distances=True, return_indices=True)
        ring = (~occ) & (gd <= GUTTER)
        out[ring] = out[gy[ring], gx[ring]]
        new_tex.append(out.astype(np.uint8))
        rep_all.append(rep)
    tr2 = dict(tr)
    tr2['tex'] = new_tex
    return tr2, rep_all
