#!/usr/bin/env python3
"""Синтез фактуры невидимого из чистого куска фото своей группы материала (T-20261123-39; признак владельца «рисунок перенесён», план paint-cycles-1123 строка 2).

Было: зерно невидимого — случайное гауссово поле с амплитудой, измеренной по фото (`surface_passport.apply_groups`) — рисунка нет, только «шум той же силы».
Стало: квилтинг (Efros–Freeman) кусков остатка фото: остаток = Lab − низкие частоты группы (полоса `low_px`), доноры — ЧИСТЫЕ известные тексели этой группы
(фото, без кромки известного, без выбросов-деталей), патч донора поворачивается и масштабируется так, чтобы направление «вверх» мира и физический масштаб на цели и на доноре
совпали (волокна/рисунок идут туда же и того же размера), швы между кусками — по минимальной ошибке на перекрытии. Чистого донора мало → честно гладко (остаток 0).

Чистые функции numpy/scipy, без поверхностного паспорта: подключает `surface_passport.apply_groups` (правила `rules/paint-fill.json` → `surface_groups.synth`).
"""
from __future__ import annotations

import numpy as np


def robust_sigma(x) -> float:
    x = np.asarray(x, np.float64).reshape(-1)
    if not len(x):
        return 0.0
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


# ------------------------------------------------------------------------------------------------ ориентация и масштаб
def uv_field_maps(V, F, UV, ids: np.ndarray, T: int, up_min: float = 0.5) -> dict:
    """По граням: угол направления «вверх мира (Y)» в пикселях атласа (nan — грань горизонтальная, направления нет) и плотность (пикселей атласа на единицу длины мира).
    → {'angle': (T,T) float с nan, 'dens': (T,T) float (0 вне развёртки)}. ids — грань тексела (−1 вне развёртки)."""
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    UV = np.asarray(UV, np.float64)
    p = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    e1, e2 = V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]
    d1, d2 = p[F[:, 1]] - p[F[:, 0]], p[F[:, 2]] - p[F[:, 0]]
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    a3 = np.linalg.norm(np.cross(e1, e2), axis=1)
    ok = (np.abs(det) > 1e-12) & (a3 > 1e-18)
    inv = np.zeros((len(F), 2, 2))
    inv[ok, 0, 0], inv[ok, 0, 1] = d2[ok, 1] / det[ok], -d2[ok, 0] / det[ok]
    inv[ok, 1, 0], inv[ok, 1, 1] = -d1[ok, 1] / det[ok], d1[ok, 0] / det[ok]
    # J (3×2): px → мир; градиент Y по пикселям = Y-строка J: gy = e1_y·inv[0,:] + e2_y·inv[1,:]
    gy = e1[:, 1:2] * inv[:, 0, :] + e2[:, 1:2] * inv[:, 1, :]
    dens = np.where(ok, np.sqrt(np.abs(det) / np.maximum(a3, 1e-18)), 0.0)
    frac = np.linalg.norm(gy, axis=1) * dens                       # доля «вертикали» в плоскости грани: вертикальная грань ≈ 1, горизонтальная ≈ 0
    ang = np.where(ok & (frac >= up_min), np.arctan2(gy[:, 1], gy[:, 0]), np.nan)
    occ = ids >= 0
    angle = np.full((T, T), np.nan)
    dm = np.zeros((T, T))
    angle[occ] = ang[ids[occ]]
    dm[occ] = dens[ids[occ]]
    return {'angle': angle, 'dens': dm}


# ------------------------------------------------------------------------------------------------ кусок донора
def _warp(donor: np.ndarray, valid: np.ndarray, cy: float, cx: float, P: int, delta: float, k: float):
    """Кусок P×P из донора с центром (cy, cx), повёрнут на delta и масштабирован в k раз (k = плотность цели / плотность донора): (P,P,C), доля валидных (P,P)."""
    from scipy.ndimage import map_coordinates
    o = (np.arange(P) - (P - 1) / 2.0)
    oy, ox = np.meshgrid(o, o, indexing='ij')
    c, s = np.cos(delta), np.sin(delta)
    ix = (c * ox + s * oy) / k                                     # поворот на −delta обратным отображением (выход → вход)
    iy = (-s * ox + c * oy) / k
    yy, xx = cy + iy, cx + ix
    H, W = valid.shape
    if yy.min() < 0 or xx.min() < 0 or yy.max() > H - 1 or xx.max() > W - 1:
        return None, None
    ch = [map_coordinates(donor[..., i], [yy, xx], order=1, mode='nearest') for i in range(donor.shape[-1])]
    vv = map_coordinates(valid.astype(np.float32), [yy, xx], order=1, mode='nearest')
    return np.stack(ch, -1), vv


