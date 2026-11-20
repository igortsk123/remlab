#!/usr/bin/env python3
"""ЭТАП 6 «ФОТО НА ВИДИМОЕ» (T-20261120-168; план paint-photo-fill-01, § «Этапы», «Проверка на каждом этапе»). Бесплатно, на процессоре (numpy + scipy + trimesh + cv2 + PIL).

Что делает: берёт форму (GLB с развёрткой; текстуры нет — серая заготовка) и вырезку фото товара, ставит камеру фото (`color_steps.best_pose` по силуэту + доводка `recolor_lp.refine_align`),
и КАЖДОМУ тексель-у, который эта камера видит (первая грань вдоль луча, угол к камере лучше `COS_MIN`, внутри силуэта фото с отступом от края), присваивает цвет фото в точке его проекции.
Прямой перенос, без нейросети: цвет и узор видимого бока — настоящие, не нарисованные. Невидимое не трогается (остаётся заготовкой) — его закрывает этап 7 (`tex_fill.py`, р.3).
Выход этапа — `<run>/<sku>/06-visible/`: `visible.glb`, `known.png` (маска «тексель взят с фото»), `check.json` (через `paint_stage.write_check`), `frame.png` (фото | рендер с камеры фото | ±40°).

Qwen-правка — ТОЛЬКО если прямой перенос не лёг: гейт «тот же товар» не прошёл → `check.json`: passed=false, `extra.needs_qwen=true`, причина по меркам (код этого запасного пути — отдельным шагом, под платный пакет).
Гейт (все пороги — `GATE` ниже; ПРОВИЗОРНЫЕ до замера на 12 трудных, вносить в план только после замера):
  silhouette_iou   — совпадение силуэта фото и рендера формы (план: ≥ 0,85, иначе камере не верим → не едет дальше, нынешний путь);
  inner_edge_agree — доля внутренних рёбер формы (разрывы нормали/глубины), рядом с которыми на фото тоже край (камера и форма сходятся не только по контуру);
  edge_corr / lab_dE — перенос не потерян при записи: края и медиана Lab «фото ↔ рендер с камеры фото» по частям (часть = геометрия GLB, пока нет масок р.1);
  known_share      — доля занятых текселей, взятых с фото (честный охват; ниже порога — нечего переносить, камера не видит предмет).
ID товаров в код не попадают.
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

COS_MIN = 0.34          # cos угла к камере: 70° и больше — вскользь, не берём (план: «угол < ~70°»)
COS_FULL = 0.55         # полный вес с этого косинуса; между COS_MIN и COS_FULL — плавная передача заготовке
EDGE_PX = 4.0           # отступ от силуэта фото, пикселей рабочего кадра: вес растёт от 0 до 1 (там фон и ореол)
GUTTER = 6              # желоб вокруг островков, пикселей текстуры (билинейная выборка у шва не берёт серый фон)
WORK = 480              # рабочий кадр камеры фото (как `color_steps.FINAL_PX`)
GREY = 128
GATE = {                # (порог, op) — провизорно, см. шапку
    'silhouette_iou': (0.85, '>='),
    'known_share': (0.15, '>='),
    'edge_corr': (0.90, '>='),
    'lab_dE': (3.0, '<='),
    'inner_edge_agree': (0.50, '>='),
}
INNER_MIN_PX = 150      # у формы меньше внутренних рёбер — мерка «неприменимо» (гладкий предмет), не провал


# ── форма и камера ─────────────────────────────────────────────────────────────────────────────────────────────────

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
        tex = np.asarray(im.convert('RGB'), np.uint8) if im is not None else np.full((2048, 2048, 3), GREY, np.uint8)
        if tex.shape[0] != tex.shape[1]:
            tex = np.asarray(Image.fromarray(tex).resize((max(tex.shape[:2]),) * 2, Image.BILINEAR))
        out.append({'name': name, 'V': np.asarray(g.vertices, np.float64), 'F': np.asarray(g.faces, np.int64), 'UV': np.asarray(uv, np.float64), 'tex': tex, 'has_tex': im is not None})
    if not out:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    return out


class Camera:
    """Ортографическая камера `color_o2.texel_map` / `mesh_render.render` (поворот yaw → pitch, рамка по габариту ×1,08 на квадрате W×W) — та же арифметика, тот же кадр, что у подгонки по силуэту."""

    def __init__(self, geoms: list, yaw_deg: float, pitch_deg: float, size: int):
        import math
        self.W = size
        cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
        cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float64)
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float64)
        self.rot = ry.T @ rx.T
        allp = np.vstack([g['V'] for g in geoms]) @ self.rot
        self.span = max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1])) * 1.08 or 1.0
        self.ox, self.oy = allp[:, 0].mean(), allp[:, 1].mean()
        self.to_cam = self.rot[:, 2]                        # направление «на камеру» в мире: глубина p_z больше = ближе

    def project(self, P: np.ndarray):
        p = np.asarray(P, np.float64) @ self.rot
        sx = (p[:, 0] - self.ox) / self.span * self.W + self.W / 2
        sv = self.W / 2 - (p[:, 1] - self.oy) / self.span * self.W
        return sx, sv, p[:, 2]

    @property
    def px_size(self) -> float:
        return self.span / self.W


def shape_buffers(geoms: list, cam: Camera):
    """Буферы вида: id грани (глобальный, -1 пусто), глубина (больше = ближе), нормали граней в кадре камеры (для рёбер формы)."""
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    V = np.vstack([g['V'] for g in geoms])
    F = np.vstack([g['F'] + offs[i] for i, g in enumerate(geoms)])
    sx, sv, d = cam.project(V)
    ids, zb = TC.raster(np.stack([sx, sv], 1), F, cam.W, d)
    ids = ids.reshape(cam.W, cam.W)
    zb = zb.reshape(cam.W, cam.W)
    n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n3 /= np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    nc = n3 @ cam.rot
    nc *= np.where(nc[:, 2:3] < 0, -1.0, 1.0)                # знак нормали не важен (как `abs(cos)` в tex_fill)
    return ids, zb, nc


def fit_photo(glb_geoms: list, glb_path: str, photo_rgba: np.ndarray, size: int = WORK, pose: tuple | None = None):
    """Поза камеры фото и фото в кадр рендера. pose=(yaw, pitch) — готовая камера (T-112, или в тесте); None — подбор по силуэту.
    Возвращает (cam, prgb, pmask, info) — prgb/pmask в кадре W×W."""
    import color_o2 as CO
    import color_steps as CS
    import recolor_lp as LP
    if pose is None:
        p = CS.best_pose(glb_path, photo_rgba[..., 3] > 128)
        yaw, pitch, src = p['yaw'], p['pitch'], {'pose_iou': p['iou']}
    else:
        yaw, pitch = pose
        src = {'pose': 'задана'}
    cam = Camera(glb_geoms, yaw, pitch, size)
    ids, _zb, _nc = shape_buffers(glb_geoms, cam)
    ralpha = ids >= 0
    prgb0, pmask0 = CO.align_photo(photo_rgba, ralpha)
    prgb, pmask, al = LP.refine_align(prgb0, pmask0, ralpha)
    return cam, prgb, pmask, {'yaw': yaw, 'pitch': pitch, **src, 'align': al}


# ── перенос ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _sample(img: np.ndarray, sx: np.ndarray, sv: np.ndarray) -> np.ndarray:
    from scipy.ndimage import map_coordinates
    return np.stack([map_coordinates(img[..., c].astype(np.float32), [sv - 0.5, sx - 0.5], order=1, mode='nearest') for c in range(img.shape[-1])], 1)


def transfer(geoms: list, cam: Camera, ids_zb, prgb: np.ndarray, pmask: np.ndarray, cos_min: float = COS_MIN) -> dict:
    """Новые текстуры + маски «известно» (T×T bool) и вес (T×T float) по геометриям. Невидимое остаётся прежним."""
    import tex_fill as TF
    from scipy.ndimage import distance_transform_edt
    zb = ids_zb
    W = cam.W
    dist_edge = distance_transform_edt(pmask)                # пикселей от края силуэта фото внутрь
    texs, knowns, weights, stats = [], [], [], []
    for g in geoms:
        T = TF._grid(g)
        tx = TF.Tex(g, g['V'], T, None)
        sx, sv, d = cam.project(tx.Q)
        cs = np.abs(tx.N @ cam.to_cam)
        ix = np.clip(np.floor(sx).astype(np.int64), 0, W - 1)
        iy = np.clip(np.floor(sv).astype(np.int64), 0, W - 1)
        inside = (sx >= 0) & (sx < W) & (sv >= 0) & (sv < W)
        eps = TC.DEPTH_EPS * cam.span + cam.px_size * 2.0 * np.sqrt(np.maximum(1.0 - cs * cs, 0.0)) / np.maximum(cs, TC.COS_SEEN)
        front = zb[iy, ix] <= d + eps
        w_ang = np.clip((cs - cos_min) / max(COS_FULL - cos_min, 1e-6), 0.0, 1.0)
        w_edge = np.clip(dist_edge[iy, ix] / EDGE_PX, 0.0, 1.0)
        w = np.where(inside & front & pmask[iy, ix], w_ang * w_edge, 0.0)
        col = _sample(prgb, sx, sv)
        tex = np.asarray(g['tex'], np.float32)
        if tex.shape[0] != T:
            tex = np.asarray(Image.fromarray(g['tex']).resize((T, T), Image.BILINEAR), np.float32)
        flat = tex.reshape(-1, 3).copy()
        use = w > 0
        flat[tx.ti[use]] = w[use, None] * col[use] + (1.0 - w[use, None]) * flat[tx.ti[use]]
        occ = np.zeros(T * T, bool)
        occ[tx.ti] = True
        wmap = np.zeros(T * T, np.float32)
        wmap[tx.ti] = w
        known = wmap.reshape(T, T) >= 0.5
        new = flat.reshape(T, T, 3)
        occ2 = occ.reshape(T, T)
        gd = distance_transform_edt(~occ2, return_distances=True, return_indices=True)       # желоб: ближайший занятый тексель на GUTTER пикселей наружу
        dd, (jy, jx) = gd
        ring = (~occ2) & (dd <= GUTTER)
        new[ring] = new[jy[ring], jx[ring]]
        texs.append(np.clip(new + 0.5, 0, 255).astype(np.uint8))
        knowns.append(known)
        weights.append(wmap.reshape(T, T))
        stats.append({'name': g['name'], 'T': T, 'occupied': int(occ.sum()), 'known': int(known.sum()), 'grazing': int(((w > 0) & (w < 1) & (cs < COS_FULL)).sum())})
    return {'tex': texs, 'known': knowns, 'weight': weights, 'stats': stats}


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
    return LP.lab_f(LP.s2l(rgb8))


def _sobel(L: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, sobel
    b = gaussian_filter(L.astype(np.float32), 1.0)
    return np.hypot(sobel(b, axis=1), sobel(b, axis=0))


def render_photo_cam(dst_glb: str, cam_yaw: float, cam_pitch: float, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Рендер без света с камеры фото по записанному GLB (честная проверка: файл читается, текстура и развёртка на месте). (rgb, альфа-маска)."""
    import recolor_lp as LP
    im = np.asarray(LP.render_unlit(dst_glb, cam_yaw, cam_pitch, size))
    return im[..., :3], im[..., 3] > 8


