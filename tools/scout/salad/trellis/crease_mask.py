"""T-194/1, T-194/2 (владелец TG 1658): МЕРКИ «тёмные полосы у изломов формы» для этапов 06/07 + карта уверенности текселя. Текстуру модуль НЕ меняет.

Дефект: на фото вдоль щелей ящиков — тонкая тёмная линия (тень щели); форма лежит против фото со сдвигом 2–6 px, поэтому линия может попасть на гладкую панель фасада (тёмные рваные полосы).
Рычаги «не брать тень щели с фото» и «красить щель по форме» (в кадре и в развёртке) проверены на 10 корпусных (Salad cpu_stage, 22.11) и ВЫРЕЗАНЫ: эффект ≈ 0 (медиана V/A 1,0), окраска щели
хуже (до ×27 по dark_streak_new). Урок: 95–99 % «тёмных полос» старой мерки — дизайн фото (зазоры, ручки), а не брак переноса; мерить надо то, чего НЕТ на фото.
Мерки (пороги — rules/tex-visible.json `crease_shadow`):
  1. полоса изломов — по растру камеры 04: пиксель-излом = сосед с углом нормалей граней > angle_deg (без разрыва глубины); полоса ±k px (k растёт с остатком силуэта 1−IoU), `crease_shadow`;
  2. `dark_streak_share` — доля пикселей полосы (без щели, валидных), где итог темнее медианы панели на dark_streak_dL L*, %;
  3. `dark_streak_new` — то же, но без тёмного, которое есть и на фото через камеру 04 (окрестность photo_dark_grow_px): ИМЕННО это — брак; дизайнерские зазоры не считаются;
  4. `slit_contrast_ratio` — контраст бороздки к панели в итоге / в фото; `frame_confidence` — уверенность фото-пикселя (у излома и блика ниже) для шага сведения швов.
Чистые функции на массивах (numpy, scipy): модуль общий для 06 (tex_visible) и инструмента streak_compare.py (по готовым выходам 06/07), без импорта этапов."""
from __future__ import annotations

import json
import os

import numpy as np

SCOUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DEFAULTS = {'angle_deg': 35.0, 'depth_jump_px': 12.0, 'k_min': 2, 'k_max': 10, 'k_resid': 0.1, 'groove_px': 1, 'ref_win': 31, 'dL_reject': 12.0, 'thin_px': 5, 'min_evidence_px': 20,
            'photo_dark_dL': 15.0, 'photo_dark_grow_px': 3, 'close_px': 8, 'conf_band': 0.6, 'conf_highlight': 0.5, 'highlight_dL': 25.0, 'conf_fill': 0.5, 'dark_streak_dL': 25.0, 'slit_contrast_min': 0.5}


