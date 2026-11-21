#!/usr/bin/env python3
"""ЭТАП 6 «ФОТО НА ВИДИМОЕ» (T-20261120-168; план paint-photo-fill-01, § «Этапы», «Проверка на каждом этапе»). Бесплатно, на процессоре (numpy + scipy + trimesh + cv2 + PIL).

Что делает: берёт форму (GLB с развёрткой; текстуры нет — серая заготовка), вырезку фото и КАМЕРУ ФОТО ОТ ЭТАПА 4 (р.2, `pose_fit.py`, T-112: перспективная; в папке прогона лежат
`stages/render_view0/{ids,uv,aoi_cos16,mask}`, `stages/manifest.json`, `stage_loss.json` с матрицей фото→кадр) и каждому тексель-у, который эта камера видит (первая грань вдоль луча, угол
к камере лучше `COS_MIN`, внутри силуэта фото с отступом от края), присваивает цвет фото в точке его проекции. Прямой перенос, без нейросети: цвет и узор видимого бока — настоящие, не нарисованные.
Своей камеры здесь нет (решение директора 20.11): камера — вход этапа. Невидимое не трогается (серая заготовка) — его закрывает этап 7 (`tex_fill.py`, р.3).
Выход этапа — `<run>/<sku>/06-visible/`: `visible.glb`, `known.png` (маска «тексель взят с фото»), `check.json` (через `paint_stage.write_check`), `frame.png` (фото | кадр с камеры фото | ±40°).

Qwen-правка — ТОЛЬКО если прямой перенос не лёг: гейт не прошёл → `check.json`: passed=false, `extra.needs_qwen=true`, причина по меркам (запасной путь — отдельным шагом, после камеры).
Гейт (все пороги — `GATE`; ПРОВИЗОРНЫЕ до замера на 12 трудных, в план — только после замера):
  silhouette_iou   — совпадение силуэта фото и формы в кадре камеры (`iou_frame` этапа 4; план: ≥ 0,85, иначе камере не верим → дальше не идёт);
  known_share      — доля занятых текселей, взятых с фото (честный охват; ниже порога — нечего переносить);
  edge_corr / lab_dE — перенос не потерян при записи: края и медиана Lab «фото ↔ кадр по новой текстуре» (по частям — часть = геометрия GLB, пока нет масок р.1).
Справочно (без порога): `edge_agree` этапа 4 — совпадение внутренних кромок формы и фото.
ID товаров в код не попадают.

  python tex_visible.py <shape.glb> <photo.rgba.png> <pose_run> <run_dir> <sku>      # pose_run — папка `fit_pose` этапа 4 (stage_loss.json + stages/)
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
SCOUT = os.path.dirname(SALAD)
sys.path[:0] = [HERE, SALAD, SCOUT]

import tex_coverage as TC  # noqa: E402
import paint_stage as PS  # noqa: E402

def _rules() -> dict:
    try:
        return json.load(open(os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


R = _rules()
COS_MIN = float(R.get('cos_min', 0.40))          # cos угла к лучу: 66° и больше — вскользь, не берём (rules/tex-visible.json)
DEPTH_JUMP = float(R.get('depth_jump_px', 12.0))  # разрыв глубины между соседними пикселями кадра больше стольких px_len — край складки/щели: полоса вокруг не берётся
COS_MED = int(R.get('cos_median_px', 5))     # медиана карты cos по занятым пикселям (рябь от грани к грани)
DEPTH_MED = int(R.get('depth_median_px', 7))   # медиана карты глубины перед поиском разрыва: на рёбрах треугольников в ней пятна-выбросы
DEPTH_BAND = int(R.get('depth_band_px', 2))      # ширина этой полосы, пикселей кадра
COS_FULL = float(R.get('cos_full', 0.60))         # полный вес с этого косинуса; между COS_MIN и COS_FULL — плавная передача заготовке
EDGE_FRAC = 4.0 / 480   # отступ от силуэта фото внутрь, доли стороны кадра: вес растёт от 0 до 1 (там фон и ореол)
GUTTER = 6              # желоб вокруг островков, пикселей текстуры (билинейная выборка у шва не берёт серый фон)
EDGE_ERODE = float(R.get('edge_erode_px', 2.0))        # жёсткая эрозия маски фото: пиксели ближе к краю силуэта не берутся совсем (там белый фон и ореол; директор 21.11)
W_TAKE = 0.25           # вес меньше — тексель не берём (остаётся прежним), вес выше — цвет фото целиком, без подмеса светлой заготовки (иначе светлые полосы на вскользь видимых краях)
HOLE_R = 2.5            # дыры между взятыми текселями (пикселей кадра реже текселей) закрываются ближайшим взятым не дальше этого, текселей
DEPTH_PX = 3.0          # допуск «тексель не заслонён»: расхождение глубины точки и буфера глубины камеры не больше стольких пикселей предмета (у косых граней — шире)
GREY = 128
FRONT_COS = 0.80       # мерка света «перёд↔бок»: перёд — cos ≥ этого, бок — от cos_min до SIDE_COS
SIDE_COS = 0.65
GATE = {                # (порог, op) — провизорно, см. шапку
    'silhouette_iou': (0.85, '>='),
    'known_share': (0.15, '>='),
    'edge_corr': (0.90, '>='),
    'lab_dE': (3.0, '<='),
}


# ── вход ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_shape(path: str) -> list:
    """GLB → геометрии {'V','F','UV','tex'}: как `tex_coverage.load_geoms`, но без текстуры берётся серая заготовка 2048² (форма из sg_prep_shape её не несёт)."""
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    out = []
    for name, g in sc.geometry.items():
        try:
            g.apply_transform(sc.graph.get(name)[0])
        except Exception:  # noqa: BLE001
            pass
        vis = getattr(g, 'visual', None)
        uv = getattr(vis, 'uv', None)
        if uv is None:
            raise ValueError(f'{os.path.basename(path)}: у геометрии «{name}» нет развёртки')
        mat = getattr(vis, 'material', None)
        im = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        if im is not None and min(im.size) < 64:                 # заглушка 1–2 пикселя, которую trimesh подставляет форме без текстуры, — это не текстура
            im = None
        tex = np.asarray(im.convert('RGB'), np.uint8) if im is not None else np.full((2048, 2048, 3), GREY, np.uint8)
        if tex.shape[0] != tex.shape[1]:
            tex = np.asarray(Image.fromarray(tex).resize((max(tex.shape[:2]),) * 2, Image.BILINEAR))
        out.append({'name': name, 'V': np.asarray(g.vertices, np.float64), 'F': np.asarray(g.faces, np.int64), 'UV': np.asarray(uv, np.float64), 'tex': tex, 'has_tex': im is not None})
    if not out:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    return out


def load_stage(pose_run: str) -> dict:
    """Камера этапа 4 из папки прогона `pose_fit.fit_pose`: растр вида (id грани, UV, cos, маска), матрица фото→кадр, числа камеры. Нет `ids.npz` — прогон старше коммита eabaff04, камеру надо пересчитать."""
    rd = os.path.join(pose_run, 'stages', 'render_view0')
    need = [os.path.join(rd, f) for f in ('ids.npz', 'uv.npz', 'depth.npz', 'aoi_cos16.png', 'mask.png')] + [os.path.join(pose_run, 'stage_loss.json')]
    miss = [os.path.basename(p) for p in need if not os.path.exists(p)]
    if miss:
        raise FileNotFoundError(f'{pose_run}: нет {", ".join(miss)} — камеру этапа 4 надо (пере)считать pose_fit.fit_pose')
    sl = json.load(open(os.path.join(pose_run, 'stage_loss.json'), encoding='utf-8'))
    ids = np.load(os.path.join(rd, 'ids.npz'))['ids']
    uv = np.load(os.path.join(rd, 'uv.npz'))['uv']
    dz = np.load(os.path.join(rd, 'depth.npz'))
    depth, px_len = dz['depth'], float(dz['px_len'])
    cos = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png')), np.float32) / 65535.0
    mask = np.asarray(Image.open(os.path.join(rd, 'mask.png'))) > 127
    if COS_MED > 1 and mask.any():
        from scipy.ndimage import median_filter
        cos = np.where(mask, median_filter(np.where(mask, cos, float(np.median(cos[mask]))), size=COS_MED), 0.0).astype(np.float32)
    px = ids.shape[0]
    P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)
    return {'ids': ids, 'uv': uv, 'depth': depth, 'px_len': px_len, 'cos': cos, 'mask': mask, 'px': px, 'P': P, 'camera': sl.get('camera'), 'iou_frame': sl['registration'].get('iou'), 'pose_run': pose_run}


def photo_to_frame(photo_rgba: np.ndarray, P: np.ndarray, px: int) -> tuple[np.ndarray, np.ndarray]:
    """Фото в кадр камеры по обратной карте P (кадр → пиксель фото; как `stage_loss.warp_inv`). Цвет — с учётом альфы (без ореола фона). Возвращает (rgb uint8 px×px×3, маска фото в кадре)."""
    import cv2
    a = photo_rgba[..., 3:4].astype(np.float32) / 255.0
    src = np.concatenate([photo_rgba[..., :3].astype(np.float32) * a, a], axis=2)
    fl = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    w = cv2.warpAffine(src, np.asarray(P, np.float64)[:2], (px, px), flags=fl, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    al = w[..., 3]
    rgb = np.where(al[..., None] > 1e-3, w[..., :3] / np.maximum(al[..., None], 1e-3), 0.0)
    return np.clip(rgb + 0.5, 0, 255).astype(np.uint8), al > 0.5


# ── перенос ────────────────────────────────────────────────────────────────────────────────────────────────────────

def face_maps(st: dict, nF: int, off: int = 0) -> dict:
    """Для каждой видимой грани — линейная карта «координата развёртки → пиксель кадра» (x, y) и глубина Z, подогнанные по пикселям растра камеры этой грани (метод наименьших квадратов, центрированно).
    Так тексель (любой плотности — текстура может быть гуще кадра) находит СВОЮ точку на фото; растр id/UV/глубины — то, что отдаёт этап 4. Грани с < 3 пикселей или вырожденные — `ok=False`."""
    ids, uv, depth, mask = st['ids'], st['uv'], st['depth'], st['mask']
    ys, xs = np.nonzero(mask & (ids >= off) & (ids < off + nF))
    f = (ids[ys, xs] - off).astype(np.int64)
    u, v = uv[ys, xs, 0].astype(np.float64), uv[ys, xs, 1].astype(np.float64)
    X, Y, Z = xs + 0.5, ys + 0.5, depth[ys, xs].astype(np.float64)
    cnt = np.bincount(f, minlength=nF).astype(np.float64)
    c1 = np.maximum(cnt, 1.0)
    mu, mv = np.bincount(f, u, nF) / c1, np.bincount(f, v, nF) / c1
    mx, my, mz = np.bincount(f, X, nF) / c1, np.bincount(f, Y, nF) / c1, np.bincount(f, Z, nF) / c1
    du, dv = u - mu[f], v - mv[f]
    Suu, Suv, Svv = np.bincount(f, du * du, nF), np.bincount(f, du * dv, nF), np.bincount(f, dv * dv, nF)
    det = Suu * Svv - Suv * Suv
    ok = (cnt >= 3) & (det > 1e-3 * np.maximum(Suu * Svv, 1e-30)) & (Suu * Svv > 0)
    d1 = np.where(ok, det, 1.0)
    out = {'ok': ok, 'mu': mu, 'mv': mv, 'mx': mx, 'my': my, 'mz': mz, 'cos': np.bincount(f, st['cos'][ys, xs].astype(np.float64), nF) / c1, 'cnt': cnt}
    for name, val in (('x', X - mx[f]), ('y', Y - my[f]), ('z', Z - mz[f])):
        sa, sb = np.bincount(f, du * val, nF), np.bincount(f, dv * val, nF)
        out['a' + name] = (sa * Svv - sb * Suv) / d1
        out['b' + name] = (sb * Suu - sa * Suv) / d1
    return out


def smooth_depth(st: dict) -> np.ndarray:
    """Глубина растра, очищенная от пятен-выбросов на рёбрах треугольников (медиана 3×3 по занятым пикселям; пустое остаётся 0)."""
    from scipy.ndimage import median_filter
    d = st['depth'].astype(np.float64)
    ok = d > 0
    if not ok.any():
        return d
    sm = median_filter(np.where(ok, d, float(np.median(d[ok]))), size=3)
    return np.where(ok, sm, 0.0)


def depth_band(st: dict) -> np.ndarray:
    """Маска кадра: пиксели у разрыва глубины (край складки, щель между подушками, торец за выступом) шире DEPTH_BAND px — фото там берёт тень щели, а не поверхность."""
    from scipy.ndimage import binary_dilation, median_filter
    d0 = st['depth'].astype(np.float64)
    ok = (d0 > 0) & st['mask']
    d = median_filter(np.where(d0 > 0, d0, float(np.median(d0[ok])) if ok.any() else 0.0), size=max(DEPTH_MED, 1)) if DEPTH_MED > 1 else d0
    lim = max(float(st.get('px_len') or 0.0), 1e-6) * DEPTH_JUMP
    jump = np.zeros(d.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        a, b = d[: d.shape[0] - dy, : d.shape[1] - dx], d[dy:, dx:]
        both = ok[: d.shape[0] - dy, : d.shape[1] - dx] & ok[dy:, dx:]
        j = both & (np.abs(a - b) > lim)
        jump[: d.shape[0] - dy, : d.shape[1] - dx] |= j
        jump[dy:, dx:] |= j
    if DEPTH_BAND <= 0:
        return jump
    return binary_dilation(jump, iterations=DEPTH_BAND)


def transfer(geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, cos_min: float = COS_MIN) -> dict:
    """Новые текстуры + маски «известно» по геометриям. Каждый занятый тексель идёт на фото СВОЕЙ точкой (карта грани, `face_maps`), берётся, если: его грань видна с углом лучше `cos_min`,
    глубина точки совпадает с буфером глубины камеры (не заслонена), точка внутри силуэта фото с отступом от края. Цвет — билинейно с фото; невидимое остаётся прежним."""
    from scipy.ndimage import distance_transform_edt, map_coordinates
    ids = st['ids']
    depth = smooth_depth(st)                                        # сырая карта в пятнах на рёбрах треугольников: проверка «не заслонён» — по медиане 3×3
    px = st['px']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    if ids.max() >= offs[-1]:
        raise ValueError(f'растр камеры ссылается на грань {int(ids.max())}, в форме граней {int(offs[-1])} — форма не та, что у камеры')
    dist_edge = distance_transform_edt(pmask)
    nogo = depth_band(st)
    n_nogo = int((nogo & st['mask']).sum())
    edge_px = max(EDGE_FRAC * px, 1.0)
    z_eps = max(float(st.get('px_len') or 0.0), 1e-6) * DEPTH_PX
    texs, knowns, stats = [], [], []
    for gi, g in enumerate(geoms):
        T = int(g['tex'].shape[0])
        F, UV = g['F'], g['UV']
        fm = face_maps(st, len(F), int(offs[gi]))
        xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
        fid, _ = TC.raster(xy, F, T)
        fid = fid.reshape(T, T)
        occ = fid >= 0
        ty, tx = np.nonzero(occ)
        f = fid[ty, tx].astype(np.int64)
        ut, vt = (tx + 0.5) / T, (ty + 0.5) / T
        du, dv = ut - fm['mu'][f], vt - fm['mv'][f]
        x = fm['mx'][f] + fm['ax'][f] * du + fm['bx'][f] * dv
        y = fm['my'][f] + fm['ay'][f] * du + fm['by'][f] * dv
        z = fm['mz'][f] + fm['az'][f] * du + fm['bz'][f] * dv
        inside = fm['ok'][f] & (x >= 0.5) & (x <= px - 0.5) & (y >= 0.5) & (y <= px - 0.5)
        xi, yi = np.clip(np.floor(x).astype(np.int64), 0, px - 1), np.clip(np.floor(y).astype(np.int64), 0, px - 1)
        front = np.abs(z - depth[yi, xi]) <= z_eps * np.maximum(1.0, 1.0 / np.maximum(fm['cos'][f], 0.2))       # у косых граней глубина меняется быстрее по пикселю — допуск растёт
        cs = fm['cos'][f]
        w_ang = np.clip((cs - cos_min) / max(COS_FULL - cos_min, 1e-6), 0.0, 1.0)
        w_edge = np.clip((map_coordinates(dist_edge.astype(np.float32), [y - 0.5, x - 0.5], order=1, mode='nearest') - EDGE_ERODE) / edge_px, 0.0, 1.0)
        w = np.where(inside & front & (depth[yi, xi] > 0) & pmask[yi, xi] & ~nogo[yi, xi], w_ang * w_edge, 0.0)
        use = w >= W_TAKE
        col = np.stack([map_coordinates(prgb[..., c].astype(np.float32), [y[use] - 0.5, x[use] - 0.5], order=1, mode='nearest') for c in range(3)], 1)
        tex = g['tex'].astype(np.float64).copy()
        sel = (ty[use], tx[use])
        tex[sel] = col
        wmap = np.zeros((T, T), np.float64)
        wmap[ty, tx] = w
        known = wmap >= W_TAKE
        n_face = int(known.sum())
        ys, xs = np.nonzero(st['mask'] & (ids >= offs[gi]) & (ids < offs[gi + 1]))             # проход 2: пиксели растра камеры — каждый на тексель СВОЕЙ развёртки (грани мельче пикселя карту грани не строят)
        wp = np.clip((st['cos'][ys, xs] - cos_min) / max(COS_FULL - cos_min, 1e-6), 0.0, 1.0) * np.clip((dist_edge[ys, xs] - EDGE_ERODE) / edge_px, 0.0, 1.0) * pmask[ys, xs] * (~nogo[ys, xs])
        keep = wp >= W_TAKE
        ys, xs, wp = ys[keep], xs[keep], wp[keep]
        tpx = np.clip(np.floor(st['uv'][ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        tpy = np.clip(np.floor(st['uv'][ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        flat = tpy * T + tpx
        sw = np.bincount(flat, wp, T * T).reshape(T, T)
        scol = np.stack([np.bincount(flat, wp * prgb[ys, xs, c].astype(np.float64), T * T).reshape(T, T) for c in range(3)], 2)
        take = occ & ~known & (sw >= W_TAKE)
        tex[take] = scol[take] / sw[take][:, None]
        known = known | take
        n_splat = int(take.sum())
        hd, (hy, hx) = distance_transform_edt(~known, return_distances=True, return_indices=True)       # дыры между пикселями: ближайший взятый тексель не дальше HOLE_R
        fill = occ & ~known & (hd <= HOLE_R)
        tex[fill] = tex[hy[fill], hx[fill]]
        known = known | fill
        n_fill = int(fill.sum())
        gd, (iy, ix) = distance_transform_edt(~occ, return_distances=True, return_indices=True)     # желоб: ближайший занятый тексель на GUTTER пикселей наружу
        ring = (~occ) & (gd <= GUTTER)
        tex[ring] = tex[iy[ring], ix[ring]]
        texs.append(np.clip(tex + 0.5, 0, 255).astype(np.uint8))
        knowns.append(known)
        stats.append({'name': g['name'], 'T': T, 'occupied': int(occ.sum()), 'known': int(known.sum()), 'faces_ok': int(fm['ok'].sum()), 'faces_seen': int((fm['cnt'] > 0).sum()), 'texels_taken': int(use.sum()), 'known_facemap': n_face, 'known_splat': n_splat, 'known_filled': n_fill})
    return {'tex': texs, 'known': knowns, 'stats': stats, 'depth_band_share': round(n_nogo / max(int(st['mask'].sum()), 1), 4)}


def write_glb(geoms: list, texs: list, dst: str) -> None:
    """Те же форма и развёртка, текстура baseColor — новая (геометрии пишутся как есть, без слияния вершин)."""
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, t in zip(geoms, texs):
        m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
        m.visual = TextureVisuals(uv=g['UV'], material=PBRMaterial(baseColorTexture=Image.fromarray(t), metallicFactor=0.0, roughnessFactor=0.9))
        sc.add_geometry(m, node_name=g['name'], geom_name=g['name'])
    sc.export(dst)


# ── мерки ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lab(rgb8: np.ndarray) -> np.ndarray:
    import recolor_lp as LP
    return LP.lab_f(rgb8)      # lab_f сам принимает sRGB 0–255 (прежний s2l перед ним сводил Lab к нулю: lab_dE и front_side были пустыми числами)


def _sobel(L: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, sobel
    b = gaussian_filter(L.astype(np.float32), 1.5)
    return np.hypot(sobel(b, axis=1), sobel(b, axis=0))


def frame_from_tex(st: dict, geoms: list, texs: list) -> np.ndarray:
    """Кадр камеры, как его даст НОВАЯ текстура: цвет по UV растра камеры (проверка, что запись текстуры и развёртка держат перенос)."""
    ids, uv, mask = st['ids'], st['uv'], st['mask']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    out = np.full(ids.shape + (3,), 255, np.uint8)
    gid = np.full(ids.shape, -1, np.int32)
    gid[ids >= 0] = np.searchsorted(offs, ids[ids >= 0], side='right') - 1
    for gi, t in enumerate(texs):
        T = t.shape[0]
        ys, xs = np.nonzero((gid == gi) & mask)
        tx_ = np.clip(np.floor(uv[ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        ty_ = np.clip(np.floor(uv[ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        out[ys, xs] = t[ty_, tx_]
    return out


def hatch(tex: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Только для показа: непросмотренные тексели — нейтральная серая штриховка (цвет заготовки не путать с цветом товара)."""
    out = tex.copy()
    ty, tx = np.mgrid[0: tex.shape[0], 0: tex.shape[1]]
    pat = np.where(((tx + ty) // 6) % 2 == 0, 205, 170).astype(np.uint8)
    miss = ~known
    out[miss] = pat[miss][:, None]
    return out


def metrics(geoms, st, prgb, pmask, tr, after: np.ndarray, cos_min: float) -> dict:
    from scipy.ndimage import binary_erosion
    import recolor_lp as LP
    occ = sum(s['occupied'] for s in tr['stats'])
    kn = sum(s['known'] for s in tr['stats'])
    iou = st.get('iou_frame')
    A, S = pmask, st['mask']
    if iou is None:
        iou = float((A & S).sum() / max((A | S).sum(), 1))
    out = {'silhouette_iou': round(float(iou), 4), 'known_share': round(kn / max(occ, 1), 4)}
    both = binary_erosion(S, iterations=3) & binary_erosion(A, iterations=3) & (st['cos'] >= cos_min)
    out['both_px'] = int(both.sum())
    if both.sum() > 200:
        Lp, La = _lab(prgb), _lab(after)
        ep, ea = _sobel(Lp[..., 0]), _sobel(La[..., 0])
        out['edge_corr'] = round(float(np.corrcoef(ep[both], ea[both])[0, 1]), 4)
        out['lab_dE'] = round(float(np.median(LP.de2000(Lp[both], La[both]))), 3)
        offs = np.cumsum([0] + [len(g['F']) for g in geoms])
        gid = np.zeros(st['ids'].shape, np.int16)
        gid[st['ids'] >= 0] = np.searchsorted(offs, st['ids'][st['ids'] >= 0], side='right') - 1
        per = {}
        for gi, g in enumerate(geoms):
            mk = both & (gid == gi)
            if mk.sum() > 100:
                per[g['name']] = round(float(np.median(LP.de2000(Lp[mk], La[mk]))), 3)
        out['lab_dE_by_part'] = per
        # независимая мерка света: одна ткань, перёд против бока — медианы Lab фото на пикселях «перёд» (cos ≥ FRONT_COS) и «бок» (cos между COS_MIN и SIDE_COS) внутри части, без полосы разрыва глубины
        free = both & ~depth_band(st)
        fs = {}
        for gi, g in enumerate(geoms):
            mk = free & (gid == gi)
            fr, sd = mk & (st['cos'] >= FRONT_COS), mk & (st['cos'] >= cos_min) & (st['cos'] < SIDE_COS)
            if fr.sum() > 300 and sd.sum() > 300:
                mf, ms = np.median(Lp[fr], axis=0), np.median(Lp[sd], axis=0)
                fs[g['name']] = {'dE': round(float(LP.de2000(mf[None], ms[None])[0]), 3), 'dL': round(float(mf[0] - ms[0]), 2), 'n_front': int(fr.sum()), 'n_side': int(sd.sum())}
        out['front_side'] = fs
    return out


def gate(m: dict) -> tuple[dict, list]:
    """Мерки с порогами (формат paint_stage) и список причин отказа. Нет измерения — не «ок»."""
    mm, why = {}, []
    for k, (thr, op) in GATE.items():
        mm[k] = {'value': m.get(k), 'threshold': thr, 'op': op}
        if k not in m or not PS.judge(m[k], op, thr):
            why.append(f'{k} {m.get(k, "нет измерения")} (нужно {op} {thr})')
    return mm, why


# ── кадр ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def frame(path: str, prgb: np.ndarray, pmask: np.ndarray, after: np.ndarray, dst_glb: str, size: int = 480, view_glb: str = None) -> None:
    """«фото | кадр с камеры фото по новой текстуре | −40° | +40°» отдельным листом; боковые — рендер без света записанного GLB (файл читается, развёртка на месте)."""
    import recolor_lp as LP
    px = prgb.shape[0]
    panels = [np.where(pmask[..., None], prgb, 255).astype(np.uint8), after]
    panels = [np.asarray(Image.fromarray(p).resize((size * 2, size * 2), Image.LANCZOS)) for p in panels]
    for yaw in (-40.0, 40.0):
        im = np.asarray(LP.render_unlit(view_glb or dst_glb, yaw, 10.0, size * 2))
        panels.append(np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8))
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)