def shape_inner_edges(ids: np.ndarray, zb: np.ndarray, nc: np.ndarray, cam: Camera, margin: int = 4) -> np.ndarray:
    """Внутренние рёбра формы в кадре: разрыв нормали граней (угол > ~35°) или скачок глубины (> 3 пикселей) между соседними пикселями, не у силуэта."""
    from scipy.ndimage import binary_erosion
    m = ids >= 0
    N = np.zeros(ids.shape + (3,), np.float32)
    N[m] = nc[ids[m]]
    inner = binary_erosion(m, iterations=margin)
    edge = np.zeros_like(m)
    dz = np.where(m, zb, 0.0)
    for ax in (0, 1):
        sh = lambda a: np.roll(a, -1, axis=ax)  # noqa: E731
        dn = (N * sh(N)).sum(-1)
        edge |= (dn < 0.82) & m & sh(m)
        edge |= (np.abs(dz - sh(dz)) > 3.0 * cam.px_size) & m & sh(m)
    return edge & inner


def metrics(geoms, cam, ids, zb, nc, prgb, pmask, tr, dst_glb: str, info: dict) -> dict:
    from scipy.ndimage import binary_dilation, binary_erosion, maximum_filter
    ralpha = ids >= 0
    iou = float((pmask & ralpha).sum() / max((pmask | ralpha).sum(), 1))
    occ = sum(s['occupied'] for s in tr['stats'])
    kn = sum(s['known'] for s in tr['stats'])
    out = {'silhouette_iou': round(iou, 4), 'known_share': round(kn / max(occ, 1), 4)}
    rgb, ra2 = render_photo_cam(dst_glb, info['yaw'], info['pitch'], cam.W)
    both = binary_erosion(ralpha, iterations=3) & binary_erosion(pmask, iterations=3) & binary_erosion(ra2, iterations=3)
    out['both_px'] = int(both.sum())
    if both.sum() > 200:
        Lp, Lr = _lab(prgb)[..., 0], _lab(rgb)[..., 0]
        ep, er = _sobel(Lp), _sobel(Lr)
        out['edge_corr'] = round(float(np.corrcoef(ep[both], er[both])[0, 1]), 4)
        import recolor_lp as LP
        out['lab_dE'] = round(float(np.median(LP.de2000(_lab(prgb)[both], _lab(rgb)[both]))), 3)
        # по частям (часть = геометрия GLB; маски частей р.1 подставят позже)
        gid = np.zeros(ids.shape, np.int16)
        offs = np.cumsum([0] + [len(g['F']) for g in geoms])
        gid[ralpha] = np.searchsorted(offs, ids[ralpha], side='right') - 1
        per = {}
        for gi, g in enumerate(geoms):
            mk = both & (gid == gi)
            if mk.sum() > 100:
                per[g['name']] = round(float(np.median(LP.de2000(_lab(prgb)[mk], _lab(rgb)[mk]))), 3)
        out['lab_dE_by_part'] = per
    edges = shape_inner_edges(ids, zb, nc, cam)
    out['inner_edges_px'] = int(edges.sum())
    if edges.sum() >= INNER_MIN_PX and pmask.sum() > 200:
        Ep = _sobel(_lab(prgb)[..., 0])
        thr = float(np.percentile(Ep[pmask], 80))
        pe = binary_dilation(Ep > thr, iterations=3)
        out['inner_edge_agree'] = round(float(pe[edges].mean()), 4)
    return out


