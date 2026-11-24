#!/usr/bin/env python3
"""«Фронт сплошной» (front_continuity, T-20261124-18; владелец TG 2571: «на фронте никогда не должно быть разрывов — узор по всему фронту, цвет — по всему, текстура — тоже»).
Вид «перед» (камера фото) корпусного товара: внутри маски предмета нет (1) полос — соседние полосы фронта (вертикальные и горизонтальные) подряд ≥ N штук с тоном чужим остальному фронту; (2) пятен — доля пикселей заметно темнее/светлее своего окружения (окно σ) у вида не превышает долю у фото больше чем на spot_excess_pct.
Все числа — data/flat3d/front-continuity.json (пороги подобраны по контролям, источник — в самом файле), в коде чисел нет.
Не меняет вердикты sides_eval: отдельный признак; подключается в отчёт автооценки отдельным шагом после калибровки.
API: front_continuity(view_rgb, view_mask, photo_rgb, photo_mask, rules=None) → {'ok': bool|None, 'r': float|None, 'strip': {...}, 'spot': {...}, 'why': str}."""
from __future__ import annotations
import json, os
import numpy as np
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', '..', 'data', 'flat3d')


def load_rules(rules: dict | None = None) -> dict:
    if rules is not None:
        return rules
    with open(os.path.join(DATA, 'front-continuity.json'), encoding='utf-8') as f:
        return json.load(f)


def _lab(rgb: np.ndarray) -> np.ndarray:
    from sides_eval import rgb_to_lab                                          # тот же Lab, что у остальных признаков
    return rgb_to_lab(np.asarray(rgb)[..., :3])


def _bbox(m: np.ndarray):
    ys, xs = np.nonzero(m)
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def _runs(flag: np.ndarray) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(flag)
    while i < n:
        if flag[i]:
            j = i
            while j < n and flag[j]:
                j += 1
            out.append((i, j - i)); i = j
        else:
            i += 1
    return out


def front_region(view_m: np.ndarray, P: dict) -> np.ndarray:
    """Фронт = маска предмета без кромки edge_pct % (край: сглаживание, контур) и без верха/низа tb_pct % по высоте."""
    y0, y1, x0, x1 = _bbox(view_m)
    h, w = y1 - y0, x1 - x0
    ed = ndi.binary_erosion(view_m, iterations=max(2, int(min(h, w) * P['edge_pct'] / 100)))
    ty = int(h * P['tb_pct'] / 100)
    ed[:y0 + ty] = False; ed[y1 - ty:] = False
    return ed


def strips(lab: np.ndarray, reg: np.ndarray, P: dict, lab_p: np.ndarray | None = None) -> dict:
    """Полосы по вертикали (axis=1) и горизонтали (axis=0): медиана Lab полосы против медианы фронта; чужая полоса — ΔE76 > strip_dE; разрыв — подряд ≥ strip_min_bands полос. Мера — ширина самого широкого разрыва, % размера фронта по оси."""
    y0, y1, x0, x1 = _bbox(reg)
    K = int(P['bands'])
    res, worst = {}, 0.0
    for axis, nm in ((1, 'вертикаль'), (0, 'горизонталь')):
        lo, hi = (x0, x1) if axis == 1 else (y0, y1)
        edges = np.linspace(lo, hi, K + 1).astype(int)
        prof = np.full((K, 3), np.nan)
        for j in range(K):
            sl = (slice(None), slice(edges[j], edges[j + 1])) if axis == 1 else (slice(edges[j], edges[j + 1]), slice(None))
            mm = reg[sl]
            if int(mm.sum()) >= int(P['min_px_band']):
                prof[j] = np.median(lab[sl][mm], axis=0)
        ok = ~np.isnan(prof[:, 0])
        if ok.sum() < 8:
            res[nm] = {'why': 'мало полос'}; continue
        ref = np.nanmedian(prof[ok], axis=0)
        dE = np.where(ok, np.sqrt(((np.nan_to_num(prof) - ref) ** 2).sum(axis=1)), 0.0)
        if lab_p is not None:                                                    # настоящие швы/двери другой отделки есть и на фото: чужой считается только избыток над фото
            pp = np.full((K, 3), np.nan)
            for j in range(K):
                sl = (slice(None), slice(edges[j], edges[j + 1])) if axis == 1 else (slice(edges[j], edges[j + 1]), slice(None))
                mm = reg[sl]
                if int(mm.sum()) >= int(P['min_px_band']):
                    pp[j] = np.median(lab_p[sl][mm], axis=0)
            okp = ok & ~np.isnan(pp[:, 0])
            if okp.sum() >= 8:
                refp = np.nanmedian(pp[okp], axis=0)
                dEp = np.where(okp, np.sqrt(((np.nan_to_num(pp) - refp) ** 2).sum(axis=1)), 0.0)
                dE = dE - dEp
        runs = [r for r in _runs(ok & (dE > P['strip_dE'])) if r[1] >= int(P['strip_min_bands'])]
        wmax = max([l for _, l in runs], default=0) * 100.0 / K
        res[nm] = {'dE_max': round(float(dE.max()), 1), 'runs': runs, 'run_pct': round(wmax, 1)}
        worst = max(worst, wmax)
    res['run_pct'] = round(worst, 1)
    return res


