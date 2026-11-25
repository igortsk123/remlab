#!/usr/bin/env python3
"""Ярлык «форма не та» этапа 04 (T-20261125-78/2; отчёт T-78: ~/remlab-logs/t2478-1125/report.md). ТОЛЬКО ОТЧЁТ: passed 04 и камеру не меняет, форму на перегон не отправляет.

Зачем. Стык «фронт|бок» (junction.front_edge) большой по трём разным причинам, и лечатся они по-разному:
  форма         — боковина формы толще бока на фото и ложится на фасад фото (комод 13224: бок берёт 64–69 % пикселей из фасада) → форму на перегон;
  скругление    — бок формы на своём месте, а фасад формы заходит на скруглённый угол фото (18370313…): перегон формы не лечит;
  ложная_кромка — цель стыка взята по КОНТУРУ там, где у формы видна боковина: кромку бока на фото мерка не нашла (тёмная боковина на сером, 321183…) — стык и доля недостоверны;
  ок            — иначе (в т.ч. «не измерено» = label None, не «ок»).

Данные берутся из готовых выходов 04 (без рендера): нормали пикселей `stages/render_view0/normal_cam.png` (камера → мир через cam_basis) делят пиксели формы на фасад (нормаль по оси глубины)
и боковину (по оси ширины, СНАРУЖИ углов фасада формы); пиксель кадра ↔ пиксель фото по canvas из pose.json. Область фасада на фото — между целевыми кромками стыка (front_edge.target_px).

  side_from_front  — доля пикселей боковины формы, чьи фото-px лежат в области фасада фото, %
  front_on_side    — доля пикселей фасада формы на боку фото (вне области фасада фото), %
  gap_pct          — стык (front_edge.gap_px) в % ширины товара на фото (front_edge.width_px)
Пороги — только в tools/scout/rules/camera-check.json → form_verdict (флаг enabled=false по умолчанию: блок в check.json не пишется, файл побайтно как раньше)."""
from __future__ import annotations

import os

import numpy as np

DEFAULTS = {'enabled': False, 'gap_pct_min': 2.0, 'form_side_front_min': 30.0, 'round_side_front_max': 10.0, 'false_edge_side_px_min': 8.0,
            'side_normal_min': 0.7, 'strip_margin_px': 1.0}


def rules(R: dict | None = None) -> dict:
    return {**DEFAULTS, **(R or {})}


def classify(gap_pct, side_front, kinds: dict, side_w: dict, R: dict | None = None) -> dict:
    """Ярлык по числам. kinds/side_w — {'l','r'}: откуда цель стыка ('кромка'|'контур') и ширина боковины формы на стороне, px фото.
    Порядок: ложная_кромка (числа недостоверны) → форма → скругление → ок; серая зона (gap_pct выше порога, side_from_front между порогами или боковины нет) — ок с uncertain=True."""
    p = rules(R)
    why = []
    for s in ('l', 'r'):
        if str(kinds.get(s, '')).startswith('контур') and float(side_w.get(s) or 0.0) >= p['false_edge_side_px_min']:
            why.append('сторона %s: цель стыка — контур, а боковина формы %.0f px ≥ %s' % (s, side_w[s], p['false_edge_side_px_min']))
    if why:
        return {'label': 'ложная_кромка', 'uncertain': False, 'why': '; '.join(why)}
    over = gap_pct is not None and gap_pct > p['gap_pct_min']
    if over and side_front is not None and side_front >= p['form_side_front_min']:
        return {'label': 'форма', 'uncertain': False, 'why': 'стык %.2f %% > %s %% и бок из фасада %.1f %% ≥ %s %%' % (gap_pct, p['gap_pct_min'], side_front, p['form_side_front_min'])}
    if over and side_front is not None and side_front < p['round_side_front_max']:
        return {'label': 'скругление', 'uncertain': False, 'why': 'стык %.2f %% > %s %% и бок из фасада %.1f %% < %s %%' % (gap_pct, p['gap_pct_min'], side_front, p['round_side_front_max'])}
    if over:
        return {'label': 'ок', 'uncertain': True, 'why': 'стык %.2f %% > %s %%, но бок из фасада %s — между порогами или боковины нет: не отнесено' % (gap_pct, p['gap_pct_min'], 'нет' if side_front is None else '%.1f %%' % side_front)}
    return {'label': 'ок', 'uncertain': False, 'why': 'стык %s %% ≤ %s %%' % ('—' if gap_pct is None else '%.2f' % gap_pct, p['gap_pct_min'])}


