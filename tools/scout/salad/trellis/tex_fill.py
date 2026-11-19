#!/usr/bin/env python3
"""ЗАЛИВКА ДЫР ПОСЛЕ ПОКРАСКИ (T-20261119-50/1, П1.91): бесплатно, на процессоре. Шаг после MV-Adapter (и после любой покраски: TRELLIS.2 родной тоже даёт чёрную россыпь).

ЗАЧЕМ. Пятна на готовой текстуре — это тексели, которые сеть не покрасила: не видны ни с одного из 6 видов (unseen), видны только вскользь (grazing), или остались «фоном» (unpainted).
Классификацию даёт `tex_coverage.analyze` (переиспользуем, своей не пишем). Ручной чистки нет: товаров будет 20 000+.

КАК ЗАЛИВАЕМ — ПО ПОВЕРХНОСТИ МЕША, НЕ ПО РАЗВЁРТКЕ:
  1. у каждого текселя — его 3D-точка на поверхности (барицентры грани) и нормаль грани;
  2. донор — хороший тексель (класс «норма» или «шов видов»), ближайший к плохому по расстоянию между точками поверхности (kd-дерево по 3D) НЕ дальше `radius` (доля размера предмета);
  3. донор должен лежать на той же связной части формы (кусок формы по положению вершин, `tex_coverage.face_components`) и смотреть в ту же сторону (|угол нормалей| ≤ `max_normal_deg`) — иначе
     не перетекает сквозь толщину подлокотника и с соседней ножки;
  4. МАТЕРИАЛЬНАЯ ОБЛАСТЬ: хорошие тексели кластеризуются по цвету (k-means в Lab, `k` кластеров); у плохого текселя кластер определяется голосованием ближайших доноров (вес 1/d²), берутся ТОЛЬКО
     доноры победившего кластера: дерево ножки не течёт на ткань;
  5. цвет — средневзвешенный (1/d²) по `n_donors` ближайшим донорам кластера; unseen/unpainted перекрашиваются целиком, grazing — смешиваются с донором по весу угла:
     w_ориг = clip((cos_лучшего_вида / COS_GRAZE)², 0, 1), cos считается по нормали грани и 6 видам MV-Adapter (без учёта загораживания — приближение сверху);
  6. цвета хороших текселей и освещение НЕ меняются (diff = 0 — проверка в тестах и в счётчиках); форма и развёртка не меняются (вершины/грани/UV совпадают с точностью 1e-6 — `guard_geometry`).
  Ярусы: 1 — донор той же части формы и той же стороны; 2 (`any_side`) — той же части, другой стороны (внутренняя сторона подлокотника); 3 (`cross_radius`) — чужой части, но близко (≤ доли размера)
  и того же кластера материала (ящик, вставка, целиком не нарисованные). Нет донора (дальше радиуса / другая нормаль / другой кусок формы) — отказ с причиной по текселю, цвет остаётся прежним. Крупные пятна unpainted (чёрные/белые детали, а не дыры) не трогаем:
  связная область unpainted больше `blob_max_frac` от всех текселей — это настоящий цвет.

  ~/venvs/scout/bin/python tex_fill.py [--out ДИР] [--yaw auto|N] [--grid 2048] [--only unseen,grazing,unpainted] ПУТЬ_GLB...
      → `<ключ>-mvtex-fill.glb` (суффикс `--suffix`), `<ключ>-mvtex-fill.json` (счётчики), картинка карты заливки `-fillmap.png` (красный — залито, жёлтый — смешано, синий — отказ).
  ~/venvs/scout/bin/python tex_fill.py --selftest   # то же, что `tests_tex_fill.py`
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tex_coverage as TC  # noqa: E402

PARAMS = {'radius': 0.10, 'max_normal_deg': 60.0, 'k': 6, 'n_donors': 24, 'any_side': True, 'cross_radius': 0.05, 'knn': 64, 'blob_max_frac': 0.01, 'kmeans_sample': 60000, 'kmeans_iter': 12, 'hf_band_frac': 0.025, 'hf_sigma': 2.0}
CLS_GOOD = (1, 6)                  # норма, шов видов (цвет нарисован сетью)
CLS_UNSEEN, CLS_GRAZING, CLS_UNPAINTED = 2, 3, 4      # (5 — unseen внутри предмета: покупатель не видит, не трогаем)
REASONS = ('no_good', 'no_donor_radius', 'no_donor_normal', 'no_donor_component')


# ---------------------------------------------------------------- цвет ---------------------------------------------
def lab2rgb(lab):
    """Lab D65 (N,3) → sRGB uint8 (N,3) — обратное к `tex_coverage.rgb2lab`."""
    import numpy as np
    lab = np.asarray(lab, np.float64)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200

    def inv(f):
        return np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) * 27 / 24389)
    xyz = np.stack([inv(fx), inv(fy), inv(fz)], 1) * np.array([0.95047, 1.0, 1.08883])
    M = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = xyz @ M.T
    c = np.where(c > 0.0031308, 1.055 * np.power(np.maximum(c, 0), 1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def kmeans(X, k: int, iters: int, seed: int = 3):
    """Простой k-means на numpy (sklearn в venv нет). → центры (k,d). Инициализация k-means++ на выборке X."""
    import numpy as np
    rng = np.random.RandomState(seed)
    k = max(1, min(k, len(X)))
    C = [X[rng.randint(len(X))]]
    for _ in range(1, k):
        d2 = np.min(((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1), axis=1)
        s = d2.sum()
        C.append(X[rng.choice(len(X), p=d2 / s)] if s > 0 else X[rng.randint(len(X))])
    C = np.array(C, np.float64)
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = X[m].mean(axis=0)
    return C


# ---------------------------------------------------------------- ядро (чистое, без GLB) --------------------------
def texel_geometry(V, F, UV, T: int):
    """Для карты T×T: индексы текселей внутри островков `ti`, грань `f`, 3D-точка `Q` и нормаль `N` (единичная, по грани), площадь грани не нужна. Тот же растеризатор, что у `tex_coverage`."""
    import numpy as np
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    UV = np.asarray(UV, np.float64)
    xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    ids, _ = TC.raster(xy, F, T)
    ti = np.nonzero(ids >= 0)[0]
    f = ids[ti].astype(np.int64)
    a_, b_, c_ = F[f, 0], F[f, 1], F[f, 2]
    px, py = (ti % T) + 0.5, (ti // T) + 0.5
    A, B, C = xy[a_], xy[b_], xy[c_]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
    wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
    wc = 1.0 - wa - wb
    Q = wa[:, None] * V[a_] + wb[:, None] * V[b_] + wc[:, None] * V[c_]
    n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    nrm = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    return ti, f, Q, nrm[f], nrm


def fill_geom(V, F, UV, tex, cls, views=None, only=('unseen', 'grazing', 'unpainted'), params=None):
    """Заливка одной геометрии. V — положения (любой кадр, расстояния в нём), tex uint8 (T,T,3), cls (T,T) uint8 — классы `tex_coverage.analyze` (0 вне, 1 норма, 2 unseen наружу, 3 grazing,
    4 unpainted, 5 unseen внутри, 6 шов). views — виды MV-Adapter (на_камеру, вправо, вверх) в ТОМ ЖЕ кадре, что V (для веса grazing); None — grazing заливается как unseen.
    → (новая текстура, статистика, карта действий (T,T) uint8: 0 нет, 1 залито, 2 смешано, 3 отказ нет донора)."""
    import numpy as np
    from scipy.spatial import cKDTree
    P = {**PARAMS, **(params or {})}
    T = tex.shape[0]
    if tex.shape[1] != T:
        raise ValueError(f'карта не квадратная: {tex.shape[:2]}')
    t0 = time.time()
    ti, f, Q, N, fnorm = texel_geometry(V, F, UV, T)
    cl = np.asarray(cls, np.uint8).reshape(-1)[ti]
    rgb = np.asarray(tex, np.uint8).reshape(-1, 3)[ti].copy()
    n_all = len(ti)
    bad = np.zeros(n_all, bool)
    if 'unseen' in only:
        bad |= cl == CLS_UNSEEN
    if 'grazing' in only:
        bad |= cl == CLS_GRAZING
    skip_blob = 0
    if 'unpainted' in only:
        un = cl == CLS_UNPAINTED
        if un.any():
            from scipy import ndimage
            m = np.zeros(T * T, bool)
            m[ti[un]] = True
            lab, n = ndimage.label(m.reshape(T, T))
            size = np.bincount(lab.reshape(-1))
            big = size[lab.reshape(-1)[ti]] > P['blob_max_frac'] * n_all      # крупная область «фона» — настоящий цвет (чёрные ножки, белая рама)
            skip_blob = int((un & big).sum())
            bad |= un & ~big
    good = np.isin(cl, CLS_GOOD)
    stat = {'texels': int(n_all), 'bad_before': int(bad.sum()), 'bad_unseen': int((bad & (cl == CLS_UNSEEN)).sum()), 'bad_grazing': int((bad & (cl == CLS_GRAZING)).sum()),
            'bad_unpainted': int((bad & (cl == CLS_UNPAINTED)).sum()), 'unpainted_big_kept': skip_blob, 'good': int(good.sum()), 'refused': {r: 0 for r in REASONS}, 'filled_other_side': 0, 'filled_other_part': 0}
    action = np.zeros(T * T, np.uint8)
    out = rgb.copy()
    if not bad.any():
        stat.update(filled=0, blended=0, refused_total=0, bad_after=0, time_s=round(time.time() - t0, 2))
        return np.asarray(tex, np.uint8).copy(), stat, action.reshape(T, T)
    gi = np.nonzero(good)[0]
    bi = np.nonzero(bad)[0]
    if len(gi) < 50:
        stat['refused']['no_good'] = int(len(bi))
        stat.update(filled=0, blended=0, refused_total=int(len(bi)), bad_after=int(len(bi)), time_s=round(time.time() - t0, 2))
        action[ti[bi]] = 3
        return np.asarray(tex, np.uint8).copy(), stat, action.reshape(T, T)
    # материальные области: k-means в Lab по хорошим текселям
    lab_g = TC.rgb2lab(rgb[gi])
    rng = np.random.RandomState(5)
    samp = lab_g[rng.choice(len(gi), min(P['kmeans_sample'], len(gi)), replace=False)]
    centers = kmeans(samp, P['k'], P['kmeans_iter'])
    clus = np.empty(len(gi), np.int16)
    for s in range(0, len(gi), 200000):
        clus[s:s + 200000] = np.argmin(((lab_g[s:s + 200000, None, :] - centers[None]) ** 2).sum(-1), axis=1)
    nc = len(centers)
    comp = TC.face_components(V, F, np.ones(len(F)))
    cface = comp[0] if comp is not None else np.zeros(len(F), np.int64)
    ctex = cface[f]
    tree = cKDTree(Q[gi])
    kn = min(P['knn'], len(gi))
    cosn = np.cos(np.radians(P['max_normal_deg']))
    # размер предмета для радиуса
    diag = float(np.linalg.norm(np.asarray(V).max(axis=0) - np.asarray(V).min(axis=0)))
    R = P['radius'] * diag
    filled = blended = 0
    refused = stat['refused']
    CH = 20000
    for s in range(0, len(bi), CH):
        b = bi[s:s + CH]
        d, ix = tree.query(Q[b], k=kn, distance_upper_bound=R)
        if kn == 1:
            d, ix = d[:, None], ix[:, None]
        valid = np.isfinite(d)
        ixc = np.where(valid, ix, 0)
        gidx = gi[ixc]
        okn = valid & ((N[b][:, None, :] * N[gidx]).sum(-1) >= cosn)
        samec = valid & (ctex[gidx] == ctex[b][:, None])
        okc = okn & samec
        # ярус 2: у места нет доноров с той же стороной (внутренняя сторона подлокотника, щель) — берём доноров любой стороны той же части формы, тот же кластер материала и радиус
        far = ~okc.any(1) & samec.any(1) & P['any_side']
        okc = np.where(far[:, None], samec, okc)
        # ярус 3: на своей части формы доноров нет (кусок целиком плохой — ящик, вставка) — доноры чужих частей, но ближе `cross_radius` и того же кластера материала
        part = ~okc.any(1) & valid.any(1) & (P['cross_radius'] > 0)
        near = valid & (d <= P['cross_radius'] * diag)
        part &= near.any(1)
        okc = np.where(part[:, None], near, okc)
        w = np.where(okc, 1.0 / (d ** 2 + (1e-4 * diag) ** 2), 0.0)
        cl_d = clus[ixc]
        votes = np.zeros((len(b), nc))
        for j in range(nc):
            votes[:, j] = (w * (cl_d == j)).sum(1)
        win = votes.argmax(1)
        wsel = np.where(cl_d == win[:, None], w, 0.0)
        # не больше n_donors ближайших (d отсортированы по возрастанию): обнуляем после n-го ненулевого
        csum = np.cumsum(wsel > 0, axis=1)
        wsel = np.where(csum <= P['n_donors'], wsel, 0.0)
        tot = wsel.sum(1)
        has = tot > 0
        col = (wsel[:, :, None] * rgb[gidx]).sum(1) / np.maximum(tot, 1e-30)[:, None]
        # причины отказа
        r_rad = ~valid.any(1)
        r_norm = ~r_rad & samec.any(1) & ~okc.any(1) & ~part             # только при any_side=False: донор той же части есть, но смотрит в другую сторону
        r_comp = ~r_rad & ~samec.any(1) & ~part                    # в радиусе только чужие части формы (ярус 3 не дотянулся)
        refused['no_donor_radius'] += int(r_rad.sum())
        refused['no_donor_normal'] += int(r_norm.sum())
        refused['no_donor_component'] += int(r_comp.sum())
        graz = cl[b] == CLS_GRAZING
        if views is not None and graz.any():
            cb = np.max(np.abs(fnorm[f[b]] @ np.array([v[0] for v in views]).T), axis=1)
            w_orig = np.clip((cb / TC.COS_GRAZE) ** 2, 0.0, 1.0)
        else:
            w_orig = np.zeros(len(b))
        w_orig = np.where(graz, w_orig, 0.0)
        new = np.clip(np.round(w_orig[:, None] * rgb[b] + (1 - w_orig[:, None]) * col), 0, 255).astype(np.uint8)
        hb = b[has]
        out[hb] = new[has]
        mixed = graz[has] & (w_orig[has] > 0.0)
        action[ti[hb]] = np.where(mixed, 2, 1)
        action[ti[b[~has]]] = 3
        stat['filled_other_side'] += int((far & has).sum())
        stat['filled_other_part'] += int((part & has).sum())
        filled += int((has & ~(graz & (w_orig > 0))).sum())
        blended += int((has & graz & (w_orig > 0)).sum())
    ref_total = int(sum(refused.values()))
    stat.update(filled=filled, blended=blended, refused_total=ref_total, bad_after=ref_total, time_s=round(time.time() - t0, 2), radius_abs=round(R, 4), clusters=nc)
    newtex = np.asarray(tex, np.uint8).copy().reshape(-1, 3)
    newtex[ti] = out
    return newtex.reshape(T, T, 3), stat, action.reshape(T, T)


# ---------------------------------------------------------------- проверки результата -----------------------------
def good_diff(tex0, tex1, cls) -> dict:
    """ΔE00 хороших текселей (класс норма/шов) до и после: должно быть 0, и число изменившихся текселей — 0."""
    import numpy as np
    m = np.isin(np.asarray(cls), CLS_GOOD)
    a = np.asarray(tex0, np.uint8)[m]
    b = np.asarray(tex1, np.uint8)[m]
    n_ch = int((a != b).any(1).sum())
    if not len(a):
        return {'good': 0, 'changed': 0, 'de00_max': 0.0, 'de00_mean': 0.0}
    de = TC.de2000_v(TC.rgb2lab(a), TC.rgb2lab(b))
    return {'good': int(len(a)), 'changed': n_ch, 'de00_max': round(float(de.max()), 4), 'de00_mean': round(float(de.mean()), 4)}


def hf_energy(tex, cls, action, band_frac: float = PARAMS['hf_band_frac'], sigma: float = PARAMS['hf_sigma']) -> dict:
    """Энергия высоких частот L* (высокочастотная часть = L − gauss(L, σ) с учётом только хороших текселей; среднее квадрата) по ХОРОШИМ текселям в полосе `band_frac`·T пикселей вокруг залитых мест (карта действий ≠ 0).
    Считается по текстуре; до и после по хорошим текселям должна совпасть (резкость принта не трогаем). Возвращает число и размер полосы."""
    import numpy as np
    from scipy import ndimage
    t = np.asarray(tex, np.uint8)
    T = t.shape[0]
    L = TC.rgb2lab(t.reshape(-1, 3))[:, 0].reshape(T, T)
    gm = np.isin(np.asarray(cls), CLS_GOOD).astype(np.float64)
    blur = ndimage.gaussian_filter(L * gm, sigma) / np.maximum(ndimage.gaussian_filter(gm, sigma), 1e-6)     # размытие только по хорошим текселям: залитые места на мерку не влияют
    hp = L - blur
    act = np.asarray(action) != 0
    if not act.any():
        return {'hf_energy': None, 'band_px': 0, 'texels': 0}
    band = max(1, int(round(band_frac * T)))
    dist = ndimage.distance_transform_edt(~act)
    m = (dist <= band) & ~act & np.isin(np.asarray(cls), CLS_GOOD)
    return {'hf_energy': round(float((hp[m] ** 2).mean()), 4) if m.any() else None, 'band_px': band, 'texels': int(m.sum())}


def guard_geometry(a: list, b: list, tol: float = 1e-6) -> dict:
    """Форма и развёртка не изменились: вершины, грани и UV совпадают (число и значения, допуск `tol`). a, b — списки геометрий `tex_coverage.load_geoms`."""
    import numpy as np
    if len(a) != len(b):
        return {'ok': False, 'why': f'число геометрий {len(a)} ≠ {len(b)}'}
    worst = {'V': 0.0, 'UV': 0.0}
    for ga, gb in zip(a, b):
        if ga['V'].shape != gb['V'].shape or ga['F'].shape != gb['F'].shape:
            return {'ok': False, 'why': f"размеры вершин/граней {ga['V'].shape}/{ga['F'].shape} ≠ {gb['V'].shape}/{gb['F'].shape}"}
        if not np.array_equal(ga['F'], gb['F']):
            return {'ok': False, 'why': 'грани изменились'}
        worst['V'] = max(worst['V'], float(np.abs(ga['V'] - gb['V']).max()) if len(ga['V']) else 0.0)
        worst['UV'] = max(worst['UV'], float(np.abs(ga['UV'] - gb['UV']).max()) if len(ga['UV']) else 0.0)
    ok = worst['V'] <= tol and worst['UV'] <= tol
    return {'ok': ok, 'max_dV': worst['V'], 'max_dUV': worst['UV'], 'tol': tol, **({} if ok else {'why': 'вершины или развёртка сдвинулись больше допуска'})}


# ---------------------------------------------------------------- GLB -------------------------------------------
def write_glb(geoms: list, textures: list, dst: str) -> None:
    """Те же форма, развёртка и материал; меняется только картинка baseColor."""
    import copy
    import trimesh
    from PIL import Image
    sc = trimesh.Scene()
    for g, tx in zip(geoms, textures):
        mesh = g['mesh'].copy()
        mat = copy.copy(mesh.visual.material)
        img = Image.fromarray(tx)
        if hasattr(mat, 'baseColorTexture'):
            mat.baseColorTexture = img
        else:
            mat.image = img
        mesh.visual.material = mat
        sc.add_geometry(mesh, geom_name=str(g.get('name') or 'mesh'))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    sc.export(dst)


def action_image(action, base):
    """Карта заливки: исходная краска приглушена; красный — залито, жёлтый — смешано (grazing), синий — отказ."""
    import numpy as np
    from PIL import Image
    img = (np.asarray(base, np.float64) * 0.55).astype(np.uint8)
    for k, col in ((1, (255, 0, 0)), (2, (255, 220, 0)), (3, (0, 90, 255))):
        img[np.asarray(action) == k] = col
    return Image.fromarray(img)


def color_classes(geoms: list, T: int, dilate: int = 1, contrast: float = 15.0, below_median: float = 20.0) -> dict:
    """Классы только по ЦВЕТУ — для покраски без видов MV-Adapter (родная краска TRELLIS.2: тёмная россыпь = дыры краски; форма там чистая). 1 — норма внутри островков; 4 — «дыра»: тексель
    почти чёрный/белый (пороги `tex_coverage.UNPAINTED`) ИЛИ тёмный выброс — темнее медианы окрестности 15×15 на `contrast` L* и при этом темнее медианы всего предмета на `below_median` L*
    (настоящий тёмный материал — ножки, рама — внутри ровный, выбросом не считается; крупные области отсекает `blob_max_frac` в `fill_geom`). Расширено на `dilate` текселей (тёмная кайма).
    unseen/grazing не определяются (видов нет). Формат — как у `tex_coverage.analyze` (`maps[i]['cls']`)."""
    import numpy as np
    from scipy import ndimage
    maps = []
    for g in geoms:
        ti, _f, _Q, _N, _fn = texel_geometry(g['V'], g['F'], g['UV'], T)
        cls = np.zeros(T * T, np.uint8)
        cls[ti] = 1
        rgb = np.asarray(g['tex'], np.uint8).reshape(-1, 3)
        isl = (cls > 0)
        unp = ((rgb.max(axis=1) <= TC.UNPAINTED['black_max']) | (rgb.min(axis=1) >= TC.UNPAINTED['white_min'])) & isl
        L = TC.rgb2lab(rgb)[:, 0].reshape(T, T)
        med = ndimage.median_filter(L, size=15)
        glob_med = float(np.median(L.reshape(-1)[isl])) if isl.any() else 0.0
        dark = ((med - L) > contrast) & (L < glob_med - below_median) & isl.reshape(T, T)
        m = dark | unp.reshape(T, T)
        if dilate > 0 and m.any():
            m = ndimage.binary_dilation(m, iterations=dilate)
        c2 = cls.reshape(T, T)
        c2[m & (c2 > 0)] = CLS_UNPAINTED
        maps.append({'cls': c2, 'base': np.asarray(g['tex'], np.uint8)})
    return {'maps': maps}


def process(glb: str, out_dir: str, yaw=None, grid: int = 2048, suffix: str = '-fill', only=('unseen', 'grazing', 'unpainted'), params=None, view_res: int = 768, classify: str = 'mv') -> dict:
    """Один GLB → заливка. `classify='mv'` — классы `tex_coverage.analyze` (покраска MV-Adapter), форма и позы — в кадре куба с `yaw`, как у `tex_coverage.process`; `'color'` — только по цвету (родная краска)."""
    import numpy as np
    import worker_trellis as W
    t0 = time.time()
    stem = os.path.basename(glb)[:-4]
    geoms = TC.load_geoms(glb)
    yw, ysrc = (0.0, 'не нужен (по цвету)') if classify == 'color' else TC.find_yaw(glb, yaw)
    T = min(int(grid), max(max(g['tex'].shape[:2]) for g in geoms))
    for g in geoms:
        if g['tex'].shape[0] != T or g['tex'].shape[1] != T:
            raise ValueError(f'{stem}: текстура {g["tex"].shape[:2]} не совпадает с сеткой {T} — задайте --grid равным размеру карты')
    r = color_classes(geoms, T) if classify == 'color' else TC.analyze(geoms, yw, T, view_res)
    Vall = np.concatenate([g['V'] for g in geoms])
    Pc = Vall if classify == 'color' else W.to_cube(Vall, yw)[0]
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    views = None if classify == 'color' else TC.mv_views(W.MV_AZ)
    new_tex, stats, actions = [], [], []
    for i, g in enumerate(geoms):
        nt, st, ac = fill_geom(Pc[offs[i]:offs[i + 1]], g['F'], g['UV'], g['tex'], r['maps'][i]['cls'], views, only, params)
        new_tex.append(nt)
        stats.append(st)
        actions.append(ac)
    dst = os.path.join(out_dir, stem + suffix + '.glb')
    write_glb(geoms, new_tex, dst)
    back = TC.load_geoms(dst)
    guard = guard_geometry(geoms, back)
    gd = [good_diff(g['tex'], b['tex'], r['maps'][i]['cls']) for i, (g, b) in enumerate(zip(geoms, back))]
    hf0 = [hf_energy(g['tex'], r['maps'][i]['cls'], actions[i]) for i, g in enumerate(geoms)]
    hf1 = [hf_energy(b['tex'], r['maps'][i]['cls'], actions[i]) for i, b in enumerate(back)]
    for i, g in enumerate(geoms):
        action_image(actions[i], new_tex[i]).save(os.path.join(out_dir, f'{stem}{suffix}-fillmap{i if len(geoms) > 1 else ""}.png'))
    agg = {k: sum(s[k] for s in stats) for k in ('texels', 'bad_before', 'bad_unseen', 'bad_grazing', 'bad_unpainted', 'unpainted_big_kept', 'filled', 'blended', 'refused_total', 'bad_after')}
    agg['refused'] = {k: sum(s['refused'][k] for s in stats) for k in REASONS}
    res = {'file': os.path.abspath(glb), 'out': dst, 'classify': classify, 'yaw_deg': yw, 'yaw_source': ysrc, 'grid': T, 'only': list(only), 'params': {**PARAMS, **(params or {})}, **agg,
           'guard_geometry': guard, 'good_diff': gd, 'hf_before': hf0, 'hf_after': hf1, 'time_s': round(time.time() - t0, 2), 'fill_time_s': [s['time_s'] for s in stats]}
    json.dump(res, open(os.path.join(out_dir, stem + suffix + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/mvadapter-fill'))
    ap.add_argument('--yaw', default='auto')
    ap.add_argument('--grid', type=int, default=2048)
    ap.add_argument('--suffix', default='-fill')
    ap.add_argument('--only', default='unseen,grazing,unpainted')
    ap.add_argument('--classify', choices=('mv', 'color'), default='mv', help='mv — классы по видам MV-Adapter (`tex_coverage`); color — только по цвету (родная краска TRELLIS.2)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        import tests_tex_fill
        return tests_tex_fill.main()
    if not a.paths:
        ap.error('нужен GLB')
    os.makedirs(a.out, exist_ok=True)
    rc = 0
    for p in a.paths:
        try:
            r = process(p, a.out, a.yaw, a.grid, a.suffix, tuple(x for x in a.only.split(',') if x), None, 768, a.classify)
        except Exception as e:  # noqa: BLE001 — один сбойный товар не роняет пачку
            print(f'FAIL {os.path.basename(p)}: {e}')
            rc = 1
            continue
        print(f"{os.path.basename(p)}: плохих {r['bad_before']} → осталось {r['bad_after']} (залито {r['filled']}, смешано {r['blended']}, отказ {r['refused']}), "
              f"хорошие diff: {r['good_diff'][0]['changed']} изм./ΔE00 макс {r['good_diff'][0]['de00_max']}, форма/UV: {'ок' if r['guard_geometry']['ok'] else r['guard_geometry']}, {r['time_s']} с")
    return rc


if __name__ == '__main__':
    sys.exit(main())
