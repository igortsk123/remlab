"""Наш гибрид: сеть решает, ЧТО товар; аналитика по белому фону возвращает тонкие детали.

Логика (по разбору с Codex):
  1. Фон оцениваем по пограничной полосе, а не по 4 углам — угол может попасть на товар,
     а полоса даёт и медиану, и разброс, по которому видно, «карточка» это или сцена.
  2. Аналитическое свидетельство A = плавный порог по расстоянию до фона. Пороги считаем
     от шума самого фона (квантиль по полосе), а не константой: у одного магазина карточка
     чистая, у другого — с градиентом.
  3. Восстанавливаем ТОЛЬКО в узкой полосе вокруг того, что сеть уже считает товаром.
     Крупное пятно вдали от товара — это тень, реквизит или ватермарка, его не приклеиваем.
  4. Морфологию сознательно почти не трогаем: opening убивает однопиксельную проволоку,
     заливка дыр заклеивает просветы проволочного основания и реечных спинок.
  5. Контактную тень режем: она не форма, а освещение — генератор превращает её в плоскость.
"""
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.abspath(__file__))
# ВНИМАНИЕ: эталонный вариант E из замера 28.08 построен над D-bria2, а НЕ над B-heavy2k.
# Проверено по маскам: гибрид берёт максимум с базой, поэтому его альфа обязана быть
# надмножеством базовой — у D-bria2 нарушений ноль, у остальных баз они есть. Прежний дефолт
# `B-heavy2k` устарел и давал бы не тот вариант, который мерили.
BASE = 'D-bria2'            # сетевая основа эталона: лучшая среди чистых сеток
OUT = 'E-hybrid'


def bg_stats(rgb, frac=0.04):
    """Фон и его разброс по пограничной полосе кадра."""
    h, w = rgb.shape[:2]
    b = max(2, int(min(h, w) * frac))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    med = np.median(band, axis=0)
    dist = np.linalg.norm(band - med, axis=1)
    return med, float(np.percentile(dist, 99)), float(np.median(dist))


def analytic(rgb, med, noise):
    """Мягкое свидетельство «это не фон»: плавный порог по расстоянию до цвета фона."""
    d = np.linalg.norm(rgb - med, axis=2)
    t0 = max(noise * 1.6, 8.0)          # ниже — заведомо фон и его шум
    t1 = max(t0 + 6.0, 22.0)            # выше — заведомо не фон
    return np.clip((d - t0) / (t1 - t0), 0, 1)


def refine(src_path, cut_path):
    src = Image.open(src_path).convert('RGB')
    cut = Image.open(cut_path).convert('RGBA')
    if cut.size != src.size:
        cut = cut.resize(src.size, Image.LANCZOS)
    rgb = np.asarray(src).astype(np.float32)
    N = np.asarray(cut)[..., 3].astype(np.float32) / 255.0

    med, p99, noise = bg_stats(rgb)
    uniform = p99 < 30 and float(np.linalg.norm(med - 255)) < 60   # белая ровная карточка
    info = {'uniform_bg': bool(uniform), 'bg_noise': round(noise, 2), 'bg_p99': round(p99, 2)}
    if not uniform:
        info['restored_px'] = 0
        return cut, info                        # сценовое фото — аналитике верить нельзя

    A = analytic(rgb, med, p99)
    support = N >= 0.15
    if not support.any():
        info['restored_px'] = 0
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
    chroma = mx - mn
    darker = mx < float(med.max())
    shadowish = below_floor & (chroma < 18) & darker

    keep = cand & ~shadowish
    keep &= ~ndimage.binary_dilation(shadowish, np.ones((3, 3)))   # не цеплять кайму тени
    out = np.maximum(N, np.where(keep, A, 0.0))
    info['restored_px'] = int(keep.sum())

    a8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    res = np.dstack([np.asarray(src), a8])
    return Image.fromarray(res, 'RGBA'), info


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else BASE
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    items = json.load(open(os.path.join(ROOT, 'set.json')))
    os.makedirs(os.path.join(ROOT, out), exist_ok=True)
    infos, fails = {}, 0
    for it in items:
        try:
            img, info = refine(os.path.join(ROOT, 'src', it['id'] + '.jpg'),
                               os.path.join(ROOT, base, it['id'] + '.png'))
        except Exception as e:                    # noqa: BLE001 — считаем, не глотаем
            fails += 1
            print('   ✗', it['id'], type(e).__name__, str(e)[:80])
            continue
        img.save(os.path.join(ROOT, out, it['id'] + '.png'))
        infos[it['id']] = info
    json.dump(infos, open(os.path.join(ROOT, f'{out}-info.json'), 'w'), indent=1)
    uni = sum(1 for v in infos.values() if v['uniform_bg'])
    rest = sum(v['restored_px'] for v in infos.values())
    print(f'{out}: готово {len(infos)}, ошибок {fails}; ровный фон у {uni}/{len(infos)}; '
          f'возвращено пикселей всего {rest}')
    top = sorted(infos.items(), key=lambda kv: -kv[1]['restored_px'])[:8]
    for k, v in top:
        print(f'   {k:28} вернули {v["restored_px"]:6} px')


if __name__ == '__main__':
    main()
