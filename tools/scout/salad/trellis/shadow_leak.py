"""T-20261124-15 (Д1 №8; журнал брака #88/#141/#179; правило R-SHADOW-LEAK): ТЕНЬ ЩЕЛИ, ЗАПЕКШАЯСЯ В «ИЗВЕСТНОЕ» на этапе 06. Чистые функции на массивах (numpy, scipy, cv2), без этапов.

Дефект: на фото мягкой мебели в щелях между подушками и в швах — тёмная узкая полоса (контактная тень). 06 переносит её в текстуру как цвет ткани; в 3D-показе свет и тень щелей дорисует сам рендер,
поэтому тень в краске ДВОЙНАЯ; а 07 берёт тон части вместе с тёмным краем (докрашенное в щелях темнее ~2×). Замер холостого прогона (#141): тёмных в щели в ~6× больше, чем вне.

ОБЩИЙ ПРИЗНАК (не по товару): пиксель кадра камеры 04 — «утечка тени», если одновременно
  1. он тёмный относительно локальной ткани (медиана окна ref_win: ниже на dark_dL L* или ниже dark_ratio × медианы) и входит в ТОНКУЮ тёмную полосу (шире thin_px px не считается — это тёмная ткань, не щель);
  2. по одной из 4 ориентаций ткань по ОБЕ стороны полосы (на расстоянии side_k px) светлее него не меньше чем на side_dL L*;
  3. по той же ориентации форма в этом месте — СИММЕТРИЧНАЯ ложбина глубины: обе стороны ближе к камере не меньше чем на trough_px px предмета, а друг от друга отличаются не больше trough_sym_px
     (ступень заслонения — не щель; тёмный рисунок на гладкой поверхности — не щель);
  4. он глубже edge_px от силуэта фото (у края — фон и ореол, их ведёт edge_bg).
ЛЕЧЕНИЕ (только если включено правилом): цвет утечки плавно поднимается к цвету СПОКОЙНОЙ ткани вокруг (нормированная гауссова свёртка по пикселям, не тёмным и не из полосы), светлота — не больше чем на
max_lift_L, цветность — на ту же долю; кромка полосы размыта feather_px (без «бусин»). Пиксели вне полосы НЕ меняются ни на бит. Тип: только семьи из `families` (паспорт типа); прочие — воздержание, prgb тот же объект.
МЕРКА (всегда, даже при выключенном правиле — «холостой режим»): избыток тёмного в щели = доля тёмных пикселей в геометрической щели (любая ложбина глубины, без условия цвета) минус доля тёмных вне
её (на расстоянии ≥ outside_gap_px), п.п.; до и «если применить». Числа порогов — rules/tex-visible.json `shadow_leak`, ID товаров в коде нет.
"""
from __future__ import annotations

import json
import os

import numpy as np

SCOUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DEFAULTS = {'enabled': False, 'families': ['мягкое'], 'dark_dL': 15.0, 'dark_ratio': 0.6, 'thin_px': 5, 'ref_win': 31, 'side_k': [4, 6], 'side_dL': 10.0,
            'trough_px': 1.0, 'trough_sym_px': 2.0, 'edge_px': 25, 'lift_sigma': 4.0, 'feather_px': 1.0, 'max_lift_L': 25.0, 'grow_px': 1, 'min_zone_px': 50, 'outside_gap_px': 3,
            'depth_median': 3}
DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))                     # (dy, dx): горизонталь, вертикаль, две диагонали


