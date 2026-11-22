#!/usr/bin/env python3
"""T-20261119-04/1 (идея владельца TG 2098): «ФОРМА ГЕНЕРАТОРА + НАСТОЯЩЕЕ ФОТО НА ПОВЕРХНОСТИ» — на процессоре, 0 ₽, в конвейер НЕ встроен.

Пиксели фото товара проецируются на UV-текстуру меша с подобранной камеры: видимые с камеры тексели берут цвет ФОТО, невидимые остаются текстурой
модели; шов по краю видимости смягчён растушёвкой. Сырой GLB не трогается, выход — `<имя>.photo.glb` рядом (заменяется только картинка baseColor).

  1. Камера — те же, что в `recolor_lp`: `color_steps.best_pose` (перебор поворота/наклона по силуэту) + `recolor_lp.refine_align` (масштаб/сдвиг фото по IoU);
     IoU < `recolor_lp.IOU_MIN` (0,6) — ОТКАЗ с причиной, файл не пишется. Проекция — та же ортографическая, что `color_o2.texel_map` / `mesh_render.render`.
  2. Видимость текселя — по ТОЖДЕСТВУ, без допуска глубины (как в localmesh-engine): грани раскладываются в кадр (художник по глубине, `cv2.fillConvexPoly` с номером
     грани); тексель видим, если в его пикселе (или касающемся — `ID_NEIGH`) стоит ЕГО грань. Пиксели у обрыва глубины (`CLIFF`·габарита, поле `CLIFF_MARGIN`) не
     трогаются: там силуэт фото на пиксель-два расходится с рендером, и фото «падает» на деталь за обрывом (ножка, вырез). Угол к камере: вес 1 до `ANGLE_FULL`
     (60°), линейно до 0 на `ANGLE_ZERO` (80°). Рядом с краем силуэта фото (эрозия маски) вес 0 — там смесь с фоном.
  3. Цвет в baseColor: по каждому тексель UV-раскладки (растеризация каждой грани в UV-пространстве, барицентрика → 3D-точка → пиксель кадра → билинейная
     выборка фото). Мелкие дыры в закрашенном (тест видимости не прошёл) закрываются и берут цвет соседей. Шов: вес падает от 1 до 0 на `FADE_R` (3D, доля габарита)
     к ближайшему НЕзакрашенному тексель с похожей нормалью (кроме обратной стороны листа): край зоны, а не край острова UV. Итог = текстура·(1−w) + фото·w.
     Пустые поля вокруг островов (отступ) заполняются соседним новым цветом (до `GUTTER` текселей).
  4. Мерка: IoU камеры, доля текселей из фото (по текселям раскладки; по пикселям кадра), ΔE00 «рендер без света ↔ фото» ДО и ПОСЛЕ — по пикселям кадра, отдельно
     по «фасаду» (грани, смотрящие в камеру, cos ≥ 0,8).
Идея и порядок шагов 2–3 — из localmesh-engine (Quentin Colus, Apache-2.0, https://github.com/Quentincls/localmesh-engine: `projection.py`, `uvraster.py`):
КОД НЕ ВЗЯТ — он на PyTorch, с перспективной камерой и связан с их конвейером (`multivue.cameras`, `Reglages`); здесь переписано на numpy/cv2 под нашу ортографическую камеру.
Риски (смотреть глазами): тень и блик фото уходят в краску; промах на ножках/вырезах (ортографика против перспективы фото); шов на ребре.

  ~/venvs/scout/bin/python photo_project.py <model.glb> <cutout.rgba.png> [--out X.photo.glb] [--feather 1] [--size 1024] [--yaw Y --pitch P] [--modes raw,hf,delight] [--all-visible]  → JSON-итог; файлы <out>.<режим>.photo.glb и <out>.lit-frames.png
  ~/venvs/scout/bin/python photo_project.py --selftest
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import color_o2 as CO  # noqa: E402
import color_steps as CS  # noqa: E402
import recolor_lp as RL  # noqa: E402

FRAME_PX = 1024         # сторона кадра проекции (выше 480 `recolor_lp`: на тексель 2048² надо больше пикселей фото)
ID_NEIGH = 1            # тексель видим, если его грань стоит в его пикселе или в пикселях на расстоянии ≤ ID_NEIGH
CLIFF = 0.02            # обрыв глубины между соседними пикселями кадра, доля габарита
CLIFF_MARGIN = 2        # пикселей вокруг обрыва — не трогаем
FADE_R = 0.012          # радиус растушёвки по 3D, доля габарита (≈ 1 см на метр)
HOLES = 3               # дыры в закрашенном до такого радиуса (текселей) закрываем
ANGLE_FULL = 60.0       # до этого угла между нормалью грани и лучом камеры — вес 1
ANGLE_ZERO = 80.0       # с этого — вес 0 (между — линейно)
FEATHER = 1.0           # σ лёгкого сглаживания веса по UV (текселей) — только против «лесенки»
GUTTER = 6              # на сколько текселей протягивать цвет за край острова
EDGE_ERODE = 3          # эрозия маски фото (пиксели кадра): край силуэта = смесь с фоном
FACADE_COS = 0.8        # «фасад» для мерки ΔE00: грани, смотрящие в камеру ближе ~37°
PLANAR_COS = 0.88       # проецируем только на «почти плоские» грани: нормаль ближе ~28° к лучу камеры (T-04/1, Codex §2)
PLANAR_MIN = 0.02       # …и только на связные куски такой плоскости не меньше этой доли силуэта (фасад, а не ножки и мелочь)
PLANAR_MARGIN = 4       # отступ от края куска и от маски, пикселей кадра: ножки тоньше 2·этого (≈ 3–5 px фото) не трогаем
LP_SIGMA = 40.0         # σ низких частот режимов света, текселей UV (рисунок мельче остаётся, свет и тон — нет)
MODES = ('raw', 'hf', 'delight')   # сырая проекция | высокие частоты фото + яркость модели | простое снятие света (яркость фасада = медиана, рисунок фото)
LIGHT_A, LIGHT_B = (0.35, 0.7, 0.9), (-0.9, 0.5, 0.4)   # два света для кадров проверки «тень не следует за светом»


def projection(parts, yaw: float, pitch: float) -> dict:
    """Те же вращение, масштаб и центр, что в `color_o2.texel_map` (ортографика): экранные x/y и глубина (больше = ближе) каждой вершины каждой части."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    rot = ry.T @ rx.T
    pts = [np.asarray(m.vertices, np.float32) @ rot for m in parts]
    allp = np.vstack(pts)
    span = max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1])) * 1.08 or 1.0
    return {'pts': pts, 'span': float(span), 'ox': float(allp[:, 0].mean()), 'oy': float(allp[:, 1].mean())}