def spots(Lv: np.ndarray, Lp: np.ndarray | None, reg: np.ndarray, P: dict) -> dict:
    """Пятна: доля пикселей фронта темнее своего окружения (гауссово окно spot_sigma px) более чем на spot_dL; у вида против фото (если фото того же ракурса есть). Мера — превышение доли вида над долей фото, п.п."""
    def share(L):
        w = ndi.gaussian_filter(reg.astype(float), P['spot_sigma'])
        bg = ndi.gaussian_filter(np.where(reg, L, 0.0), P['spot_sigma']) / np.maximum(w, 1e-6)
        return float((((L - bg) < -P['spot_dL']) & reg).sum()) / max(int(reg.sum()), 1) * 100.0
    sv = share(Lv)
    sp = share(Lp) if Lp is not None else None
    ex = sv - (sp if sp is not None else float(P['spot_base_pct']))
    return {'view_pct': round(sv, 1), 'photo_pct': None if sp is None else round(sp, 1), 'excess_pct': round(ex, 1)}


def align_photo(view_rgb, view_m, photo_rgb, photo_m):
    """Фото приводится к bbox предмета вида (одна камера — форма та же; для полос и долей пятен грубой подгонки достаточно)."""
    from PIL import Image
    vy0, vy1, vx0, vx1 = _bbox(view_m); py0, py1, px0, px1 = _bbox(photo_m)
    h, w = vy1 - vy0, vx1 - vx0
    pc = np.asarray(Image.fromarray(np.asarray(photo_rgb)[py0:py1, px0:px1, :3]).resize((w, h), Image.LANCZOS))
    pm = np.asarray(Image.fromarray((photo_m[py0:py1, px0:px1] * 255).astype(np.uint8)).resize((w, h), Image.NEAREST)) > 127
    full = np.zeros(view_m.shape + (3,), np.uint8); fm = np.zeros(view_m.shape, bool)
    full[vy0:vy1, vx0:vx1] = pc; fm[vy0:vy1, vx0:vx1] = pm
    return full, fm


def front_continuity(view_rgb, view_mask, photo_rgb=None, photo_mask=None, rules: dict | None = None) -> dict:
    P = load_rules(rules)
    if int(view_mask.sum()) < int(P['min_px']):
        return {'ok': None, 'r': None, 'why': 'маска вида мала — не измерено'}
    reg = front_region(view_mask, P)
    if int(reg.sum()) < int(P['min_px']):
        return {'ok': None, 'r': None, 'why': 'фронт мал — не измерено'}
    lab = _lab(view_rgb)
    Lp = None; lab_p = None
    if photo_rgb is not None and photo_mask is not None and int(photo_mask.sum()) >= int(P['min_px']):
        pr, pm = align_photo(view_rgb, view_mask, photo_rgb, photo_mask)
        lab_p = _lab(pr); Lp = lab_p[..., 0]
        reg_p = reg & pm
        if int(reg_p.sum()) >= int(P['min_px']):
            reg = reg_p
    st = strips(lab, reg, P, lab_p)
    sp = spots(lab[..., 0], Lp, reg, P)
    r_strip = st['run_pct'] / float(P['strip_run_pct_max'])
    r_spot = max(sp['excess_pct'], 0.0) / float(P['spot_excess_pct'])
    r = max(r_strip, r_spot)
    why = 'ok' if r <= 1 else ('полоса чужого тона' if r_strip >= r_spot else 'пятна темнее окружения')
    return {'ok': bool(r <= 1.0), 'r': round(float(r), 3), 'strip': st, 'spot': sp, 'why': why}
