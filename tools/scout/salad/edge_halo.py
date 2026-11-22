#!/usr/bin/env python3
"""ЧИСТКА ОРЕОЛА ПО КРОМКЕ ВЫРЕЗКИ (T-20261119-99, «ушки» над спинкой дивана): светлые бесцветные чёрточки, оставшиеся от белого фона на
самом краю маски поверх ТЁМНОГО контура (кант, обводка, тень-край). Они непрозрачны (α≈226 > 0,8·255) — TRELLIS `preprocess_image` оставляет
их как деталь, а форма вырастает «ушками» там, где они лежат.

ПРАВИЛО (одно для всех товаров, без ID): пиксель в узкой полосе у внешней границы маски убирается, если он
  1) светлее фона минус `NEAR_BG` (то есть почти фон) и бесцветный (max−min ≤ CHROMA);
  2) заметно светлее «внутреннего ориентира» — среднего по пикселям на глубине BAND+1…BAND+10 px от границы — на ≥ `MIN_GAP` яркости.
Проход повторяется (новая граница → следующая полоска ореола), не больше `ITERS` раз. Тело не сжимается: срезается только светлое поверх
тёмного (Dreamina «Fix halos»: уменьшать всю маску нельзя — ломает форму). Светлый товар на белом фоне — не трогаем (контраст тела с
фоном < MIN_CONTRAST). Что внутри маски и не у границы — не трогается; ножки (тёмные), ручки, кант — не светлые → остаются.

  from clean_edge_halo import clean_edge_halo
  rgba2, info = clean_edge_halo(rgba)   # info: removed (px), iters, body_lum, skipped (причина, если не применялось)
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

NEAR_BG = 45          # «почти фон»: яркость ≥ bg_lum − NEAR_BG
CHROMA = 22           # бесцветное: max−min ≤
MIN_GAP = 45          # светлее ориентира внутри не меньше чем на
MIN_CONTRAST = 45     # контраст с фоном, ниже которого `clean_islands` не считает островок тенью (шаг кромки с T-99/3 решает ЛОКАЛЬНО: MIN_GAP к ориентиру и тёмному соседу)
BAND_REL = 0.0013     # полоса у границы — доля ширины тела (≈3 px на 2321)
REF_DEPTH = 10        # ориентир — на глубине BAND+1 … BAND+REF_DEPTH px
ITERS = 3
LIGHT_DEPTH = 4      # светлое тело-сосед считается только на глубине от кромки ≥ band+4 (чёрточка/«ушко» 2–3 px толщиной им не является)
MAX_RUN_REL = 0.03   # самый длинный размер куска-кандидата не больше доли ширины тела (дивана 2321 px → 70 px; чёрточки 8–25 px)
NEIGH = 2            # px сверх полосы: тёмный сосед (светлее него на MIN_GAP) обязателен — свободный светлый провод/трос без тёмного соседа — товар, не ореол
MAX_PERIM_SHARE = 0.35  # убрано больше 35 % длины границы (а не площади: у тонких ножек площадь мала, а ореол длинный — стул 227×305 откатывался зря) — это не ореол: откат, статус «подозрение»


def border_lum(rgb) -> float:
    """Яркость фона исходного фото — медиана рамки в 4 px (np.ndarray H×W×3/4)."""
    a = np.asarray(rgb)[..., :3].astype(np.float32).mean(axis=2)
    frame = np.concatenate([a[:4].ravel(), a[-4:].ravel(), a[:, :4].ravel(), a[:, -4:].ravel()])
    return float(np.median(frame))


def _bad_ring(A, lum, chroma, body_lum, bg_lum, band):
    """Пиксели у границы, которые правило считает ореолом (один проход): светлые, бесцветные, светлее внутреннего ориентира на MIN_GAP."""
    solid = A[..., 3] > 128
    dist = ndimage.distance_transform_edt(solid)
    ring = solid & (dist <= band)
    inner = (solid & (dist > band) & (dist <= band + REF_DEPTH)).astype(np.float32)
    win = 2 * (band + REF_DEPTH) + 1
    num = ndimage.uniform_filter(lum * inner, size=win)
    den = ndimage.uniform_filter(inner, size=win)
    ref = np.where(den > 1e-4, num / np.maximum(den, 1e-4), body_lum)
    bad = ring & (lum >= bg_lum - NEAR_BG) & (chroma <= CHROMA) & ((ref - lum) <= -MIN_GAP)
    # ореол — это светлое ВПЛОТНУЮ к тёмному краю; светлая линия без тёмного соседа (подвес люстры, провод) — товар. Сосед — твёрдый пиксель в окне band+NEIGH, темнее на MIN_GAP.
    wnd = 2 * (band + NEIGH) + 1
    nb_min = ndimage.minimum_filter(np.where(solid, lum, 255.0), size=wnd)
    bad &= (lum - nb_min) >= MIN_GAP
    # T-99/3: рядом СВЕТЛОЕ тело (белая трубка люстры у чёрного кольца, белый фасад у дубовой столешницы) — кандидат обязан быть ближе по яркости к ФОНУ, чем к этому светлому телу;
    # иначе это сам товар (блик/край трубки), а не остаток фона. Где светлого тела рядом нет (тёмное тело, дуб) — условие не действует.
    lightin = (solid & (dist >= band + LIGHT_DEPTH) & (dist <= band + LIGHT_DEPTH + REF_DEPTH)).astype(np.float32) * (lum >= bg_lum - MIN_GAP)   # толстое светлое (не сама чёрточка)
    lnum = ndimage.uniform_filter(lum * lightin, size=win)
    lden = ndimage.uniform_filter(lightin, size=win)
    near_light = lden > 1e-4
    lbody = np.where(near_light, lnum / np.maximum(lden, 1e-4), 0.0)
    bad &= ~near_light | ((bg_lum - lum) <= (lum - lbody))
    # ореол — КОРОТКИЕ чёрточки; длинная светлая кромка (стекло, белый абажур, светлый борт) — сам товар. Куски длиннее MAX_RUN_REL·ширины тела не режем.
    if bad.any():
        cx = np.where(solid.any(axis=0))[0]
        wb = int(cx.max() - cx.min() + 1)
        lab, n = ndimage.label(bad, structure=np.ones((3, 3)))
        objs = ndimage.find_objects(lab)
        lim = max(4, MAX_RUN_REL * wb)
        for i, sl in enumerate(objs, 1):
            if max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) > lim:
                bad[lab == i] = False
    return bad


# СТОРОЖ ЧИСТОТЫ КРОМКИ (T-99, владелец TG 2022–2023: «чтобы ни один пиксель фона не остался»): считает, сколько грязи у кромки осталось.
ISLAND_MIN_PX = 8          # отдельный островок (α>128) меньше — шум, не считаем
DIRTY_LIGHT_SHARE = 0.03   # светлых бесцветных у тёмного края больше 3 % длины границы — «грязная» (замер 200 вырезок 19.11: до чистки медиана 22 %, после — у 75 % ноль)


def audit(rgba, bg_lum: float = 255.0) -> dict:
    """Не меняет картинку. → {'status': 'clean'|'dirty'|'skipped', 'light_edge': px, 'semi_edge': px, 'islands': N, 'island_px': px, 'reasons': [...]}.
    light_edge — светлые бесцветные пиксели у тёмного края (их убирает `clean_edge_halo`); semi_edge — полупрозрачные пиксели в полосе у границы;
    islands — отдельные куски α>128 кроме самого большого. Светлое тело (контраст с фоном < MIN_CONTRAST) → 'skipped' (по цвету края ореол не виден)."""
    A = np.asarray(rgba.convert('RGBA')).astype(np.float32)
    a = A[..., 3]
    solid = a > 128
    out = {'status': 'clean', 'light_edge': 0, 'semi_edge': 0, 'islands': 0, 'island_px': 0, 'reasons': []}
    if not solid.any():
        out.update(status='skipped', reasons=['пустая маска'])
        return out
    ys, xs = np.where(solid)
    wb = int(xs.max() - xs.min() + 1)
    lum = A[..., :3].mean(axis=2)
    chroma = A[..., :3].max(axis=2) - A[..., :3].min(axis=2)
    lab, n = ndimage.label(solid, structure=np.ones((3, 3)))
    if n > 1:
        sizes = ndimage.sum(solid, lab, range(1, n + 1))
        small = [s_ for s_ in sizes if s_ >= ISLAND_MIN_PX]
        out['islands'] = len(small) - 1
        out['island_px'] = int(sum(small) - max(small)) if small else 0
    band = max(2, int(round(BAND_REL * wb)))
    near = ndimage.distance_transform_edt(~solid) <= band
    out['semi_edge'] = int(((a > 4) & (a <= 204) & near).sum())
    perim = max(int((solid & ~ndimage.binary_erosion(solid)).sum()), 1)
    body_lum = float(np.median(lum[solid]))
    out['light_edge'] = int(_bad_ring(A, lum, chroma, body_lum, bg_lum, band).sum())
    out['light_share'] = round(out['light_edge'] / perim, 4)
    if out['light_share'] > DIRTY_LIGHT_SHARE:
        out['reasons'].append(f'светлых у тёмного края {out["light_edge"]} px ({100 * out["light_share"]:.1f} % границы)')
    if out['islands']:
        out['reasons'].append(f'отдельных островков {out["islands"]} ({out["island_px"]} px)')
    if out['reasons']:
        out['status'] = 'dirty'
    return out


def clean_edge_halo(rgba, bg_lum: float = 255.0):
    """rgba: PIL.Image RGBA → (PIL.Image RGBA, info)."""
    from PIL import Image
    A = np.asarray(rgba.convert('RGBA')).copy()
    a = A[..., 3].astype(np.float32)
    ys, xs = np.where(a > 128)
    info = {'removed': 0, 'iters': 0, 'body_lum': None, 'skipped': None}
    if not len(ys):
        info['skipped'] = 'пустая маска'
        return rgba, info
    wb = int(xs.max() - xs.min() + 1)
    rgb = A[..., :3].astype(np.float32)
    lum = rgb.mean(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    body_lum = float(np.median(lum[a > 128]))
    info['body_lum'] = round(body_lum, 1)
    band = max(2, int(round(BAND_REL * wb)))
    total = 0
    for it in range(ITERS):
        bad = _bad_ring(A, lum, chroma, body_lum, bg_lum, band)
        n = int(bad.sum())
        if not n:
            break
        A[bad, 3] = 0
        total += n
        info['iters'] = it + 1
    info['removed'] = total
    perim = max(int((a > 128).sum() - ndimage.binary_erosion(a > 128).sum()), 1)
    if total > MAX_PERIM_SHARE * perim:
        info.update(removed=0, iters=0, skipped=f'убрано {total} px — слишком много для ореола (светлая кромка — сам товар), откат')
        return rgba, info
    return Image.fromarray(A, 'RGBA'), info


if __name__ == '__main__':
    import sys
    from PIL import Image
    src, dst = sys.argv[1:3]
    out, inf = clean_edge_halo(Image.open(src))
    out.save(dst)
    print(inf)
