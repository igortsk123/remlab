"""Гибрид вырезки: сеть решает, ЧТО товар; аналитика по фону возвращает тонкие детали.

Портировано из замера соседней сессии (`tools/scout/mask_bench/hybrid.py`, прогон 36 товаров,
страница `/test/cutout-bench/`). Логика не изменена — только убрана файловая обвязка бенча,
чтобы функция работала на объектах PIL внутри воркера.

ЗАЧЕМ ЭТО В КОНВЕЙЕРЕ МЕШЕЙ. Вырезка — вход генератора: что срезано с фото, того не будет в
меше, а что прилипло от фона — станет геометрией. По замеру 28.08 (36 товаров: стулья, комоды,
стеллажи, столики, торшеры) чистый BiRefNet держит 79% деталей толщиной 1–2 пикселя, гибрид —
95%. Для люстр, спинок и тонких ножек это решающая разница.

Сверка 28.08 на нашей базе: гибрид поверх BiRefNet теряет 1.56% эталонной маски против 2.90%
у чистого BiRefNet — вдвое меньше, вровень с чистой BRIA RMBG 2.0. Полный эталон (гибрид
поверх BRIA) даёт IoU 0.991 против наших 0.973; остаток разрыва — качество базовой маски,
и он закрывается только заменой сети (BRIA на HuggingFace под воротами).

Логика (по разбору с Codex в исходном замере):
  1. Фон оцениваем по пограничной полосе, а не по 4 углам — угол может попасть на товар,
     а полоса даёт и медиану, и разброс, по которому видно, «карточка» это или сцена.
  2. Пороги считаем от шума самого фона, а не константой: у одного магазина карточка
     чистая, у другого — с градиентом.
  3. Восстанавливаем ТОЛЬКО в узкой полосе вокруг того, что сеть уже считает товаром.
     Крупное пятно вдали от товара — тень, реквизит или ватермарка, его не приклеиваем.
  4. Морфологию почти не трогаем: opening убивает однопиксельную проволоку, заливка дыр
     заклеивает просветы проволочного основания и реечных спинок.
  5. Контактную тень режем: она не форма, а освещение — генератор превращает её в плоскость.
"""
import numpy as np
from PIL import Image


def bg_stats(rgb: np.ndarray, frac: float = 0.04):
    """Фон и его разброс по пограничной полосе кадра."""
    h, w = rgb.shape[:2]
    b = max(2, int(min(h, w) * frac))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    med = np.median(band, axis=0)
    dist = np.linalg.norm(band - med, axis=1)
    return med, float(np.percentile(dist, 99)), float(np.median(dist))


def analytic(rgb: np.ndarray, med: np.ndarray, noise: float) -> np.ndarray:
    """Мягкое свидетельство «это не фон»: плавный порог по расстоянию до цвета фона."""
    d = np.linalg.norm(rgb - med, axis=2)
    t0 = max(noise * 1.6, 8.0)          # ниже — заведомо фон и его шум
    t1 = max(t0 + 6.0, 22.0)            # выше — заведомо не фон
    return np.clip((d - t0) / (t1 - t0), 0, 1)


def refine(src: Image.Image, cut: Image.Image) -> tuple[Image.Image, dict]:
    """src — исходное фото (RGB), cut — вырезка сети (RGBA). Возвращает уточнённую RGBA."""
    from scipy import ndimage

    src = src.convert('RGB')
    cut = cut.convert('RGBA')
    if cut.size != src.size:
        cut = cut.resize(src.size, Image.LANCZOS)
    rgb = np.asarray(src).astype(np.float32)
    N = np.asarray(cut)[..., 3].astype(np.float32) / 255.0

    med, p99, noise = bg_stats(rgb)
    uniform = p99 < 30 and float(np.linalg.norm(med - 255)) < 60   # белая ровная карточка
    info = {'uniform_bg': bool(uniform), 'bg_noise': round(noise, 2), 'bg_p99': round(p99, 2),
            'restored_px': 0}
    if not uniform:
        return cut, info                        # сценовое фото — аналитике верить нельзя

    A = analytic(rgb, med, p99)
    support = N >= 0.15
    if not support.any():
        return cut, info

    # полоса поиска: рядом с тем, что сеть уже держит за товар
    band = ndimage.binary_dilation(support, np.ones((3, 3)), iterations=6) & ~support
    cand = band & (A >= 0.5)

    # Контактная тень лежит НА ПОЛУ, то есть ниже самой нижней точки товара в своём столбце.
    # Порог по «целиком ниже всего предмета» не работает: тень примыкает к ножкам вплотную,
    # и её верх оказывается выше нижней кромки соседних частей (поймано на креслах).
    solid = N >= 0.5
    col_has = solid.any(axis=0)
    col_bottom = np.where(col_has, solid.shape[0] - 1 - solid[::-1].argmax(axis=0), -1)
    yy = np.arange(rgb.shape[0])[:, None]
    below_floor = (yy > col_bottom[None, :]) & col_has[None, :]

    # …и она бесцветная: у тени тон фона, только темнее. Настоящая деталь обычно имеет цвет.
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    shadowish = below_floor & ((mx - mn) < 18) & (mx < float(med.max()))

    keep = cand & ~shadowish
    keep &= ~ndimage.binary_dilation(shadowish, np.ones((3, 3)))   # не цеплять кайму тени
    out = np.maximum(N, np.where(keep, A, 0.0))
    info['restored_px'] = int(keep.sum())

    a8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([np.asarray(src), a8]), 'RGBA'), info
