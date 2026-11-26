"""Тонкая плита — один материал (T-97/1 фаза 7; план paint-variant-a-code-01 п.7; проба р.2 t97-1126-run/p7, Киннер v4d). ВЫКЛЮЧЕНО (`rules/part-grain.json` → thin_plate.enabled=false): модуль не вызывается, ни одного байта текстуры не трогает.

ПРАВИЛО (общее, без ID и имён товаров). Если верх (роль «верх») — тонкая плита (толщина ≪ длины и ширины), то её НИЗ и ТОРЕЦ красятся тоном и волокном ЛИЦА: каждому тексели низа/торца кладётся цвет ближайшего (в плане) тексели лица.
Это про тело столешницы целиком: у цельной сетки TRELLIS видимый снизу «низ» — часто отдельная панель другой роли (ножки) под лицом, поэтому низ плиты берётся по самой нижней крупной плоскости ЛЮБОЙ роли, а не по роли «верх».
ШАГИ (по порядку; пороги — rules.thin_plate):
 1. Ось «вверх» = ось с наибольшей площадью граней, смотрящих вдоль неё. Лицо: грани роли «верх», смотрящие вверх; y_лицо = взвешенный по площади квантиль face_quantile высот.
 2. Низ: самая нижняя плоскость вниз-смотрящих граней любой роли в пределах t_max = thin_ratio·min(размеры верха в плане) под лицом, площадью бина ≥ bin_area_frac·площади лица (шаг бина bin_step, единицы GLB); y_низ — взвешенная медиана двух бинов.
    Тонкая, если есть такой низ и толщина y_лицо − y_низ < t_max. Не тонкая → ничего не меняется (причина в след).
 3. Плита S: грани «низ» (вниз-смотрящие, высота в [y_низ − down_below·t, y_низ + down_above·t]) + грани «торец» (|n_вверх| ≤ side_n_max, высота от y_низ до y_лицо + side_above·t).
 4. Что красим: тексели S, не общие с гранями вне S, и не «известные на фото» (known); общие тексели — по владельцу (подпикселей S ≥ чужих в 2× растре). Известные, лежащие только на гранях низа, считаются неизвестными (камера фото снизу их не видит).
    Видимый на фото торец (известные) — свой, не трогаем.
 5. Цвет: ближайший (cKDTree в плане) тексель лица (грани лица с высотой выше y_лицо − face_depth·t); дальше max_pair_steps шагов лица — не красим.
 6. Швы: тексели S по растру без центра в грани S и тексели зазора рядом с перекрашенными (≤ dilate_px, ближе к перекрашенному, чем к чужому) берут цвет ближайшего перекрашенного — иначе фильтрация текстуры тянет в шов старый цвет.
Вход — текстура ПОСЛЕ зерна (part_grain_stage), так что низ получает то же волокно, что и лицо. Возвращает новую текстуру и маску перекрашенных текселей (для `part_grain_mask.png`: 07 на них своей фактуры не кладёт)."""
from __future__ import annotations

import numpy as np

KEYS = ('thin_ratio', 'bin_step', 'bin_area_frac', 'face_quantile', 'face_n_min', 'side_n_max', 'down_below', 'down_above', 'side_above', 'face_depth', 'max_pair_steps', 'dilate_px', 'fill_inside_px')


def check_rules(tp: dict) -> None:
    miss = [k for k in KEYS if k not in tp]
    if miss:
        raise ValueError('part-grain.json: thin_plate без ключей %s' % miss)
    if not (0 < float(tp['thin_ratio']) <= 0.5) or not (0 < float(tp['bin_step']) < 0.05) or not (0 < float(tp['bin_area_frac']) <= 1) or not (0.5 < float(tp['face_quantile']) <= 1.0):
        raise ValueError('part-grain.json: thin_plate — толщина/шаг/доля/квантиль вне пределов')
    if not (0.3 <= float(tp['face_n_min']) < 1) or not (0 < float(tp['side_n_max']) <= 0.9) or int(tp['dilate_px']) < 0 or int(tp['fill_inside_px']) < 0 or float(tp['max_pair_steps']) <= 0:
        raise ValueError('part-grain.json: thin_plate — нормали/дилатация/пары вне пределов')


def _wq(x, w, q):
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, q * cw[-1])])


def _raster(uv_img, F, sel, T):
    import cv2
    m = np.zeros((T, T), np.uint8)
    for i in np.nonzero(sel)[0]:
        cv2.fillConvexPoly(m, np.round(uv_img[F[i]] * T).astype(np.int32), 1)
    return m.astype(bool)


