#!/usr/bin/env python3
"""О2 плана mesh-color-03 (T-20261106-85/4): поправка светлоты текстуры по фото — на процессоре, без GPU, 0 ₽.

ЗАЧЕМ. О0 показал: светлоту портит сама нейросеть покраски (шаг multiview) — тянет её к середине, и одной общей поправкой
на все товары это не лечится (разброс 2,7 ступени). Здесь поправка считается ДЛЯ КАЖДОГО меша по его же фото:
  А — один множитель «фото / меш» на всю текстуру (в линейном свете, оттенок не трогаем);
  Б — множитель только у крупных однотонных участков, видимых на фото. Участок — кластер цвета рендера без света в позе
      фото; ему в пару — кластеры фото на тех же пикселях. Не трогаем: рисунок (дерево, ткань — большой местный разброс
      светлоты), металл (карта metallic текстуры), участки со слабым совпадением с фото и мелкие (< AREA_MIN видимого).
      На текстуру множитель ложится мягко: тексель берёт поправку участков пропорционально близости цвета (σ = SIGMA_DE),
      далёкий от всех участков цвет остаётся как был — швов нет.
ОТКАЗ — отдельный класс, без поправки: «провал» (текстура целиком почти чёрная, Y < 0,01 — множитель не вернёт рисунок)
и «не тот материал» (крупному видимому участку нужна поправка больше MAX_STOPS ступеней — сеть покрасила не тем).

МЕРКА (план): рендер без света (`mesh_render` `UNLIT=1`) в позе фото против фото. Области — кластеры цвета ФОТО
(≥ 3 % общего силуэта); у каждой ΔL = байт sRGB медианы рендера − медианы фото и сдвиг цвета ΔC (медианный RGB за
вычетом серой части — хрома без светлоты). Норма: медиана |ΔL| ≤ 20, худшая из областей ≥ 8 % (NORM_REGION) ≤ 40,
медиана ΔC ≤ 8; медианы — по площади областей (иначе щель-ручка 4 % весит как корпус 82 %); худшая из областей ≥ 3 % —
справка в листе, не норма (ведущий 07.11, T-85/5).
Поза — из О0 (`color_steps` подбор по силуэту); фото вписывается в силуэт рендера по рамке.

T-85/5: А-L — тот же множитель, но только по светлоте Y, цветность Lab (a, b) прежняя (`gain_L`): у А осветление дерева
поднимало и насыщенность. Набор вариантов — `O2_VARIANTS` (по умолчанию «A,B»; «A,AL» — без Б). Чужие GLB той же формы
(О1 — перекраска со сдвигом входа) меряются той же меркой: 4-й столбец list.tsv «O1=путь.glb[;имя=путь…]»; для них ещё
`<имя>_stops` — сколько ступеней светлоты осталось до фото (по нему считается следующий круг О1).

  ~/venvs/scout/bin/python color_o2.py batch <list.tsv> <steps.jsonl из О0> <папка> [метки крупного листа через запятую]
      [--reuse <o2.jsonl прежнего прогона>]   # «было» и А не зависят от порогов Б — их рендеры берутся готовыми
  ~/venvs/scout/bin/python color_o2.py sheet <o2.jsonl> <папка> [метки крупного листа]   # только листы
  ~/venvs/scout/bin/python color_o2.py --selftest
Живые меши не трогает: исправленные GLB пишутся только в <папка>/glb/.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import color_steps as CS  # noqa: E402

K_TEX = 6            # кластеров цвета у рендера меша
K_PHOTO = 6          # кластеров цвета у фото
MERGE_DE = 7.0       # ближе — один участок
AREA_MIN = 0.06      # «крупный» участок — доля видимого силуэта
PHOTO_STD_MAX = 3.5  # «однотонный»: медиана местного разброса L* (окно 3×3) на ФОТО участка. Судим по фото, не по мешу:
                     # сеть рисует шум и полосы и на однотонной панели (у графитового шкафа 936236 разброс меша 10–15),
                     # а на фото видно настоящий материал (рифление, дерево 5–8; однотонная панель и ткань дивана 0,2–2)
SHARE_MIN = 0.6      # доля пикселей участка, попавших в «свои» кластеры фото
METAL_MAX = 0.5      # металл (карта metallic) — не трогаем
MAX_STOPS = 3.0      # больше — «не тот материал»
SIGMA_DE = 9.0       # мягкость переноса поправки на тексели (ΔE)
COLLAPSE_Y = 0.01
REGION_MIN = 0.03    # область мерки — доля общего силуэта
NORM_REGION = 0.08   # «худшая область» в норме — только области ≥ 8 % (ведущий 07.11: ножки и складки 3–7 % — справка)
VARIANTS = set(os.environ.get('O2_VARIANTS', 'A,B').split(','))   # A, AL, B; «было» считается всегда


# ── цвет ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def s2l(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def l2s(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


_M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
_WHITE = np.array([0.95047, 1.0, 1.08883], np.float32)


def lab(rgb8: np.ndarray) -> np.ndarray:
    lin = s2l(rgb8.astype(np.float32) / 255.0)
    xyz = (lin @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def ylin(rgb8: np.ndarray) -> np.ndarray:
    return s2l(rgb8.astype(np.float32) / 255.0) @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def _finv(f: np.ndarray) -> np.ndarray:
    return np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787)


def lab2rgb8(Lab: np.ndarray) -> np.ndarray:
    fy = (Lab[..., 0] + 16) / 116
    xyz = np.stack([_finv(fy + Lab[..., 1] / 500), _finv(fy), _finv(fy - Lab[..., 2] / 200)], -1) * _WHITE
    lin = xyz @ np.linalg.inv(_M).T.astype(np.float32)
    return np.round(l2s(lin) * 255).astype(np.uint8)


def gain_L(tex: np.ndarray, lg: float, chunk: int = 1 << 20) -> np.ndarray:
    """А-L (T-20261106-85/5): тот же множитель яркости Y = 2^lg, но цветность Lab (a, b) остаётся прежней — хрома не растёт
    вместе со светлотой. Множитель в линейном RGB (`gain`) сохраняет отношения каналов, и при осветлении дерева его
    насыщенность в байтах росла (721606 стал персиковым, 007531 — оранжевее; ведущий 07.11)."""
    flat = tex.reshape(-1, 3)
    out = np.empty_like(flat)
    k = 2.0 ** float(lg)
    for s in range(0, len(flat), chunk):
        L = lab(flat[s:s + chunk])
        Y = np.clip(_finv((L[..., 0] + 16) / 116) * k, 0, 1)
        f = np.where(Y > 0.008856, np.cbrt(Y), 7.787 * Y + 16 / 116)
        L[..., 0] = 116 * f - 16
        out[s:s + chunk] = lab2rgb8(L)
    return out.reshape(tex.shape)


def gain(tex: np.ndarray, lg) -> np.ndarray:
    """Светлота × 2^lg в линейном свете (оттенок цел); lg — число или карта размером с текстуру."""
    lg = np.asarray(lg, np.float32)
    k = np.power(2.0, lg)[..., None] if lg.ndim else 2.0 ** float(lg)
    return np.round(l2s(s2l(tex.astype(np.float32) / 255.0) * k) * 255).astype(np.uint8)


def local_std(L: np.ndarray, size: int = 7) -> np.ndarray:
    from scipy.ndimage import uniform_filter
    m = uniform_filter(L, size)
    return np.sqrt(np.maximum(uniform_filter(L * L, size) - m * m, 0))


# ── кластеры ───────────────────────────────────────────────────────────────────────────────────────────────────────

def assign(X: np.ndarray, C: np.ndarray, chunk: int = 400_000) -> np.ndarray:
    out = np.empty(len(X), np.int32)
    for s in range(0, len(X), chunk):
        x = X[s:s + chunk]
        out[s:s + chunk] = ((x[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
    return out


def kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 30) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if len(X) > 40000:
        X = X[rng.choice(len(X), 40000, replace=False)]
    C = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = ((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1).min(1)
        if d.sum() <= 0:
            break
        C.append(X[rng.choice(len(X), p=d / d.sum())])
    C = np.array(C, np.float32)
    for _ in range(iters):
        a = assign(X, C)
        n = np.array([X[a == j].mean(0) if (a == j).any() else C[j] for j in range(len(C))], np.float32)
        if np.allclose(n, C, atol=1e-3):
            break
        C = n
    a = assign(X, C)
    w = np.bincount(a, minlength=len(C)).astype(np.float32)
    while len(C) > 1:                                  # близкие центры — один участок
        d = np.sqrt(((C[:, None] - C[None]) ** 2).sum(-1)) + np.eye(len(C)) * 1e9
        i, j = np.unravel_index(d.argmin(), d.shape)
        if d[i, j] >= MERGE_DE:
            break
        C[i] = (C[i] * w[i] + C[j] * w[j]) / max(w[i] + w[j], 1)
        w[i] += w[j]
        C, w = np.delete(C, j, 0), np.delete(w, j)
    keep = w > 0
    return C[keep]


# ── карта «пиксель рендера → тексель» (тот же растеризатор, что mesh_render.render) ───────────────────────────────────

def texel_map(parts, yaw_deg: float, pitch_deg: float, size: int):
    """Для каждого пикселя: номер части (−1 фон) и тексель (tx, ty). Арифметика — копия `mesh_render.render`,
    поэтому текстура, выбранная по карте, равна рендеру без света (проверяется в самопроверке и на каждом меше)."""
    import mesh_render as MR
    W = H = size
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    rot = ry.T @ rx.T
    allp = np.vstack([np.asarray(m.vertices, np.float32) @ rot for m in parts])
    span = max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1])) * 1.08 or 1.0
    ox, oy = allp[:, 0].mean(), allp[:, 1].mean()
    zbuf = np.full((H, W), -1e9, np.float32)
    part = np.full((H, W), -1, np.int16)
    TX = np.zeros((H, W), np.int32)
    TY = np.zeros((H, W), np.int32)
    for pi, mesh in enumerate(parts):
        p = np.asarray(mesh.vertices, np.float32) @ rot
        f = np.asarray(mesh.faces, np.int32)
        sx = (p[:, 0] - ox) / span * W + W / 2
        sv = H / 2 - (p[:, 1] - oy) / span * W
        depth = p[:, 2]
        tex, uv = MR.texture_of(mesh)
        th, tw = (tex.shape[:2] if tex is not None else (1, 1))
        for idx in np.argsort(depth[f].mean(axis=1)):
            a, b, c = f[idx]
            xs = np.array([sx[a], sx[b], sx[c]])
            ys = np.array([sv[a], sv[b], sv[c]])
            x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()) + 1)
            y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max()) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(det) < 1e-9:
                continue
            gy, gx = np.mgrid[y0:y1, x0:x1]
            w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / det
            w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / det
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * depth[a] + w1 * depth[b] + w2 * depth[c]
            sub = zbuf[y0:y1, x0:x1]
            upd = inside & (z > sub)
            if not upd.any():
                continue
            sub[upd] = z[upd]
            part[y0:y1, x0:x1][upd] = pi
            if tex is not None:
                u = w0 * uv[a, 0] + w1 * uv[b, 0] + w2 * uv[c, 0]
                vv = w0 * uv[a, 1] + w1 * uv[b, 1] + w2 * uv[c, 1]
                TX[y0:y1, x0:x1][upd] = np.clip((u % 1.0) * (tw - 1), 0, tw - 1).astype(int)[upd]
                TY[y0:y1, x0:x1][upd] = np.clip((1.0 - (vv % 1.0)) * (th - 1), 0, th - 1).astype(int)[upd]
    return part, TX, TY


def from_map(tm, texs: list) -> np.ndarray:
    part, TX, TY = tm
    out = np.zeros(part.shape + (3,), np.uint8)
    for pi, t in enumerate(texs):
        m = part == pi
        if t is not None and m.any():
            out[m] = t[TY[m], TX[m]]
    return out


def metallic_of(mesh) -> np.ndarray | None:
    mat = getattr(getattr(mesh, 'visual', None), 'material', None)
    img = getattr(mat, 'metallicRoughnessTexture', None)
    if img is None:
        return None
    mf = getattr(mat, 'metallicFactor', None)
    return np.asarray(img.convert('RGB'))[..., 2].astype(np.float32) / 255.0 * (1.0 if mf is None else float(mf))


# ── фото в кадр рендера ────────────────────────────────────────────────────────────────────────────────────────────

def align_photo(P: np.ndarray, ralpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Фото (RGBA) вписывается рамкой товара в рамку силуэта рендера."""
    pa = P[..., 3] > 128
    ys, xs = np.where(pa)
    crop = P[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ry, rx = np.where(ralpha)
    y0, x0, rh, rw = ry.min(), rx.min(), ry.max() - ry.min() + 1, rx.max() - rx.min() + 1
    im = np.asarray(Image.fromarray(crop).resize((rw, rh), Image.LANCZOS))
    out = np.zeros(ralpha.shape + (4,), np.uint8)
    out[y0:y0 + rh, x0:x0 + rw] = im
    return out[..., :3], out[..., 3] > 200


def erode(m: np.ndarray, r: int = 3) -> np.ndarray:
    from scipy.ndimage import binary_erosion
    return binary_erosion(m, iterations=r)


# ── мерка ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def measure(rgb: np.ndarray, ralpha: np.ndarray, prgb: np.ndarray, pmask: np.ndarray, pcl: np.ndarray,
            y_photo: float) -> dict:
    both = erode(ralpha) & erode(pmask)
    y_r = CS.lum(rgb, ralpha)
    res = {'dL_all': round(CS.to_byte(y_r or 0) - CS.to_byte(y_photo), 1), 'y': None if y_r is None else round(y_r, 4),
           'regions': []}
    Yr, Yp = ylin(rgb), ylin(prgb)
    for j in range(int(pcl.max()) + 1):
        reg = both & (pcl == j)
        if reg.sum() < REGION_MIN * both.sum() or reg.sum() < 50:
            continue
        dl = CS.to_byte(float(np.median(Yr[reg]))) - CS.to_byte(float(np.median(Yp[reg])))
        mr = np.median(rgb[reg].astype(np.float32), 0)
        mp = np.median(prgb[reg].astype(np.float32), 0)
        dc = float(np.linalg.norm((mr - mr.mean()) - (mp - mp.mean())))
        res['regions'].append({'j': j, 'share': round(float(reg.sum() / both.sum()), 3), 'dL': round(dl, 1),
                               'dC': round(dc, 1)})
    dls = [abs(r['dL']) for r in res['regions']]
    dcs = [r['dC'] for r in res['regions']]
    ws = [r['share'] for r in res['regions']]

    def wmed(v: list) -> float:                        # медиана по площади: корпус 82 % весит больше щели 4 %
        o = np.argsort(v)
        c = np.cumsum(np.asarray(ws)[o])
        return float(np.asarray(v)[o][np.searchsorted(c, c[-1] / 2)])
    res['med_dL'] = round(wmed(dls), 1) if dls else None
    res['max_dL'] = round(float(max(dls)), 1) if dls else None          # справка: худшая из областей ≥ 3 %
    big = [abs(r['dL']) for r in res['regions'] if r['share'] >= NORM_REGION]
    res['max_dL8'] = round(float(max(big)), 1) if big else None         # норма: худшая из областей ≥ 8 % (ведущий 07.11)
    res['med_dC'] = round(wmed(dcs), 1) if dcs else None
    res['pass'] = bool(dls) and res['med_dL'] <= 20 and (res['max_dL8'] or 0) <= 40 and res['med_dC'] <= 8
    return res