def gate(m: dict) -> tuple[dict, list]:
    """Мерки с порогами (формат paint_stage) и список причин отказа."""
    mm, why = {}, []
    for k, (thr, op) in GATE.items():
        if k not in m:
            if k == 'inner_edge_agree':
                continue                                    # гладкий предмет — мерка неприменима
            mm[k] = {'value': None, 'threshold': thr, 'op': op}
            why.append(f'{k}: нет измерения')
            continue
        mm[k] = {'value': m[k], 'threshold': thr, 'op': op}
        if not PS.judge(m[k], op, thr):
            why.append(f'{k} {m[k]} (нужно {op} {thr})')
    return mm, why


# ── кадр ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def frame(path: str, prgb: np.ndarray, pmask: np.ndarray, dst_glb: str, info: dict, size: int) -> None:
    """«фото | рендер с камеры фото | −40° | +40°» отдельным листом, полный размер панелей."""
    import recolor_lp as LP
    panels = [np.where(pmask[..., None], prgb, 255).astype(np.uint8)]
    for dy in (0.0, -40.0, 40.0):
        im = np.asarray(LP.render_unlit(dst_glb, info['yaw'] + dy, info['pitch'], size))
        rgb = np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8)
        panels.append(rgb)
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)


# ── этап ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(glb: str, photo: str, run_dir: str, sku: str, pose: tuple | None = None, size: int = WORK, cos_min: float = COS_MIN, force_camera: bool = False) -> dict:
    t0 = time.time()
    d = PS.stage_dir(run_dir, sku, '06-visible')
    geoms = load_shape(glb)
    P = np.asarray(Image.open(photo).convert('RGBA'))
    cam, prgb, pmask, info = fit_photo(geoms, glb, P, size, pose)
    ids, zb, nc = shape_buffers(geoms, cam)
    if info['align']['iou'] < GATE['silhouette_iou'][0] and not force_camera:           # force_camera — ТОЛЬКО диагностика (посмотреть, что получится); гейт в check.json всё равно не пройден
        # камере не верим: перенос не делаем (fail-closed), кадр — для диагноза
        res = {'silhouette_iou': info['align']['iou']}
        mm, why = gate(res)
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': info['align']['iou'], 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason='камера фото не легла по силуэту — перенос не делался; ' + '; '.join(why), seconds=round(time.time() - t0, 1), needs_qwen=False, camera_failed=True, camera=info)
        return {'sku': sku, 'passed': False, 'reason': 'camera', 'info': info}
    tr = transfer(geoms, cam, zb, prgb, pmask, cos_min)
    dst = os.path.join(d, 'visible.glb')
    write_glb(geoms, tr['tex'], dst)
    for i, k in enumerate(tr['known']):
        Image.fromarray((k * 255).astype(np.uint8)).save(os.path.join(d, 'known.png' if i == 0 else f'known{i}.png'))
    m = metrics(geoms, cam, ids, zb, nc, prgb, pmask, tr, dst, info)
    frame(os.path.join(d, 'frame.png'), prgb, pmask, dst, info, size)
    mm, why = gate(m)
    main = mm.pop('silhouette_iou')
    ok = not why
    PS.write_check(d, '06-visible', sku, passed=ok, metric={'name': 'silhouette_iou', **{k: main[k] for k in ('value', 'threshold', 'op')}}, metrics=mm,
                   reason='' if ok else '; '.join(why), seconds=round(time.time() - t0, 1), outputs=['visible.glb', 'known.png', 'frame.png'],
                   frame='frame.png', needs_qwen=(not ok), cos_min=cos_min, camera=info, stats=tr['stats'], extra_metrics={k: v for k, v in m.items() if k not in GATE})
    return {'sku': sku, 'passed': ok, 'metrics': m, 'why': why, 'dir': d}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb')
    ap.add_argument('photo', help='RGBA-вырезка товара')
    ap.add_argument('run_dir')
    ap.add_argument('sku')
    ap.add_argument('--yaw', type=float, default=None)
    ap.add_argument('--pitch', type=float, default=None)
    ap.add_argument('--size', type=int, default=WORK)
    ap.add_argument('--force-camera', action='store_true', help='диагностика: делать перенос, даже если силуэт не лёг (check.json всё равно красный)')
    a = ap.parse_args()
    pose = (a.yaw, a.pitch) if a.yaw is not None and a.pitch is not None else None
    r = run(a.glb, a.photo, a.run_dir, a.sku, pose, a.size, force_camera=a.force_camera)
    print(json.dumps(r, ensure_ascii=False, default=str)[:2000])
    return 0 if r['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
