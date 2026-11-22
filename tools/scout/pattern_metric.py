#!/usr/bin/env python3
"""T-20261119-04/1 (Codex 19.11 §4, `_intake/codex/2026-11-19-texture-on-shape-answer.md`): МЕТРИКА УЗОРА `pattern_grad_ncc` — «совпадает ли РИСУНОК поверхности с фото»,
а не средний цвет. Общая функция для всей пробы моделей (TRELLIS.2 / Hunyuan / Pixal3D / Hunyuan Paint …): камера и вырезка у всех одинаковые, меряется рендер без света
против выровненного фото в кадре.

Шаги (каждый — параметр):
  1. Оба кадра → Lab (sRGB, D65); низкие частоты долой: канал − гауссово размытие σ = SIGMA_FRAC · ширина рамки маски. Остаётся рисунок (листья, доски, ткань), свет и общий
     тон уходят — поэтому тень/блик фото и сдвиг яркости метрику не двигают.
  2. Градиенты Собеля каждого канала (L, a, b) — вектор (gx, gy) на пиксель, т.е. И величина, И направление края.
  3. Окна PATCH×PATCH с шагом STRIDE внутри маски (покрытие ≥ COVER_MIN, у фото в окне есть рисунок — энергия градиента ≥ ENERGY_MIN, иначе окно «плоское» и в счёт не идёт —
     иначе гладкая стена даст любое число). В каждом окне — локальная NCC градиентных полей: Σ(a·b)/√(Σ|a|²·Σ|b|²) по трём каналам; рендер сдвигается на ±SHIFT_PX
     по обеим осям (допуск на ошибку камеры), берётся лучший сдвиг. NCC ∈ [−1, 1]: 1 — тот же рисунок, ~0 — несвязанный, <0 — инвертированный.
  3б. Камера: у проб камера ортографическая и подбирается по силуэту, а фасад — плоскость, снятая в перспективе. Для плоскости ошибка камеры — ГОМОГРАФИЯ, поэтому до окон
     рендер совмещается с фото `cv2.findTransformECC` (MOTION_HOMOGRAPHY, три масштаба, по светлоте внутри маски) — один протокол для ВСЕХ моделей (Codex: «фит камеры у каждого
     меша свой, одним оптимизатором»). Совмещение не подгоняет чужой рисунок под фото: у неверного рисунка NCC остаётся низким (проверено тестом). Сбой ECC — без совмещения, в итоге `registration`.
  4. Итог по окнам: медиана и нижний дециль (p10) — «худшее место»; также доля окон с NCC ≥ GOOD. Окон нет (поверхность гладкая или маска мала) — None, не 0.
Рядом можно класть маску «фасад» (любая булева маска) — меряется только в ней. Не заменяет ΔE00 (цвет) — дополняет его. CLIP/«похоже по смыслу» для узора непригодны (Codex).

  from pattern_metric import pattern_grad_ncc
  r = pattern_grad_ncc(render_rgb_uint8, photo_rgb_uint8, mask_bool)   # → {'median', 'p10', 'share_good', 'n_patches', ...}
  ~/venvs/scout/bin/python pattern_metric.py --selftest
"""
from __future__ import annotations

import sys

import numpy as np

CC_MIN = 0.5   # ECC: коэффициент совмещения ниже — гомографию не применяем (подгонка под чужой рисунок)

