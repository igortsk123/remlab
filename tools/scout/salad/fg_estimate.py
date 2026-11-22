"""Быстрая оценка цвета предмета у кромки (fast foreground estimation, blur fusion) — T-20261119-99/2.

Порт функции `refine_foreground` из репозитория ZhengPeng7/BiRefNet (`image_proc.py`, лицензия MIT), которая сама ссылается на Photoroom `fast-foreground-estimation`
(Forte & Pitié «F, B, Alpha Matting» + blur fusion). Мы свою реализацию написали на scipy (без cv2 — его нет в образе), алгоритм тот же: два прохода (окно r, затем 6).
Что делает: у пикселей полупрозрачной кромки восстанавливает цвет ПРЕДМЕТА (вычитает подмешанный фон). Что НЕ делает: альфа не меняется — геометрию («ушки») она не трогает.
Применяется только в полосе у границы (BAND px), остальное — как было. Нужна только арифметика numpy/scipy.
"""
import numpy as np
from scipy import ndimage

R1, R2 = 90, 6          # окна двух проходов — как в BiRefNet
BAND = 3                # px от границы (внутрь и наружу), где цвет пересчитывается


def _est(img, fg, bk, al, r):
    box = lambda x: ndimage.uniform_filter(x, size=(r, r, 1) if x.ndim == 3 else (r, r), mode='nearest')  # noqa: E731
    ba = box(al)
    bfg = box(fg * al) / (ba + 1e-5)
    bb = box(bk * (1 - al)) / ((1 - ba) + 1e-5)
    out = bfg + al * (img - al * bfg - (1 - al) * bb)
    return np.clip(out, 0, 1), bb


def foreground(rgb01: np.ndarray, alpha01: np.ndarray) -> np.ndarray:
    """rgb01 H×W×3 (0..1), alpha01 H×W (0..1) → оценка цвета предмета H×W×3 (0..1)."""
    a = alpha01[:, :, None].astype(np.float32)
    img = rgb01.astype(np.float32)
    fg, bb = _est(img, img, img, a, R1)
    return _est(img, fg, bb, a, R2)[0]


def refine_edges(rgb: np.ndarray, alpha: np.ndarray, band: int = BAND):
    """rgb H×W×3 (float 0..255), alpha H×W (0..1) → (rgb с пересчитанным цветом в полосе, число изменённых px). α не трогается."""
    solid = alpha > 0.5
    if not solid.any():
        return rgb, 0
    di = ndimage.distance_transform_edt(solid)
    do = ndimage.distance_transform_edt(~solid)
    sel = ((solid & (di <= band)) | (~solid & (do <= 1) & (alpha > 0.02)))
    if not sel.any():
        return rgb, 0
    fg = foreground(rgb / 255.0, alpha) * 255.0
    out = np.where(sel[..., None], fg, rgb)
    return out, int(sel.sum())
