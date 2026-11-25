#!/usr/bin/env python3
"""Автооценка «со всех сторон» (T-20261123-37): 5 признаков владельца по каждой стороне листа `sides_sheet.py`.
Признаки (правила и пороги — `data/flat3d/sides-eval.json`, в коде чисел нет): заплатки · чёткость лица · однотонно где однотонно · рисунок перенесён · недокрасы/переходы.
Шестой признак `back_tone` (тон тыла ≈ тон лица, T-34/4) — в режиме наблюдения (`enforce=false` в правилах): r пишется в eval.json, на ok и оценку не влияет, пока не откалиброван.
Каждая мерка → r («как плохо / допуск»); r ≤ 1 — прошла, оценка 0–1 = clip(1 − r/2). Сторона сравнивается с фото той же вещи: что есть на фото (рисунок дерева, градиент), браком не считается.
Вход — лист PNG: клетки по `size` px (фото + виды по порядку `views` правил `sides-sheet.json`), заголовок `header_px`. Только numpy/scipy/PIL: секунды на товар, ядра, не Salad.

  sides_eval.py batch --sheets ПАПКА_С_ЛИСТАМИ --out ПАПКА [--only id,id]
Выход: ПАПКА/eval.json {id: {views: {имя: {признак: {r, score, ok|None, …}}}, score, ok, worst}} и ПАПКА/summary.json (общий % прошли все 5 на всех сторонах).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scout'))   # общий свидетель «перёда»
import front_axis as FA  # noqa: E402
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', '..', 'data', 'flat3d')
FEATURES = ('patches', 'sharpness', 'uniform', 'pattern', 'underpaint', 'back_tone')


def load_rules(rules: dict | None = None) -> dict:
    if rules is not None:
        return rules
    with open(os.path.join(DATA, 'sides-eval.json'), encoding='utf-8') as f:
        return json.load(f)


def load_sheet_rules() -> dict:
    with open(os.path.join(DATA, 'sides-sheet.json'), encoding='utf-8') as f:
        return json.load(f)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


# ---------- тон без формы: render ÷ «глина» ----------

def srgb_lin(rgb: np.ndarray) -> np.ndarray:
    c = np.asarray(rgb, dtype=np.float64)[..., :3] / 255.0
    return np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)


def lin_srgb(lin: np.ndarray) -> np.ndarray:
    c = np.clip(lin, 0.0, 1.0)
    return (np.where(c > 0.0031308, 1.055 * np.power(c, 1 / 2.4) - 0.055, 12.92 * c) * 255.0).round().astype(np.uint8)


def albedo_of(view_rgb: np.ndarray, clay_rgb: np.ndarray, shade_min: float) -> np.ndarray:
    """Тон без формы: цвет вида ÷ яркость той же формы из белой глины (линейный свет). Где глина темнее shade_min (глубокая тень) — делим на shade_min, чтобы шум не рос."""
    shade = np.maximum(srgb_lin(clay_rgb).mean(axis=2), shade_min)
    return srgb_lin(view_rgb) / shade[..., None]


def lum(lin: np.ndarray, mask: np.ndarray) -> float:
    return float(np.median((lin @ np.array([0.2126, 0.7152, 0.0722]))[mask])) if mask.any() else 0.0


# ---------- маски и вспомогательное ----------

def view_mask(rgb: np.ndarray, g: dict) -> np.ndarray:
    """Предмет на белом фоне вида: всё, что не белое; дыры залиты; край съеден на erode_px (там сглаживание и контур)."""
    m = (np.asarray(rgb)[..., :3].min(axis=2) < g['bg_white_below'])
    m = ndi.binary_fill_holes(m)
    return ndi.binary_erosion(m, iterations=int(g['erode_px']))


def photo_cell(cell: np.ndarray, g: dict) -> tuple[np.ndarray, np.ndarray]:
    """Фото в клетке: прямоугольник не-белого; фон фото — медиана рамки прямоугольника; маска = цвет дальше photo_bg_dE (ΔE76) от фона; вне прямоугольника маска пуста."""
    rgb = np.asarray(cell)[..., :3]
    rect = rgb.min(axis=2) < g['photo_rect_below']
    if not rect.any():
        return rgb, np.zeros(rect.shape, bool)
    ys, xs = np.where(rect)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    lab = rgb_to_lab(rgb)
    ring = np.zeros(rect.shape, bool)
    ring[y0:y1, x0:x1] = True
    ring[y0 + 3:y1 - 3, x0 + 3:x1 - 3] = False
    bg = np.median(lab[ring], axis=0)
    far = np.sqrt(((lab - bg) ** 2).sum(axis=2)) > g['photo_bg_dE']
    box = np.zeros(rect.shape, bool)
    box[y0:y1, x0:x1] = True
    m = ndi.binary_fill_holes(ndi.binary_opening(far & box, iterations=1))
    return rgb, ndi.binary_erosion(m, iterations=int(g['erode_px']))


def nblur(img: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Размытие только по предмету (нормированная свёртка): фон не подмешивается к краю."""
    w = ndi.gaussian_filter(mask.astype(np.float64), sigma)
    if img.ndim == 3:
        out = np.stack([ndi.gaussian_filter(img[..., k] * mask, sigma) for k in range(img.shape[2])], axis=-1)
        return out / np.maximum(w, 1e-6)[..., None]
    return ndi.gaussian_filter(img * mask, sigma) / np.maximum(w, 1e-6)


