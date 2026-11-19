#!/usr/bin/env python3
"""T-93: шаг чистки ПОСЛЕ маски (после гибрида/components) — общее правило, без особых случаев:
  убрать отдельные островки у нижней кромки предмета, которые похожи на ТЕНЬ/БЛИК ПОЛА, а не на сам предмет.
Признаки (все относительные — от цвета самого тела, не константы под товар):
  1. островок — связная область α>THR (8-связность), НЕ главное тело и меньше MAX_SHARE от него;
  2. лежит в нижней полосе предмета: его центр ниже (низ_тела − BAND·высота_тела);
  3. «тень-подобен»: малонасыщенный (max−min ≤ CHROMA) и по яркости ближе к ФОНУ, чем к телу: t=(Lфон−L)/(Lфон−Lтела) < T_MAX.
     Если тело почти одной яркости с фоном (белый предмет, Lфон−Lтела < MIN_CONTRAST) признак 3 не работает — островок не режем по яркости.
Связанные с телом части (ножки) не трогаются вовсе: режутся только ОТДЕЛЬНЫЕ компоненты.
  clean_islands.py <in.rgba.png> <out.rgba.png> — CLI; печать списка срезанных островков."""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

THR = 0.04            # α, с которой пиксель считается «есть»
MAX_SHARE = 0.03      # островок не крупнее 3 % площади тела
BAND = 0.14           # нижние 14 % высоты тела
CHROMA = 22           # max−min по каналам: «бесцветный»
T_MAX = 0.75          # ближе к фону, чем к телу (0 — как тело, 1 — как фон)
MIN_CONTRAST = 45     # минимум разницы яркости фона и тела для признака 3
GROW = 1              # px: срезаем ещё полоску вокруг (мягкий край блика)


def lum(rgb):
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def clean_islands(rgba: Image.Image, bg_lum: float = 255.0):
    """rgba — вырезка (RGBA). Возвращает (RGBA без островков, отчёт). Тело — самая большая компонента."""
    im = np.asarray(rgba.convert('RGBA')).astype(np.float32)
    rgb, a = im[..., :3], im[..., 3] / 255.0
    lab, n = ndimage.label(a > THR, structure=np.ones((3, 3)))
    info = {'components': int(n), 'removed': [], 'kept_small': []}
    if n < 2:
        return rgba, info
    sizes = ndimage.sum(np.ones_like(a), lab, range(1, n + 1))
    bi = 1 + int(np.argmax(sizes))
    body = lab == bi
    ys, xs = np.where(body)
    y0, y1 = int(ys.min()), int(ys.max())
    h = max(1, y1 - y0 + 1)
    Lc = lum(rgb)
    core = body & (a > 0.9) & (np.arange(a.shape[0])[:, None] < y1 - BAND * h)      # цвет тела — без нижней полосы
    Lb = float(np.median(Lc[core])) if core.any() else float(np.median(Lc[body & (a > 0.9)]))
    info.update(body_px=int(body.sum()), body_lum=round(Lb, 1), bg_lum=bg_lum, body_box=[int(xs.min()), y0, int(xs.max()), y1])
    out = a.copy()
    kill = np.zeros_like(body)
    for i in range(1, n + 1):
        if i == bi:
            continue
        m = lab == i
        area = int(m.sum())
        cy, cx = ndimage.center_of_mass(m)
        mx, mn = rgb[m].max(axis=1), rgb[m].min(axis=1)
        chroma = float((mx - mn).mean())
        L = float(Lc[m].mean())
        t = (bg_lum - L) / (bg_lum - Lb) if (bg_lum - Lb) > 1e-3 else None
        rec = {'area': area, 'center': [round(float(cx), 1), round(float(cy), 1)], 'lum': round(L, 1), 'chroma': round(chroma, 1), 't': None if t is None else round(float(t), 2)}
        in_band = cy >= y1 - BAND * h
        small = area <= MAX_SHARE * body.sum()
        shadowish = chroma <= CHROMA and (bg_lum - Lb) >= MIN_CONTRAST and t is not None and t < T_MAX
        if in_band and small and shadowish:
            kill |= m
            info['removed'].append(rec)
        else:
            rec['why_kept'] = [k for k, ok in (('вне нижней полосы', not in_band), ('крупный', not small), ('не тень-подобен', not shadowish)) if ok]
            info['kept_small'].append(rec)
    if kill.any():
        if GROW:
            kill = ndimage.binary_dilation(kill, np.ones((3, 3)), iterations=GROW) & ~body
        out[kill] = 0.0
    res = np.dstack([rgb, out * 255.0]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(res, 'RGBA'), info


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    r, inf = clean_islands(Image.open(src))
    r.save(dst)
    print('компонент', inf['components'], '| тело', inf.get('body_px'), 'яркость тела', inf.get('body_lum'), '| срезано', len(inf['removed']))
    for k in inf['removed']:
        print('  СРЕЗАН', k)
    for k in inf['kept_small']:
        print('  оставлен', k)