SIGMA_FRAC = 0.02       # σ снятия низких частот, доля ширины рамки маски (рисунок мельче этого остаётся)
PATCH = 32              # окно, пикселей
STRIDE = 16
SHIFT_PX = 2            # допуск на сдвиг камеры, пикселей
COVER_MIN = 0.8         # доля окна внутри маски
ENERGY_MIN = 1.0        # средняя квадратичная энергия градиента фото в окне (Lab-единицы²); меньше — окно плоское
GOOD = 0.5              # NCC окна ≥ этого — «рисунок совпал»


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8/float (0–255) → Lab D65 (float32), без зависимостей кроме numpy."""
    c = np.asarray(rgb, np.float32)[..., :3] / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]], np.float32)
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1).astype(np.float32)


def _grad_field(lab: np.ndarray, sigma: float) -> np.ndarray:
    """(H, W, 6): градиенты Собеля (gx, gy) каналов L, a, b после снятия низких частот."""
    import cv2
    out = []
    for c in range(3):
        ch = lab[..., c]
        hp = ch - cv2.GaussianBlur(ch, (0, 0), sigma)
        out += [cv2.Sobel(hp, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(hp, cv2.CV_32F, 0, 1, ksize=3)]
    return np.stack(out, -1)


def register_homography(render_rgb: np.ndarray, photo_rgb: np.ndarray, mask: np.ndarray, scales=(0.25, 0.5, 1.0), iters: int = 120) -> tuple[np.ndarray | None, dict]:
    """Гомография H (3×3), совмещающая рендер с фото внутри маски (ECC по светлоте, от грубого масштаба к полному) → (H | None при сбое, {cc, ...}).
    Применять: cv2.warpPerspective(render, H, (w, h), flags=INTER_LINEAR | WARP_INVERSE_MAP)."""
    import cv2
    gr = rgb_to_lab(render_rgb)[..., 0]
    gp = rgb_to_lab(photo_rgb)[..., 0]
    gr, gp = cv2.GaussianBlur(gr, (0, 0), 1.5), cv2.GaussianBlur(gp, (0, 0), 1.5)
    m8 = (mask.astype(np.uint8)) * 255
    H = np.eye(3, dtype=np.float32)
    s_prev = scales[0]
    cc = None
    try:
        for s in scales:
            r = s / s_prev
            H = (np.diag([r, r, 1.0]).astype(np.float32) @ H @ np.diag([1 / r, 1 / r, 1.0]).astype(np.float32)) if s != s_prev else H
            s_prev = s
            sz = (int(gr.shape[1] * s), int(gr.shape[0] * s))
            a, b = cv2.resize(gp, sz, interpolation=cv2.INTER_AREA), cv2.resize(gr, sz, interpolation=cv2.INTER_AREA)
            mk = cv2.resize(m8, sz, interpolation=cv2.INTER_NEAREST)
            cc, H = cv2.findTransformECC(a, b, H, cv2.MOTION_HOMOGRAPHY, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-5), mk, 5)
        # H — для масштаба scales[-1] (=1.0) → кадр полного размера
        return H, {'cc': round(float(cc), 3), 'H': [round(float(x), 5) for x in H.ravel()]}
    except cv2.error as e:
        return None, {'cc': None, 'error': str(e)[:120]}


def pattern_grad_ncc(render_rgb: np.ndarray, photo_rgb: np.ndarray, mask: np.ndarray, sigma_frac: float = SIGMA_FRAC, patch: int = PATCH, stride: int = STRIDE,
                     shift: int = SHIFT_PX, cover_min: float = COVER_MIN, energy_min: float = ENERGY_MIN, good: float = GOOD, register: str | None = 'homography') -> dict:
    """→ {median, p10, mean, share_good, n_patches, n_flat, sigma, registration}; median/p10 = None, если окон с рисунком нет. Кадры одного размера; mask — где мерить (фасад).
    register='homography' (по умолчанию) — совместить рендер с фото ECC до замера; None — без совмещения (только допуск сдвига)."""
    import cv2
    assert render_rgb.shape[:2] == photo_rgb.shape[:2] == mask.shape[:2], 'кадры и маска — одного размера'
    reg = None
    if register == 'homography' and mask.sum() >= patch * patch:
        H, reg = register_homography(render_rgb, photo_rgb, mask)
        if H is not None and (reg.get('cc') or 0) < CC_MIN:
            reg['rejected'] = 'cc < %.2f — совмещению не верим, замер без него' % CC_MIN
            H = None
        if H is not None:
            h0, w0 = mask.shape
            render_rgb = cv2.warpPerspective(render_rgb, H, (w0, h0), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    ys, xs = np.nonzero(mask)
    if len(xs) < patch * patch:
        return {'registration': reg, 'median': None, 'p10': None, 'mean': None, 'share_good': None, 'n_patches': 0, 'n_flat': 0, 'note': 'маска меньше окна'}
    sigma = max(sigma_frac * (xs.max() - xs.min() + 1), 1.0)
    A, B = _grad_field(rgb_to_lab(render_rgb), sigma), _grad_field(rgb_to_lab(photo_rgb), sigma)
    m = mask.astype(np.float32)
    k = (patch, patch)

    def box(x):
        return cv2.boxFilter(x, -1, k, normalize=True, borderType=cv2.BORDER_CONSTANT)
    cover = box(m)
    ea = box((A ** 2).sum(-1) * m)                      # энергия по окну: рендер и фото — для знаменателя NCC
    eb_photo = box((B ** 2).sum(-1) * m)
    best = np.full(mask.shape, -1.0, np.float32)
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            As = cv2.warpAffine(A, M, (A.shape[1], A.shape[0]), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            ms = cv2.warpAffine(m, M, (m.shape[1], m.shape[0]), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            num = box((As * B).sum(-1) * m * ms)
            den = np.sqrt(np.maximum(box((As ** 2).sum(-1) * m * ms) * eb_photo, 1e-12))
            best = np.maximum(best, num / den)
    h, w = mask.shape
    cy, cx = np.mgrid[patch // 2:h - patch // 2:stride, patch // 2:w - patch // 2:stride]
    cy, cx = cy.ravel(), cx.ravel()
    ok_cov = cover[cy, cx] >= cover_min
    energetic = eb_photo[cy, cx] / np.maximum(cover[cy, cx], 1e-6) >= energy_min
    sel = ok_cov & energetic & (ea[cy, cx] > 1e-6)
    n_flat = int((ok_cov & ~energetic).sum())
    vals = best[cy[sel], cx[sel]]
    if len(vals) == 0:
        return {'registration': reg, 'median': None, 'p10': None, 'mean': None, 'share_good': None, 'n_patches': 0, 'n_flat': n_flat, 'sigma': round(float(sigma), 2),
                'note': 'нет окон с рисунком (поверхность гладкая или фото без деталей)'}
    return {'registration': (reg or {}).get('cc') if reg else None, 'median': round(float(np.median(vals)), 3), 'p10': round(float(np.percentile(vals, 10)), 3), 'mean': round(float(vals.mean()), 3),
            'share_good': round(float((vals >= good).mean()), 3), 'n_patches': int(len(vals)), 'n_flat': n_flat, 'sigma': round(float(sigma), 2)}


def selftest() -> int:
    import cv2
    fails = []

    def check(n, c, e=''):
        print(('OK   ' if c else 'FAIL ') + n + (f'  [{e}]' if e else ''))
        if not c:
            fails.append(n)
    rng = np.random.default_rng(3)

    def pattern(seed):                                  # «листья»: случайные цветные пятна мелкого масштаба на ровном фоне
        r = np.random.default_rng(seed)
        img = np.full((256, 256, 3), 140.0, np.float32)
        for _ in range(900):
            x, y = r.integers(0, 256, 2)
            cv2.ellipse(img, (int(x), int(y)), (int(r.integers(2, 6)), int(r.integers(2, 6))), float(r.integers(0, 180)), 0, 360, [float(v) for v in r.integers(60, 220, 3)], -1)
        return img.clip(0, 255).astype(np.uint8)
    mask = np.zeros((256, 256), bool)
    mask[20:236, 20:236] = True
    base = pattern(1)
    same = pattern_grad_ncc(base, base, mask)
    check('тот же рисунок — NCC ≈ 1', same['median'] > 0.95 and same['p10'] > 0.9, str(same))
    sh = np.roll(base, (1, 2), (0, 1))
    r = pattern_grad_ncc(sh, base, mask)
    check('сдвиг на 1–2 px в допуске — всё ещё высоко', r['median'] > 0.85, str(r['median']))
    far = np.roll(base, (9, 11), (0, 1))
    r = pattern_grad_ncc(far, base, mask, register=None)
    check('без совмещения: сдвиг на 10 px вне допуска — низко', r['median'] < 0.45, str(r['median']))
    r = pattern_grad_ncc(far, base, mask)
    check('с совмещением (гомография): тот же рисунок со сдвигом 10 px находится — высоко', r['median'] > 0.85, str(r['median']))
    other = pattern(2)
    r = pattern_grad_ncc(other, base, mask)
    check('другой рисунок — низко (|NCC| < 0,3)', abs(r['median']) < 0.3, str(r))
    grad = (base.astype(np.float32) * 0.5 + np.linspace(0, 120, 256)[None, :, None]).clip(0, 255).astype(np.uint8)
    r = pattern_grad_ncc(grad, base, mask)
    check('свет (градиент яркости + контраст) рисунок не ломает', r['median'] > 0.8, str(r['median']))
    flat = np.full((256, 256, 3), 140, np.uint8)
    r = pattern_grad_ncc(flat, flat, mask)
    check('гладкая поверхность — None (окон с рисунком нет), не 0 и не 1', r['median'] is None and r['n_patches'] == 0, str(r))
    inv = (255 - base).astype(np.uint8)
    r = pattern_grad_ncc(inv, base, mask)
    check('инвертированный рисунок — не выше ≈ 0 (рисунок «наоборот» не засчитан как похожий)', r['median'] < 0.1, str(r['median']))
    small = np.zeros_like(mask)
    small[10:20, 10:20] = True
    check('маска меньше окна — None', pattern_grad_ncc(base, base, small)['median'] is None)
    left = mask.copy()
    left[:, 128:] = False
    mixed = base.copy()
    mixed[:, 128:] = other[:, 128:]
    r = pattern_grad_ncc(mixed, base, left)
    check('метрика считает только внутри маски (чужая половина не мешает)', r['median'] > 0.9, str(r['median']))
    print('\nПРОВАЛЕНО: ' + ', '.join(fails) if fails else '\nвсё прошло')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else (print(__doc__) or 2))
