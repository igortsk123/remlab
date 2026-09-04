#!/usr/bin/env python3
"""Фронт корпусной мебели (комод/тв-тумба): владелец 31.08 — «у них ручки спереди мелкие».

Силуэт и цвет фронт таких не видят; признак фасада — ДЕТАЛЬНОСТЬ: ручки, филёнки, ниши
дают плотность краёв в рендере, задняя стенка у генератора ровная. Считаем edge density
четырёх сторон (yaw 0/90/180/270), фронт = максимум; малый отрыв → не уверены.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))


UP_HYPS = {                       # 6 осей «что считать верхом» (канон: topview_render)
    'I':    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    'X180': [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
    'X90':  [[1, 0, 0], [0, 0, -1], [0, 1, 0]],
    'X-90': [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
    'Z90':  [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
    'Z-90': [[0, 1, 0], [-1, 0, 0], [0, 0, 1]],
}

CABINET_ROLES = {'комод', 'тв-тумба', 'тумба'}


def front_by_detail(glb: str) -> tuple[float, float]:
    """→ (yaw фронта, отрыв top1-top2 в долях). Отрыв <0.12 — считать неуверенным."""
    import mesh_render as MR
    parts = MR.load_parts(glb)
    scores = {}
    for yaw in (0, 90, 180, 270):
        img = MR.render(parts, yaw_deg=yaw, pitch_deg=8.0, size=(420, 420))
        a = np.asarray(img).astype(np.float32)
        alpha = a[..., 3] > 8
        if alpha.sum() < 500:
            scores[yaw] = 0.0
            continue
        g = a[..., :3].mean(axis=2)
        gx = np.abs(np.diff(g, axis=1))[:, :]
        gy = np.abs(np.diff(g, axis=0))[:, :]
        m = alpha[:, 1:] & alpha[:, :-1]
        my = alpha[1:, :] & alpha[:-1, :]
        edges = (gx[m].mean() if m.any() else 0) + (gy[my].mean() if my.any() else 0)
        scores[yaw] = float(edges)
    order = sorted(scores, key=scores.get, reverse=True)
    top1, top2 = scores[order[0]], scores[order[1]]
    margin = (top1 - top2) / max(top1, 1e-6)
    return float(order[0]), float(margin)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--front-by-depth':
        # Вызов из topview_render ДОЧЕРНИМ процессом (04.09): trimesh на плотных Hunyuan-мешах не
        # отдаёт память (+100 МБ/меш), и второй полный load меша в родителе топ-вью был одной из
        # двух причин 10 ГБ и earlyoom. Печатаем только [yaw, источник] — dbg наружу не нужен.
        import json as _json
        _yaw, _src, _ = front_by_depth(sys.argv[2])
        print(_json.dumps([_yaw, _src]))
    else:
        print(front_by_detail(sys.argv[1]))


def front_combo(glb: str, cutout_png: str | None) -> tuple[float | None, str]:
    """Два сигнала: детальность (ручки) + сходство с фото (фасад в кадре).
    Согласны → (yaw, 'cabinet_agree'); расходятся/слабо → (None, 'cabinet_unsure')."""
    import mesh_render as MR
    from PIL import Image
    parts = MR.load_parts(glb)
    e_scores, p_scores = {}, {}
    photo = None
    if cutout_png and os.path.exists(cutout_png):
        ph = Image.open(cutout_png).convert('RGBA')
        pa = np.asarray(ph).astype(np.float32)
        pm = pa[..., 3] > 100
        if pm.sum() > 500:
            photo = (pa, pm)
    def grid(a, mask, G=4):
        h, w = mask.shape
        out = []
        ys, xs = np.where(mask)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        for i in range(G):
            for j in range(G):
                sy, ey = y0 + (y1 - y0) * i // G, y0 + (y1 - y0) * (i + 1) // G
                sx, ex = x0 + (x1 - x0) * j // G, x0 + (x1 - x0) * (j + 1) // G
                cell = mask[sy:ey, sx:ex]
                out.append(a[sy:ey, sx:ex][cell][:, :3].mean(axis=0) if cell.any()
                           else np.zeros(3))
        return np.array(out)
    pg = grid(photo[0], photo[1]) if photo else None
    for yaw in (0, 90, 180, 270):
        img = MR.render(parts, yaw_deg=yaw, pitch_deg=8.0, size=(420, 420))
        a = np.asarray(img).astype(np.float32)
        alpha = a[..., 3] > 8
        if alpha.sum() < 500:
            e_scores[yaw] = p_scores[yaw] = 0.0
            continue
        g = a[..., :3].mean(axis=2)
        gx = np.abs(np.diff(g, axis=1))
        gy = np.abs(np.diff(g, axis=0))
        m = alpha[:, 1:] & alpha[:, :-1]
        my = alpha[1:, :] & alpha[:-1, :]
        e_scores[yaw] = float((gx[m].mean() if m.any() else 0) + (gy[my].mean() if my.any() else 0))
        if pg is not None:
            rg = grid(a, alpha)
            p_scores[yaw] = -float(np.linalg.norm(pg - rg, axis=1).mean())
        else:
            p_scores[yaw] = 0.0
    e_best = max(e_scores, key=e_scores.get)
    e_sorted = sorted(e_scores.values(), reverse=True)
    e_margin = (e_sorted[0] - e_sorted[1]) / max(e_sorted[0], 1e-6)
    p_best = max(p_scores, key=p_scores.get) if pg is not None else None
    # ПРИОРИТЕТ ДЕТАЛЬНОСТИ (проверено на комоде 5969: фото-сетка на однотонном сером
    # выбрала гладкий ЗАД, edge — настоящий фасад с ручками): edge с отрывом решает сам.
    if e_margin >= 0.12:
        src = 'cabinet_agree' if p_best == e_best else 'cabinet_edge'
        return float(e_best), src
    if p_best is not None and p_best == e_best:
        return float(e_best), 'cabinet_agree_weak'
    return None, 'cabinet_unsure'


def front_geometry_first(glb: str, dims: dict | None = None) -> tuple[float | None, str]:
    """Geometry-first фронт корпусной (советник 31.08 + Codex-разбор): рельеф, не RGB.

    1) Кандидаты — только ДВЕ ШИРОКИЕ стороны (комод 140×40 «боком» невозможен: бок с
       петлями ломал edge-метрику — комод 5582).
    2) Каждая рендерится БЕЗ ТЕКСТУРЫ (flat-серый) с боковым светом: щели ящиков и ручки
       дают shading-контраст чистой геометрии («exaggerated geometry render»).
    3) FrontScore = плотность краёв + горизонтальные швы (ряды с сильным |∇y| — щели
       ящиков горизонтальны). Максимум = фронт; малый отрыв → разметка.
    """
    import mesh_render as MR
    parts = MR.load_parts(glb)
    import trimesh
    import numpy as _np
    allv = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in parts])
    wx, wz = float(_np.ptp(allv[:, 0])), float(_np.ptp(allv[:, 2]))
    # широкая пара: стороны, смотрящие вдоль КОРОТКОЙ оси (видимая ширина максимальна)
    cands = (0, 180) if wx >= wz else (90, 270)
    if min(wx, wz) / max(wx, wz) > 0.85:
        return None, 'cabinet_squarish'            # почти квадрат в плане — в разметку
    scores = {}
    for yaw in cands:
        img = MR.render(parts, yaw_deg=yaw, pitch_deg=6.0, size=(420, 420),
                        flat=(150, 150, 150), light=(0.85, 0.25, 0.45))
        a = _np.asarray(img).astype(_np.float32)
        alpha = a[..., 3] > 8
        if alpha.sum() < 500:
            scores[yaw] = 0.0
            continue
        from scipy import ndimage as _ndi
        inner = _ndi.binary_erosion(alpha, iterations=4)   # только ВНУТРЕННОСТЬ:
        # силуэтный контур и канты давали гладкому заду edge выше фасада (комод 5969)
        g = a[..., :3].mean(axis=2)
        gy = _np.abs(_np.diff(g, axis=0))
        my = inner[1:, :] & inner[:-1, :]
        gx = _np.abs(_np.diff(g, axis=1))
        mx = inner[:, 1:] & inner[:, :-1]
        edge = float((gx[mx].mean() if mx.any() else 0) + (gy[my].mean() if my.any() else 0))
        # горизонтальные швы: ряды с внятным внутренним |∇y| — порог АБСОЛЮТНЫЙ
        rows = _np.where(my.any(axis=1),
                         (gy * my).sum(axis=1) / _np.maximum(my.sum(axis=1), 1), 0.0)
        seams = float((rows > 4.0).sum())
        scores[yaw] = edge + 0.05 * seams
    a_, b_ = cands
    top, second = max(scores[a_], scores[b_]), min(scores[a_], scores[b_])
    margin = (top - second) / max(top, 1e-6)
    best = a_ if scores[a_] >= scores[b_] else b_
    if margin >= 0.10:
        return float(best), 'cabinet_geometry'
    return None, 'cabinet_unsure'


def _depth_map(parts, yaw_deg: float, size: int = 300):
    """Ортографическая карта глубины стороны (обратная растеризация MR, только z-буфер)."""
    import math
    import numpy as _np
    W = H = size
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    rot = _np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], _np.float32).T
    allp = _np.vstack([_np.asarray(m.vertices, _np.float32) @ rot for m in parts])
    span = max(_np.ptp(allp[:, 0]), _np.ptp(allp[:, 1])) * 1.08 or 1.0
    ox, oy = allp[:, 0].mean(), allp[:, 1].mean()
    zbuf = _np.full((H, W), -1e9, _np.float32)
    for m in parts:
        p = _np.asarray(m.vertices, _np.float32) @ rot
        f = _np.asarray(m.faces, _np.int32)
        sx = (p[:, 0] - ox) / span * W + W / 2
        sv = H / 2 - (p[:, 1] - oy) / span * W
        depth = p[:, 2]
        for idx in range(len(f)):
            a, b, c = f[idx]
            xs = _np.array([sx[a], sx[b], sx[c]])
            ys = _np.array([sv[a], sv[b], sv[c]])
            x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()) + 1)
            y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max()) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(det) < 1e-9:
                continue
            gy, gx = _np.mgrid[y0:y1, x0:x1]
            w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / det
            w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / det
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * depth[a] + w1 * depth[b] + w2 * depth[c]
            sub = zbuf[y0:y1, x0:x1]
            upd = inside & (z > sub)
            sub[upd] = z[upd]
    return zbuf


def front_by_depth(glb: str) -> tuple[float | None, str, dict]:
    """Фасад = МЕЛКИЙ рельеф глубины (ручки/щели), дырявый зад = ПРОВАЛЫ внутрь.

    score = small_relief − 2×deep_holes; кандидаты — только две широкие стороны."""
    import mesh_render as MR
    import numpy as _np
    parts = MR.load_parts(glb)
    allv = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in parts])
    wx, wz = float(_np.ptp(allv[:, 0])), float(_np.ptp(allv[:, 2]))
    if min(wx, wz) / max(wx, wz) > 0.85:
        return None, 'cabinet_squarish', {}
    cands = (0, 180) if wx >= wz else (90, 270)
    body_depth = min(wx, wz)                        # толщина корпуса в юнитах
    dbg = {}
    scores = {}
    for yaw in cands:
        z = _depth_map(parts, yaw)
        seen = z > -1e8
        from scipy import ndimage as _ndi
        inner = _ndi.binary_erosion(seen, iterations=4)
        gz = _np.abs(_np.diff(z, axis=0))
        m = inner[1:, :] & inner[:-1, :]
        gz2 = _np.abs(_np.diff(z, axis=1))
        m2 = inner[:, 1:] & inner[:, :-1]
        g = _np.concatenate([gz[m], gz2[m2]])
        if not len(g):
            scores[yaw] = -9
            continue
        # порог НАД фасеточными волнами Hunyuan (комод 5969: волны зада умирают к 0.02,
        # ступени ручек живут до 0.04): резкие ступени и есть фасад
        small = float(((g > 0.02 * body_depth) & (g < 0.15 * body_depth)).mean())
        deep = float((g > 0.25 * body_depth).mean())
        # полость — ТОЖЕ фасадный признак (ниша ТВ-тумбы, открытые полки); «дырявых
        # задов» по глубине на пилоте не оказалось (у всех задов нули)
        scores[yaw] = small + deep
        dbg[yaw] = {'small': round(small, 4), 'deep': round(deep, 4)}
    a_, b_ = cands
    top = max(scores[a_], scores[b_])
    margin = abs(scores[a_] - scores[b_]) / max(abs(top), 1e-6)
    best = a_ if scores[a_] >= scores[b_] else b_
    if margin >= 0.15:
        return float(best), 'cabinet_depth', dbg
    return None, 'cabinet_unsure', dbg


def upright_by_legs(glb: str) -> tuple[str, float]:
    """«Верх» корпусной мебели по подсказке владельца (31.08): у стоящего комода низ —
    РАЗРЕЖЕННЫЙ (ножки: мелкие пятна опоры), верх — сплошная плоская крышка; у лежащего
    низ сплошной. Перебираем 6 осей, счёт = разреженность низа + сплошность/плоскость
    верха. → (ключ UP_HYPS, отрыв)."""
    import mesh_render as MR
    import numpy as _np
    parts = MR.load_parts(glb)
    V0 = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in parts])
    best, second = ('I', -9), -9
    scores = {}
    for name, Rh in UP_HYPS.items():
        V = V0 @ _np.asarray(Rh, _np.float32).T
        lo, hi = V[:, 1].min(), V[:, 1].max()
        h = max(hi - lo, 1e-6)
        G = 48
        def fill(mask_pts):
            if len(mask_pts) < 8:
                return 0.0
            gx = _np.clip(((mask_pts[:, 0] - V[:, 0].min()) / max(_np.ptp(V[:, 0]), 1e-6) * (G - 1)).astype(int), 0, G - 1)
            gz = _np.clip(((mask_pts[:, 2] - V[:, 2].min()) / max(_np.ptp(V[:, 2]), 1e-6) * (G - 1)).astype(int), 0, G - 1)
            grid = _np.zeros((G, G), bool)
            grid[gx, gz] = True
            return float(grid.mean())
        bot = V[(V[:, 1] < lo + 0.10 * h)]
        top = V[(V[:, 1] > hi - 0.06 * h)]
        legs = 1.0 - fill(bot)                        # разреженный низ = ножки
        flat_top = fill(top)                          # сплошная крышка
        scores[name] = legs + flat_top
    ordered = sorted(scores, key=scores.get, reverse=True)
    margin = scores[ordered[0]] - scores[ordered[1]]
    return ordered[0], float(margin)


def upright_cabinet(glb: str) -> tuple[str, str]:
    """Комбинированный «верх» корпусной: (а) фасад-на-верхней-проекции → лежит на спине
    (комод 8333, владелец: «он сверху»); (б) громкие ножки (margin ≥0.3) → их гипотеза;
    иначе I. → (ключ UP_HYPS, source)."""
    import mesh_render as MR
    import numpy as _np
    from scipy import ndimage as _ndi
    parts = MR.load_parts(glb)

    def relief(yaw_parts, yaw):
        z = _depth_map(yaw_parts, yaw)
        seen = z > -1e8
        inner = _ndi.binary_erosion(seen, iterations=4)
        g = _np.concatenate([_np.abs(_np.diff(z, axis=0))[inner[1:, :] & inner[:-1, :]],
                             _np.abs(_np.diff(z, axis=1))[inner[:, 1:] & inner[:, :-1]]])
        if not len(g):
            return 0.0
        V = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in yaw_parts])
        body = min(float(_np.ptp(V[:, 0])), float(_np.ptp(V[:, 2])))
        return float(((g > 0.02 * body) & (g < 0.15 * body)).mean())

    # top-проекция: поворачиваем X90 (верх ложится в камеру бокового рендера)
    import copy
    def rotated(hyp):
        Rm = _np.asarray(UP_HYPS[hyp], _np.float32)
        out = []
        for m in parts:
            m2 = m.copy()
            m2.vertices = _np.asarray(m2.vertices, _np.float32) @ Rm.T
            out.append(m2)
        return out
    top_relief = relief(rotated('X90'), 0)            # смотрим на бывший верх
    side_relief = max(relief(parts, 0), relief(parts, 90),
                      relief(parts, 180), relief(parts, 270))
    if top_relief > max(side_relief, 0.001) * 1.5:
        # фасад смотрит вверх: ставим на ноги; из двух вариантов берём тот, где ножки громче
        a, am = upright_by_legs_score(rotated('X90'))
        b, bm = upright_by_legs_score(rotated('X-90'))
        return ('X90', 'cabinet_on_back') if am >= bm else ('X-90', 'cabinet_on_back')
    hyp, margin = upright_by_legs(glb)
    if hyp != 'I' and margin >= 0.30:
        return hyp, 'cabinet_legs'
    return 'I', 'as_is'


def upright_by_legs_score(parts) -> tuple[str, float]:
    """Счёт «ножки+крышка» для УЖЕ повернутых частей (identity-гипотеза)."""
    import numpy as _np
    V = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in parts])
    lo, hi = V[:, 1].min(), V[:, 1].max()
    h = max(hi - lo, 1e-6)
    G = 48
    def fill(pts):
        if len(pts) < 8:
            return 0.0
        gx = _np.clip(((pts[:, 0] - V[:, 0].min()) / max(_np.ptp(V[:, 0]), 1e-6) * (G - 1)).astype(int), 0, G - 1)
        gz = _np.clip(((pts[:, 2] - V[:, 2].min()) / max(_np.ptp(V[:, 2]), 1e-6) * (G - 1)).astype(int), 0, G - 1)
        grid = _np.zeros((G, G), bool)
        grid[gx, gz] = True
        return float(grid.mean())
    legs = 1.0 - fill(V[V[:, 1] < lo + 0.10 * h])
    flat_top = fill(V[V[:, 1] > hi - 0.06 * h])
    return 'I', legs + flat_top


def upright_by_passport(glb: str, dims: dict | None) -> tuple[str | None, float]:
    """«Верх» по паспорту: 8333 лежал на спине, и это видно АРИФМЕТИКОЙ — высота меша
    оказалась меньше глубины, у комодов по паспорту наоборот. Выбираем ось-перестановку
    с минимальным рассогласованием пропорций (w,d,h); паспорт с неразличимыми d/h или
    слабый отрыв → None."""
    import mesh_render as MR
    import numpy as _np
    d0 = dims or {}
    w, dd, h = d0.get('w') or d0.get('dia'), d0.get('d'), d0.get('h')
    if not (w and dd and h):
        return None, 0.0
    want = _np.array(sorted([float(w), float(dd), float(h)], reverse=True))
    if abs(float(h) - float(dd)) / max(float(h), float(dd)) < 0.25:
        return None, 0.0                              # d≈h — паспорт не различает оси
    parts = MR.load_parts(glb)
    V0 = _np.vstack([_np.asarray(m.vertices, _np.float32) for m in parts])
    tgt = _np.array([float(w), float(h), float(dd)])   # x=w, y=h, z=d в канонике рендера
    tgt = tgt / tgt.max()
    # три КЛАССА осей (какая ось меша вертикальна): пары гипотез в классе эквивалентны
    # по |пропорциям| (X180 не меняет модулей — из-за этого margin по 6 гипотезам был 0)
    CLASSES = {'Y': ('I', 'X180'), 'Z': ('X90', 'X-90'), 'X': ('Z90', 'Z-90')}
    errs = {}
    for cls, (name, _alt) in CLASSES.items():
        Rh = _np.asarray(UP_HYPS[name], _np.float32)
        V = V0 @ Rh.T
        e = _np.array([float(_np.ptp(V[:, 0])), float(_np.ptp(V[:, 1])), float(_np.ptp(V[:, 2]))])
        e = e / e.max()
        err = min(abs(e[0] - tgt[0]) + abs(e[2] - tgt[2]),
                  abs(e[0] - tgt[2]) + abs(e[2] - tgt[0])) + 1.6 * abs(e[1] - tgt[1])
        errs[cls] = float(err)
    ordered = sorted(errs, key=errs.get)
    margin = errs[ordered[1]] - errs[ordered[0]]
    if margin < 0.10 or ordered[0] == 'Y':
        return (None, margin)                        # стоит как есть либо неубедительно
    # знак внутри класса — по ножкам (низ разреженнее)
    cands = CLASSES[ordered[0]]
    import mesh_render as MR2
    def legs_of(hyp):
        Rm = _np.asarray(UP_HYPS[hyp], _np.float32)
        out = []
        for m in MR2.load_parts(glb):
            m2 = m.copy()
            m2.vertices = _np.asarray(m2.vertices, _np.float32) @ Rm.T
            out.append(m2)
        return upright_by_legs_score(out)[1]
    best = cands[0] if legs_of(cands[0]) >= legs_of(cands[1]) else cands[1]
    return (best, margin)