# ── этап ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False) -> dict:
    """Этап 6 для одного товара. Любая ошибка (форма не читается, нет файлов камеры, не та форма) — НЕ роняет пакет: пишет check.json passed=false с причиной (fail-closed, T-168)."""
    t0 = time.time()
    try:
        return _run(glb, photo, pose_run, run_dir, sku, cos_min, body_only)
    except Exception as e:  # noqa: BLE001 — причина уходит в check.json и в ответ, пакет идёт дальше
        d = PS.stage_dir(run_dir, sku, '06-visible')
        why = f'{type(e).__name__}: {e}'[:400]
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': 0.0, 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason=f'этап 6 не выполнен: {why}', seconds=round(time.time() - t0, 1), needs_qwen=False, stage_error=why, pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'error', 'why': [why], 'dir': d}


def camera_gate(pose_run: str) -> tuple:
    """Гейт предыдущего этапа: `<pose_run>/04-camera/check.json`. (True|False|None, причина словами). None — файла нет (прогон камеры старше гейта): этап идёт, но в check.json пишется camera_gate=absent."""
    p = os.path.join(pose_run, '04-camera', 'check.json')
    if not os.path.exists(p):
        return None, 'у камеры нет check.json'
    try:
        ch = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return False, f'check.json камеры не читается ({e})'
    if ch.get('passed') is True:
        return True, ''
    mt = ch.get('metric') or {}
    bad = [f"{k} {v.get('value')} (нужно {v.get('op')} {v.get('threshold')})" for k, v in (ch.get('metrics') or {}).items() if isinstance(v, dict) and v.get('ok') is False]
    if mt and mt.get('ok') is False:
        bad.insert(0, f"{mt.get('name')} {mt.get('value')} (нужно {mt.get('op')} {mt.get('threshold')})")
    return False, 'камера этапа 4 не прошла свой гейт: ' + ('; '.join(bad) or str(ch.get('reason') or 'passed=false'))