def rescale_to_area(rgb: np.ndarray, mask: np.ndarray, area: float, up_max: float | None = None, memo: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Фото подгоняется по площади предмета к стороне, чтобы сравнивать резкость/рисунок в одном масштабе.
    up_max (правила geometry.photo_upscale_max; нет — без потолка) — предел линейного увеличения: тонкая вещь (стол на ножках: маска фото ≈200 px) иначе раздувалась в 7000×7000 px (минуты на товар).
    memo — одинаковый размер у разных видов не пересчитывается (resize зависит только от размера)."""
    from PIL import Image
    a0 = float(mask.sum())
    if a0 < 1 or area < 1:
        return rgb, mask
    s = float(np.sqrt(area / a0))
    if up_max and s > up_max:
        s = float(up_max)
    if abs(s - 1) < 0.05:
        return rgb, mask
    h, w = mask.shape
    sz = (max(8, int(round(w * s))), max(8, int(round(h * s))))
    if memo is not None and ('rs', sz) in memo:
        return memo[('rs', sz)]
    im = np.asarray(Image.fromarray(rgb).resize(sz, Image.LANCZOS))
    mk = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(sz, Image.NEAREST)) > 127
    if memo is not None:
        memo[('rs', sz)] = (im, mk)
    return im, mk


# ---------- группы материала: палитра фото ----------

def wspace(lab: np.ndarray, wl: float) -> np.ndarray:
    return lab * np.array([wl, 1.0, 1.0])


def palette(lab: np.ndarray, mask: np.ndarray, P: dict, wl: float) -> np.ndarray:  # noqa: E501
    """Основные тона фото (k-средние без случайности: старт — самая далёкая точка от уже взятых). Группа = тон, занимающий ≥ min_share площади."""
    pts = wspace(nblur(lab, mask, P['sigma']), wl)[mask]
    if len(pts) == 0:
        return np.zeros((0, 3))
    pts = pts[:: max(1, len(pts) // int(P['sample']))]
    cs = [np.median(pts, axis=0)]
    for _ in range(int(P['k']) - 1):
        d = np.min([np.linalg.norm(pts - c, axis=1) for c in cs], axis=0)
        cs.append(pts[int(d.argmax())])
    cs = np.array(cs)
    for _ in range(12):
        lab_i = np.argmin(np.linalg.norm(pts[:, None] - cs[None], axis=2), axis=1)
        cs = np.array([pts[lab_i == i].mean(axis=0) if (lab_i == i).any() else cs[i] for i in range(len(cs))])
    lab_i = np.argmin(np.linalg.norm(pts[:, None] - cs[None], axis=2), axis=1)
    keep = [i for i in range(len(cs)) if (lab_i == i).mean() >= P['min_share']]
    return cs[keep]


def assign(lab: np.ndarray, mask: np.ndarray, cs: np.ndarray, wl: float, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """Метка группы на каждый пиксель предмета (−1 вне) и расстояние до ближайшего тона палитры."""
    sm = wspace(nblur(lab, mask, sigma), wl)
    d = np.linalg.norm(sm[..., None, :] - cs[None, None], axis=3)
    lbl = np.where(mask, d.argmin(axis=2), -1)
    return lbl, np.where(mask, d.min(axis=2), 0.0)


def groups_of(lab, mask, cs, P, wl):
    lbl, dist = assign(lab, mask, cs, wl, P['sigma'])
    out = {}
    for g in range(len(cs)):
        gm = lbl == g
        if gm.sum() >= max(P['min_group_share'] * mask.sum(), P['min_group_px']):
            out[g] = gm
    return lbl, dist, out


# ---------- пять признаков: каждый → (r или None, подробности) ----------

def f_patches(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Заплатки внутри группы материала: (а) пиксели «чужого» тона — дальше foreign_dE от любого тона фото; (б) крупный тон группы ушёл от медианы группы дальше patch_dE;
    (в) резкие границы тона ВНУТРИ группы (по обе стороны одна группа, скачок цветности ab, не форма). Всё — избыток над фото той же вещи."""
    p, wl, P = R['patches'], R['lab_l_weight'], R['palette']
    lbl_s, dist_s, gs = ctx['s']
    lbl_p, dist_p, gp = ctx['p']
    n = float(m_s.sum())
    foreign = float((dist_s[m_s] > p['foreign_dE']).mean())
    foreign_p = float((dist_p[m_p] > p['foreign_dE']).mean()) if m_p.sum() else 0.0

    def within(lab, lbl, gm_all, mask):
        sm = nblur(lab, mask, p['sigma'])
        bad = 0
        for g, gm in gm_all.items():
            v = sm[gm]
            med = np.median(v, axis=0)
            d = np.sqrt((v[:, 0] - med[0]) ** 2 * wl ** 2 + (v[:, 1] - med[1]) ** 2 + (v[:, 2] - med[2]) ** 2)
            bad += int((d > p['patch_dE']).sum())
        return bad / max(1.0, float(mask.sum()))

    def edges(lab, lbl, mask):
        ab = nblur(lab[..., 1:], mask, p['edge_sigma'])
        grad = np.maximum(np.hypot(ndi.sobel(ab[..., 0], axis=0), ndi.sobel(ab[..., 1], axis=0)), np.hypot(ndi.sobel(ab[..., 0], axis=1), ndi.sobel(ab[..., 1], axis=1))) / 8.0
        same = ndi.maximum_filter(lbl, size=7) == ndi.minimum_filter(np.where(lbl < 0, 99, lbl), size=7)
        e = (grad > p['edge_ab_grad']) & ndi.binary_erosion(mask, iterations=int(p['edge_sigma']) + 2) & same
        l2, k = ndi.label(e, structure=np.ones((3, 3)))
        sizes = np.asarray(ndi.sum(e, l2, range(1, k + 1))) if k else np.array([])
        return int((sizes >= p['edge_min_len']).sum())

    w_s, w_p = within(lab_s, lbl_s, gs, m_s), (within(lab_p, lbl_p, gp, m_p) if m_p.sum() else 0.0)
    e_s, e_p = edges(lab_s, lbl_s, m_s), (edges(lab_p, lbl_p, m_p) if m_p.sum() else 0)
    r = max(max(0.0, foreign - foreign_p) / p['foreign_max'], max(0.0, w_s - w_p) / p['share_max'], max(0, e_s - e_p) / p['edges_max'])
    return r, {'foreign': round(foreign, 3), 'within': round(w_s, 3), 'within_photo': round(w_p, 3), 'edges': e_s, 'edges_photo': e_p}


LAP_ERODE = 2                                                      # отступ от края маски (px) у первого замера чёткости; повторы отступают дальше на shift_px


def lap_energy(lab: np.ndarray, mask: np.ndarray, erode: int = LAP_ERODE) -> float:
    lap = ndi.laplace(ndi.gaussian_filter(lab[..., 0], 0.7))
    inner = ndi.binary_erosion(mask, iterations=int(erode))
    return float((lap[inner] ** 2).mean()) if inner.any() else 0.0


def sharp_ratio(lab_s, m_s, lab_p, m_p, erode: int = LAP_ERODE) -> float | None:
    """Энергия Лапласа стороны / фото при заданном отступе от края маски; None — на таком отступе у фото нет деталей (энергия 0)."""
    e_p = lap_energy(lab_p, m_p, erode)
    return None if e_p <= 0 else lap_energy(lab_s, m_s, erode) / e_p


def f_sharpness(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Чёткость лица. ratio ≥ ratio_min — да; ratio < ratio_min·(1−tol) — нет; между («у порога», шум света/шейдинга) — `repeats` независимых замеров с другим отступом от края маски
    (+shift_px, +2·shift_px…), решение по среднему из всех замеров. Одно правило для всех товаров; числа — только `sharpness` в sides-eval.json. Итог несёт `repeats` — сколько повторов было."""
    p = R['sharpness']
    e_p = lap_energy(lab_p, m_p)
    if e_p < p['photo_energy_min']:
        return None, {'energy_photo': round(e_p, 4), 'why': 'фото без деталей (энергия кромок ниже порога sharpness.photo_energy_min)', 'inapplicable': True}
    e_s = lap_energy(lab_s, m_s)
    ratio = e_s / e_p
    lo, hi = p['ratio_min'] * (1.0 - p.get('tol', 0.0)), p['ratio_min']
    det = {'ratio': round(ratio, 2), 'repeats': 0}
    if lo <= ratio < hi and int(p.get('repeats', 0)) > 0:             # у порога — пересчёт
        rs = [ratio]
        for k in range(1, int(p['repeats']) + 1):
            rk = sharp_ratio(lab_s, m_s, lab_p, m_p, LAP_ERODE + k * int(p['shift_px']))
            if rk is not None:
                rs.append(rk)
        ratio = float(np.mean(rs))
        det.update({'repeats': len(rs) - 1, 'near_threshold': True, 'ratio_first': det['ratio'], 'ratios': [round(x, 3) for x in rs], 'ratio': round(ratio, 2)})
    return p['ratio_min'] / max(ratio, 1e-6), det


def group_sigma(lab, gm, sigma):
    m = ndi.binary_erosion(gm, iterations=2)
    if m.sum() < 50:
        return None
    sm = nblur(lab[..., 1:], gm, sigma)[m]
    return float(np.sqrt(sm.var(axis=0).sum()))


def f_uniform(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Однотонно где однотонно: группа, однородная на фото (разброс ab ≤ photo_sigma_max), на стороне не шире k × фото + floor. r — худшая группа."""
    p = R['uniform']
    _, _, gs = ctx['s']
    _, _, gp = ctx['p']
    rs, det = [], {}
    for g in gs:
        if g not in gp:
            continue
        sp, ss = group_sigma(lab_p, gp[g], p['sigma']), group_sigma(lab_s, gs[g], p['sigma'])
        if sp is None or ss is None or sp > p['photo_sigma_max']:
            continue
        rs.append(ss / (p['k'] * sp + p['floor']))
        det[f'g{g}'] = [round(ss, 2), round(sp, 2)]
    if not rs:
        return None, {'why': 'нет однородных групп на фото'}
    return max(rs), det


def group_pattern(lab, gm, p):
    m = ndi.binary_erosion(gm, iterations=int(p['sigma_hi']))
    if m.sum() < 50:
        return None
    L = lab[..., 0]
    hp = ndi.gaussian_filter(L, p['sigma_lo']) - ndi.gaussian_filter(L, p['sigma_hi'])
    return float(hp[m].std()), float(max(L[m].mean(), p.get('mean_L_floor', 20.0)))


def pattern_scale(lab, gm, p):
    """Размер элемента рисунка (px): длина волны ПИКА радиального спектра яркости (рисунок минус крупный свет `scale_sigma`, лёгкое сглаживание `sigma_lo` гасит гармоники тонких линий)
    в полосе `band_px`; None — мало пикселей/нет энергии. Сравнивается сторона с фото после подгонки фото по площади (один масштаб)."""
    m = ndi.binary_erosion(gm, iterations=int(p['sigma_hi']))
    if m.sum() < int(p.get('scale_min_px', 400)):
        return None
    L = ndi.gaussian_filter(lab[..., 0], p['sigma_lo'])
    hp = np.where(m, L - ndi.gaussian_filter(lab[..., 0], p['scale_sigma']), 0.0)
    ys, xs = np.where(m)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    hp, mm = hp[sl], m[sl]
    hp = np.where(mm, hp - hp[mm].mean(), 0.0)
    n = 256
    P = np.abs(np.fft.fft2(hp, s=(n, n))) ** 2
    f = np.hypot(np.fft.fftfreq(n)[:, None], np.fft.fftfreq(n)[None, :])
    lo, hi = p['band_px']
    sel = (f >= 1.0 / hi) & (f <= 1.0 / lo)
    if not sel.any() or P[sel].sum() <= 1e-9:
        return None
    edges = np.linspace(1.0 / hi, 1.0 / lo, 49)
    idx = np.digitize(f[sel], edges)
    prof = np.array([P[sel][idx == k].mean() if (idx == k).any() else 0.0 for k in range(1, len(edges))])
    k = int(prof.argmax())
    fc, df = (edges[k] + edges[k + 1]) / 2.0, edges[1] - edges[0]
    if 0 < k < len(prof) - 1:                                                    # пик между корзинами: парабола по трём корзинам (T-34/4 А) — без ступенек шага корзины (ответы 1,0→1,455→1,683 при пороге между ними)
        a, b, c = prof[k - 1], prof[k], prof[k + 1]
        den = a - 2.0 * b + c
        if den < 0.0:
            fc += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * df
    return float(1.0 / fc)


def group_large(lab, gm, p):
    """Крупные детали (пятна, фасад, рисунок крупнее зерна): размах яркости между крупным размытием `large_sigma` и `scale_sigma`, относительно яркости группы."""
    m = ndi.binary_erosion(gm, iterations=int(p['large_sigma']))
    if m.sum() < 50:
        return None
    L = lab[..., 0]
    d = ndi.gaussian_filter(L, p['scale_sigma']) - ndi.gaussian_filter(L, p['large_sigma'])
    return float(d[m].std() / max(L[m].mean(), p.get('mean_L_floor', 20.0)))


def f_pattern_typed(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Рисунок по ТИПУ товара (paint.hidden_pattern паспорта типа; T-47/3): continue — рисунок и его РАЗМЕР как на фото; body — на заду/боках/верху рисунка фасада нет (front_on_back = брак);
    same_fabric — фактура ткани как на фото (энергия в [ratio_min, ratio_max]) без крупных деталей; plain — ровно (контраст ≤ rel_max). Пороги — `pattern_by_type`."""
    p, T = R['pattern'], R['pattern_by_type']
    ps = {**p, **T['scale']}
    mode, view = ctx['hp'], ctx['view']
    _, _, gs = ctx['s']
    _, _, gp = ctx['p']
    rs, det = [], {}
    rel_p_all = [gps[0] / gps[1] for gps in (group_pattern(lab_p, gp[g], p) for g in gp) if gps is not None] if mode == 'plain' else []
    rel_p_top = max(rel_p_all) if rel_p_all else None                           # plain: у группы без пары на фото опора — самая рябая группа фото, а не пол (T-34/4 В)
    na = []                                                                      # continue: группы, где размер элемента не измерен (энергия решает отдельно, но это видно в отчёте)
    n_side = n_pair = 0                                                          # группы стороны с измеримым рисунком / из них — с парой-узором на фото (continue, same_fabric: «рисунок потерян целиком»)
    if mode == 'same_fabric':                                                    # крупные детали (пятна, фасад) — по всему предмету, а не по тонам: тон рвётся на куски и не переживает размытие
        sc = T['same_fabric']
        lg, lgp = group_large(lab_s, m_s, ps), group_large(lab_p, m_p, ps)
        if lg is not None and lgp is not None:
            rs.append((lg - sc['large_floor'] * lgp) / max(sc['large_max'] * lgp, 1e-6))
            det['large'] = [round(lg, 4), round(lgp, 4)]
    for g in gs:
        gss = group_pattern(lab_s, gs[g], p)
        if gss is None:
            continue
        rel_s = gss[0] / gss[1]
        n_side += 1
        gps = group_pattern(lab_p, gp[g], p) if g in gp else None
        rel_p = None if gps is None else gps[0] / gps[1]
        if mode == 'plain':
            ref = rel_p if rel_p is not None else rel_p_top                      # «ровно» = не рябее, чем сама вещь на фото (ткань стула имеет свой тканый рисунок)
            lim = max(T['plain']['rel_max'], 0 if ref is None else T['plain']['photo_k'] * ref)
            rs.append(rel_s / lim)
            det[f'g{g}'] = [round(rel_s, 4), None if rel_p is None else round(rel_p, 4)]
        elif mode == 'body':
            if view in T['body']['face_views']:                                  # фасад: рисунок должен быть (как «continue»)
                if gps is None or gps[0] < p['photo_energy_min']:
                    continue
                rs.append(p['ratio_min'] / max(rel_s / rel_p, 1e-6))
                det[f'g{g}'] = [round(rel_s, 4), round(rel_p, 4)]
            elif rel_p is not None and gps[0] >= p['photo_energy_min']:          # зад/бок/верх: рисунка фасада нет
                rs.append((rel_s / rel_p) / T['body']['side_max_ratio'])
                det[f'g{g}'] = [round(rel_s, 4), round(rel_p, 4)]
        elif mode == 'same_fabric':
            if rel_p is None or gps[0] < p['photo_energy_min']:
                continue
            n_pair += 1
            q = rel_s / rel_p
            sc = T['same_fabric']
            rs.append(max(sc['ratio_min'] / max(q, 1e-6), q / sc['ratio_max']))
            det[f'g{g}'] = [round(q, 3)]
        else:                                                                    # continue: энергия рисунка И его размер
            if gps is None or gps[0] < p['photo_energy_min']:
                continue
            n_pair += 1
            r_e = p['ratio_min'] / max(rel_s / rel_p, 1e-6)
            ss, sp = pattern_scale(lab_s, gs[g], ps), pattern_scale(lab_p, gp[g], ps)
            if ss is None or sp is None:                                         # размер не измерен — НЕ «размер сошёлся» (r_s=0), а «не измерено»: группу судит одна энергия, группа попадает в scale_na
                rs.append(r_e)
                na.append(g)
                det[f'g{g}'] = [round(rel_s / rel_p, 3), None]
            else:
                rs.append(max(r_e, max(ss / sp, sp / ss) / T['continue']['scale_k']))
                det[f'g{g}'] = [round(rel_s / rel_p, 3), round(ss / sp, 3)]
    lost = T.get(mode, {}).get('lost_r') if mode in ('continue', 'same_fabric') else None
    if lost is not None and n_side and not n_pair:                               # «рисунок потерян целиком»: нет пары-узора ПО ГРУППАМ — теперь проверяем по предмету целиком (свет мог увести цвет стороны в другую группу, а деталь вроде ножек на виде сверху не видна)
        pat_m = np.zeros(m_p.shape, bool)
        for g in gp:
            q = group_pattern(lab_p, gp[g], p)
            if q is not None and q[0] >= p['photo_energy_min']:
                pat_m |= gp[g] & m_p
        sc_l = T[mode]
        gp_all, gs_all = (group_pattern(lab_p, pat_m, p) if pat_m.sum() >= 50 else None), group_pattern(lab_s, m_s, p)
        dE = float(np.sqrt(((lab_s[m_s].mean(axis=0) - lab_p[pat_m].mean(axis=0)) ** 2).sum())) if pat_m.any() else None      # цвет стороны против цвета узорной части фото: далеко — сторона показывает другой материал (белая столешница при узорных ножках), а не потерянный рисунок
        if gp_all is not None and gs_all is not None and dE is not None and dE <= sc_l['lost_max_dE'] and pat_m.sum() >= sc_l['lost_min_share'] * m_p.sum() and (gs_all[0] / gs_all[1]) < p['ratio_min'] * (gp_all[0] / gp_all[1]):
            rs.append(float(lost))                                               # рисунок занимает заметную долю фото, цвет стороны — цвет узорной части, а энергии рисунка по предмету целиком < ratio_min × фото — потерян целиком (плоский тон), не «не измерено»; r — `lost_r`
            det['lost'] = True
            det['lost_dE'] = round(dE, 1)
    if not rs:
        return None, {'why': 'нет измеряемой группы', 'mode': mode}
    if na:
        det['scale_na'] = na
    return max(rs), {**det, 'mode': mode}


def f_pattern(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Рисунок перенесён: в каждой группе, где на фото рисунок есть (энергия ≥ photo_energy_min), на стороне ≥ ratio_min × фото. r — худшая группа. Если у товара задан тип рисунка (`hidden_pattern`) — по типу."""
    if ctx.get('hp') in ('continue', 'body', 'same_fabric', 'plain'):
        return f_pattern_typed(lab_s, m_s, lab_p, m_p, R, ctx)
    if ctx.get('hp') in ('unknown', 'not_applicable'):                      # нет типа/политики или рисунок типу не нужен — признак «не оценено», не проход и не брак
        return None, {'why': 'не оценено: ' + ctx['hp'], 'mode': ctx['hp']}
    p = R['pattern']
    _, _, gs = ctx['s']
    _, _, gp = ctx['p']
    rs, det = [], {}
    photo_pat = any((q := group_pattern(lab_p, gp[g], p)) is not None and q[0] >= p['photo_energy_min'] for g in gp)      # мерка по фото: есть ли рисунок хоть в одной группе (порог photo_energy_min из правил)
    for g in gs:
        if g not in gp:
            continue
        gps, gss = group_pattern(lab_p, gp[g], p), group_pattern(lab_s, gs[g], p)
        if gps is None or gss is None or gps[0] < p['photo_energy_min']:
            continue
        # контраст рисунка относительно яркости группы: на стороне в тени тот же рисунок даёт меньший абсолютный размах (свет сайта темнее листа)
        rs.append(p['ratio_min'] / max((gss[0] / gss[1]) / (gps[0] / gps[1]), 1e-6))
        det[f'g{g}'] = [round(gss[0], 2), round(gps[0], 2)]
    if not rs:
        if photo_pat:
            return None, {'why': 'рисунок на фото есть, на стороне не измерен (нет группы/пары)'}
        return None, {'why': 'на фото нет рисунка (энергия узора ниже порога photo_energy_min)', 'inapplicable': True}
    return max(rs), det


def underpaint_shares(lab: np.ndarray, mask: np.ndarray, p: dict) -> dict:
    v = lab[mask]
    chroma = np.hypot(v[:, 1], v[:, 2])
    lo, hi = p['grey_L']
    return {'grey': float(((chroma < p['grey_chroma']) & (v[:, 0] > lo) & (v[:, 0] < hi)).mean()),
            'black': float((v[:, 0] < p['black_L']).mean()), 'white': float((v[:, 0] > p['white_L']).mean())}


def jump_share(lab: np.ndarray, mask: np.ndarray, p: dict) -> float:
    sm = nblur(lab, mask, 1.2)
    k = int(p['jump_px'])
    inner = ndi.binary_erosion(mask, iterations=k + 3)
    hits = np.zeros(mask.shape, bool)
    for dy, dx in ((0, k), (k, 0)):
        a = sm[: sm.shape[0] - dy, : sm.shape[1] - dx]
        b = sm[dy:, dx:]
        h = (np.hypot(a[..., 1] - b[..., 1], a[..., 2] - b[..., 2]) > p['jump_dab']) & (np.abs(a[..., 0] - b[..., 0]) < p['jump_dL_max'])
        hits[: h.shape[0], : h.shape[1]] |= h
    return float(hits[inner].mean()) if inner.any() else 0.0


def f_underpaint(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    p = R['underpaint']
    s = underpaint_shares(lab_s, m_s, p)                # серое/чёрное/белое — по тону без света и формы (лист «глина»); без неё — по виду
    lab_v = ctx.get('lab_r', lab_s)                      # скачки тона — по самому виду
    have = m_p.sum() >= R['geometry']['min_px']
    ph = underpaint_shares(lab_p, m_p, p) if have else {'grey': 0.0, 'black': 0.0, 'white': 0.0}
    ex = {k: max(0.0, s[k] - ph[k]) for k in s}
    if have:                                           # белое/чёрное на фото есть (белая столешница, чёрная ткань) — на стороне это не недокрас
        near = underpaint_shares(lab_p, m_p, dict(p, black_L=p['black_L'] + p['near_margin'], white_L=p['white_L'] - p['near_margin']))
        for k in ('black', 'white'):
            if near[k] >= p['near_share']:
                ex[k] = 0.0
    j, j_p = jump_share(lab_v, m_s, p), (jump_share(lab_p, m_p, p) if have else 0.0)
    r = max(ex['grey'] / p['grey_excess_max'], ex['black'] / p['black_excess_max'], ex['white'] / p['white_excess_max'], max(0.0, j - j_p) / p['jump_share_max'])
    return r, {'grey': round(s['grey'], 3), 'black': round(s['black'], 3), 'white': round(s['white'], 3), 'jump': round(j, 4), 'jump_photo': round(j_p, 4)}


def f_back_tone(lab_s, m_s, lab_p, m_p, R, ctx) -> tuple:
    """Тон тыла ≈ тон лица (T-34/4 В): на не-лицевой стороне (вне `face_views`) ни один тон палитры не занимает заметно БОЛЬШЕ площади, чем на фото той же вещи
    (избыток = доля тона на стороне − доля на фото, по сырым меткам, без отсева малых групп фото). Ловит тыл спинки в тоне ножек вместо ткани лица (доли тонов фото не переносятся на сторону без пары)."""
    T = R['back_tone']
    if ctx['view'] in T['face_views']:
        return None, {'why': 'лицевая сторона (back_tone.face_views в правилах)', 'inapplicable': True}
    lbl_s, _, gs = ctx['s']
    lbl_p, _, _ = ctx['p']
    if not m_p.sum():
        return None, {'why': 'нет фото'}
    rs, det = [], {}
    for g in gs:
        sh_s = float((lbl_s[m_s] == g).mean())
        if sh_s < T['min_share']:
            continue
        sh_p = float((lbl_p[m_p] == g).mean())
        rs.append(max(0.0, sh_s - sh_p) / T['excess_max'])
        det[f'g{g}'] = [round(sh_s, 3), round(sh_p, 3)]
    if not rs:
        return None, {'why': 'нет крупной группы'}
    return max(rs), det


FUNCS = {'patches': f_patches, 'sharpness': f_sharpness, 'uniform': f_uniform, 'pattern': f_pattern, 'underpaint': f_underpaint, 'back_tone': f_back_tone}


def feat_status(d: dict, observe_only: bool = False) -> str:
    """Статус признака на стороне: ok (измерено, прошло) · fail (измерено, не прошло) · unmeasured («не измерено» — измерить не вышло, причина в `why`) · na (признак неприменим по сути:
    у лица нет «тона тыла», на фото нет рисунка/деталей) · observe (признак в режиме наблюдения enforce=false — не считается). Только ok/fail идут в вердикт; unmeasured НЕ равно «прошёл» (T-20261124-22)."""
    if observe_only or d.get('observe'):
        return 'observe'
    if d.get('r') is None:
        return 'na' if d.get('inapplicable') else 'unmeasured'
    return 'ok' if d.get('ok') else 'fail'


def verdict_of(cnt: dict) -> tuple:
    """(ok, status) товара по счёту статусов: ok=False — есть не прошедший; ok=None («не измерено») — не прошедших нет, но что-то применимое не измерено или не измерено ничего; ok=True — всё применимое
    измерено и прошло. na (неприменимо) и observe вердикт не меняют."""
    if cnt.get('fail'):
        return False, 'failed'
    if cnt.get('unmeasured') or not cnt.get('ok'):
        return None, 'unmeasured'
    return True, 'passed'


def score_of(r: float | None) -> float | None:
    return None if r is None else round(float(min(1.0, max(0.0, 1.0 - r / 2.0))), 3)


def eval_view(view_rgb: np.ndarray, photo_rgb: np.ndarray, photo_mask: np.ndarray, name: str, R: dict, tone_rgb: np.ndarray | None = None, memo: dict | None = None, hp: str | None = None) -> dict:
    """tone_rgb — вид без формы (albedo_of, уже нормированный по фото); без него тон берётся прямо с вида (тень формы тогда считается тоном)."""
    g = R['geometry']
    m = view_mask(view_rgb, g)
    if int(m.sum()) < g['min_px']:
        return {'na': f"предмета на виде {int(m.sum())} px (< {g['min_px']})"}
    lab_r = rgb_to_lab(np.asarray(view_rgb)[..., :3])
    lab_s = lab_r if tone_rgb is None else rgb_to_lab(tone_rgb)
    p_rgb, p_m = rescale_to_area(photo_rgb, photo_mask, float(m.sum()), g.get('photo_upscale_max'), memo)
    wl, P = R['lab_l_weight'], R['palette']
    pk = ('ph', p_rgb.shape[:2], p_rgb is photo_rgb)
    if memo is not None and pk in memo:                                # то же фото в том же размере: лаб, палитра, группы — один раз на товар (результат тот же)
        lab_p, cs, gp = memo[pk]
    else:
        lab_p = rgb_to_lab(p_rgb)
        cs = palette(lab_p, p_m, P, wl) if p_m.sum() >= g['min_px'] else np.zeros((0, 3))
        gp = groups_of(lab_p, p_m, cs, P, wl) if len(cs) else None
        if memo is not None:
            memo[pk] = (lab_p, cs, gp)
    if len(cs) == 0:
        return {'na': 'на фото не нашли предмет'}
    ctx = {'s': groups_of(lab_s, m, cs, P, wl), 'p': gp, 'lab_r': lab_r, 'hp': hp, 'view': name}
    out = {}
    for feat in FEATURES:
        if feat == 'sharpness' and name not in R['sharpness']['views']:
            continue
        r, det = FUNCS[feat](lab_r if feat in ('sharpness', 'pattern') else lab_s, m, lab_p, p_m, R, ctx)
        out[feat] = {'r': None if r is None else round(float(r), 3), 'score': score_of(r), 'ok': None if r is None else bool(r <= 1.0), **det}
        if r is not None and R.get(feat, {}).get('enforce') is False:                 # «наблюдение» (enforce=false в правилах): r и подробности пишутся, но ни ok, ни оценка не считаются — признак ещё не откалиброван
            out[feat].update({'ok': None, 'score': None, 'observe': True, 'would_fail': bool(r > 1.0)})
        out[feat]['status'] = feat_status(out[feat], R.get(feat, {}).get('enforce') is False)
        if out[feat]['status'] == 'unmeasured':
            out[feat].setdefault('why', 'признак не посчитан (нет данных)')
    return out


def front_shares(V, F, UV, known, az_deg, R, names=None) -> dict:
    """Доля известных с фото текселей по сторонам листа — общий свидетель «перёда» `tools/scout/front_axis.py` (T-21/2: один источник для 06, 07 и листа)."""
    return FA.front_shares(V, F, UV, known, az_deg, R, names)


def front_flipped(shares: dict, R: dict) -> bool:
    return FA.front_flipped(shares, R)


def flip_sheet(sheet: np.ndarray, S: int, hp: int) -> np.ndarray:
    """Поворот на 180°: перед↔зад (ячейки 1↔4), бок↔др. бок (3↔5); «3/4» (2) без пары — белая (n/a). Фото (0) и верх (6) на месте."""
    out = sheet.copy()
    cell = lambda i: (slice(hp, hp + S), slice(i * S, (i + 1) * S))
    for a, b in ((1, 4), (3, 5)):
        out[cell(a)], out[cell(b)] = sheet[cell(b)], sheet[cell(a)]
    out[cell(2)] = 255
    return out


def eval_sheet(sheet_rgb: np.ndarray, R: dict, sheet_rules: dict | None = None, clay_rgb: np.ndarray | None = None, flip: bool = False, hidden_pattern: str | None = None) -> dict:
    """Лист → {views: {имя: {признак: {...}}}, ok, status, counts, unmeasured, score, worst}. ok=True — всё применимое измерено и r ≤ 1; ok=False — есть не прошедший; ok=None («не измерено») — не прошедших
    нет, но часть применимого не измерена (список `unmeasured` с причинами; раньше такое засчитывалось как «прошёл»). na/observe вердикт не меняют; score — худший из ИЗМЕРЕННЫХ.
    clay_rgb — лист «глина» (sides_sheet --clay): тогда тон считается без формы (albedo), иначе — прямо с видов."""
    sr = sheet_rules or load_sheet_rules()
    S, hp = int(sr['size']), int(sr['header_px'])
    names = [v['name'] for v in sr['views']]
    if flip:                                                       # ракурс листа развёрнут на 180° — пересчёт сторон (предохранитель front_guard)
        sheet_rgb = flip_sheet(sheet_rgb, S, hp)
        clay_rgb = None if clay_rgb is None else flip_sheet(clay_rgb, S, hp)
    cells = [sheet_rgb[hp: hp + S, i * S: (i + 1) * S] for i in range(len(names) + 1)]
    p_rgb, p_m = photo_cell(cells[0], R['geometry'])
    pmin = R['geometry'].get('photo_min_px')
    if pmin and int(p_m.sum()) < pmin:                              # тонкая вещь: маска фото съедена краем — сравнивать не с чем; не провал и не проход (директор 23.11)
        return {'views': {}, 'albedo_scale': None, 'ok': None, 'score': None, 'worst': None, 'photo_ok': False, 'flipped': bool(flip), 'uncertain': f'маска фото {int(p_m.sum())} px (< {pmin}): не измерено',
                'status': 'unmeasured', 'counts': None, 'unmeasured': [{'view': '*', 'feature': '*', 'why': f'маска фото {int(p_m.sum())} px (< {pmin})'}]}
    tone = [None] * len(names)
    scale = None
    if clay_rgb is not None:
        sm = R['albedo']['shade_min']
        alb = [albedo_of(cells[i + 1], clay_rgb[hp: hp + S, (i + 1) * S: (i + 2) * S], sm) for i in range(len(names))]
        m0 = view_mask(cells[1], R['geometry'])
        a0, p0 = lum(alb[0], m0), lum(srgb_lin(p_rgb), p_m)
        scale = p0 / a0 if a0 > 1e-6 and p0 > 1e-6 else 1.0          # один общий множитель на все виды: тон лица = тон фото (общий сдвиг тона — дело ворот кадра, не этой мерки)
        tone = [lin_srgb(a * scale) for a in alb]
    memo: dict = {}
    views = {n: eval_view(cells[i + 1], p_rgb, p_m, n, R, tone[i], memo, hidden_pattern) for i, n in enumerate(names)}
    worst, scores = None, []
    cnt = {'ok': 0, 'fail': 0, 'unmeasured': 0, 'na': 0, 'observe': 0, 'na_views': 0}
    unmeasured = []
    for n, fs in views.items():
        if 'na' in fs:                                                # вид без предмета: неприменим, не «не измерено»
            cnt['na_views'] += 1
            continue
        for f, d in fs.items():
            st = d.get('status') or feat_status(d)
            cnt[st] += 1
            if st == 'unmeasured':
                unmeasured.append({'view': n, 'feature': f, 'why': d.get('why') or 'нет данных'})
            if st not in ('ok', 'fail') or d.get('score') is None:
                continue
            scores.append(d['score'])
            if worst is None or d['score'] < worst[2]:
                worst = (n, f, d['score'])
    ok, status = verdict_of(cnt)
    return {'views': views, 'albedo_scale': None if scale is None else round(float(scale), 3), 'ok': ok, 'score': min(scores) if scores else None, 'worst': None if worst is None else {'view': worst[0], 'feature': worst[1], 'score': worst[2]},
            'photo_ok': bool(p_m.sum() >= R['geometry']['min_px']), 'flipped': bool(flip), 'status': status, 'counts': cnt, 'unmeasured': unmeasured}


def known_shares_of(item: dict, R: dict) -> dict | None:
    """Доли известного по сторонам для товара из items.json (glb + check06; known.png лежит рядом с check.json этапа 06). Нет файлов — None (предохранитель молчит)."""
    try:
        import trimesh
        from PIL import Image
        c6 = item.get('check06')
        kp = os.path.join(os.path.dirname(c6), 'known.png')
        az = json.load(open(c6, encoding='utf-8'))['extra']['camera']['az']
        sc = trimesh.load(item['glb'], force='scene')
        gs = list(sc.geometry.values())
        V = np.concatenate([g.vertices for g in gs])
        off, F, UV = 0, [], []
        for g in gs:
            F.append(g.faces + off)
            off += len(g.vertices)
            UV.append(np.asarray(g.visual.uv))
        known = np.asarray(Image.open(kp).convert('L'))
        return front_shares(V, np.concatenate(F), np.concatenate(UV), known, float(az), R)
    except Exception:  # noqa: BLE001 — нет known/az/GLB: ракурс не проверяем, это видно в eval.json (front_shares=None)
        return None


def _sha(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()


def _file_bytes(p: str | None) -> bytes:
    try:
        with open(p, 'rb') as f:
            return f.read()
    except (OSError, TypeError):
        return b''


def cache_key(sheets: str, i: str, R: dict, clay_dir: str, item: dict | None) -> str:
    """Ключ кэша оценки товара: лист + глина + правила + код оценки и «перёда» + вход ракурса (item, check06, known.png, GLB). Те же входы — тот же результат."""
    it = dict(item or {})
    c6 = it.get('check06')
    extra = [_file_bytes(c6), _file_bytes(os.path.join(os.path.dirname(c6), 'known.png')) if c6 else b'', _file_bytes(it.get('glb')) if c6 else b'']
    return _sha(_file_bytes(os.path.join(sheets, i + '.png')), _file_bytes(os.path.join(clay_dir, i + '.clay.png')), json.dumps(R, sort_keys=True, ensure_ascii=False).encode(),
                json.dumps(it, sort_keys=True, ensure_ascii=False).encode(), _file_bytes(os.path.abspath(__file__)), _file_bytes(FA.__file__), *extra)


RULE_ID = 'R-SIDES-EVAL-TYPE'


def rule_entry(item: dict, hp: str) -> dict:
    """Запись правила для аудита прогона (extra.rules[]) — ОДНИМ форматом на все этапы: `rule_record.entry` (тип и digest из `paint_policy(роль)`). Применено по типу (continue/body/same_fabric/plain)
    или воздержание с причиной (unknown, not_applicable, observe, нет политики); роли/типа нет — воздержание «тип не определён (no_type)»."""
    scout = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scout')
    if scout not in sys.path:
        sys.path.insert(0, scout)
    import rule_record as RR  # noqa: PLC0415
    if hp in ('continue', 'body', 'same_fabric', 'plain'):
        return RR.entry(RULE_ID, item.get('role'), True)
    return RR.entry(RULE_ID, item.get('role'), False, item.get('policy_reason') or f'hidden_pattern={hp}')


def eval_one(sheets: str, i: str, R: dict, clay_dir: str, item: dict | None, cache_dir: str | None = None) -> dict:
    """Оценка одного листа (общая для последовательного и параллельного прогона); при cache_dir — из кэша, если входы те же."""
    from PIL import Image
    kp = None
    if cache_dir:
        kp = os.path.join(cache_dir, cache_key(sheets, i, R, clay_dir, item) + '.json')
        if os.path.isfile(kp):
            try:
                with open(kp, encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
    cp = os.path.join(clay_dir, i + '.clay.png')
    clay = np.asarray(Image.open(cp).convert('RGB')) if os.path.exists(cp) else None
    fs = known_shares_of(item, R) if item else None
    flip = front_flipped(fs, R) if fs else False
    hp = (item or {}).get('hidden_pattern')
    r = eval_sheet(np.asarray(Image.open(os.path.join(sheets, i + '.png')).convert('RGB')), R, clay_rgb=clay, flip=flip, hidden_pattern=hp)
    r['front_shares'] = fs
    if hp:
        r['hidden_pattern'] = hp
        r['passport_digest'] = (item or {}).get('passport_digest')
        r['policy_reason'] = (item or {}).get('policy_reason')            # одна политика и один digest в 07, check.json и оценке
        r['extra'] = {'rules': [rule_entry(item or {}, hp)]}                                 # формат tools/ops/rule_registry_audit.py: rule_id, type, digest, applied | abstain+причина
    if flip:
        r['note'] = 'ракурс развёрнут'
    if kp:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = f'{kp}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(r, f, ensure_ascii=False)
        os.replace(tmp, kp)
    return r


def add_front(sheets: str, res: dict, R: dict) -> dict:
    """Признак «фронт сплошной» (front_continuity.py, data/flat3d/front-continuity.json) — ОТДЕЛЬНАЯ строка: res[id]['front'] и сводка; ok/score/status пяти признаков не трогает.
    Только корпусные (hidden_pattern = body), лист не развёрнут; остальным — «не применимо». «Не измерено» (маска мала) ≠ прошёл."""
    from PIL import Image
    if HERE not in sys.path:
        sys.path.insert(0, HERE)                                                           # -I (изолированный запуск): соседний модуль не виден сам
    import front_continuity as FC
    sr = load_sheet_rules()
    S, hp_ = int(sr['size']), int(sr['header_px'])
    out = {'applicable': 0, 'passed': 0, 'failed': 0, 'unmeasured': 0, 'failed_ids': [], 'unmeasured_ids': []}
    for i, v in res.items():
        if v.get('hidden_pattern') != 'body' or v.get('flipped'):
            v['front'] = {'status': 'na', 'why': 'не корпусной товар или ракурс развёрнут'}
            continue
        sh = np.asarray(Image.open(os.path.join(sheets, i + '.png')).convert('RGB'))
        c0, c1 = sh[hp_: hp_ + S, 0:S], sh[hp_: hp_ + S, S: 2 * S]                         # ячейки: 0 — фото, 1 — «перед»
        p_rgb, p_m = photo_cell(c0, R['geometry'])
        r = FC.front_continuity(c1, view_mask(c1, R['geometry']), p_rgb, p_m)
        st = 'unmeasured' if r['ok'] is None else ('passed' if r['ok'] else 'failed')
        v['front'] = {'status': st, 'r': r['r'], 'why': r['why'], 'strip': r.get('strip'), 'spot': r.get('spot')}
        out['applicable'] += 1
        out[st] += 1
        if st == 'failed':
            out['failed_ids'].append(i)
        elif st == 'unmeasured':
            out['unmeasured_ids'].append(i)
    return out


def _eval_job(a: tuple) -> dict:
    return eval_one(*a)


def batch(sheets: str, out: str, only: list | None = None, rules: dict | None = None, clay_dir: str | None = None, items: dict | None = None,
          workers: int = 1, cache_dir: str | None = None) -> dict:
    """workers > 1 — товары параллельно (пул процессов; число = ядра по heavy-slot, `HEAVY_SLOT_CORES`); результат тот же, порядок — по id. cache_dir — кэш оценки по sha входов."""
    R = load_rules(rules)
    ids = sorted(f[:-4] for f in os.listdir(sheets) if f.endswith('.png') and not f.endswith('.clay.png'))
    if only:
        ids = [i for i in ids if i in only]
    os.makedirs(out, exist_ok=True)
    cd = clay_dir or sheets
    jobs = [(sheets, i, R, cd, (items or {}).get(i), cache_dir) for i in ids]
    if workers > 1 and len(jobs) > 1:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=mp.get_context('fork')) as ex:
            outs = list(ex.map(_eval_job, jobs))
    else:
        outs = [_eval_job(j) for j in jobs]
    res = dict(zip(ids, outs))
    front_ids = add_front(sheets, res, R)                                              # «фронт сплошной» (T-20261124-18): отдельная строка, вердикты 5 признаков не меняет
    unc = sorted(k for k, v in res.items() if v.get('uncertain'))                  # «не измерено» целиком (маска фото мала)
    meas = [k for k in res if k not in unc]
    stat = {k: (v.get('status') or ('unmeasured' if v.get('uncertain') or v.get('ok') is None else ('passed' if v.get('ok') else 'failed'))) for k, v in res.items()}
    passed_ids = sorted(k for k, s_ in stat.items() if s_ == 'passed')
    failed_ids = sorted(k for k, s_ in stat.items() if s_ == 'failed')
    unm_ids = sorted(k for k, s_ in stat.items() if s_ == 'unmeasured')        # три числа: прошли ВСЁ (всё применимое измерено) · есть «не измерено» · не прошли — сумма = items
    n_ok = len(passed_ids)
    na_by_reason: dict = {}
    na_feat = na_view = 0
    for v_ in res.values():                                                    # «неприменимо» — сколько признаков (и видов) выпало из проверки и почему
        for fs_ in (v_.get('views') or {}).values():
            if 'na' in fs_:
                na_view += 1
                na_by_reason[str(fs_['na'])[:40]] = na_by_reason.get(str(fs_['na'])[:40], 0) + 1
                continue
            for d_ in fs_.values():
                if d_.get('status') == 'na':
                    na_feat += 1
                    k_ = str(d_.get('why') or 'без причины').split(' (')[0]
                    na_by_reason[k_] = na_by_reason.get(k_, 0) + 1
    flipped = sorted(k for k, v in res.items() if v.get('flipped'))
    summary = {'front_continuity': front_ids, 'items': len(res), 'measured': len(meas), 'uncertain': unc, 'flipped': len(flipped), 'flipped_ids': flipped, 'passed_all': n_ok,
               'passed_all_pct': round(100.0 * n_ok / len(res), 1) if res else None,        # от ВСЕХ товаров: «не измерено» в знаменателе, не прячется
               'failed': len(failed_ids), 'with_unmeasured': len(unm_ids), 'failed_ids': failed_ids, 'unmeasured_ids': unm_ids,
               'na_features': na_feat, 'na_views': na_view, 'na_by_reason': dict(sorted(na_by_reason.items())),
               'worst_first': sorted(meas, key=lambda k: (res[k]['score'] if res[k]['score'] is not None else 2.0, k)) + unc}
    with open(os.path.join(out, 'eval.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return {'eval': res, 'summary': summary}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('batch')
    b.add_argument('--sheets', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--only', default='')
    b.add_argument('--items', default='', help='items.json листов (glb, check06) — для предохранителя ракурса front_guard')
    b.add_argument('--clay-dir', default='', help='папка с <id>.clay.png (по умолчанию — рядом с листами)')
    b.add_argument('--workers', type=int, default=int(os.environ.get('HEAVY_SLOT_CORES') or 1), help='товаров параллельно (по умолчанию — ядра heavy-slot)')
    b.add_argument('--cache', default='', help='папка кэша оценки по sha входов (лист, глина, правила, код)')
    a = ap.parse_args(argv)
    items = {x['id']: x for x in json.load(open(a.items, encoding='utf-8'))} if a.items else None
    r = batch(a.sheets, a.out, [x for x in a.only.split(',') if x] or None, clay_dir=a.clay_dir or None, items=items, workers=a.workers, cache_dir=a.cache or None)
    s = r['summary']
    f_ = s['front_continuity']
    print(f"фронт сплошной (корпусные): применимо {f_['applicable']} · прошли {f_['passed']} · не прошли {f_['failed']} {f_['failed_ids']} · не измерено {f_['unmeasured']}")
    print(f"товаров {s['items']}: прошли ВСЁ (всё измерено) {s['passed_all']} ({s['passed_all_pct']} %) · есть «не измерено» {s['with_unmeasured']} · не прошли {s['failed']} · неприменимо {s['na_features']} признаков и {s['na_views']} видов; ракурс развёрнут: {s['flipped']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
