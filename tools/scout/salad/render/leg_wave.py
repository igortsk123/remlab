"""Мерка «волнистый контур ножки» (T-20261124-57, П1.160; паспорт `plans/mesh-type-rules-01.md`, класс 1б, 21.11: Сакура, передняя ножка, вход out30-v3 — владелец обвёл).

Дефект: контур тонкой вертикальной детали (ножки) на силуэте формы идёт ДЛИННОЙ волной (период — доля длины ножки), а не прямо/плавной дугой; мелкую рябь (шаг в несколько граней) Таубин×3 гасит, длинную — нет.
Мерка по силуэту формы (тот же, что у `thin_checks`: `sil_at` на азимуте фото), без фото: ножки = вертикальные компоненты силуэта ниже корпуса. Для каждой ножки и каждого её края (левого/правого) —
профиль x(y) по строкам, без `leg_trim` длины у стыка с корпусом и у пола; вычитается плавная кривая (многочлен степени `lw_deg`, т.е. прямая или одна дуга законны); остаток чуть сглаживается (`lw_smooth` строк);
волна = число «горбов» остатка (пики и впадины с проминенцией ≥ `lw_prom` × толщины ножки). Значение — наибольшая по ножкам амплитуда волны ÷ толщина ножки среди ножек с ≥ `lw_min_ext` горбами
(0 — таких нет). Сработало бы при значении ≥ `lw_amp`. Пороги — `rules/form-checks.json`; ID товаров в коде нет, тип привязывает только то, что у силуэта есть тонкие вертикальные ножки.

Нужны numpy, scipy. Вход — маска силуэта (bool, строки сверху вниз).
"""
from __future__ import annotations

import numpy as np


def body_bottom_row(mask: np.ndarray, cover_min: float) -> int | None:
    """Последняя строка корпуса: ширина силуэта ≥ `cover_min` × максимальной (ниже — ножки). None — маска пуста."""
    w = mask.sum(axis=1).astype(np.float64)
    if w.max() <= 0:
        return None
    return int(np.nonzero(w >= cover_min * w.max())[0][-1])


def leg_components(mask: np.ndarray, p: dict) -> tuple[list[dict], int | None]:
    """Ножки: компоненты силуэта ниже корпуса, высотой ≥ `lw_min_h` × высоты силуэта и вытянутые (высота ÷ медианная ширина ≥ `lw_min_aspect`). → ([{y0, y1, x0, x1, w, lab_mask}], строка корпуса)."""
    from scipy import ndimage
    bb = body_bottom_row(mask, float(p['lw_body_cover']))
    if bb is None:
        return [], None
    H = mask.shape[0]
    below = mask.copy()
    below[:bb + 1] = False
    lab, n = ndimage.label(below, structure=np.ones((3, 3), bool))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        m = lab[sl] == i
        rows = m.sum(axis=1)
        rows = rows[rows > 0]
        h = int(m.any(axis=1).sum())
        w = float(np.median(rows))
        if h < float(p['lw_min_h']) * H or h / max(w, 1.0) < float(p['lw_min_aspect']):
            continue
        out.append({'y0': sl[0].start, 'y1': sl[0].stop, 'x0': sl[1].start, 'x1': sl[1].stop, 'w': w, 'mask': m})
    out.sort(key=lambda c: c['x0'])
    return out, bb


def edge_wave(prof: np.ndarray, w: float, p: dict) -> dict:
    """prof — x(y) одного края по строкам; w — толщина ножки, px. → {amp: размах волны ÷ w, n_ext: число горбов остатка с проминенцией ≥ lw_prom·w}."""
    from scipy.signal import find_peaks
    y = np.arange(len(prof), dtype=np.float64)
    k = int(p['lw_smooth'])
    if k > 1:
        pad = np.pad(prof.astype(np.float64), (k // 2, k // 2), mode='edge')
        prof = np.convolve(pad, np.ones(k) / k, mode='valid')
    res = prof - np.polyval(np.polyfit(y, prof, int(p['lw_deg'])), y)
    prom = float(p['lw_prom']) * max(w, 1.0)
    up, _ = find_peaks(res, prominence=prom)
    dn, _ = find_peaks(-res, prominence=prom)
    ext = sorted(np.concatenate([up, dn]).tolist())
    amp = float((np.percentile(res, 95) - np.percentile(res, 5)) / 2.0 / max(w, 1.0))
    return {'amp': amp, 'n_ext': len(ext)}


def leg_wave_stats(mask: np.ndarray, p: dict) -> dict:
    """{'status': 'ok'|'na', 'why', 'value', 'n_legs', 'legs': [{x, w, amp, n_ext, wavy}]}. `na` — ножек (вертикальных компонентов ниже корпуса) нет."""
    comps, bb = leg_components(mask, p)
    if not comps:
        return {'status': 'na', 'why': 'ножек (вытянутых компонентов ниже корпуса) нет', 'n_legs': 0, 'legs': []}
    legs, value = [], 0.0
    for c in comps:
        m = c['mask']
        rows = np.nonzero(m.any(axis=1))[0]
        t = int(round(float(p['lw_trim']) * len(rows)))
        rows = rows[t:len(rows) - t] if len(rows) > 2 * t + 8 else rows
        if len(rows) < int(p['lw_min_rows']):
            continue
        xl = np.array([np.nonzero(m[r])[0].min() for r in rows], dtype=np.float64)
        xr = np.array([np.nonzero(m[r])[0].max() for r in rows], dtype=np.float64)
        ew = [edge_wave(xl, c['w'], p), edge_wave(xr, c['w'], p)]
        amp = max(e['amp'] for e in ew)
        n_ext = max(e['n_ext'] for e in ew)
        wavy = bool(n_ext >= int(p['lw_min_ext']))
        legs.append({'x': round((c['x0'] + c['x1']) / 2 / mask.shape[1], 3), 'w': round(c['w'], 1), 'rows': int(len(rows)), 'amp': round(amp, 3), 'n_ext': int(n_ext), 'wavy': wavy})
        if wavy:
            value = max(value, amp)
    if not legs:
        return {'status': 'na', 'why': 'ножки слишком короткие для профиля', 'n_legs': 0, 'legs': []}
    return {'status': 'ok', 'why': '', 'value': round(value, 3), 'n_legs': len(legs), 'legs': legs}