def load_rules(path: str | None = None) -> dict:
    """rules/tex-visible.json → `shadow_leak` (нет файла/ключа — DEFAULTS, правило выключено)."""
    r = dict(DEFAULTS)
    try:
        r.update(json.load(open(path or os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8')).get('shadow_leak') or {})
    except (OSError, ValueError):
        pass
    return r


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """b[y, x] = a[y+dy, x+dx], за краем кадра — ближайший пиксель."""
    h, w = a.shape[:2]
    ys = np.clip(np.arange(h) + dy, 0, h - 1)
    xs = np.clip(np.arange(w) + dx, 0, w - 1)
    return a[ys][:, xs]


def _lum8(rgb: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(np.ascontiguousarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2LAB)[..., 0]


def _ref(L8: np.ndarray, valid: np.ndarray, win: int) -> np.ndarray:
    """Медиана L окна win: пиксели вне valid заменены ближайшим допустимым (как crease_mask.reference_l8)."""
    import cv2
    from scipy.ndimage import distance_transform_edt
    if not valid.any():
        return L8.copy()
    _d, (iy, ix) = distance_transform_edt(~valid, return_indices=True)
    return cv2.medianBlur(np.ascontiguousarray(L8[iy, ix]), int(win) | 1)


def _dark(L8: np.ndarray, ref: np.ndarray, r: dict) -> np.ndarray:
    d = ref.astype(np.float32) - L8.astype(np.float32)
    return (d > float(r['dark_dL']) * 2.55) | (L8.astype(np.float32) < float(r['dark_ratio']) * ref.astype(np.float32))


def _thin(dark: np.ndarray, thin_px: int) -> np.ndarray:
    from scipy.ndimage import binary_opening
    return dark & ~binary_opening(dark, structure=np.ones((int(thin_px) + 1, int(thin_px) + 1), bool))


def depth_trough(st: dict, r: dict) -> list:
    """По каждой ориентации: bool-карта «симметричная ложбина глубины» (обе стороны на side_k px ближе не меньше trough_px px предмета, стороны различаются не больше trough_sym_px).
    Соседи обязаны быть формой (mask). Глубина — медиана 3×3 внутри формы (на рёбрах треугольников в карте пятна-выбросы)."""
    from scipy.ndimage import median_filter
    mask = st['mask'] & (st['ids'] >= 0)
    d = np.asarray(st['depth'], np.float32)
    dm = int(r['depth_median'])
    if dm > 1:
        d = median_filter(np.where(mask, d, np.float32(np.nan)).astype(np.float32), size=dm, mode='nearest')
    pl = max(float(st.get('px_len') or 0.0), 1e-6)
    ks = [int(k) for k in r['side_k']]
    out = []
    for dy, dx in DIRS:
        da = np.mean([_shift(d, dy * k, dx * k) for k in ks], axis=0)
        db = np.mean([_shift(d, -dy * k, -dx * k) for k in ks], axis=0)
        ma = np.all([_shift(mask, dy * k, dx * k) for k in ks], axis=0)
        mb = np.all([_shift(mask, -dy * k, -dx * k) for k in ks], axis=0)
        with np.errstate(invalid='ignore'):
            near_a = (d - da) >= float(r['trough_px']) * pl                  # центр ДАЛЬШЕ боковой точки (глубина — расстояние до камеры): боковые ближе → ложбина
            near_b = (d - db) >= float(r['trough_px']) * pl
            sym = np.abs(da - db) <= float(r['trough_sym_px']) * pl
        out.append(mask & ma & mb & near_a & near_b & sym & np.isfinite(d))
    return out


def detect(prgb: np.ndarray, pmask: np.ndarray, st: dict, r: dict | None = None) -> dict:
    """→ {leak: bool кадра (утечка тени), zone: bool кадра (геометрическая щель, любой тон), dark: bool (тёмные), stats}."""
    from scipy.ndimage import binary_dilation, distance_transform_edt
    r = r or load_rules()
    valid = st['mask'] & pmask
    L8 = _lum8(prgb)
    ref = _ref(L8, valid, int(r['ref_win']))
    dark = _dark(L8, ref, r) & valid
    thin = _thin(dark, int(r['thin_px']))
    ks = [int(k) for k in r['side_k']]
    troughs = depth_trough(st, r)
    Lf = L8.astype(np.float32)
    lighter = np.zeros(valid.shape, bool)
    zone = np.zeros(valid.shape, bool)
    for (dy, dx), tr in zip(DIRS, troughs):
        la = np.mean([_shift(Lf, dy * k, dx * k) for k in ks], axis=0)
        lb = np.mean([_shift(Lf, -dy * k, -dx * k) for k in ks], axis=0)
        both = (la - Lf >= float(r['side_dL']) * 2.55) & (lb - Lf >= float(r['side_dL']) * 2.55)
        lighter |= both & tr
        zone |= tr
    inner = distance_transform_edt(pmask) >= float(r['edge_px'])
    leak = thin & lighter & inner & valid
    zone = zone & valid & inner
    zone = binary_dilation(zone, iterations=max(int(r['grow_px']), 0)) & valid if int(r['grow_px']) > 0 else zone
    return {'leak': leak, 'zone': zone, 'dark': dark, 'L8': L8, 'ref': ref,
            'stats': {'leak_px': int(leak.sum()), 'zone_px': int(zone.sum()), 'dark_px': int(dark.sum()), 'thin_dark_px': int(thin.sum()), 'valid_px': int(valid.sum())}}


def excess_pp(dark: np.ndarray, zone: np.ndarray, valid: np.ndarray, r: dict) -> dict:
    """Избыток тёмного в щели: % тёмных в зоне − % тёмных вне зоны (дальше outside_gap_px от неё), п.п. Зона < min_zone_px — None."""
    from scipy.ndimage import binary_dilation
    nz = int(zone.sum())
    if nz < int(r['min_zone_px']):
        return {'excess_pp': None, 'zone_px': nz, 'dark_in_zone_pct': None, 'dark_out_pct': None}
    out = valid & ~binary_dilation(zone, iterations=max(int(r['outside_gap_px']), 1))
    no = int(out.sum())
    pin = 100.0 * float((dark & zone).sum()) / nz
    pout = 100.0 * float((dark & out).sum()) / max(no, 1)
    return {'excess_pp': round(pin - pout, 3), 'zone_px': nz, 'dark_in_zone_pct': round(pin, 3), 'dark_out_pct': round(pout, 3)}


def lift(prgb: np.ndarray, pmask: np.ndarray, st: dict, det: dict, r: dict) -> tuple:
    """Поднять цвет утечки к цвету спокойной ткани вокруг. → (новый prgb uint8, bool «пиксель изменён»). Пиксели с весом < 0,02 не трогаются вовсе (побайтно те же)."""
    import cv2
    from scipy.ndimage import binary_dilation, gaussian_filter
    leak = det['leak']
    if not leak.any():
        return prgb, np.zeros(leak.shape, bool)
    valid = st['mask'] & pmask
    band = binary_dilation(leak, iterations=max(int(r['grow_px']), 0) + 1)
    calm = valid & ~det['dark'] & ~band
    lab = cv2.cvtColor(np.ascontiguousarray(prgb, dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    sg = float(r['lift_sigma'])
    cw = gaussian_filter(calm.astype(np.float32), sg, mode='nearest')
    tgt = np.stack([gaussian_filter(lab[..., c] * calm, sg, mode='nearest') for c in range(3)], 2) / np.maximum(cw, 1e-3)[..., None]
    w = np.clip(gaussian_filter(binary_dilation(leak, iterations=max(int(r['grow_px']), 0)).astype(np.float32), float(r['feather_px']), mode='nearest') * 1.0, 0.0, 1.0)
    w = np.where(cw > 0.02, w, 0.0) * valid
    dl = np.clip(tgt[..., 0] - lab[..., 0], 0.0, float(r['max_lift_L']) * 2.55)      # только поднимаем светлоту; тёмнее соседей не делаем
    frac = np.where(tgt[..., 0] - lab[..., 0] > 1e-3, dl / np.maximum(tgt[..., 0] - lab[..., 0], 1e-3), 0.0)
    new = lab.copy()
    new[..., 0] = lab[..., 0] + w * dl
    for c in (1, 2):
        new[..., c] = lab[..., c] + w * frac * (tgt[..., c] - lab[..., c])
    rgb = cv2.cvtColor(np.clip(new + 0.5, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    changed = w >= 0.02
    out = np.ascontiguousarray(prgb).copy()
    out[changed] = rgb[changed]
    return out, changed


def family_allowed(family: str | None, r: dict) -> bool:
    return bool(family) and family in (r.get('families') or [])


def run(prgb: np.ndarray, pmask: np.ndarray, st: dict, family: str | None, r: dict | None = None, enabled: bool | None = None) -> dict:
    """Точка входа 06. → {prgb (тот же объект, если не менялся), info (в check.json `shadow_leak`), maps|None}.
    Семья не из `families` → воздержание. Правило выключено (`enabled` false) → только мерка «если применить», prgb не тронут (побайтно)."""
    r = r or load_rules()
    on = bool(r['enabled']) if enabled is None else bool(enabled)
    info = {'enabled': on, 'family': family, 'applied': False}
    if not family_allowed(family, r):
        info['abstain'] = 'family'
        return {'prgb': prgb, 'info': info, 'maps': None}
    det = detect(prgb, pmask, st, r)
    valid = st['mask'] & pmask
    before = excess_pp(det['dark'], det['zone'], valid, r)
    new, changed = lift(prgb, pmask, st, det, r)
    L8n = _lum8(new)
    darkn = _dark(L8n, det['ref'], r) & valid
    after = excess_pp(darkn, det['zone'], valid, r)
    from scipy.ndimage import binary_dilation
    outside_changed = int((changed & ~binary_dilation(det['zone'] | det['leak'], iterations=max(int(r['grow_px']), 0) + 4)).sum())   # изменённое дальше feather от щели: должно быть 0
    info.update(det['stats'])
    info.update({'excess_pp_before': before['excess_pp'], 'excess_pp_if_applied': after['excess_pp'], 'dark_in_zone_pct': before['dark_in_zone_pct'], 'dark_out_pct': before['dark_out_pct'],
                 'dark_in_zone_pct_if_applied': after['dark_in_zone_pct'], 'changed_px': int(changed.sum()), 'applied': bool(on and changed.any())})
    maps = {'before': prgb, 'after': new, 'leak': det['leak'], 'zone': det['zone']} if det['stats']['leak_px'] else None
    return {'prgb': new if (on and changed.any()) else prgb, 'info': info, 'maps': maps, 'outside_changed_px': outside_changed}