def body_cut(pose_run: str):
    """«Корпус годен» (р.2): камера не прошла гейт ТОЛЬКО из-за нижней полосы (ножки формы не совпадают с фото), верх лёг (iou_top ≥ порога). Возвращает {'row': первая строка нижней полосы в пикселях кадра камеры, 'frame_px'} или None."""
    p = os.path.join(pose_run, '04-camera', 'check.json')
    try:
        ch = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    ex = ch.get('extra') or {}
    rows = ex.get('strip_rows')
    if not (ex.get('bottom_shape_mismatch') and rows and len(rows) == 2):
        return None
    if float(ex.get('iou_top') or 0.0) < float(ex.get('bottom_top_iou_min') or 0.85):
        return None
    bad = [k for k, v in (ch.get('metrics') or {}).items() if isinstance(v, dict) and v.get('ok') is False]
    if any(not k.endswith('_bottom') for k in bad):                  # провал не только внизу — корпусу тоже не верим
        return None
    try:
        sl = json.load(open(os.path.join(pose_run, 'stage_loss.json'), encoding='utf-8'))
        fpx = int(sl.get('frame_px') or 0)
    except (OSError, ValueError):
        fpx = 0
    return {'row': int(rows[0]), 'frame_px': fpx, 'iou_top': float(ex.get('iou_top') or 0.0)}