# ── вариант Б: участки ────────────────────────────────────────────────────────────────────────────────────────────

def zones(base: np.ndarray, ralpha: np.ndarray, prgb: np.ndarray, pmask: np.ndarray, pcl: np.ndarray,
          tm, metals: list) -> tuple[np.ndarray, list, np.ndarray]:
    vis = erode(ralpha, 2)
    both = erode(ralpha) & erode(pmask)
    Lab = lab(base)
    C = kmeans(Lab[vis], K_TEX, seed=1)
    cl = np.full(ralpha.shape, -1, np.int32)
    cl[ralpha] = assign(Lab[ralpha], C)
    lstd = local_std(Lab[..., 0])
    pstd = local_std(lab(prgb)[..., 0], 3)
    Yb, Yp = ylin(base), ylin(prgb)
    part, TX, TY = tm
    met = np.zeros(ralpha.shape, np.float32)
    for pi, mm in enumerate(metals):
        m = part == pi
        if mm is not None and m.any():
            sy, sx = mm.shape[0] / max(TY.max() + 1, 1), mm.shape[1] / max(TX.max() + 1, 1)
            met[m] = mm[np.clip((TY[m] * sy).astype(int), 0, mm.shape[0] - 1),
                        np.clip((TX[m] * sx).astype(int), 0, mm.shape[1] - 1)]
    info = []
    for i in range(len(C)):
        ci = vis & (cl == i)
        z = {'i': i, 'lab': [round(float(v), 1) for v in C[i]], 'area': round(float(ci.sum() / max(vis.sum(), 1)), 3),
             'spread': round(float(np.sqrt(((Lab[ci] - C[i]) ** 2).sum(-1).mean())), 1) if ci.any() else SIGMA_DE,
             'tex_std': round(float(np.median(lstd[ci])), 2) if ci.any() else None,
             'metal': round(float(np.mean(met[ci] > METAL_MAX)), 2) if ci.any() else None, 'lg': 0.0}
        ov = both & (cl == i)
        if ov.sum() >= 50:
            cnt = np.bincount(pcl[ov], minlength=int(pcl.max()) + 1).astype(np.float32) / ov.sum()
            mates = [int(j) for j in np.where(cnt >= 0.2)[0]]
            share = float(cnt[mates].sum()) if mates else 0.0
            reg = ov & np.isin(pcl, mates)
            yt, ym = float(np.median(Yp[reg])), float(np.median(Yb[reg]))
            z.update(mates=mates, share=round(share, 2), y_photo=round(yt, 4), y_mesh=round(ym, 4),
                     need=round(math.log2(max(yt, 1e-5) / max(ym, 1e-5)), 2),
                     photo_std=round(float(np.median(pstd[reg])), 2))
        if z['area'] < AREA_MIN:
            z['st'] = 'мелкий'
        elif 'need' not in z or z['share'] < SHARE_MIN:
            z['st'] = 'нет пары на фото'
        elif z['metal'] and z['metal'] > 0.5:
            z['st'] = 'металл'
        elif z['photo_std'] > PHOTO_STD_MAX and abs(z['need']) <= MAX_STOPS and os.environ.get('O2_PATTERN') == '1':
            z['st'] = 'рисунок·правим'                  # опыт Б′: множитель светлоты рисунок сохраняет
            z['lg'] = z['need']
        elif z['photo_std'] > PHOTO_STD_MAX:
            z['st'] = 'рисунок'
        elif abs(z['need']) > MAX_STOPS:
            z['st'] = 'не тот материал'
        else:
            z['st'] = 'правим'
            z['lg'] = z['need']
        info.append(z)
    return C, info, cl