def load_rules(path: str | None = None) -> dict:
    """rules/tex-visible.json → `crease_shadow` (нет файла/ключа — DEFAULTS)."""
    r = dict(DEFAULTS)
    try:
        r.update(json.load(open(path or os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8')).get('crease_shadow') or {})
    except (OSError, ValueError):
        pass
    return r


def face_normals(geoms: list) -> np.ndarray:
    """Единичные нормали граней всех геометрий подряд (индекс = id растра камеры). Вырожденная грань — нулевой вектор."""
    out = []
    for g in geoms:
        V, F = np.asarray(g['V'], np.float64), np.asarray(g['F'], np.int64)
        n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        out.append(np.where(ln > 1e-18, n / np.maximum(ln, 1e-18), 0.0))
    return np.concatenate(out, axis=0)


def crease_pixels(ids: np.ndarray, depth: np.ndarray, mask: np.ndarray, nf: np.ndarray, px_len: float, rules: dict) -> np.ndarray:
    """Пиксели кадра у геометрического излома: соседи (4-связность) в форме, разрыв глубины меньше depth_jump_px·px_len (это не край силуэта/заслонения), угол нормалей граней > angle_deg
    (знак нормали не важен: |cos|)."""
    cmin = float(np.cos(np.radians(float(rules['angle_deg']))))
    lim = max(float(px_len), 1e-6) * float(rules['depth_jump_px'])
    ok = mask & (ids >= 0)
    nfp = nf[np.clip(ids, 0, len(nf) - 1)]
    out = np.zeros(mask.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        h, w = mask.shape[0] - dy, mask.shape[1] - dx
        a, b = (slice(0, h), slice(0, w)), (slice(dy, dy + h), slice(dx, dx + w))
        both = ok[a] & ok[b] & (np.abs(depth[a].astype(np.float64) - depth[b].astype(np.float64)) < lim)
        c = np.abs(np.einsum('ijk,ijk->ij', nfp[a], nfp[b]))
        e = both & (c < cmin) & (ids[a] != ids[b])
        out[a] |= e
        out[b] |= e
    return out


def band_k(px: int, iou: float | None, rules: dict) -> int:
    """Полоса ±k px: k_min + k_resid·(1−IoU)·px (остаток силуэта → сдвиг формы против фото), не больше k_max."""
    res = 0.0 if iou is None else max(0.0, 1.0 - float(iou)) * float(rules['k_resid']) * float(px)
    return int(min(int(rules['k_max']), int(round(int(rules['k_min']) + res))))


def lum8(rgb: np.ndarray) -> np.ndarray:
    """L* в шкале 0–255 (cv2 Lab uint8) — для сравнения яркостей."""
    import cv2
    return cv2.cvtColor(np.ascontiguousarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2LAB)[..., 0]


def reference_l8(L8: np.ndarray, valid: np.ndarray, win: int) -> np.ndarray:
    """Медиана L панели: пиксели вне `valid` (полоса изломов, фон) заполняются ближайшим допустимым, потом медианный фильтр окна win (нечётное)."""
    import cv2
    from scipy.ndimage import distance_transform_edt
    win = int(win) | 1
    if not valid.any():
        return L8.copy()
    _d, (iy, ix) = distance_transform_edt(~valid, return_indices=True)
    return cv2.medianBlur(np.ascontiguousarray(L8[iy, ix]), win)


def _disc(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def _thin(dark: np.ndarray, thin_px: int) -> np.ndarray:
    """Тонкие участки маски: то, что не переживает морфологическое открытие квадратом (thin_px+1): ширина ≤ thin_px."""
    from scipy.ndimage import binary_opening
    return dark & ~binary_opening(dark, structure=np.ones((int(thin_px) + 1, int(thin_px) + 1), bool))


def crease_shadow(prgb: np.ndarray, pmask: np.ndarray, st: dict, geoms: list, rules: dict | None = None) -> dict:
    """ТОЛЬКО ИЗМЕРЕНИЕ (T-194/1, T-194/2): полоса изломов формы в кадре камеры 04 и «щель» — где на фото вдоль излома есть тонкая тёмная линия. Текстуру не меняет (рычаги «не брать тень щели» и
    «красить щель по форме» проверены на 10 корпусных и вырезаны: эффект ≈ 0, окраска вредна). st — камера 04 (`tex_visible.load_stage`), prgb/pmask — фото в кадре камеры.
    → {groove (bool кадра: излом ±groove_px при тёмной линии на фото), slit_rgb|None, band (bool), crease (bool), stats}."""
    from scipy.ndimage import binary_closing, binary_dilation, distance_transform_edt, label
    r = rules or load_rules()
    mask = st['mask']
    z = np.zeros(mask.shape, bool)
    empty = {'groove': z, 'slit_rgb': None, 'band': z, 'crease': z,
             'stats': {'crease_px': 0, 'band_px': 0, 'k': 0, 'thin_dark_px': 0, 'groove_px': 0, 'evidence_components': 0, 'slit_rgb': None}}
    nf = face_normals(geoms)
    crease = crease_pixels(st['ids'], st['depth'], mask, nf, st.get('px_len') or 0.0, r)
    if not crease.any():
        return empty
    k = band_k(int(st['px']), st.get('iou_frame'), r)
    rc = int(r['close_px'])                                            # излом меша на растре идёт пунктиром (мелкие грани, шов формы): замыкаем промежутки до 2·close_px — линия щели на фото непрерывная
    cl = binary_closing(np.pad(crease, rc), structure=_disc(rc))[rc:-rc, rc:-rc] if rc > 0 else crease      # с запасом по краям кадра: closing на границе иначе съедает излом
    band = binary_dilation(cl, iterations=max(k, 1)) & mask
    L8 = lum8(prgb)
    ref = reference_l8(L8, mask & pmask & ~band, int(r['ref_win']))
    dark = band & pmask & ((ref.astype(np.int16) - L8.astype(np.int16)) > float(r['dL_reject']) * 2.55)
    thin = _thin(dark, int(r['thin_px']))
    on_groove = crease | (distance_transform_edt(~crease) <= float(r['groove_px']))
    lab_b, n_b = label(band)
    ev_ok = np.zeros(n_b + 1, bool)
    if n_b:
        ev_ok = np.bincount(lab_b[thin], minlength=n_b + 1) >= int(r['min_evidence_px'])
        ev_ok[0] = False
    evidence = ev_ok[lab_b]                                            # полосы, где на фото есть тёмная линия
    slit_rgb = np.median(prgb[thin].astype(np.float64), axis=0) if int(thin.sum()) >= int(r['min_evidence_px']) else None
    groove = on_groove & band & evidence & mask if slit_rgb is not None else z
    stats = {'crease_px': int(crease.sum()), 'band_px': int(band.sum()), 'k': int(k), 'thin_dark_px': int(thin.sum()), 'groove_px': int(groove.sum()), 'evidence_components': int(ev_ok.sum()),
             'slit_rgb': None if slit_rgb is None else [round(float(x), 1) for x in slit_rgb]}
    return {'groove': groove, 'slit_rgb': slit_rgb, 'band': band, 'crease': crease, 'stats': stats}


def dark_streak_share(after_rgb: np.ndarray, band: np.ndarray, groove: np.ndarray, valid: np.ndarray, mask: np.ndarray, rules: dict | None = None) -> dict:
    """Мерка «тёмные рваные полосы на панелях»: доля пикселей полосы изломов (без пикселей щели), валидных (`valid` — взятые/залитые, не серая заготовка), где L* кадра ниже медианы панели
    (медиана по пикселям вне полосы) на dark_streak_dL. → {share_pct, band_px, streak_px}. Нет полосы/валидных — share_pct None."""
    r = rules or load_rules()
    L8 = lum8(after_rgb)
    ref = reference_l8(L8, mask & valid & ~band, int(r['ref_win']))
    cand = band & mask & valid & ~groove
    n = int(cand.sum())
    if n < 50:
        return {'share_pct': None, 'band_px': n, 'streak_px': 0}
    streak = cand & ((ref.astype(np.int16) - L8.astype(np.int16)) > float(r['dark_streak_dL']) * 2.55)
    return {'share_pct': round(100.0 * float(streak.sum()) / n, 3), 'band_px': n, 'streak_px': int(streak.sum())}


def dark_streak_new(after_rgb: np.ndarray, photo_rgb: np.ndarray, pmask: np.ndarray, band: np.ndarray, groove: np.ndarray, valid: np.ndarray, mask: np.ndarray,
                    rules: dict | None = None) -> dict:
    """Мерка T-194/2 «тёмное у излома, которого НЕТ на фото»: как dark_streak_share, но пиксель-полоса считается браком, только если на фото (через камеру 04, `photo_rgb`/`pmask`) в окрестности
    photo_dark_grow_px нет тёмного (L* ниже медианы панели ФОТО на photo_dark_dL). Дизайнерские зазоры и ручки фото браком не считаются (там тёмное и на фото); сдвиг щели относительно излома меша
    ≤ photo_dark_grow_px не засчитывается. → {share_pct, band_px, streak_px, streak_in_photo_px}."""
    from scipy.ndimage import binary_dilation
    r = rules or load_rules()
    L8 = lum8(after_rgb)
    ref = reference_l8(L8, mask & valid & ~band, int(r['ref_win']))
    cand = band & mask & valid & ~groove
    n = int(cand.sum())
    if n < 50:
        return {'share_pct': None, 'band_px': n, 'streak_px': 0, 'streak_in_photo_px': 0}
    streak = cand & ((ref.astype(np.int16) - L8.astype(np.int16)) > float(r['dark_streak_dL']) * 2.55)
    pv = pmask & mask
    P8 = lum8(photo_rgb)
    pref = reference_l8(P8, pv & ~band, int(r['ref_win']))
    pdark = pv & ((pref.astype(np.int16) - P8.astype(np.int16)) > float(r['photo_dark_dL']) * 2.55)
    g = int(r['photo_dark_grow_px'])
    pdark_n = binary_dilation(pdark, iterations=g) if g > 0 else pdark
    new = streak & ~pdark_n
    return {'share_pct': round(100.0 * float(new.sum()) / n, 3), 'band_px': n, 'streak_px': int(streak.sum()), 'streak_in_photo_px': int((streak & pdark_n).sum())}


def slit_contrast_ratio(photo_rgb: np.ndarray, after_rgb: np.ndarray, cs: dict, mask: np.ndarray, valid: np.ndarray, rules: dict | None = None) -> dict:
    """Контроль «щель осталась видимой»: (L панели − L щели) в итоге / то же в фото. Щель в фото — тонкие тёмные выбросы полосы, в итоге — пиксели щели `groove`. Нет щели — ratio None."""
    r = rules or load_rules()
    if not cs['groove'].any() or cs['slit_rgb'] is None:
        return {'ratio': None, 'note': 'щели с тёмной линией нет'}
    Lp, La = lum8(photo_rgb), lum8(after_rgb)
    ref = reference_l8(Lp, mask & valid & ~cs['band'], int(r['ref_win']))
    refa = reference_l8(La, mask & valid & ~cs['band'], int(r['ref_win']))
    dark = cs['band'] & ((ref.astype(np.int16) - Lp.astype(np.int16)) > float(r['dL_reject']) * 2.55)
    thin = _thin(dark, int(r['thin_px']))
    if thin.sum() < 20:
        return {'ratio': None, 'note': 'в фото тонкой тёмной линии мало'}
    d_photo = float(np.median(ref[thin].astype(np.float64) - Lp[thin]))
    g = cs['groove'] & valid
    d_after = float(np.median(refa[g].astype(np.float64) - La[g])) if g.any() else 0.0
    return {'ratio': round(d_after / max(d_photo, 1e-6), 3), 'dL_photo': round(d_photo / 2.55, 2), 'dL_after': round(d_after / 2.55, 2), 'min': float(r['slit_contrast_min'])}


def frame_confidence(prgb: np.ndarray, pmask: np.ndarray, st: dict, cs: dict, rules: dict | None = None) -> np.ndarray:
    """Уверенность фото-пикселя кадра (множитель 0…1; угол обзора и край силуэта считает сам перенос): у излома (полоса изломов меша) — conf_band, у блика (светлее медианы панели на highlight_dL L*) —
    conf_highlight; обе вместе перемножаются. Для шага сведения швов: известный тексель с малой уверенностью уступает соседу при швах (T-194/1, указание директора 22.11)."""
    r = rules or load_rules()
    cf = np.ones(st['mask'].shape, np.float32)
    cf[cs['band']] *= float(r['conf_band'])
    L8 = lum8(prgb)
    ref = reference_l8(L8, st['mask'] & pmask & ~cs['band'], int(r['ref_win']))
    cf[(L8.astype(np.int16) - ref.astype(np.int16)) > float(r['highlight_dL']) * 2.55] *= float(r['conf_highlight'])
    return cf
