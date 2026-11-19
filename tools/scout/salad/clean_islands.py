#!/usr/bin/env python3
"""T-93: шаг чистки ПОСЛЕ маски (после гибрида/components) — общее правило, без особых случаев:
  убрать отдельные островки у нижней кромки предмета, которые похожи на ТЕНЬ/БЛИК ПОЛА, а не на сам предмет.
Признаки (все относительные — от цвета самого тела, не константы под товар):
  1. островок — связная область α>THR (8-связность), НЕ главное тело и меньше MAX_SHARE от него;
  2. (только при BAND_ONLY) лежит в нижней полосе предмета: его центр ниже (низ_тела − BAND·высота_тела); по умолчанию — где угодно по контуру;
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
CRUMB_MIN = 4         # px: отдельный кусок не больше этого — крошка, срезается при любом цвете (T-99/2: серые крупинки у углов белого комода)
CRUMB_REL = 2e-5      # …или не больше этой доли площади тела (диван 1,5 млн px → 30 px)
BAND_ONLY = False     # True — как в пробе T-93: только нижняя полоса BAND (тень пола); по умолчанию — весь контур
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
        in_band = True if not BAND_ONLY else cy >= y1 - BAND * h      # T-99: по всему контуру (крошки над спинкой, сбоку), не только у низа
        small = area <= MAX_SHARE * body.sum()
        shadowish = chroma <= CHROMA and (bg_lum - Lb) >= MIN_CONTRAST and t is not None and t < T_MAX
        crumb = area <= max(CRUMB_MIN, CRUMB_REL * body.sum())      # T-99/2: «крошка» — отдельный кусок в несколько пикселей; цвет не важен (у светлого товара тоже)
        if crumb or (in_band and small and shadowish):
            kill |= m
            rec['crumb'] = bool(crumb)
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


# ---- T-107: «крупинка, похожая на фон» на кромке --------------------------------------------------------------------------------------
# Над светлой дубовой крышкой комода остаются кремовые точки: они не отдельные островки (касаются тела, 8-связность их приклеила), цвет почти
# фона (cream 254,243,227 при фоне 255), но `clean_islands` берёт только крошки ≤ max(4 px, 2e-5·тело), `edge_halo` требует тёмного соседа,
# `components.clean` оставляет всё ближе NEAR_PX к телу. Ни одно правило не спрашивало «похож ли кусочек на ФОН» (для дырок такая проверка
# есть — `components.fill_holes_unlike_bg`). Правило: связный кусок ПОХОЖИХ НА ФОН пикселей, лежащий на кромке (касается пустоты или края кадра),
# КОМПАКТНЫЙ (не длиннее SPECK_MAX_SIDE_REL·ширина тела, не меньше SPECK_MIN_SIDE px) и заметно светлее соседнего тела (≥ SPECK_CONTRAST) — убрать.
# Вытянутое/крупное (провод, трос, ножка, белая трубка, белый корпус) — длиннее предела или не светлее тела — не трогается. Откат: убрано > SPECK_MAX_SHARE тела.
SPECK_BG_DIST = 45        # «похож на фон»: расстояние до цвета фона по RGB ≤ (кремовые точки комода: 24–36)
SPECK_MIN_SIDE = 6        # px: куски короче этого — всегда «компактные»
SPECK_MAX_SIDE_REL = 0.015  # …длиннее max(SPECK_MIN_SIDE, это·ширина тела) — уже не крупинка
SPECK_CONTRAST = 35       # на столько светлее соседнего тела (яркость), иначе это часть светлого тела
SPECK_REF_NEAR, SPECK_REF_FAR = 3, 10   # px: кольцо, по которому берём цвет соседнего тела
SPECK_MIN_THICK = 3       # px: соседнее тело толще (расстояние до пустоты у кольца ≥ этого) — иначе это провод/трос/тонкая ножка: их и точки при них не трогаем
SPECK_MAX_SHARE = 0.01    # откат: убрано больше 1 % площади тела


def clean_bg_like_specks(rgba: Image.Image, bg_rgb=(255.0, 255.0, 255.0)):
    """→ (RGBA без крупинок, {'removed_px', 'pieces', 'skipped'?}). bg_rgb — цвет фона каталога (по углам исходного фото)."""
    im = np.asarray(rgba.convert('RGBA')).astype(np.float32)
    rgb, a = im[..., :3], im[..., 3] / 255.0
    al = a > THR
    rep = {'removed_px': 0, 'pieces': 0}
    if not al.any():
        return rgba, rep
    ys, xs = np.where(al)
    body_w = int(xs.max() - xs.min() + 1)
    max_side = max(SPECK_MIN_SIDE, int(round(SPECK_MAX_SIDE_REL * body_w)))
    dist = np.linalg.norm(rgb - np.array(bg_rgb, np.float32), axis=2)
    Lc = lum(rgb)
    on_edge = ndimage.binary_dilation(~al, np.ones((3, 3)), border_value=1) & al          # кромка: касается пустоты или края кадра
    thick = ndimage.distance_transform_edt(np.pad(al, 1))[1:-1, 1:-1]      # толщина тела: расстояние до пустоты (край кадра — тоже пустота)
    cand = al & (dist <= SPECK_BG_DIST)
    lab, n = ndimage.label(cand, structure=np.ones((3, 3)))
    if n == 0:
        return rgba, rep
    kill = np.zeros(al.shape, bool)
    pieces = 0
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        pad = SPECK_REF_FAR + 1
        y0, y1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, al.shape[0])
        x0, x1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, al.shape[1])
        m = lab[y0:y1, x0:x1] == i
        if not (m & on_edge[y0:y1, x0:x1]).any():
            continue                                                  # внутри тела (блик) — не кромка
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if max(h, w) > max_side:
            continue                                                  # длинное/крупное — провод, трос, ножка, светлая часть товара
        ring = (ndimage.binary_dilation(m, np.ones((3, 3)), iterations=SPECK_REF_FAR)
                & ~ndimage.binary_dilation(m, np.ones((3, 3)), iterations=SPECK_REF_NEAR)
                & al[y0:y1, x0:x1] & ~(lab[y0:y1, x0:x1] > 0))
        if ring.sum() < 6:
            continue                                                  # соседнего тела нет — это не крупинка на теле
        if float(np.median(thick[y0:y1, x0:x1][ring])) < SPECK_MIN_THICK:
            continue                                                  # рядом тонкое (провод, трос, ножка) — не трогаем
        if float(Lc[y0:y1, x0:x1][m].mean()) - float(np.median(Lc[y0:y1, x0:x1][ring])) < SPECK_CONTRAST:
            continue                                                  # не светлее тела — часть светлого тела
        kill[y0:y1, x0:x1] |= m
        pieces += 1
    if not kill.any():
        return rgba, rep
    grown = ndimage.binary_dilation(kill, np.ones((3, 3))) & al & (dist <= SPECK_BG_DIST + 20)    # мягкая кромка крупинки
    kill |= grown
    removed = int(kill.sum())
    if removed > SPECK_MAX_SHARE * al.sum():
        rep['skipped'] = f'убрать пришлось бы {removed} px (> {SPECK_MAX_SHARE:.0%} тела) — не трогаем'
        return rgba, rep
    out = a.copy()
    out[kill] = 0.0
    rep.update(removed_px=removed, pieces=pieces)
    return Image.fromarray(np.dstack([rgb, out * 255.0]).clip(0, 255).astype(np.uint8), 'RGBA'), rep


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    r, inf = clean_islands(Image.open(src))
    r.save(dst)
    print('компонент', inf['components'], '| тело', inf.get('body_px'), 'яркость тела', inf.get('body_lum'), '| срезано', len(inf['removed']))
    for k in inf['removed']:
        print('  СРЕЗАН', k)
    for k in inf['kept_small']:
        print('  оставлен', k)