def _run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False) -> dict:
    t0 = time.time()
    d = PS.stage_dir(run_dir, sku, '06-visible')
    cg, cg_why = camera_gate(pose_run)
    bc = body_cut(pose_run) if (cg is False and body_only) else None
    if cg is False and bc is None:                                   # вход не прошёл прежний гейт — этап его не берёт
        PS.write_check(d, '06-visible', sku, passed=False, reason=cg_why + ' — этап 6 вход не берёт, перенос не делался', seconds=round(time.time() - t0, 1),
                       needs_qwen=False, camera_failed=True, camera_gate='failed', pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'camera_gate', 'why': [cg_why]}
    geoms = load_shape(glb)
    st = load_stage(pose_run)
    P = np.asarray(Image.open(photo).convert('RGBA'))
    prgb, pmask = photo_to_frame(P, st['P'], st['px'])
    cut_row = None
    if bc is not None:                                               # переносим только выше нижней полосы; ножки — этапу 8
        cut_row = int(round(bc['row'] * st['px'] / bc['frame_px'])) if bc['frame_px'] else int(bc['row'])
        cut_row = max(1, min(st['px'], cut_row - 4))                 # запас 4 px над полосой
        st['ids'] = st['ids'].copy(); st['ids'][cut_row:] = -1
        st['cos'] = st['cos'].copy(); st['cos'][cut_row:] = 0.0
        st['mask'] = st['mask'].copy(); st['mask'][cut_row:] = False
        pmask = pmask.copy(); pmask[cut_row:] = False
        prgb = prgb.copy(); prgb[cut_row:] = 0
    iou_here = float((pmask & st['mask']).sum() / max((pmask | st['mask']).sum(), 1))
    if st.get('iou_frame') is not None and cut_row is None and abs(iou_here - st['iou_frame']) > 0.02:
        raise ValueError(f'фото не то или матрица не та: IoU силуэта здесь {iou_here:.3f}, в прогоне камеры {st["iou_frame"]:.3f}')
    st['iou_frame'] = iou_here
    if iou_here < GATE['silhouette_iou'][0]:                         # камере не верим: перенос не делаем (fail-closed)
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': round(iou_here, 4), 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason=f'камера фото не легла по силуэту (IoU {iou_here:.3f}) — перенос не делался', seconds=round(time.time() - t0, 1), needs_qwen=False, camera_failed=True,
                       camera=st['camera'], pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'camera', 'iou': iou_here}
    tr = transfer(geoms, st, prgb, pmask, cos_min)
    dst = os.path.join(d, 'visible.glb')
    write_glb(geoms, tr['tex'], dst)
    for i, k in enumerate(tr['known']):
        Image.fromarray((k * 255).astype(np.uint8)).save(os.path.join(d, 'known.png' if i == 0 else f'known{i}.png'))
    after = frame_from_tex(st, geoms, tr['tex'])
    m = metrics(geoms, st, prgb, pmask, tr, after, cos_min)
    view = os.path.join(d, '_view.glb')                                 # для показа: непросмотренное — штриховка; в visible.glb заготовка не тронута (этап 7 заливает её)
    write_glb(geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])], view)
    after_vis = frame_from_tex(st, geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])])
    frame(os.path.join(d, 'frame.png'), prgb, pmask, after_vis, dst, view_glb=view)
    os.remove(view)
    mm, why = gate(m)
    main = mm.pop('silhouette_iou')
    ok = not why
    PS.write_check(d, '06-visible', sku, passed=ok, metric={'name': 'silhouette_iou', **{k: main[k] for k in ('value', 'threshold', 'op')}}, metrics=mm,
                   reason='' if ok else '; '.join(why), seconds=round(time.time() - t0, 1), outputs=['visible.glb', 'known.png', 'frame.png'], frame='frame.png',
                   needs_qwen=(not ok), cos_min=cos_min, camera=st['camera'], pose_run=pose_run, stats=tr['stats'], depth_band_share=tr['depth_band_share'], body_only=(cut_row is not None), cut_row=cut_row, legs_left_to_stage8=(cut_row is not None), extra_metrics={k: v for k, v in m.items() if k not in GATE})
    return {'sku': sku, 'passed': ok, 'metrics': m, 'why': why, 'dir': d}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb')
    ap.add_argument('photo', help='RGBA-вырезка товара (то же фото, по которому посчитана камера)')
    ap.add_argument('pose_run', help='папка прогона pose_fit.fit_pose (stage_loss.json, stages/render_view0/)')
    ap.add_argument('run_dir')
    ap.add_argument('--body-only', action='store_true', help='камера красная только внизу (bottom_shape_mismatch): перенос выше нижней полосы, ножки — этапу 8')
    ap.add_argument('sku')
    a = ap.parse_args()
    r = run(a.glb, a.photo, a.pose_run, a.run_dir, a.sku, body_only=a.body_only)
    print(json.dumps(r, ensure_ascii=False, default=str)[:2000])
    return 0 if r['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