def _texel_pos(sel, V, uv_img, F, PL, T):
    """Для граней sel → (ix, iy, X, Z): центры текселей внутри UV-треугольника и их позиция в плане (барицентрически)."""
    ix_l, iy_l, x_l, z_l = [], [], [], []
    for i in np.nonzero(sel)[0]:
        uv = uv_img[F[i]].astype(np.float64) * T
        x0, x1 = int(np.floor(uv[:, 0].min())), int(np.ceil(uv[:, 0].max()))
        y0, y1 = int(np.floor(uv[:, 1].min())), int(np.ceil(uv[:, 1].max()))
        if x1 <= x0 or y1 <= y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        d = (uv[1, 1] - uv[2, 1]) * (uv[0, 0] - uv[2, 0]) + (uv[2, 0] - uv[1, 0]) * (uv[0, 1] - uv[2, 1])
        if abs(d) < 1e-12:
            continue
        l0 = ((uv[1, 1] - uv[2, 1]) * (gx - uv[2, 0]) + (uv[2, 0] - uv[1, 0]) * (gy - uv[2, 1])) / d
        l1 = ((uv[2, 1] - uv[0, 1]) * (gx - uv[2, 0]) + (uv[0, 0] - uv[2, 0]) * (gy - uv[2, 1])) / d
        l2 = 1 - l0 - l1
        m = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        if not m.any():
            continue
        p3 = V[F[i]].astype(np.float64)
        ix_l.append(np.floor(gx[m]).astype(np.int64))
        iy_l.append(np.floor(gy[m]).astype(np.int64))
        x_l.append(l0[m] * p3[0, PL[0]] + l1[m] * p3[1, PL[0]] + l2[m] * p3[2, PL[0]])
        z_l.append(l0[m] * p3[0, PL[1]] + l1[m] * p3[1, PL[1]] + l2[m] * p3[2, PL[1]])
    if not ix_l:
        e = np.zeros(0, np.int64)
        return e, e, np.zeros(0), np.zeros(0)
    ix, iy = np.concatenate(ix_l), np.concatenate(iy_l)
    ok = (ix >= 0) & (ix < T) & (iy >= 0) & (iy < T)
    return ix[ok], iy[ok], np.concatenate(x_l)[ok], np.concatenate(z_l)[ok]