def world_normals(nrm_rgb: np.ndarray, cam: dict) -> tuple:
    """normal_cam.png (RGB = n·0.5+0.5 в осях камеры: right, up, к камере) → маска предмета и мировые нормали (кадр n×n×3). Обратно к pose_fit.pixel_attrs: ncam = [n·right, n·up, −n·fwd]."""
    import pose_fit as PF
    _C, right, up, fwd = PF.cam_basis(cam['az'], cam['el'], cam['d'], PF.cam_tilt(cam))
    mask = nrm_rgb.reshape(nrm_rgb.shape[0], nrm_rgb.shape[1], -1)[..., :3].max(axis=2) > 0
    nc = nrm_rgb[..., :3].astype(np.float64) / 255.0 * 2.0 - 1.0
    W = nc[..., 0:1] * right + nc[..., 1:2] * up - nc[..., 2:3] * fwd
    return mask, W


def side_stats(nrm_rgb: np.ndarray, box: dict, cam: dict, cv: dict, fe: dict, R: dict | None = None) -> dict:
    """Доли по кадру нормалей и front_edge (fe.measured=True): side_from_front, front_on_side, ширина боковины слева/справа (px фото)."""
    p = rules(R)
    mask, W = world_normals(nrm_rgb, cam)
    n = nrm_rgb.shape[0]
    da, wa = box['depth_axis'], box['width_axis']
    fr = mask & (np.abs(W[..., da]) >= p['side_normal_min'])
    sd = mask & (np.abs(W[..., wa]) >= p['side_normal_min']) & ~fr
    fl, frr = float(fe['form_px']['l']), float(fe['form_px']['r'])
    tl, tr = float(fe['target_px']['l']), float(fe['target_px']['r'])

    def xph(ix):
        return cv['x0'] + (ix + 0.5) * cv['side'] / n
    ys, xs = np.nonzero(sd)
    xp = xph(xs)
    strip = (xp < fl - p['strip_margin_px']) | (xp > frr + p['strip_margin_px'])                 # боковина — снаружи фасада формы (внутри: ножки, фаски, внутренние стенки)
    xp = xp[strip]
    _y, xf = np.nonzero(fr)
    xpf = xph(xf)
    wl = float(fl - xp[xp < fl].min()) if (xp < fl).any() else 0.0
    wr = float(xp[xp > frr].max() - frr) if (xp > frr).any() else 0.0
    return {'side_from_front': None if len(xp) == 0 else round(100.0 * float(((xp >= tl) & (xp <= tr)).sum()) / len(xp), 2),
            'front_on_side': None if len(xpf) == 0 else round(100.0 * float(((xpf < tl) | (xpf > tr)).sum()) / len(xpf), 2),
            'side_px': int(len(xp)), 'side_w_px': {'l': round(wl, 1), 'r': round(wr, 1)}}


def from_run(run: str, pose: dict, fe: dict, cv: dict, JN, R: dict | None = None) -> dict:
    """Блок form_verdict для check.json 04 по готовым выходам (`run`/stages/render_view0/normal_cam.png). Не измерено → label None с причиной; сбой не роняет этап 4."""
    p = rules(R)
    try:
        if not fe.get('measured'):
            return {'measured': False, 'label': None, 'reason': 'стык не измерен: %s' % (fe.get('reason') or '—')}
        from PIL import Image
        npath = os.path.join(run, 'stages', 'render_view0', 'normal_cam.png')
        if not os.path.isfile(npath):
            return {'measured': False, 'label': None, 'reason': 'нет stages/render_view0/normal_cam.png'}
        fb = pose.get('form_box')
        if not fb:
            return {'measured': False, 'label': None, 'reason': 'нет габарита формы в pose.json (form_box)'}
        box = JN.box_geometry(fb['lo'], fb['hi'])
        st = side_stats(np.asarray(Image.open(npath).convert('RGB')), box, pose['camera'], cv, fe, p)
        gap_pct = round(100.0 * float(fe['gap_px']) / float(fe['width_px']), 2)
        res = classify(gap_pct, st['side_from_front'], fe['kind'], st['side_w_px'], p)
        return {'measured': True, **res, 'gap_pct': gap_pct, 'side_from_front': st['side_from_front'], 'front_on_side': st['front_on_side'], 'edge_kind': dict(fe['kind']),
                'side_w_px': st['side_w_px'], 'side_px': st['side_px'], 'thresholds': {k: p[k] for k in DEFAULTS if k != 'enabled'}}
    except Exception as e:  # noqa: BLE001 — мерка не роняет этап 4
        return {'measured': False, 'label': None, 'reason': f'сбой мерки: {type(e).__name__}: {str(e)[:100]}'}