def to_screen(P: dict, pts: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return ((pts[:, 0] - P['ox']) / P['span'] * size + size / 2, size / 2 - (pts[:, 1] - P['oy']) / P['span'] * size, pts[:, 2])


def gather(parts, P: dict, size: int) -> dict:
    """Все грани всех частей одним списком: экранные координаты вершин (F,3), глубины (F,3), UV в текселях (F,3), |cos| нормали к лучу камеры (F,)."""
    sxs, sys_, zs, uxs, uys, cos, p3s, n3s = [], [], [], [], [], [], [], []
    tex0 = None
    for pi, m in enumerate(parts):
        import mesh_render as MR
        tex, uv = MR.texture_of(m)
        if tex is None:
            continue
        if tex0 is None:
            tex0 = tex
        elif tex.shape != tex0.shape or not np.array_equal(tex, tex0):
            raise ValueError('у частей разные baseColor-текстуры — не поддержано (нужна одна картинка на меш)')
        f = np.asarray(m.faces, np.int32)
        sx, sv, z = to_screen(P, P['pts'][pi], size)
        th, tw = tex.shape[:2]
        ux, uy = (uv[:, 0] % 1.0) * (tw - 1), (1.0 - (uv[:, 1] % 1.0)) * (th - 1)
        p = P['pts'][pi]
        n = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
        ln = np.linalg.norm(n, axis=1)
        cos.append(np.abs(n[:, 2]) / np.maximum(ln, 1e-12))
        n3s.append(n / np.maximum(ln, 1e-12)[:, None])
        p3s.append(p[f])
        sxs.append(sx[f]), sys_.append(sv[f]), zs.append(z[f]), uxs.append(ux[f]), uys.append(uy[f])
    if tex0 is None:
        raise ValueError('у меша нет baseColor-текстуры/UV')
    return {'sx': np.vstack(sxs), 'sy': np.vstack(sys_), 'z': np.vstack(zs), 'ux': np.vstack(uxs), 'uy': np.vstack(uys), 'cos': np.concatenate(cos), 'p3': np.concatenate(p3s), 'n3': np.vstack(n3s).astype(np.float32), 'tex': tex0}


def raster_ids(G: dict, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Кадр: номер грани в пикселе (−1 фон; дальние грани рисуются первыми — как `texel_map`) и z-буфер по плоскости грани."""
    import cv2
    ids = np.full((size, size), -1, np.int32)
    order = np.argsort(G['z'].mean(axis=1))
    sx, sy = np.round(G['sx'] * 16).astype(np.int32), np.round(G['sy'] * 16).astype(np.int32)
    for i in order:
        cv2.fillConvexPoly(ids, np.stack([sx[i], sy[i]], 1), int(i), lineType=cv2.LINE_8, shift=4)
    zb = np.full((size, size), -1e9, np.float32)
    yy, xx = np.nonzero(ids >= 0)
    f = ids[yy, xx]
    x0, x1, x2 = G['sx'][f].T
    y0, y1, y2 = G['sy'][f].T
    det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    ok = np.abs(det) > 1e-9
    w0 = np.where(ok, ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) / np.where(ok, det, 1), 1 / 3)
    w1 = np.where(ok, ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) / np.where(ok, det, 1), 1 / 3)
    w0, w1 = np.clip(w0, 0, 1), np.clip(w1, 0, 1)
    w2 = np.clip(1 - w0 - w1, 0, 1)
    z = G['z'][f]
    zb[yy, xx] = w0 * z[:, 0] + w1 * z[:, 1] + w2 * z[:, 2]
    return ids, zb


def cliff_mask(zb: np.ndarray, ids: np.ndarray, size: int) -> np.ndarray:
    """Пиксели у обрыва глубины (скачок между соседями > CLIFF·габарит кадра) и фона — расширены на CLIFF_MARGIN: там фото и рендер расходятся на пиксель-два."""
    from scipy.ndimage import maximum_filter
    cov = ids >= 0
    z = np.where(cov, zb, np.nan)
    jump = np.zeros(zb.shape, bool)
    lim = CLIFF * size
    for dy, dx in ((0, 1), (1, 0)):
        a = z[dy:, dx:]
        b = z[:z.shape[0] - dy, :z.shape[1] - dx]
        j = np.abs(a - b) > lim                              # zb здесь в пикселях кадра (глубина / габарит · size)
        jump[dy:, dx:] |= np.nan_to_num(j, nan=False)
        jump[:zb.shape[0] - dy, :zb.shape[1] - dx] |= np.nan_to_num(j, nan=False)
    return maximum_filter(jump, size=2 * CLIFF_MARGIN + 1)


def planar_mask(ids: np.ndarray, G: dict, size: int) -> tuple[np.ndarray, dict]:
    """Где фото можно класть: почти плоские (cos ≥ PLANAR_COS) связные куски видимого ≥ PLANAR_MIN силуэта, отступ PLANAR_MARGIN px от края куска.
    Тонкое (ножки, рейки: уже 2·отступа) пропадает при отступе — модель там не трогаем."""
    from scipy.ndimage import binary_erosion, label
    cov = ids >= 0
    cs = np.zeros(ids.shape, np.float32)
    cs[cov] = G['cos'][ids[cov]]
    plane = cov & (cs >= PLANAR_COS)
    lab, n = label(plane)
    keep = np.zeros_like(plane)
    areas = []
    for j in range(1, n + 1):
        a = int((lab == j).sum())
        areas.append(a)
        if a >= PLANAR_MIN * cov.sum():
            keep |= lab == j
    out = binary_erosion(keep, iterations=PLANAR_MARGIN)
    return out, {'planar_px': int(keep.sum()), 'allowed_px': int(out.sum()), 'allowed_share': round(float(out.sum() / max(cov.sum(), 1)), 3),
                 'planar_pieces': int(sum(a >= PLANAR_MIN * cov.sum() for a in areas))}


def texel_pass(G: dict, ids: np.ndarray, size: int, bad: np.ndarray) -> dict:
    """Растеризация граней в UV: для каждого тексель — пиксель кадра, видимость ПО ТОЖДЕСТВУ (его грань стоит в пикселе/рядом), вес угла, 3D-точка и нормаль грани.
    `bad` — пиксели у обрыва глубины: тексель на них не трогаем. Тексель, закрытый несколькими гранями раскладки, берёт последнюю."""
    import cv2
    th, tw = G['tex'].shape[:2]
    SX = np.full((th, tw), -1.0, np.float32)
    SY = np.full((th, tw), -1.0, np.float32)
    VIS = np.zeros((th, tw), np.float32)       # вес угла × видимость; 0 — тексель не виден
    COV = np.zeros((th, tw), np.uint8)         # тексель принадлежит какой-то грани
    P3 = np.zeros((th, tw, 3), np.float32)     # 3D-точка (камерные оси, единицы модели)
    FID = np.full((th, tw), -1, np.int32)      # грань текселя
    for i in range(len(G['ux'])):
        cv2.fillConvexPoly(COV, np.round(np.stack([G['ux'][i], G['uy'][i]], 1) * 16).astype(np.int32), 1, lineType=cv2.LINE_8, shift=4)
    ang = np.degrees(np.arccos(np.clip(G['cos'], 0, 1)))
    wang = np.clip((ANGLE_ZERO - ang) / (ANGLE_ZERO - ANGLE_FULL), 0, 1)
    seen = np.unique(ids[ids >= 0])               # грани, у которых в кадре есть хотя бы один пиксель
    cand = seen[G['cos'][seen] > 1e-3] if len(seen) else seen
    k = ID_NEIGH
    for i in cand:
        tx, ty = G['ux'][i], G['uy'][i]
        x0, x1 = int(max(0, math.floor(tx.min()))), int(min(tw - 1, math.ceil(tx.max())))
        y0, y1 = int(max(0, math.floor(ty.min()))), int(min(th - 1, math.ceil(ty.max())))
        if x1 < x0 or y1 < y0:
            continue
        det = (ty[1] - ty[2]) * (tx[0] - tx[2]) + (tx[2] - tx[1]) * (ty[0] - ty[2])
        if abs(det) < 1e-9:
            continue
        gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        w0 = ((ty[1] - ty[2]) * (gx - tx[2]) + (tx[2] - tx[1]) * (gy - ty[2])) / det
        w1 = ((ty[2] - ty[0]) * (gx - tx[2]) + (tx[0] - tx[2]) * (gy - ty[2])) / det
        w2 = 1 - w0 - w1
        e = -0.02
        inside = (w0 >= e) & (w1 >= e) & (w2 >= e)
        if not inside.any():
            continue
        sx = w0 * G['sx'][i, 0] + w1 * G['sx'][i, 1] + w2 * G['sx'][i, 2]
        sy = w0 * G['sy'][i, 0] + w1 * G['sy'][i, 1] + w2 * G['sy'][i, 2]
        px, py = np.clip(np.round(sx).astype(int), 0, size - 1), np.clip(np.round(sy).astype(int), 0, size - 1)
        hit = np.zeros(sx.shape, bool)
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                hit |= ids[np.clip(py + dy, 0, size - 1), np.clip(px + dx, 0, size - 1)] == i
        vis = inside & hit & ~bad[py, px] & (sx >= 0) & (sx <= size - 1) & (sy >= 0) & (sy <= size - 1)
        if not vis.any():
            continue
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        SX[sl][vis] = sx[vis]
        SY[sl][vis] = sy[vis]
        VIS[sl][vis] = wang[i]
        FID[sl][vis] = i
        for c in range(3):
            P3[sl][..., c][vis] = (w0 * G['p3'][i, 0, c] + w1 * G['p3'][i, 1, c] + w2 * G['p3'][i, 2, c])[vis]
    return {'SX': SX, 'SY': SY, 'VIS': VIS, 'COV': COV, 'P3': P3, 'FID': FID, 'n_cand': int(len(cand))}


def fade_weight(T: dict, G: dict, painted: np.ndarray, radius: float, step: int = 3) -> np.ndarray:
    """Вес 0…1 у каждого закрашенного тексель: 0 на краю ЗОНЫ, 1 на расстоянии `radius` (3D) и дальше — гладкая кривая. Границей считается ближайший НЕзакрашенный тексель раскладки с
    похожей нормалью (cos > 0,2): обратная сторона тонкой стенки краем не считается, край острова UV — тоже (зона, а не остров)."""
    from scipy.spatial import cKDTree
    cov = T['COV'].astype(bool)
    non = np.argwhere(cov & ~painted)[::step]
    oui = np.argwhere(painted)
    w = np.ones(painted.shape, np.float32)
    if len(non) == 0 or len(oui) == 0:
        return w
    nrm = G['n3']
    tree = cKDTree(T['P3'][non[:, 0], non[:, 1]])
    nq = nrm[np.maximum(T['FID'][non[:, 0], non[:, 1]], 0)]
    nq = np.where((T['FID'][non[:, 0], non[:, 1]] >= 0)[:, None], nq, 0)
    for i in range(0, len(oui), 500_000):
        o = oui[i:i + 500_000]
        dist, j = tree.query(T['P3'][o[:, 0], o[:, 1]], k=8, distance_upper_bound=radius, workers=-1)
        ok = np.isfinite(dist)
        jj = np.where(ok, j, 0)
        same = ok & (np.einsum('nkc,nc->nk', nq[jj], nrm[T['FID'][o[:, 0], o[:, 1]]]) > 0.2)
        t = np.clip(np.where(same, dist, radius).min(1) / radius, 0.0, 1.0)
        w[o[:, 0], o[:, 1]] = t * t * (3 - 2 * t)
    return w


def relight(tex: np.ndarray, ph: np.ndarray, region: np.ndarray, mode: str, sigma: float = LP_SIGMA) -> np.ndarray:
    """Режим света на закрашиваемой области (`region` — булева маска текселей): цвет фото `ph` (float RGB 0–255) → новый RGB.
    raw — как есть. hf — L = низкие частоты L ТЕКСТУРЫ МОДЕЛИ + высокие частоты L фото; a, b — фото. delight — L = медиана L фото по области + высокие частоты L фото;
    a, b — фото (простое снятие света: градиент освещения каталога не пишется в краску, рисунок остаётся). Низкие частоты — нормированный гаусс внутри области."""
    import cv2
    if mode == 'raw' or not region.any():
        return ph
    m = region.astype(np.float32)

    def low(x):
        num = cv2.GaussianBlur(x * m, (0, 0), sigma)
        den = cv2.GaussianBlur(m, (0, 0), sigma)
        return num / np.maximum(den, 1e-4)
    Lp = RL.lab_f(np.clip(ph, 0, 255))
    hf = Lp[..., 0] - low(Lp[..., 0])
    if mode == 'hf':
        Lm = RL.lab_f(tex)
        L = low(Lm[..., 0]) + hf
    elif mode == 'delight':
        L = float(np.median(Lp[..., 0][region])) + hf
    else:
        raise ValueError(mode)
    out = np.stack([np.clip(L, 0, 100), Lp[..., 1], Lp[..., 2]], -1)
    return RL.l2s8(RL.lab_to_lin(out.astype(np.float32))).astype(np.float32)


def paint(tex: np.ndarray, T: dict, G: dict, prgb: np.ndarray, pmask: np.ndarray, span: float, feather: float = FEATHER, gutter: int = GUTTER,
          radius: float = FADE_R, holes: int = HOLES, mode: str = 'raw', lp_sigma: float = LP_SIGMA) -> tuple[np.ndarray, dict]:
    """Новая текстура: фото на видимых текселях, дыры закрыты, растушёвка по 3D к краю зоны, отступ у островов. → (uint8 RGB, числа)."""
    import cv2
    from scipy.ndimage import distance_transform_edt
    pm = CO.erode(pmask, EDGE_ERODE).astype(np.float32)
    ph = cv2.remap(prgb.astype(np.float32), T['SX'], T['SY'], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    pw = cv2.remap(pm, T['SX'], T['SY'], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    w_raw = T['VIS'] * (pw > 0.999)
    cov = T['COV'].astype(bool)
    n_cov = max(int(cov.sum()), 1)
    painted0 = w_raw > 0.5
    stats = {'texels_covered': int(cov.sum()), 'texels_visible': int((T['VIS'][cov] > 0).sum()), 'texels_photo': int(painted0[cov].sum()),
             'texel_share_photo': round(float(painted0[cov].sum() / n_cov), 4)}
    if holes > 0:                                                    # закрыть мелкие дыры: тексель внутри зоны, но тест видимости не прошёл
        n = 2 * holes + 1
        kern = np.ones((n, n), np.uint8)
        closed = cv2.morphologyEx(painted0.astype(np.uint8), cv2.MORPH_CLOSE, kern).astype(bool) & cov
        hole = closed & ~painted0
        if hole.any():
            num = cv2.blur((w_raw[..., None] * ph) * painted0[..., None], (n, n))
            den = cv2.blur(w_raw * painted0, (n, n))
            ok = hole & (den > 1e-4)
            ph[ok] = (num[ok] / den[ok, None])
            w_raw[ok] = den[ok] * 1.0
            stats['holes_filled'] = int(ok.sum())
    painted = w_raw > 0.5
    ph = relight(tex, ph, painted, mode, lp_sigma)
    fade = fade_weight(T, G, painted, radius * span)
    w = np.clip(w_raw * fade, 0, 1)
    if feather > 0:
        w = np.where(painted, cv2.GaussianBlur(w, (0, 0), feather), w)
    new = tex.astype(np.float32) * (1 - w[..., None]) + ph * w[..., None]
    if gutter > 0 and cov.any():
        d, (iy, ix) = distance_transform_edt(~cov, return_indices=True)
        fill = (~cov) & (d <= gutter)
        new[fill] = new[iy[fill], ix[fill]]
    stats.update(w_mean_photo=round(float(w[painted].mean()), 4) if painted.any() else 0.0, share_full_weight=round(float((w[cov] > 0.95).sum() / n_cov), 4),
                 texel_share_effective=round(float(w[cov].sum() / n_cov), 4))
    return np.clip(np.round(new), 0, 255).astype(np.uint8), stats


def de_report(rgb: np.ndarray, ralpha: np.ndarray, prgb: np.ndarray, pmask: np.ndarray, facade: np.ndarray) -> dict:
    """ΔE00 «рендер без света ↔ фото» по пикселям кадра: всё видимое и «фасад» (грани, смотрящие в камеру)."""
    both = CO.erode(ralpha) & CO.erode(pmask)
    de = RL.de2000(RL.lab_f(rgb)[both], RL.lab_f(prgb)[both])
    out = {'de_med': round(float(np.median(de)), 2), 'de_p90': round(float(np.percentile(de, 90)), 2), 'px': int(both.sum())}
    fa = both & facade
    if fa.sum() > 50:
        d2 = RL.de2000(RL.lab_f(rgb)[fa], RL.lab_f(prgb)[fa])
        out.update(facade_de_med=round(float(np.median(d2)), 2), facade_de_p90=round(float(np.percentile(d2, 90)), 2), facade_px=int(fa.sum()))
    return out


def lf_std(rgb: np.ndarray, mask: np.ndarray, sigma: float = 20.0) -> float | None:
    """Размах низкочастотной светлоты L в маске (σ-размытие): «сколько света запечено» — у модели без запечённой тени мало, у сырого фото с каталожным градиентом больше."""
    import cv2
    if mask.sum() < 100:
        return None
    L = RL.lab_f(rgb)[..., 0]
    m = mask.astype(np.float32)
    low = cv2.GaussianBlur(L * m, (0, 0), sigma) / np.maximum(cv2.GaussianBlur(m, (0, 0), sigma), 1e-4)
    return round(float(low[mask].std()), 2)


def lit_row(glb_list: list, yaw: float, pitch: float, size: int, photo: np.ndarray, crop: tuple) -> np.ndarray:
    """Строка кадров: фото | для каждого GLB — свет A | свет B (обычный Ламберт `mesh_render.render`), обрезка по рамке силуэта."""
    import mesh_render as MR
    y0, y1, x0, x1 = crop
    cells = [photo[y0:y1, x0:x1]]
    for g in glb_list:
        parts = MR.load_parts(g)
        for light in (LIGHT_A, LIGHT_B):
            im = np.asarray(MR.render(parts, yaw_deg=yaw, pitch_deg=pitch, size=(size, size), light=light))
            a = im[..., 3:4].astype(np.float32) / 255 if im.shape[-1] == 4 else 1.0
            rgb = (im[..., :3] * a + 255 * (1 - a)).astype(np.uint8)
            cells.append(rgb[y0:y1, x0:x1])
    return np.concatenate(cells, 1)


def project(glb: str, cutout: str, out: str | None = None, feather: float = FEATHER, size: int = FRAME_PX, yaw: float | None = None,
            pitch: float | None = None, modes: tuple = MODES, planar: bool = True, lp_sigma: float = LP_SIGMA, log=print) -> dict:
    """Весь путь. Камера и видимость считаются ОДИН раз; на каждый режим света (`modes`) — свой `<out>.<режим>.photo.glb`. planar=False — проекция на всё видимое (базовый замер).
    → итог: status 'ok' | 'отказ: …', камера, числа «было/стало» по режимам (ΔE00 всего и фасада, pattern_grad_ncc, размах низкочастотной светлоты), пути."""
    import cv2
    import mesh_render as MR
    import pattern_metric as PM
    from PIL import Image
    t0 = time.time()
    r: dict = {'glb': glb, 'cutout': cutout, 'planar': planar}
    P_in = CS.rgba(cutout)
    if yaw is None:
        pose = CS.best_pose(glb, P_in[..., 3] > 128)
        yaw, pitch = pose['yaw'], pose['pitch']
        r['pose_iou'] = pose['iou']
    r.update(yaw=yaw, pitch=pitch)
    parts = MR.load_parts(glb)
    P = projection(parts, yaw, pitch)
    G = gather(parts, P, size)
    log(f'  граней {len(G["sx"])}, текстура {G["tex"].shape[:2]}, камера yaw {yaw} pitch {pitch}, {time.time() - t0:.0f} с')
    ids, zb = raster_ids(G, size)
    ralpha = ids >= 0
    prgb0, pmask0 = CO.align_photo(P_in, ralpha)
    prgb, pmask, al = RL.refine_align(prgb0, pmask0, ralpha)
    r['align'] = al
    if al['iou'] < RL.IOU_MIN:
        r['status'] = 'отказ: силуэт фото не совпал с рендером (IoU %.2f < %.2f) — камере не верим, файл не записан' % (al['iou'], RL.IOU_MIN)
        return r
    log(f'  кадр: {int(ralpha.sum())} пикс., IoU камеры {al["iou"]} (до доводки {al["iou0"]}), {time.time() - t0:.0f} с')
    cliff = cliff_mask(zb / P['span'] * size, ids, size)
    allowed, pinfo = planar_mask(ids, G, size)
    r['planar_info'] = pinfo
    bad = (cliff | ~allowed) if planar else cliff
    T = texel_pass(G, ids, size, bad)
    log(f'  тексели: кандидатов-граней {T["n_cand"]}, видимых текселей {int((T["VIS"] > 0).sum())}, допущено пикселей {pinfo["allowed_px"]} ({pinfo["allowed_share"]}), {time.time() - t0:.0f} с')
    ys, xs = np.nonzero(ralpha)
    facade = np.zeros_like(ralpha)
    facade[ys, xs] = G['cos'][ids[ys, xs]] >= FACADE_COS
    fmask = (allowed if planar else facade) & CO.erode(ralpha) & CO.erode(pmask)         # где меряем рисунок
    base = np.asarray(RL.render_unlit(glb, yaw, pitch, size))
    r['was'] = de_report(base[..., :3], base[..., 3] > 128, prgb, pmask, facade)
    r['was']['pattern'] = PM.pattern_grad_ncc(base[..., :3], prgb, fmask)
    r['was']['lf_std'] = lf_std(base[..., :3], fmask)
    r['photo_lf_std'] = lf_std(prgb, fmask)
    r['facade_share'] = round(float(facade.sum() / max(ralpha.sum(), 1)), 3)
    r['modes'] = {}
    stem = out[:-4] if out and out.endswith('.glb') else (out or (glb[:-4] if glb.endswith('.glb') else glb))
    if stem.endswith('.photo'):
        stem = stem[:-6]
    outs = []
    for mode in modes:
        new_tex, st = paint(G['tex'], T, G, prgb, pmask, P['span'], feather, mode=mode, lp_sigma=lp_sigma)
        st['cliff_px_share'] = round(float(bad[ralpha].mean()), 4)
        path = f'{stem}.{mode}.photo.glb'
        RL.rewrite_glb(glb, path, lambda arr, nt=new_tex: (nt if arr.shape[:2] == nt.shape[:2] else None, {'photo_project': mode}))
        now = np.asarray(RL.render_unlit(path, yaw, pitch, size))
        m = de_report(now[..., :3], now[..., 3] > 128, prgb, pmask, facade)
        m['pattern'] = PM.pattern_grad_ncc(now[..., :3], prgb, fmask)
        m['lf_std'] = lf_std(now[..., :3], fmask)
        r['modes'][mode] = {'out': path, 'paint': st, 'now': m, 'glb_mb': round(os.path.getsize(path) / 1e6, 2)}
        outs.append(path)
        log(f'  режим {mode}: ΔE00 {r["was"]["de_med"]}→{m["de_med"]}, фасад {r["was"].get("facade_de_med")}→{m.get("facade_de_med")}, pattern {r["was"]["pattern"]["median"]}→{m["pattern"]["median"]}, {time.time() - t0:.0f} с')
    # кадры: фото | исходник A,B | raw A,B | hf A,B | delight A,B — обрезка по рамке силуэта
    yy, xx = np.nonzero(ralpha)
    pad = 12
    crop = (max(yy.min() - pad, 0), min(yy.max() + pad, size), max(xx.min() - pad, 0), min(xx.max() + pad, size))
    ph_bg = np.where(pmask[..., None], prgb, 255).astype(np.uint8)
    row = lit_row([glb] + outs, yaw, pitch, size, ph_bg, crop)
    png = f'{stem}.lit-frames.png'
    Image.fromarray(row).save(png)
    r.update(status='ok', frames=png, secs=round(time.time() - t0, 1))
    return r


def selftest() -> int:
    """Без внешних файлов: плоский «комод»-ящик с текстурой-шумом, «фото» — известная картинка на его лицевой стороне; после проекции рендер совпадает с фото,
    тыл остаётся текстурой модели; несовпавший силуэт — отказ без файла."""
    import tempfile

    import trimesh
    from PIL import Image
    fails = []

    def check(n, c, e=''):
        print(('OK   ' if c else 'FAIL ') + n + (f'  [{e}]' if e else ''))
        if not c:
            fails.append(n)
    tmp = tempfile.mkdtemp(prefix='photo_project_')
    rng = np.random.default_rng(1)
    noise = (rng.random((256, 256, 3)) * 60 + 80).astype(np.uint8)
    box = trimesh.creation.box(extents=(1.0, 0.6, 0.4))
    # UV: каждая грань — своя область текстуры (грани разворачиваем вручную по плоскостям)
    verts, faces, uvs = [], [], []
    for fi, f in enumerate(box.faces):
        v = box.vertices[f]
        n = np.cross(v[1] - v[0], v[2] - v[0])
        n = n / np.linalg.norm(n)
        a = np.argmax(np.abs(n))
        ax = [i for i in range(3) if i != a]
        uv0 = (v[:, ax] - box.vertices[:, ax].min(0)) / np.ptp(box.vertices[:, ax], 0)
        tile = a * 2 + int(n[a] > 0)                                   # шесть сторон — шесть своих клеток 3×2 в текстуре
        uv = np.array([(tile % 3) / 3, (tile // 3) / 2]) + (0.02 + 0.96 * uv0) * np.array([1 / 3, 1 / 2])
        base = len(verts)
        verts.extend(v.tolist())
        uvs.extend(uv.tolist())
        faces.append([base, base + 1, base + 2])
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.array(uvs), material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(noise)))
    glb = os.path.join(tmp, 'box.glb')
    mesh.export(glb)
    import mesh_render as MR
    parts = MR.load_parts(glb)
    P = projection(parts, 0.0, 0.0)
    G = gather(parts, P, 256)
    ids, zb = raster_ids(G, 256)
    check('кадр: ящик занимает пиксели, z-буфер заполнен', (ids >= 0).sum() > 5000 and (zb[ids >= 0] > -1e8).all())
    # «фото» — тот же силуэт, яркий цветной градиент (цель — увидеть его на рендере)
    ys, xs = np.nonzero(ids >= 0)
    ph = np.zeros((256, 256, 4), np.uint8)
    ph[ys, xs, 0] = (200 + 0 * xs).astype(np.uint8)
    ph[ys, xs, 1] = np.clip(60 + (xs - xs.min()) * 150 // max(np.ptp(xs), 1), 0, 255).astype(np.uint8)
    ph[ys, xs, 2] = 40
    ph[ys, xs, 3] = 255
    cut = os.path.join(tmp, 'cut.rgba.png')
    Image.fromarray(ph).save(cut)
    res = project(glb, cut, yaw=0.0, pitch=0.0, size=256, planar=False, modes=('raw',), log=lambda *a: None)
    mr = res['modes']['raw']
    check('проекция ok, файл записан', res['status'] == 'ok' and os.path.exists(mr['out']), str(res.get('status')))
    check('IoU камеры высокий', res['align']['iou'] > 0.95, str(res['align']))
    check('ΔE00 к фото упало (было → стало)', mr['now']['de_med'] < 0.5 * res['was']['de_med'] and mr['now']['de_med'] < 6, f"{res['was']['de_med']} → {mr['now']['de_med']}")
    check('доля текселей из фото есть, но не вся раскладка (тыл — текстура модели)', 0.05 < mr['paint']['texel_share_photo'] < 0.6, str(mr['paint']['texel_share_photo']))
    check('сырой GLB не тронут, выход — рядом с суффиксом .photo.glb', mr['out'] != glb and mr['out'].endswith('.raw.photo.glb'))
    # узкая проекция (только почти плоское с отступом) и режимы света: фасад ящика — одна плоскость; градиент яркости фото в `delight` уходит, в `raw` остаётся
    res3 = project(glb, cut, yaw=0.0, pitch=0.0, size=256, planar=True, modes=('raw', 'hf', 'delight'), lp_sigma=6.0, log=lambda *a: None)
    check('planar: допущена плоскость фасада, отступ от края', res3['status'] == 'ok' and 0.5 < res3['planar_info']['allowed_share'] < 0.95, str(res3['planar_info']))
    m3 = res3['modes']
    check('delight: размах низкочастотной светлоты ниже, чем у raw (свет фото не запечён)', m3['delight']['now']['lf_std'] < 0.6 * m3['raw']['now']['lf_std'],
          f"raw {m3['raw']['now']['lf_std']} hf {m3['hf']['now']['lf_std']} delight {m3['delight']['now']['lf_std']}")
    check('три режима — три разных файла, кадры света записаны', len({m3[k]['out'] for k in m3}) == 3 and os.path.exists(res3['frames']))
    # отказ по силуэту: фото-треугольник вместо ящика
    ph2 = np.zeros((256, 256, 4), np.uint8)
    yy, xx = np.mgrid[:256, :256]
    ph2[(yy > 40) & (yy < 220) & (xx > 40) & ((xx - 40) < (yy - 40))] = (10, 200, 10, 255)       # прямоугольный треугольник: после вписывания в рамку IoU ≈ 0,5
    cut2 = os.path.join(tmp, 'cut2.rgba.png')
    Image.fromarray(ph2).save(cut2)
    out2 = os.path.join(tmp, 'x.photo.glb')
    res2 = project(glb, cut2, out=out2, yaw=0.0, pitch=0.0, size=256, planar=False, modes=('raw',), log=lambda *a: None)
    check('несовпавший силуэт — отказ, файла нет', res2['status'].startswith('отказ') and not os.path.exists(out2) and not os.path.exists(os.path.join(tmp, 'x.raw.photo.glb')), res2['status'][:90])
    print('\nПРОВАЛЕНО: ' + ', '.join(fails) if fails else '\nвсё прошло')
    return 1 if fails else 0


def main() -> int:
    a = sys.argv[1:]
    if '--selftest' in a:
        return selftest()
    if len(a) < 2:
        print(__doc__)
        return 2

    def opt(n, d=None, t=str):
        return t(a[a.index(n) + 1]) if n in a else d
    modes = tuple(opt('--modes', ','.join(MODES)).split(','))
    r = project(a[0], a[1], opt('--out'), opt('--feather', FEATHER, float), opt('--size', FRAME_PX, int), opt('--yaw', None, float), opt('--pitch', None, float), modes, '--all-visible' not in a,
                opt('--lp-sigma', LP_SIGMA, float))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r['status'] == 'ok' else 3


if __name__ == '__main__':
    sys.exit(main())