def _seam_cut(err: np.ndarray) -> np.ndarray:
    """Путь минимальной ошибки сверху вниз по полосе err (h,w) → колонка разреза на каждой строке (классический DP Efros–Freeman)."""
    h, w = err.shape
    cost = err.astype(np.float64).copy()
    for y in range(1, h):
        prev = cost[y - 1]
        left = np.concatenate([[np.inf], prev[:-1]])
        right = np.concatenate([prev[1:], [np.inf]])
        cost[y] += np.minimum(prev, np.minimum(left, right))
    cut = np.zeros(h, np.int64)
    cut[-1] = int(np.argmin(cost[-1]))
    for y in range(h - 2, -1, -1):
        x = cut[y + 1]
        lo, hi = max(x - 1, 0), min(x + 2, w)
        cut[y] = lo + int(np.argmin(cost[y, lo:hi]))
    return cut


def quilt(donor: np.ndarray, donor_valid: np.ndarray, target: np.ndarray, orient_t: np.ndarray | None, orient_d: np.ndarray | None,
          dens_t: np.ndarray | None, dens_d: np.ndarray | None, P: int, ov: int, n_cand: int = 24, tol: float = 0.1, seed: int = 0,
          scale_clip: tuple = (0.5, 2.0)) -> tuple:
    """Квилтинг остатка по маске `target` (T,T) из `donor` (T,T,C) в местах `donor_valid`. Патч донора выбирается среди n_cand случайных по минимуму ошибки на уже готовом перекрытии (в пределах tol от минимума),
    шов — по минимуму ошибки (левая/верхняя полоса перекрытия). → (res (T,T,C) нулевой вне target, done (T,T) bool — где синтезировано)."""
    T = target.shape[0]
    C = donor.shape[-1]
    rng = np.random.RandomState(seed)
    dy, dx = np.nonzero(donor_valid)
    out = np.zeros((T, T, C), np.float32)
    done = np.zeros((T, T), bool)
    if len(dy) < P * P // 2:
        return out, done
    step = max(P - ov, 1)
    ys, xs = np.nonzero(target)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    for ty in range(y0 - (y0 % step), y1 + 1, step):
        for tx in range(x0 - (x0 % step), x1 + 1, step):
            ya, xa = ty, tx
            yb, xb = min(ya + P, T), min(xa + P, T)
            if ya < 0 or xa < 0:
                continue
            tm = target[ya:yb, xa:xb]
            if not tm.any():
                continue
            ph, pw = yb - ya, xb - xa
            tgt_c = (ya + P // 2, xa + P // 2)
            cy_t, cx_t = min(tgt_c[0], T - 1), min(tgt_c[1], T - 1)
            at = None
            kt = None
            if orient_t is not None:                                # направление и плотность цели — по её текселям в куске (медиана), не по одному центру
                a_blk = orient_t[ya:yb, xa:xb][tm]
                a_blk = a_blk[~np.isnan(a_blk)]
                if len(a_blk):
                    at = float(np.arctan2(np.median(np.sin(a_blk)), np.median(np.cos(a_blk))))
                d_blk = dens_t[ya:yb, xa:xb][tm] if dens_t is not None else np.array([])
                d_blk = d_blk[d_blk > 0]
                kt = float(np.median(d_blk)) if len(d_blk) else None
            dn = done[ya:yb, xa:xb]
            best = []
            tries = 0
            while len(best) < n_cand and tries < 3 * n_cand:
                tries += 1
                j = int(rng.randint(len(dy)))
                cy, cx = float(dy[j]), float(dx[j])
                delta, k = 0.0, 1.0
                if at is not None and orient_d is not None:
                    ad = orient_d[int(cy), int(cx)]
                    if not np.isnan(ad):
                        delta = at - float(ad)
                if kt is not None and dens_d is not None and dens_d[int(cy), int(cx)] > 0:
                    k = float(np.clip(kt / float(dens_d[int(cy), int(cx)]), scale_clip[0], scale_clip[1]))
                patch, vv = _warp(donor, donor_valid, cy, cx, P, delta, k)
                if patch is None or vv.min() < 0.999:
                    continue
                pc = patch[:ph, :pw]
                e = float(((pc[dn] - out[ya:yb, xa:xb][dn]) ** 2).mean()) if dn.any() else 0.0
                best.append((e, pc))
            if not best:
                continue
            emin = min(b[0] for b in best)
            ok_c = [b for b in best if b[0] <= emin * (1.0 + tol) + 1e-9]
            pc = ok_c[int(rng.randint(len(ok_c)))][1]
            take = ~dn                                                # нетронутое берём целиком
            if dn.any():
                o = min(ov, pw, ph)
                ev = ((pc - out[ya:yb, xa:xb]) ** 2).sum(-1)
                keep = np.zeros((ph, pw), bool)
                if dn[:, :o].mean() > 0.8 and pw > o:                # левая полоса перекрытия: вертикальный разрез
                    cut = _seam_cut(ev[:, :o])
                    keep[:, :o] |= np.arange(o)[None, :] >= cut[:, None]
                if dn[:o, :].mean() > 0.8 and ph > o:                # верхняя полоса: горизонтальный разрез
                    cutt = _seam_cut(ev[:o, :].T)
                    kk = np.arange(o)[:, None] >= cutt[None, :]
                    keep[:o, :] = kk if not keep[:o, :o].any() else keep[:o, :] & kk
                take = take | (dn & keep)
            sel = take & tm
            out[ya:yb, xa:xb][sel] = pc[sel]
            done[ya:yb, xa:xb] |= sel
    return out, done & target


def donor_residual(lab: np.ndarray, known: np.ndarray, low_px: float, erode_px: int, clip_k: float, chroma_max: float, keep_detail: bool, blur_fn) -> tuple:
    """Остаток фото группы и маска ЧИСТОГО донора: остаток = Lab − маско-нормированный размыв (σ=low_px) по известным текселям группы; чистый = известное без кромки (erode_px),
    без выбросов (|ΔL| > clip_k·σ — контур ручки/двери; у узора — keep_detail — выбросы по L остаются, режутся только по цветности)."""
    from scipy.ndimage import binary_erosion
    low = blur_fn(lab, known, low_px)
    res = (lab - low).astype(np.float32)
    core = binary_erosion(known, iterations=max(int(erode_px), 0)) if erode_px > 0 else known.copy()
    sig = robust_sigma(res[core][:, 0]) if core.any() else 0.0
    clean = core.copy()
    if core.any():
        if not keep_detail:
            clean &= np.abs(res[..., 0]) <= clip_k * max(sig, 1e-6)
        clean &= np.hypot(res[..., 1], res[..., 2]) <= chroma_max
    return res, clean, sig


def synth_group(lab: np.ndarray, known: np.ndarray, target: np.ndarray, maps: dict | None, cfg: dict, blur_fn, keep_detail: bool = False, seed: int = 0) -> tuple:
    """Остаток фактуры для невидимого текселя группы: → (res (T,T,3) в Lab (ΔL,Δa,Δb), info). Донора мало (< cfg.min_donor_px чистых текселей) — res = 0 (честно гладко), info.mode = 'smooth'.
    cfg: low_px, patch_px, overlap_px, min_donor_px, donor_erode_px, clip_k, chroma_max, n_cand, tol, up_min, seed_step. maps — результат `uv_field_maps` (angle, dens) или None."""
    T = lab.shape[0]
    res_d, clean, sig_d = donor_residual(lab, known, float(cfg['low_px']), int(cfg['donor_erode_px']), float(cfg['clip_k']), float(cfg['chroma_max']), keep_detail, blur_fn)
    n_clean = int(clean.sum())
    info = {'donor_px': n_clean, 'target_px': int(target.sum()), 'sigma_donor_L': round(sig_d, 3), 'patch_px': int(cfg['patch_px'])}
    P, ov = int(cfg['patch_px']), int(cfg['overlap_px'])
    if n_clean < int(cfg['min_donor_px']) or not target.any():
        info['mode'] = 'smooth'
        info['why'] = f"чистых текселей донора {n_clean} < {int(cfg['min_donor_px'])}" if target.any() else 'нет невидимого'
        return np.zeros((T, T, 3), np.float32), info
    mm = maps or {}
    out, done = quilt(res_d, clean, target, mm.get('angle'), mm.get('angle'), mm.get('dens'), mm.get('dens'), P, ov, int(cfg['n_cand']), float(cfg['tol']), seed)
    cov = float(done.sum()) / max(int(target.sum()), 1)
    sig_s = robust_sigma(out[done][:, 0]) if done.any() else 0.0
    info.update({'mode': 'quilt', 'covered': round(cov, 4), 'sigma_synth_L': round(sig_s, 3), 'energy_ratio': round(sig_s / max(sig_d, 1e-6), 3)})
    if cov < float(cfg['min_cover']):                                 # кусочки не накрыли цель — недокрытое остаётся гладким (0), это видно в info
        info['why'] = f"накрыто {cov:.0%} < {float(cfg['min_cover']):.0%}: остальное гладко"
    return out, info