def apply(tex, V, uv_img, F, face_group, top_gi: int, known, tp: dict):
    """tex (T,T,3) uint8 после зерна; V (n,3) позиции GLB; uv_img (n,2) — (u, v как строка текстуры: row = v·T); F (m,3); face_group (m,) int; top_gi — индекс группы «верх»; known (T,T) bool; tp = rules['thin_plate'].
    → (новая текстура, маска перекрашенных (T,T) bool, след dict). Не тонкая / нет лица → текстура та же, маска пустая, в следе причина."""
    from scipy import ndimage
    from scipy.spatial import cKDTree
    T = int(tex.shape[0])
    info = {'applied': False, 'reason': None}
    empty = np.zeros((T, T), bool)
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    fg = np.asarray(face_group)
    a, b, c = (V[F[:, i]] for i in range(3))
    n = np.cross(b - a, c - a)
    ar = np.linalg.norm(n, axis=1) / 2
    n /= np.maximum(2 * ar, 1e-20)[:, None]
    cen = (a + b + c) / 3
    UP = int(np.argmax([ar[np.abs(n[:, k]) > 0.9].sum() for k in range(3)]))
    PL = [k for k in range(3) if k != UP]
    nu = n[:, UP]
    h = cen[:, UP]
    fn_min, sn_max = float(tp['face_n_min']), float(tp['side_n_max'])
    upm = (nu > fn_min) & (fg == top_gi)
    if not upm.any():
        info['reason'] = 'нет граней лица (верх, смотрит вверх)'
        return tex, empty, info
    y_top = _wq(h[upm], ar[upm], float(tp['face_quantile']))
    ext = [float(np.ptp(cen[fg == top_gi][:, k])) for k in PL]
    t_max = float(tp['thin_ratio']) * min(ext)
    A_lica = float(ar[upm].sum())
    dall = (nu < -fn_min) & (h >= y_top - t_max) & (h < y_top)
    step = float(tp['bin_step'])
    info.update(ось_вверх=UP, y_лицо=round(y_top, 4), размеры_верха=[round(e, 3) for e in ext], t_max=round(t_max, 4), A_лица=round(A_lica, 4))
    if not dall.any():
        info['reason'] = 'нет вниз-смотрящих граней под лицом в пределах t_max'
        return tex, empty, info
    bins = np.floor((h[dall] - (y_top - t_max)) / step).astype(int)
    area_b = np.bincount(bins, weights=ar[dall])
    cand = [k for k in range(len(area_b)) if area_b[k] >= float(tp['bin_area_frac']) * A_lica]
    if not cand:
        info['reason'] = 'нет крупной нижней плоскости (площадь бина < %.2f площади лица)' % float(tp['bin_area_frac'])
        return tex, empty, info
    k0 = cand[0]
    sel0 = dall & (h >= y_top - t_max + k0 * step) & (h < y_top - t_max + (k0 + 2) * step)
    y_bot = _wq(h[sel0], ar[sel0], 0.5)
    t = y_top - y_bot
    info.update(y_низ=round(y_bot, 4), толщина=round(t, 4))
    if not t < t_max:
        info['reason'] = 'не тонкая: толщина %.4f ≥ %.4f' % (t, t_max)
        return tex, empty, info
    lo_ = y_bot - float(tp['down_below']) * t
    hi_ = y_top + float(tp['side_above']) * t
    down = (nu < -fn_min) & (h >= lo_) & (h <= y_bot + float(tp['down_above']) * t)
    side = (np.abs(nu) <= sn_max) & (h >= y_bot) & (h <= hi_)
    S = down | side
    face_lica = (nu > fn_min) & (h > y_top - float(tp['face_depth']) * t) & (fg == top_gi)
    R_S = _raster(uv_img, F, S, T)
    R_O = _raster(uv_img, F, ~S, T)
    S2 = _raster_sub(uv_img, F, S, T)
    O2 = _raster_sub(uv_img, F, ~S, T)
    known = np.asarray(known, bool)
    R_dn = _raster(uv_img, F, down, T)
    R_sd = _raster(uv_img, F, side, T)
    known_dn = known & R_dn & ~R_sd & ~R_O
    known = known & ~known_dn
    own = R_S & R_O & (S2 >= O2)
    change = (R_S & ~R_O & ~known) | (own & ~known)
    lx, ly, lX, lZ = _texel_pos(face_lica, V, uv_img, F, PL, T)
    if len(lx) == 0:
        info['reason'] = 'у лица нет текселей'
        return tex, empty, info
    sx, sy, sX, sZ = _texel_pos(S, V, uv_img, F, PL, T)
    mm = change[sy, sx]
    sx, sy, sX, sZ = sx[mm], sy[mm], sX[mm], sZ[mm]
    tree = cKDTree(np.stack([lX, lZ], 1))
    dist, idx = tree.query(np.stack([sX, sZ], 1))
    spacing = float(np.median(tree.query(np.stack([lX[::50], lZ[::50]], 1), k=2)[0][:, 1]))
    ok = dist < float(tp['max_pair_steps']) * spacing
    out = tex.copy()
    out[sy[ok], sx[ok]] = tex[ly[idx[ok]], lx[idx[ok]]]
    done = np.zeros((T, T), bool)
    done[sy[ok], sx[ok]] = True
    N = int(tp['dilate_px'])
    dd, (gy_, gx_) = ndimage.distance_transform_edt(~done, return_indices=True)
    foreign = (R_O & ~R_S) | (R_S & known & ~done)
    df = ndimage.distance_transform_edt(~foreign)
    grow_gap = ~(R_S | R_O) & (dd <= N) & (dd < df)
    grow_in = R_S & ~R_O & ~known & ~done & (dd <= int(tp['fill_inside_px']))
    grow = grow_gap | grow_in
    out[grow] = out[gy_[grow], gx_[grow]]
    changed = done | grow
    info.update(applied=True, тонкая=True, граней_низ=int(down.sum()), граней_торец=int(side.sum()), тексели_плиты=int(R_S.sum()), тексели_общие=int((R_S & R_O).sum()),
                известных_только_на_низе_снято=int(known_dn.sum()), общих_по_владельцу=int((own & ~known).sum()), для_перекраски=int(change.sum()), перекрашено_цветом_лица=int(done.sum()),
                не_нашли_пары=int((~ok).sum()), дозаполнено_внутри=int(grow_in.sum()), дозаполнено_зазор=int(grow_gap.sum()), перекрашено_текселей=int(changed.sum()))
    return out, changed, info


def _raster_sub(uv_img, F, sel, T):
    """Покрытие в 2× растре, свёрнутое в сетку T: число подпикселей на тексель (владелец общего тексели)."""
    return _raster(uv_img, F, sel, 2 * T).reshape(T, 2, T, 2).sum((1, 3))
