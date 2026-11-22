"""Сверка НОЖЕК формы с фото по маскам одной позы (T-191/3): одна реализация для этапа 04 (check.json → extra.legs_match), этапа 06 (граница «корпус / ножки», доверенные ножки) и Ш0 (form_checks).

Зачем. Корпус формы ложится по фото (IoU силуэта хорош), а низ меша (положение, число, высота ножек) часто нет: перенос цвета фото на ножку, стоящую мимо, даёт тёмное/светлое пятно мимо ножки.
Мерка по готовым выходам 14 форм с раздельными ножками (T-191/2): ошибка ножки ÷ её толщина — годные ≤ 0,41, брак ≥ 0,71 (нормировка на ширину корпуса или шаг между ножками их НЕ разделяет).

Что считается. Ножки = компоненты связности нижней полосы `band` высоты предмета (по маске фото; у формы — по её маске); мелкие (< `min_rel` площади крупнейшей и < `min_area` px) — шум.
Для каждой пары ножка фото ↔ ножка формы (венгерский алгоритм по расстоянию центров): ошибка = расстояние центров минус общий сдвиг корпуса (боковые края выше полосы), ÷ толщина ножки фото (медиана ширины по строкам).
Ножка годна: ошибка ÷ толщина ≤ `err_over_w_max`. Форма «ножки не годны» (`mismatch`): число ножек фото/формы разное, ИЛИ пол (низ формы против низа фото) вне `floor_dy_pct_max` % высоты, ИЛИ хотя бы одна ножка не годна.
Высота ножек (отношение) только пишется. Меньше двух раздельных ножек на фото — мерка не применима (цоколь, одна широкая ножка): `applicable: false`, `mismatch: false`.
Пороги — `tools/scout/rules/camera-check.json`, блок `legs_match` (единственный источник для 04, 06 и Ш0). Зависимости: numpy, scipy.
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'camera-check.json'))
DEFAULTS = {'band': 0.18, 'min_area': 100, 'min_rel': 0.0, 'err_over_w_max': 0.6, 'floor_dy_pct_max': 2.5, 'body_cover_min': 0.6, 'edge_rows': [0.045, 0.008]}


def load_rules(path: str = RULES_PATH) -> dict:
    """Блок `legs_match` из camera-check.json поверх DEFAULTS (нет файла/блока — значения по умолчанию)."""
    try:
        blk = json.load(open(path, encoding='utf-8')).get('legs_match') or {}
    except (OSError, ValueError):
        blk = {}
    return dict(DEFAULTS, **{k: v for k, v in blk.items() if not k.startswith('_')})


def components(m: np.ndarray, y0: int, y1: int, min_area: int, min_rel: float) -> list[dict]:
    """Компоненты маски в строках [y0, y1): центр, толщина (медиана ширины по строкам), рамка, площадь; шум (< min_area И < min_rel × крупнейшая) отброшен. Слева направо."""
    from scipy import ndimage
    reg = np.zeros(m.shape, bool)
    reg[y0:y1] = m[y0:y1]
    lab, n = ndimage.label(reg, structure=np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if len(ys) < min_area:
            continue
        cnt = np.bincount(ys - ys.min())
        out.append({'cx': float(xs.mean()), 'cy': float(ys.mean()), 'w': float(np.median(cnt[cnt > 0])), 'x0': int(xs.min()), 'x1': int(xs.max()), 'y0': int(ys.min()), 'y1': int(ys.max()), 'area': int(len(ys))})
    if out and min_rel > 0:
        big = max(c['area'] for c in out)
        out = [c for c in out if c['area'] >= min_rel * big]
    return sorted(out, key=lambda d: d['cx'])


def body_bottom_row(mask: np.ndarray, cover_min: float = 0.6) -> int | None:
    """Последняя строка корпуса: где силуэт занимает ≥ cover_min максимальной ширины (ниже — ножки: узкие полосы). None — маска пуста."""
    w = mask.sum(axis=1).astype(np.float64)
    if w.max() <= 0:
        return None
    return int(np.nonzero(w >= cover_min * w.max())[0][-1])


def _edges(m: np.ndarray, bb: int | None, H: int, fr: list) -> tuple:
    """Боковые края КОРПУСА: строки чуть выше нижней кромки корпуса bb (своей маски), чтобы не мерить по ножкам."""
    if bb is None:
        return None, None
    r0, r1 = max(bb - int(fr[0] * H), 0), max(bb - int(fr[1] * H), 1)
    cols = np.nonzero(m[r0:r1].any(axis=0))[0] if r1 > r0 else np.array([])
    return (int(cols.min()), int(cols.max())) if cols.size else (None, None)


def legs_report(S: np.ndarray, pa: np.ndarray, rules: dict | None = None) -> dict:
    """S — маска формы с позы, pa — маска фото в тех же пикселях. Возвращает отчёт (см. шапку модуля); `trusted_boxes` — рамки в кадре ножек ФОРМЫ, прошедших сверку; `cut_row` — первая строка ножек."""
    from scipy.optimize import linear_sum_assignment
    R = dict(load_rules() if rules is None else rules)
    rep: dict = {'applicable': False, 'mismatch': False, 'ok': True, 'why': '', 'legs': [], 'trusted_boxes': [], 'cut_row': None}
    ys, _ = np.nonzero(pa)
    if not len(ys):
        rep['why'] = 'маска фото пуста'
        return rep
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    H = y1 - y0
    ya = y1 - int(H * R['band'])
    cp = components(pa, ya, y1, int(R['min_area']), float(R['min_rel']))
    cs = components(S, ya, y1, int(R['min_area']), float(R['min_rel']))
    rep.update(n_photo=len(cp), n_mesh=len(cs), H=H)
    if len(cp) < 2:
        rep['why'] = f'ножки фото не раздельны ({len(cp)}) — не применима'
        return rep
    rep['applicable'] = True
    bp, bs = body_bottom_row(pa, float(R['body_cover_min'])), body_bottom_row(S, float(R['body_cover_min']))
    rep['cut_row'] = int(min(b for b in (bp, bs) if b is not None) + 1)
    ysS, _ = np.nonzero(S)
    rep['floor_dy_pct'] = round(float((int(ysS.max()) + 1 - y1) / H * 100), 2) if len(ysS) else None
    rep['floor_ok'] = bool(rep['floor_dy_pct'] is not None and abs(rep['floor_dy_pct']) <= R['floor_dy_pct_max'])
    rep['count_ok'] = bool(len(cp) == len(cs))
    (px0, px1), (sx0, sx1) = _edges(pa, bp, H, R['edge_rows']), _edges(S, bs, H, R['edge_rows'])
    shift = ((sx0 - px0) + (sx1 - px1)) / 2.0 if None not in (px0, px1, sx0, sx1) else 0.0
    rep['body_shift_px'] = round(float(shift), 1)
    if cs:
        D = np.array([[np.hypot(a['cx'] - b['cx'], a['cy'] - b['cy']) for b in cs] for a in cp])
        ri, ci = linear_sum_assignment(D)
        for i, c in zip(ri, ci):
            a, b = cp[i], cs[c]
            err = float(np.hypot(b['cx'] - a['cx'] - shift, b['cy'] - a['cy']))
            eow = err / max(a['w'], 1.0)
            leg = {'photo': [round(a['cx'], 1), round(a['cy'], 1)], 'mesh': [round(b['cx'], 1), round(b['cy'], 1)], 'w_px': round(a['w'], 1), 'err_px': round(err, 1), 'err_over_w': round(eow, 3), 'ok': bool(eow <= R['err_over_w_max'])}
            rep['legs'].append(leg)
            if leg['ok']:
                rep['trusted_boxes'].append([b['x0'], b['y0'], b['x1'], b['y1']])
        hr = [(cs[c]['y1'] - cs[c]['y0'] + 1) / max(cp[i]['y1'] - cp[i]['y0'] + 1, 1) for i, c in zip(ri, ci)]
        rep['leg_h_ratio'] = round(float(np.median(hr)), 2)
    if not rep['floor_ok']:                                           # пол сдвинут — по высоте ножки формы стоят мимо и у «годных» по горизонтали: фото не переносим ни на одну
        rep['trusted_boxes'] = []
    rep['err_over_w_max'] = max((l['err_over_w'] for l in rep['legs']), default=None)
    legs_ok = bool(rep['legs']) and all(l['ok'] for l in rep['legs'])
    rep['ok'] = bool(rep['count_ok'] and rep['floor_ok'] and legs_ok)
    rep['mismatch'] = not rep['ok']
    if rep['mismatch']:
        why = []
        if not rep['count_ok']:
            why.append(f'число ножек фото/формы {len(cp)}/{len(cs)}')
        if not rep['floor_ok']:
            why.append(f'пол формы {rep["floor_dy_pct"]:+.1f} % высоты (допуск ±{R["floor_dy_pct_max"]})')
        bad = [l for l in rep['legs'] if not l['ok']]
        if bad:
            why.append(f'ножек не годных {len(bad)} из {len(rep["legs"])} (ошибка/толщина до {max(l["err_over_w"] for l in bad):.2f} > {R["err_over_w_max"]})')
        rep['why'] = '; '.join(why)
    return rep


def compact(rep: dict) -> dict:
    """Короткая запись для check.json (без рамок): применимость, итог, числа и ножки."""
    keep = ('applicable', 'mismatch', 'ok', 'why', 'n_photo', 'n_mesh', 'count_ok', 'floor_dy_pct', 'floor_ok', 'leg_h_ratio', 'body_shift_px', 'err_over_w_max', 'cut_row', 'legs')
    return {k: rep[k] for k in keep if k in rep}
