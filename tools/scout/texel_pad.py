#!/usr/bin/env python3
"""ЗАЛИВКА НЕПОКРЫТЫХ ТЕКСЕЛЕЙ при экспорте текстуры (T-20261125-70; общее правило для 07 и 08, без имён товаров).

ЗАЧЕМ. Развёртка UV покрывает не всю картинку: ~31 % текстуры (у многих товаров ровно столько — острова TRELLIS уложены в сетку) — зазоры между островами и швы, куда центр
ни одной грани не попал. Покраска их не трогает (красить «нечем»), и они остаются старым цветом заготовки. Рендер при фильтрации/мип-уровнях берёт их у края острова — старый цвет
(оранжевый, серо-розовый) «протекает»: серый налёт и оранжевая крапка (р.2 T-69/3).

ЧТО УЖЕ БЫЛО (не дублируем, а замыкаем): копия цвета ближайшего покрытого тексела в `gutter` px — `tex_fill.fill` (cfg gutter, 8), `seam_stage`, `surface_passport` (gutter_px), `photo_project`.
Почему не хватало: (1) они делаются ВНУТРИ своих этапов, а после них цвет покрытых текселей меняют ещё хуки 07 и этап 08 (сдвиг части, тон стекла) — отступ остаётся прежним цветом;
(2) радиус 8 px: у части товаров зазор шире (до 21 px) — дальше старый цвет остаётся совсем; (3) отчёта о том, сколько текстуры не покрыто и каким цветом, не было.
ЗДЕСЬ — один проход ПОСЛЕ последней покраски, перед записью файла: покрытое не меняется ни на единицу; прежний отступ (непокрытое в `keep_px` px от острова — его уже залил gutter этапа)
считается покрытым и тоже НЕ перезаписывается (решение директора, T-70); дальше него непокрытое заливается средним по уже известным соседям (kernel×kernel), `passes` раз
(за проход цвет уходит на 1 px вглубь зазора). Число проходов, ядро и keep_px — только `tools/scout/rules/paint-fill.json` → `texel_fill` (в коде чисел нет; keep_px = gutter этапа,
тест `tests_texel_pad` сверяет с `tex_fill.FILL['gutter']`).

«ПОКРЫТО» = центр тексела внутри грани (как у `tex_fill.Tex` и сторожа охвата: `tex_coverage.raster`) — то же определение, что у покраски.
ОТЧЁТ (строка в проверку этапа): доля непокрытых, средний цвет непокрытых ДО заливки и покрытых; «чужой цвет» = ΔE76 среднего цвета полосы (до `passes` px от острова) до среднего цвета кромки острова —
до и после; `band_unfilled` — текселей полосы, которых заливка не достала (должно быть 0).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.environ.get('FILL_RULES') or os.path.join(HERE, 'rules', 'paint-fill.json')
TRELLIS = os.path.join(HERE, 'salad', 'trellis')


def rules(path: str | None = None) -> dict:
    """`texel_fill` из rules/paint-fill.json: {passes, kernel, band_rim_dE_max}. Нет ключа — KeyError (чисел в коде нет)."""
    with open(path or RULES_PATH, encoding='utf-8') as f:
        r = json.load(f).get('texel_fill')
    if not isinstance(r, dict):
        raise KeyError('rules/paint-fill.json: нет ключа texel_fill')
    for k in ('passes', 'kernel', 'keep_px', 'band_rim_dE_max'):
        if k not in r:
            raise KeyError(f'rules/paint-fill.json: texel_fill.{k} не задан')
    if int(r['kernel']) % 2 != 1 or int(r['kernel']) < 3 or int(r['passes']) < 0 or int(r['keep_px']) < 0:
        raise ValueError(f'texel_fill: kernel — нечётное ≥3, passes ≥0, keep_px ≥0 (получено {r["kernel"]}, {r["passes"]}, {r["keep_px"]})')
    return r


def _tc():
    if TRELLIS not in sys.path:
        sys.path.insert(0, TRELLIS)
    import tex_coverage as TC
    return TC


def coverage_from_uv(uv, faces, T: int) -> np.ndarray:
    """bool (T,T): тексел покрыт, если его центр внутри какой-нибудь грани (ось y картинки вниз — как у Tex)."""
    uv = np.asarray(uv, np.float64)
    xy = np.stack([uv[:, 0] * T, (1.0 - uv[:, 1]) * T], 1)
    ids, _ = _tc().raster(xy, np.asarray(faces, np.int64), T)
    return (np.asarray(ids) >= 0).reshape(T, T)


def fill_uncovered(rgb: np.ndarray, cov: np.ndarray, passes: int, kernel: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """→ (новая картинка, достигнутые bool). Покрытые тексели не меняются; непокрытые, у которых за ≤passes проходов появился покрытый сосед, = среднее по покрытым соседям kernel×kernel."""
    from scipy.ndimage import uniform_filter
    a = np.asarray(rgb)
    cov = np.asarray(cov, bool)
    out = a.copy()
    known = cov.copy()
    if passes <= 0 or not (~cov).any() or not cov.any():
        return out, np.zeros(cov.shape, bool)
    im = a[..., :3].astype(np.float32)
    cv = cov.astype(np.float32)
    for _ in range(int(passes)):
        den = uniform_filter(cv, size=kernel, mode='constant')
        new = (~known) & (den > 1e-6)
        if not new.any():
            break
        for ch in range(3):
            num = uniform_filter(im[..., ch] * cv, size=kernel, mode='constant')
            im[..., ch][new] = num[new] / den[new]
        cv[new] = 1.0
        known |= new
    reached = known & ~cov
    out[..., :3][reached] = np.clip(np.rint(im[reached]), 0, 255).astype(a.dtype)
    return out, reached


def _band_vs_rim(lab_a: np.ndarray, lab_b: np.ndarray, band: np.ndarray, rim: np.ndarray) -> tuple[float, float]:
    """ΔE76 среднего цвета полосы (непокрытое в пределах passes px от острова) до среднего цвета кромки (покрытое в пределах passes px от зазора): до заливки (lab_a) и после (lab_b).
    Целые числа по полосе, а не по текселю: у рисунка (дерево, ткань) отдельный тексел законно отличается от соседа; «чужой цвет заготовки» виден именно в среднем."""
    ref = lab_a[rim].mean(axis=0)
    return float(np.linalg.norm(lab_a[band].mean(axis=0) - ref)), float(np.linalg.norm(lab_b[band].mean(axis=0) - ref))


def pad_texture(rgb: np.ndarray, cov: np.ndarray, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """Заливка одной текстуры + отчёт «до → после». `rgb` — (T,T,3|4) uint8; `cov` — покрытие (coverage_from_uv)."""
    from scipy.ndimage import distance_transform_edt
    c = cfg or rules()
    passes, kernel, keep_px = int(c['passes']), int(c['kernel']), int(c.get('keep_px', 0))
    a = np.asarray(rgb)
    cov = np.asarray(cov, bool)
    unc = ~cov
    n_unc = int(unc.sum())
    rep: dict = {'size': int(a.shape[0]), 'uncovered_pct': round(100.0 * n_unc / cov.size, 2), 'passes': passes, 'kernel': kernel, 'keep_px': keep_px, 'kept_texels': 0, 'keep_changed': 0,
                 'changed_texels': 0, 'band_texels': 0, 'band_unfilled': 0, 'band_vs_rim_dE_before': None, 'band_vs_rim_dE_after': None, 'unreached_pct': 0.0}
    if not n_unc or not cov.any():
        return a.copy(), rep
    rep['uncovered_mean_rgb_before'] = [round(float(v), 1) for v in a[..., :3][unc].mean(axis=0)]
    rep['covered_mean_rgb'] = [round(float(v), 1) for v in a[..., :3][cov].mean(axis=0)]
    keep = unc & (distance_transform_edt(unc) <= keep_px)        # отступ, который уже сделал этап (gutter): считается покрытым и не перезаписывается (решение директора, T-70)
    known0 = cov | keep
    rem = ~known0                                                 # непокрытое ДАЛЬШЕ отступа — только его заливаем
    rep['kept_texels'] = int(keep.sum())
    if not rem.any():
        return a.copy(), rep
    band = rem & (distance_transform_edt(rem) <= passes)
    out, reached = fill_uncovered(a, known0, passes, kernel)
    rep['band_texels'] = int(band.sum())
    rep['band_unfilled'] = int((band & ~reached).sum())
    rep['changed_texels'] = int(np.any(out != a, axis=-1).sum())
    rep['keep_changed'] = int(np.any(out != a, axis=-1)[keep].sum())
    rep['unreached_pct'] = round(100.0 * float((rem & ~reached).sum()) / n_unc, 2)
    rim = known0 & (distance_transform_edt(known0) <= passes)
    if band.any() and rim.any():
        tcm = _tc()
        lab_a = tcm.rgb2lab(a[..., :3].reshape(-1, 3).astype(np.uint8)).reshape(a.shape[0], a.shape[1], 3)
        lab_b = tcm.rgb2lab(out[..., :3].reshape(-1, 3).astype(np.uint8)).reshape(a.shape[0], a.shape[1], 3)
        d0, d1 = _band_vs_rim(lab_a, lab_b, band, rim)
        rep.update(band_vs_rim_dE_before=round(d0, 2), band_vs_rim_dE_after=round(d1, 2))
    return out, rep


def pad_geoms(geoms: list, texs: list, cfg: dict | None = None) -> tuple[list, dict]:
    """Все геометрии этапа 07: (новые текстуры, сводный отчёт). Геометрия — dict с `UV`, `F` (как у tex_fill)."""
    c = cfg or rules()
    outs, per = [], []
    for g, t in zip(geoms, texs):
        t = np.asarray(t)
        cov = coverage_from_uv(g['UV'], g['F'], int(t.shape[0]))
        o, r = pad_texture(t, cov, c)
        outs.append(o)
        per.append(r)
    return outs, summary(per, c)


def summary(per: list[dict], cfg: dict) -> dict:
    """Сводка по текстурам: худшее значение каждой мерки (в проверку этапа) + список по геометриям."""
    def worst(k):
        v = [r[k] for r in per if r.get(k) is not None]
        return round(float(max(v)), 2) if v else None
    wts = [(r['uncovered_pct'] * r['size'] ** 2, r) for r in per if r.get('uncovered_mean_rgb_before')]
    tot = sum(w for w, _ in wts)
    mean_unc = [round(sum(w * r['uncovered_mean_rgb_before'][c] for w, r in wts) / tot, 1) for c in range(3)] if tot > 0 else None       # средний цвет непокрытых ДО заливки (вес — число текселей)
    mean_cov = [round(sum(w * r['covered_mean_rgb'][c] for w, r in wts) / tot, 1) for c in range(3)] if tot > 0 else None
    return {'passes': int(cfg['passes']), 'kernel': int(cfg['kernel']), 'keep_px': int(cfg['keep_px']), 'kept_texels': int(sum(r['kept_texels'] for r in per)), 'keep_changed': int(sum(r['keep_changed'] for r in per)), 'uncovered_pct': worst('uncovered_pct'), 'uncovered_mean_rgb_before': mean_unc, 'covered_mean_rgb': mean_cov, 'band_unfilled': int(sum(r['band_unfilled'] for r in per)),
            'band_texels': int(sum(r['band_texels'] for r in per)), 'changed_texels': int(sum(r['changed_texels'] for r in per)), 'unreached_pct': worst('unreached_pct'),
            'band_vs_rim_dE_before': worst('band_vs_rim_dE_before'), 'band_vs_rim_dE_after': worst('band_vs_rim_dE_after'), 'geoms': per}


def check_metrics(rep: dict, cfg: dict | None = None) -> dict:
    """Мерки для check.json этапа: `texel_uncovered_pct` (справочно: доля непокрытых, с средним цветом до заливки), `texel_band_unfilled` (≤ 0 — залито всё в пределах passes px: судит этап),
    `texel_band_vs_rim_dE` (справочно: ΔE76 среднего цвета полосы до среднего цвета кромки острова, до → после; порог `band_rim_dE_max` — гипотеза, этап не судит)."""
    c = cfg or rules()
    return {'texel_uncovered_pct': {'value': rep.get('uncovered_pct'), 'mean_rgb_before': rep.get('uncovered_mean_rgb_before'), 'covered_mean_rgb': rep.get('covered_mean_rgb'), 'ok': None},
            'texel_band_unfilled': {'value': rep['band_unfilled'], 'threshold': 0, 'op': '<=', 'ok': rep['band_unfilled'] <= 0},
            'texel_keep_changed': {'value': rep['keep_changed'], 'threshold': 0, 'op': '<=', 'ok': rep['keep_changed'] <= 0, 'note': f'зона отступа ({rep.get("keep_px")} px, уже залита этапом) не тронута'},
            'texel_band_vs_rim_dE': {'value': rep.get('band_vs_rim_dE_after'), 'before': rep.get('band_vs_rim_dE_before'), 'hypothesis_threshold': c['band_rim_dE_max'], 'ok': None}}