def soft_lg(tex: np.ndarray, C: np.ndarray, lgs: np.ndarray, metal: np.ndarray | None,
            vote: np.ndarray | None = None, sig: np.ndarray | None = None) -> np.ndarray:
    """Поправка каждому текселю: среднее поправок участков с весом близости цвета; знаменатель не меньше веса на 2,5σ —
    далёкие от всех участков цвета плавно уходят к нулю. `vote` — какие участки голосуют: мелкие (шум кластеризации)
    не голосуют, иначе их нулевая поправка разбавляет соседний крупный участок (комод 869565: недоправка +19).
    `sig` — σ каждого участка = его собственный разброс цвета (не меньше SIGMA_DE): у дивана 533015 один участок на 96 %
    с широким разбросом, и общая σ = 9 недоправляла его края (+27 против 0 у А)."""
    sig = np.full(len(C), SIGMA_DE, np.float32) if sig is None else np.maximum(np.asarray(sig, np.float32), SIGMA_DE)
    if vote is not None:
        C, lgs, sig = C[vote], lgs[vote], sig[vote]
    h, w = tex.shape[:2]
    L = lab(tex.reshape(-1, 3))
    out = np.zeros(len(L), np.float32)
    for s in range(0, len(L), 500_000):
        x = L[s:s + 500_000]
        d2 = ((x[:, None, :] - C[None]) ** 2).sum(-1)
        wk = np.exp(-d2 / (2 * sig[None] ** 2))
        w0 = math.exp(-2.5 ** 2 / 2)
        out[s:s + 500_000] = (wk * lgs[None]).sum(1) / np.maximum(wk.sum(1), w0)
    out = out.reshape(h, w)
    if metal is not None:
        mm = np.asarray(Image.fromarray((metal * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)) / 255.0
        out *= (mm <= METAL_MAX)
    return out


# ── один меш ──────────────────────────────────────────────────────────────────────────────────────────────────────

def write_glb(src: str, dst: str, texs: list) -> None:
    import trimesh
    sc = trimesh.load(src, force='scene')
    for (name, g), t in zip(sc.geometry.items(), texs):
        if t is not None:
            g.visual.material.baseColorTexture = Image.fromarray(t)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    sc.export(dst)


def one(label: str, run_dir: str, photo: str, pose: dict, out: str, k: int, prev: dict | None = None,
        extra: dict | None = None) -> dict:
    import mesh_render as MR
    glb = os.path.join(run_dir, 'model.glb')
    tiles = os.path.join(out, 'tiles', f'{k:03d}')
    os.makedirs(tiles, exist_ok=True)
    parts = MR.load_parts(glb)
    yaw, pitch = pose['yaw'], pose['pitch']
    tm = texel_map(parts, yaw, pitch, CS.FINAL_PX)
    texs = [MR.texture_of(p)[0] for p in parts]
    metals = [metallic_of(p) for p in parts]
    ralpha = tm[0] >= 0
    base = from_map(tm, texs)
    P = CS.rgba(photo)
    y_photo = CS.lum(P[..., :3], P[..., 3] > 128)
    prgb, pmask = align_photo(P, ralpha)
    Image.fromarray(np.dstack([prgb, (pmask * 255).astype(np.uint8)])).save(os.path.join(tiles, 'photo.png'))
    pvis = erode(pmask, 2)
    PC = kmeans(lab(prgb)[pvis], K_PHOTO, seed=2)
    pcl = np.full(pmask.shape, -1, np.int32)
    pcl[pmask] = assign(lab(prgb)[pmask], PC)

    r = {'label': label, 'dir': run_dir, 'photo': photo, 'yaw': yaw, 'pitch': pitch, 'y_photo': round(y_photo, 4)}
    y_tex = CS.glb_basecolor(glb)
    r['y_tex'] = None if y_tex is None else round(y_tex, 4)
    y_vis = CS.lum(base, ralpha) or 0.0
    r['y_vis'] = round(y_vis, 4)

    # прежний прогон той же пачки (--reuse): «было» и А не зависят от порогов Б — берём готовые рендеры и цифры
    old = None
    if prev and prev.get('yaw') == yaw and prev.get('pitch') == pitch and isinstance(prev.get('A'), dict):
        if all(os.path.exists(os.path.join(prev['tiles'], f'{n}.png')) or (n == 'A' and 'skip' in prev['A'])
               for n in ('was', 'A')):
            old = prev

    # «было»: настоящий рендер mesh_render UNLIT=1 + сверка карты текселей с ним
    if old:
        import shutil
        for n in ('was', 'A'):
            if os.path.exists(os.path.join(old['tiles'], f'{n}.png')):
                shutil.copyfile(os.path.join(old['tiles'], f'{n}.png'), os.path.join(tiles, f'{n}.png'))
        a0 = np.asarray(Image.open(os.path.join(tiles, 'was.png')).convert('RGBA'))
    else:
        a0 = np.asarray(CS.unlit(glb, yaw, pitch, os.path.join(tiles, 'was.png'))[1])
    same = (np.abs(a0[..., :3].astype(int) - base.astype(int)).max(-1) <= 1) & ralpha
    r['map_check'] = round(float(same.sum() / max(ralpha.sum(), 1)), 4)
    r['was'] = measure(a0[..., :3], a0[..., 3] > 128, prgb, pmask, pcl, y_photo)

    # класс
    if y_tex is not None and y_tex < COLLAPSE_Y:
        r['cls'] = 'провал'
    elif abs(math.log2(max(y_photo, 1e-5) / max(y_vis, 1e-5))) > MAX_STOPS:
        r['cls'] = 'не тот материал'
    else:
        r['cls'] = None

    # А
    lgA = math.log2(max(y_photo, 1e-5) / max(y_vis, 1e-5))
    r['A_stops'] = round(lgA, 2)
    if r['cls'] is None and old and os.path.exists(os.path.join(tiles, 'A.png')):
        aA = np.asarray(Image.open(os.path.join(tiles, 'A.png')).convert('RGBA'))
        r['A'] = measure(aA[..., :3], aA[..., 3] > 128, prgb, pmask, pcl, y_photo)
        r['A_glb'] = old.get('A_glb') or os.path.join(os.path.dirname(os.path.dirname(old['tiles'])), 'glb',
                                                      os.path.basename(old['tiles']), 'A.glb')
    elif r['cls'] is None:
        tA = [None if t is None else gain(t, lgA) for t in texs]
        gA = os.path.join(out, 'glb', f'{k:03d}', 'A.glb')
        write_glb(glb, gA, tA)
        _, imA = CS.unlit(gA, yaw, pitch, os.path.join(tiles, 'A.png'))
        aA = np.asarray(imA)
        r['A'] = measure(aA[..., :3], aA[..., 3] > 128, prgb, pmask, pcl, y_photo)
        r['A_glb'] = gA
    else:
        r['A'] = {'skip': r['cls']}

    # А-L: тот же множитель только по светлоте (цветность Lab прежняя)
    if 'AL' in VARIANTS:
        if r['cls'] is None:
            tL = [None if t is None else gain_L(t, lgA) for t in texs]
            gL = os.path.join(out, 'glb', f'{k:03d}', 'AL.glb')
            write_glb(glb, gL, tL)
            aL = np.asarray(CS.unlit(gL, yaw, pitch, os.path.join(tiles, 'AL.png'))[1])
            r['AL'] = measure(aL[..., :3], aL[..., 3] > 128, prgb, pmask, pcl, y_photo)
            r['AL_glb'] = gL
        else:
            r['AL'] = {'skip': r['cls']}

    # чужие GLB той же формы (О1 — перекраска со сдвигом входа): рендер в той же позе, та же мерка
    for name, g in (extra or {}).items():
        if not os.path.exists(g):
            r[name] = {'skip': 'нет файла'}
            continue
        aX = np.asarray(CS.unlit(g, yaw, pitch, os.path.join(tiles, f'{name}.png'))[1])
        r[name] = measure(aX[..., :3], aX[..., 3] > 128, prgb, pmask, pcl, y_photo)
        r[f'{name}_glb'] = g
        y_x = CS.lum(aX[..., :3], aX[..., 3] > 128) or 0.0      # сколько ступеней ещё не хватает (для следующего круга О1)
        r[f'{name}_y_vis'] = round(y_x, 4)
        r[f'{name}_stops'] = round(math.log2(max(y_photo, 1e-5) / max(y_x, 1e-5)), 3)

    # Б (класс отказа — не лечим и здесь; участки всё равно считаем и показываем)
    if 'B' not in VARIANTS:
        r['zones'] = []
    elif r['cls'] == 'провал':
        r['B'] = {'skip': r['cls']}
        r['zones'] = []
    else:
        C, info, cl = zones(base, ralpha, prgb, pmask, pcl, tm, metals)
        r['zones'] = info
        lgs = np.array([z['lg'] for z in info], np.float32)
        ov = np.zeros(base.shape, np.uint8) + 235
        pal = {'правим': (40, 170, 60), 'не тот материал': (210, 40, 40), 'рисунок': (230, 170, 30),
               'рисунок·правим': (120, 200, 60),
               'металл': (60, 120, 220), 'нет пары на фото': (150, 150, 150), 'мелкий': (200, 200, 200)}
        for z in info:
            ov[cl == z['i']] = pal[z['st']]
        Image.fromarray(ov).save(os.path.join(tiles, 'zones.png'))
        if any(z['st'] == 'не тот материал' for z in info):
            wrong = sum(z['area'] for z in info if z['st'] == 'не тот материал')
            r['B_wrong_area'] = round(wrong, 3)
        if r['cls']:
            r['B'] = {'skip': r['cls']}
        elif not lgs.any():
            r['B'] = {'skip': 'нечего править'}
        else:
            vote = np.array([z['st'] != 'мелкий' for z in info])
            sig = np.array([z['spread'] for z in info], np.float32)
            tB = [None if t is None else gain(t, soft_lg(t, C, lgs, m, vote, sig)) for t, m in zip(texs, metals)]
            gB = os.path.join(out, 'glb', f'{k:03d}', 'B.glb')
            write_glb(glb, gB, tB)
            _, imB = CS.unlit(gB, yaw, pitch, os.path.join(tiles, 'B.png'))
            aB = np.asarray(imB)
            r['B'] = measure(aB[..., :3], aB[..., 3] > 128, prgb, pmask, pcl, y_photo)
    r['tiles'] = tiles
    return r


# ── листы ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lines(m: dict, c: str, r: dict) -> list[tuple[str, tuple]]:
    if 'skip' in m:
        return [(f"не правим: {m['skip']}", (130, 60, 0))]
    ok = m.get('pass')
    red, amber, green = (190, 0, 0), (180, 100, 0), (0, 120, 0)
    cl = lambda v, lo, hi: green if v <= lo else amber if v <= hi else red  # noqa: E731
    m8 = m.get('max_dL8')
    out = [(f"ΔL общий {m['dL_all']:+.0f}", cl(abs(m['dL_all']), 20, 40)),
           (f"медиана |ΔL| {m['med_dL']:.0f}", cl(m['med_dL'], 20, 40)),
           (f"худшая ≥8% |ΔL| {m8:.0f}" if m8 is not None else 'худшая ≥8% —', cl(m8 or 0, 40, 60)),
           (f"хрома ΔC {m['med_dC']:.0f}", cl(m['med_dC'], 8, 16)),
           ('НОРМА ✓' if ok else 'не норма', green if ok else red),
           (f"справка: худшая ≥3% {m['max_dL']:.0f}", (110, 110, 110))]
    if c in ('A', 'AL'):
        out.append((f"множитель {r['A_stops']:+.2f} ступени", (60, 60, 60)))
    if c == 'O1' and r.get('O1_note'):
        out.append((r['O1_note'], (60, 60, 60)))
    return out


def region_map(r: dict) -> Image.Image | None:
    """Области мерки (кластеры фото) окрашены по |ΔL| варианта Б (или А): зелёный ≤ 20, жёлтый ≤ 40, красный > 40;
    серый — область меньше REGION_MIN (не меряется). Кластеры пересчитываются с тем же зерном, что в `one`."""
    p = os.path.join(r['tiles'], 'photo.png')
    m = r['B'] if 'regions' in r.get('B', {}) else r.get('A', {})
    if not os.path.exists(p) or 'regions' not in m:
        return None
    P = np.asarray(Image.open(p).convert('RGBA'))
    prgb, pmask = P[..., :3], P[..., 3] > 127
    PC = kmeans(lab(prgb)[erode(pmask, 2)], K_PHOTO, seed=2)
    pcl = np.full(pmask.shape, -1, np.int32)
    pcl[pmask] = assign(lab(prgb)[pmask], PC)
    out = np.zeros(P.shape, np.uint8)
    out[pmask] = (190, 190, 190, 255)
    for g in m['regions']:
        d = abs(g['dL'])
        out[pcl == g['j']] = (60, 170, 70, 255) if d <= 20 else (235, 170, 30, 255) if d <= 40 else (215, 40, 40, 255)
    return Image.fromarray(out)


METRIC_COLS = ('was', 'A', 'AL', 'B', 'O1')


def sheet(rs: list, out_png: str, tile: int, hard: bool = False, cols: list | None = None, title: str = 'О2') -> None:
    cols = list(cols or (['photo', 'was', 'A', 'B'] + (['zones', 'err'] if hard else [])))
    names = {'photo': 'фото товара', 'was': 'было (меш без света)', 'A': 'А: один множитель', 'B': 'Б: по участкам',
             'AL': 'А-L: множитель по светлоте', 'O1': 'О1: перекраска (лучший круг)',
             'zones': 'участки Б', 'err': 'где промах Б'}
    fs, fb = CS._font(max(12, tile // 19)), CS._font(max(13, tile // 16))
    lh = max(15, tile // 15)
    text_rows = 9 if hard else 8
    head = lh * 4
    W = tile * len(cols)
    row_h = lh + tile + lh * text_rows + 10
    sh = Image.new('RGB', (W, head + len(rs) * row_h), (243, 243, 243))
    dr = ImageDraw.Draw(sh)
    dr.text((6, 4), f'{title} · мерка: рендер без света против фото; ΔL — байты sRGB (0–255); норма: медиана |ΔL| ≤ 20, '
            'худшая область ≥ 8 % ≤ 40, хрома ≤ 8', fill=(0, 0, 0), font=fs)
    dr.text((6, 4 + lh), 'зелёный — в норме, жёлтый — близко, красный — далеко; медианы по площади областей фото',
            fill=(60, 60, 60), font=fs)
    for j, c in enumerate(cols):
        dr.text((j * tile + 6, 4 + 2.5 * lh), names[c], fill=(0, 0, 0), font=fb)
    pal_txt = {'правим': (40, 150, 60), 'не тот материал': (200, 30, 30), 'рисунок': (190, 130, 0),
               'рисунок·правим': (90, 150, 40),
               'металл': (50, 100, 200), 'нет пары на фото': (110, 110, 110), 'мелкий': (150, 150, 150)}
    for i, r in enumerate(rs):
        y0 = head + i * row_h
        dr.line((0, y0 - 4, W, y0 - 4), fill=(200, 200, 200))
        h = f"{r['label']} · Y фото {r['y_photo']} → меш {r.get('y_vis')}"
        if r.get('cls'):
            h += f" · КЛАСС: {r['cls'].upper()} (не лечим)"
        dr.text((6, y0), h, fill=(0, 0, 140), font=fb)
        for j, c in enumerate(cols):
            x = j * tile
            if c == 'err':
                im = region_map(r)
            else:
                p = os.path.join(r['tiles'], f'{c}.png')
                im = Image.open(p).convert('RGBA') if os.path.exists(p) else None
            if im is not None and c == 'zones':
                a = np.asarray(Image.open(os.path.join(r['tiles'], 'was.png')).convert('RGBA'))[..., 3] > 0
                z = np.asarray(im.convert('RGB'))
                im = Image.fromarray(np.dstack([z, (a * 255).astype(np.uint8)]))
            if im is not None and im.getbbox():
                im = im.crop(im.getbbox())
                im.thumbnail((tile - 8, tile - 8))
                bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
                bg.alpha_composite(im)
                sh.paste(bg.convert('RGB'), (x + 4 + (tile - 8 - im.size[0]) // 2, y0 + lh + (tile - 8 - im.size[1]) // 2))
            ty = y0 + lh + tile
            if c in METRIC_COLS and isinstance(r.get(c), dict):
                for q, (s, col) in enumerate(_lines(r[c], c, r)):
                    dr.text((x + 6, ty + q * lh), s, fill=col, font=fs)
            if c == 'zones':
                for q, z in enumerate(sorted(r.get('zones', []), key=lambda z: -z['area'])[:text_rows]):
                    s = f"{z['area'] * 100:.0f}% · {z['st']}"
                    if 'need' in z and z['st'] != 'мелкий':
                        s += f" · {z['need']:+.1f} ст"
                    dr.text((x + 6, ty + q * lh), s, fill=pal_txt.get(z['st'], (40, 40, 40)), font=fs)
            if c == 'err':
                for q, s in enumerate(('зелёный |ΔL| ≤ 20', 'жёлтый ≤ 40', 'красный > 40', 'серый — < 3 %, не меряем')):
                    dr.text((x + 6, ty + q * lh), s, fill=(60, 60, 60), font=fs)
    sh.save(out_png)


# ── пачка ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def batch(list_tsv: str, steps_jsonl: str, out: str, big: list[str], reuse: str | None = None) -> int:
    os.makedirs(out, exist_ok=True)
    prev = {}
    if reuse:
        for ln in open(reuse, encoding='utf-8'):
            r = json.loads(ln)
            if 'err' not in r:
                prev[r['label']] = r
    poses = {}
    for ln in open(steps_jsonl, encoding='utf-8'):
        r = json.loads(ln)
        if r.get('pose'):
            poses[r['label']] = r['pose']
    rows = [ln.rstrip('\n').split('\t') for ln in open(list_tsv, encoding='utf-8') if ln.strip()]
    res, bad = [], 0
    with open(os.path.join(out, 'o2.jsonl'), 'w', encoding='utf-8') as fo:
        for k, row in enumerate(rows):
            label, run_dir, photo = row[:3]
            # 4-й столбец (необязательный): «имя=путь.glb;имя2=…» — чужие GLB той же формы (О1) в ту же мерку
            extra = dict(x.split('=', 1) for x in (row[3].split(';') if len(row) > 3 else []) if '=' in x)
            try:
                r = one(label, run_dir, photo, poses[label], out, k, prev.get(label), extra)
            except Exception as e:  # noqa: BLE001 — счётчик сбоев, не молча
                import traceback
                traceback.print_exc()
                r = {'label': label, 'err': f'{type(e).__name__}: {str(e)[:200]}'}
                bad += 1
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
            fo.flush()
            res.append(r)
            if 'err' in r:
                print(f'[{k + 1}/{len(rows)}] {label}: СБОЙ {r["err"]}', flush=True)
            else:
                f = lambda m: m.get('skip') or f"{m['dL_all']:+.0f}/{m['med_dL']}/{m.get('max_dL8')}/{m['med_dC']}{' ✓' if m['pass'] else ''}"  # noqa: E731,E501
                print(f"[{k + 1}/{len(rows)}] {label}: карта {r['map_check']} класс {r['cls']} было {f(r['was'])} "
                      + ' '.join(f"{c} {f(r[c])}" for c in METRIC_COLS[1:] if isinstance(r.get(c), dict))
                      + ' участки ' + ' '.join(f"{z['area']:.2f}:{z['st']}" for z in r['zones']), flush=True)
    sheets([r for r in res if 'err' not in r], out, big)
    print(f'разобрано {len(rows)}, сбоев {bad}; лист {os.path.join(out, "sheet.png")}')
    return 1 if bad else 0


def sheets(ok: list, out: str, big: list[str]) -> None:
    if any(isinstance(r.get('B'), dict) for r in ok):
        sheet(ok, os.path.join(out, 'sheet.png'), 240)
    else:   # без Б (T-85/5): столбцы — те варианты, что есть хоть у одной строки
        cols = ['photo', 'was'] + [c for c in METRIC_COLS[1:] if any(isinstance(r.get(c), dict) for r in ok)]
        sheet(ok, os.path.join(out, 'sheet.png'), 240, cols=cols, title='О2/О1')
    if big:
        sheet([r for b in big for r in ok if r['label'] == b], os.path.join(out, 'sheet-hard.png'), 400, hard=True)


# ── самопроверка ──────────────────────────────────────────────────────────────────────────────────────────────────

def selftest() -> int:
    import tempfile
    import trimesh
    import mesh_render as MR
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if not cond else ''))
        bad += 0 if cond else 1

    # ящик с текстурой из двух половин: светлая (200) и тёмная (60)
    box = trimesh.creation.box(extents=(1.0, 0.6, 0.4))
    v = np.asarray(box.vertices)
    uv = np.column_stack([(v[:, 0] + 0.5) * 0.98 + 0.01, (v[:, 1] + 0.3) / 0.6 * 0.98 + 0.01])
    img = np.zeros((32, 32, 3), np.uint8)
    img[:, :16] = 200
    img[:, 16:] = 60
    box.visual = trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(img))
    with tempfile.TemporaryDirectory(prefix='color-o2-', dir=os.environ.get('O2_TEST_TMP')) as tmp:
        glb = os.path.join(tmp, 'm.glb')
        trimesh.Scene([box]).export(glb)
        parts = MR.load_parts(glb)
        tm = texel_map(parts, 15, 10, 120)
        texs = [MR.texture_of(p)[0] for p in parts]
        os.environ['UNLIT'] = '1'
        ref = np.asarray(MR.render(MR.load_parts(glb), yaw_deg=15, pitch_deg=10, size=(120, 120)))
        os.environ.pop('UNLIT')
        mine = from_map(tm, texs)
        ok('карта текселей = рендер без света', bool(np.array_equal(ref[..., :3], mine) and
                                                    np.array_equal(ref[..., 3] > 0, tm[0] >= 0)))
        g = gain(np.full((2, 2, 3), 128, np.uint8), 1.0)
        ok('множитель ×2 в линейном свете: 128 → 176', int(g[0, 0, 0]) == 176, g[0, 0])
        ok('множитель 0 ступеней — без изменений', np.array_equal(gain(img, 0.0), img))
        gl = gain_L(np.full((2, 2, 3), 128, np.uint8), 1.0)
        ok('А-L: серый 128 ×2 по Y → 176', bool(np.all(np.abs(gl.astype(int) - 176) <= 1)), gl[0, 0])
        wood = np.array([[[180, 120, 80], [150, 110, 90]]], np.uint8)
        lw, ll = lab(wood), lab(gain_L(wood, 0.6))
        ok('А-L: цветность a,b прежняя, светлота выросла',
           bool(np.abs(lw[..., 1:] - ll[..., 1:]).max() < 1.0 and (ll[..., 0] > lw[..., 0] + 5).all()),
           (lw.round(1).tolist(), ll.round(1).tolist()))
        ok('А-L: 0 ступеней — без изменений (±1)', int(np.abs(gain_L(img, 0.0).astype(int) - img).max()) <= 1)
        C = np.array(lab(np.array([[200, 200, 200], [60, 60, 60]], np.uint8)), np.float32)
        lg = soft_lg(img, C, np.array([-1.0, 0.0], np.float32), None)
        ok('Б: правим только светлый участок, тёмный цел', abs(lg[0, 0] + 1) < 0.02 and abs(lg[0, 31]) < 0.02, lg[0, [0, 31]])
        far = soft_lg(np.full((2, 2, 3), (20, 200, 30), np.uint8), C, np.array([-1.0, -1.0], np.float32), None)
        ok('Б: цвет далеко от участков — без поправки', float(np.abs(far).max()) < 0.01, far.max())
        X = np.vstack([np.random.default_rng(0).normal(c, 1.0, (500, 3)) for c in ((20, 0, 0), (60, 10, 10), (61, 10, 11))])
        ok('кластеры: близкие центры сливаются', len(kmeans(X.astype(np.float32), 3)) == 2)
        P = np.zeros((50, 80, 4), np.uint8)
        P[10:40, 20:60] = (90, 90, 90, 255)
        ra = np.zeros((120, 120), bool)
        ra[30:90, 10:110] = True
        prgb, pm = align_photo(P, ra)
        ok('фото вписано в рамку силуэта', bool(pm[31:89, 11:109].all() and not pm[:29].any()))
    print('самопроверка: ' + ('ПРОВАЛ' if bad else 'все проверки прошли'))
    return 1 if bad else 0


def main() -> int:
    a = sys.argv[1:]
    if a and a[0] == '--selftest':
        return selftest()
    reuse = None
    if '--reuse' in a:
        i = a.index('--reuse')
        reuse = a[i + 1]
        a = a[:i] + a[i + 2:]
    if len(a) >= 3 and a[0] == 'sheet':                   # пересобрать листы из готового o2.jsonl
        ok = [json.loads(ln) for ln in open(a[1], encoding='utf-8')]
        sheets([r for r in ok if 'err' not in r], a[2], [s for s in (a[3].split(',') if len(a) > 3 else []) if s])
        return 0
    if len(a) >= 4 and a[0] == 'batch':
        return batch(a[1], a[2], a[3], [s for s in (a[4].split(',') if len(a) > 4 else []) if s], reuse)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
