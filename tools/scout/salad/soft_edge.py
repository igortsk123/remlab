"""ОПЦИОНАЛЬНЫЙ A/B-вариант мягкого края (T-20261119-104/5), по умолчанию ВЫКЛЮЧЕН: основной — аналитика `studio_bg.soft_alpha` (по ответу Codex).
Включается env `CUTOUT_SOFT_EDGE=pymatting` (нужен пакет pymatting, ≈0,6 с на кадр 800×600 на CPU). Прозрачность кромки считает closed-form matting (pymatting, MIT) по trimap,
а цвет тела у кромки — estimate_foreground_ml (убирает подмешанный белый). Так делает rembg `alpha_matting`.

Trimap строится по ЦВЕТУ, а не сужением маски (сужение/расширение «тащит фон внутрь» и убивает тонкие трубки — разбор «Background Matting»):
  фон   — пиксели «как фон» (≤ 3 от цвета фона), достающие заливкой до рамки, и всё дальше `band` px от маски;
  тело  — внутри маски, где пиксель заметно отличается от фона (> 40; для тонкой трубки это сама трубка) или дальше `band` px от границы;
  неизвестное — остальное в узкой кромке (≤ `band` px от границы маски).
Решается только в ограничивающем прямоугольнике неизвестного (≈ 0,6 с на кадр 800×600 на CPU). Только для фото с известным ровным фоном (bg_mode white_flat);
нет pymatting / сбой / слишком много неизвестного → вырезка остаётся как была (причина — в info). 
Не трогает `salad/preprocess._cut_chain` (меши)."""
import os

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

BAND = int(os.environ.get('CUTOUT_SOFT_EDGE_BAND', '3'))
FG_DIST = 40.0
SURE_BG = 3.0
MAX_UNKNOWN = 600_000


def enabled() -> bool:
    return os.environ.get('CUTOUT_SOFT_EDGE', '') == 'pymatting'


def apply(shape: Image.Image, src_rgb: np.ndarray, bg, info: dict, band: int = BAND) -> Image.Image:
    """shape — полнокадровая RGBA после defringe; src_rgb — исходное фото; возвращает RGBA с мягким краем."""
    rep: dict = {}
    info['soft_edge'] = rep
    try:
        from pymatting import estimate_alpha_cf, estimate_foreground_ml
    except Exception as e:  # noqa: BLE001 — нет библиотеки: вырезка как была
        rep['skipped'] = f'нет pymatting ({type(e).__name__})'
        return shape
    try:
        a = np.asarray(shape)
        alpha = a[..., 3].astype(np.float32) / 255.0
        mask = alpha > 0.5
        if not mask.any():
            rep['skipped'] = 'пустая маска'
            return shape
        d = np.abs(src_rgb.astype(np.float32) - np.asarray(bg, np.float32)).max(axis=2)
        lab, _ = ndi.label(d <= SURE_BG)
        ids = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        bg_sure = np.isin(lab, ids[ids > 0])
        zone = ndi.binary_dilation(mask, iterations=band)
        inner = ndi.binary_erosion(mask, iterations=band)
        tri = np.full(mask.shape, 0.5, np.float32)
        tri[~zone] = 0.0
        tri[bg_sure] = 0.0
        tri[mask & (d > FG_DIST) & ~bg_sure] = 1.0
        tri[inner] = 1.0
        unk = tri == 0.5
        n = int(unk.sum())
        rep['unknown_px'] = n
        if not n:
            rep['skipped'] = 'нет неизвестной кромки'
            return shape
        if n > MAX_UNKNOWN:
            rep['skipped'] = f'неизвестного {n} px > {MAX_UNKNOWN} — слишком много'
            return shape
        ys, xs = np.where(unk)
        pad = 16
        y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + pad)
        x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + pad)
        img = src_rgb[y0:y1, x0:x1].astype(np.float64) / 255.0
        a2 = alpha.copy()
        a2[y0:y1, x0:x1] = estimate_alpha_cf(img, tri[y0:y1, x0:x1].astype(np.float64))
        fg = estimate_foreground_ml(img, a2[y0:y1, x0:x1].astype(np.float64))
        rgb2 = a[..., :3].copy()
        rgb2[y0:y1, x0:x1] = np.where(unk[y0:y1, x0:x1, None] | (a2[y0:y1, x0:x1, None] < 0.98), np.clip(fg * 255, 0, 255), rgb2[y0:y1, x0:x1]).astype(np.uint8)
        a2[~zone] = 0.0
        a2[tri == 1.0] = np.maximum(a2[tri == 1.0], alpha[tri == 1.0])
        rep['solved_box'] = [int(x0), int(y0), int(x1), int(y1)]
        return Image.fromarray(np.dstack([rgb2, (np.clip(a2, 0, 1) * 255).astype(np.uint8)]), 'RGBA')
    except Exception as e:  # noqa: BLE001 — сбой матирования не валит вырезку
        rep['error'] = f'{type(e).__name__}: {str(e)[:100]}'
        return shape
