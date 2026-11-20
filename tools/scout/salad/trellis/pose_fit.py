#!/usr/bin/env python3
"""T-20261119-112/1: КАМЕРА ФОТО ПО СИЛУЭТУ → папка `stages/` для проекции фото с любого ракурса (процессор, без видеокарты).

Зачем. `photo_front.py` кладёт фото на форму через кадр «вида 0» — фронтальную ортографию. Фото в 3/4 (видна боковина, перспектива) на такой кадр не ложится (T-88/2: комод, кромки 0,21→0,35 < 0,50).
Здесь камера фото ПОДБИРАЕТСЯ: перспективная камера на сфере вокруг формы (азимут, подъём, расстояние → сила перспективы, масштаб, сдвиг), цель — IoU силуэта (альфа фото) и силуэта формы.
Всё общее, без особых случаев: фронтальная ортография — частный случай (az=0, el=0, d→∞).

  pose_fit.py --glb <GLB с UV и базой> --photo <фото .rgba.png> --out-run <папка> [--yaw N] [--px 1536] [--n-fit 256] [--topk 4]
  → <out-run>/stages/{manifest.json, render_view0/{mask,aoi_cos16,normal_cam}.png, render_view0/{uv,depth}.npz}, <out-run>/stage_loss.json (регистрация фото → кадр), <out-run>/pose.json, <out-run>/pose_overlay.png

Как. (1) Сетка: азимут 0…345° шаг 15, подъём −10…40, сила перспективы d ∈ {2,3,5,10} (размеры предмета), масштаб и сдвиг — аналитически по габариту силуэта (сходство по bbox); IoU по облаку вершин.
(2) Уточнение Нелдера–Мида (az, el, ln d, ln f, cx, cy) от лучших разных стартов; цель 1−IoU.
(3) Силуэт симметричен «спереди/сзади» и у ящиков слабо различает азимут: из кандидатов с IoU не ниже лучшего−`TIE_IOU` выбирается тот, у кого после рендера базы совпадение кромок с фото выше
(`photo_front.edge_agreement`; фото в кадр, перспективный кадр 768 px).
(4) Кадр камеры (`render_persp`): грань на пиксель (глубина, дальние первыми), перспективно-верные барицентры → UV, нормаль, cos угла к лучу, глубина; регистрация фото → кадр — точная (поле фото вырезано
квадратом вокруг силуэта), дальше `photo_front` уточняет ECC как раньше.
Обозначения: форма в кубе `worker_trellis.to_cube(V, yaw)` (Y вверх, спереди +Z); камера смотрит в начало куба с расстояния d (куб ≈ 1), азимут 0 — спереди, + — камера вправо (от предмета).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))

TIE_IOU = 0.03                     # кандидаты с IoU не ниже лучшего − этого выбираются по совпадению кромок
GRID_AZ = tuple(range(0, 360, 15))
GRID_EL = (-10, 0, 10, 20, 30, 40)
GRID_D = (2.0, 3.0, 5.0, 10.0)
D_MIN, D_MAX = 1.5, 60.0           # расстояние камеры (куб ≈ 1): внутрь предмета и в бесконечность не пускаем
MARGIN = 0.08                      # поле вокруг силуэта в кадре, доля стороны
SHIFT = 4                          # субпиксель fillConvexPoly
W_IOU = 2.0                        # вес силуэта против кромок в уточнении по кромкам
R_AZ, R_EL, R_LND = 15.0, 10.0, 0.5   # пределы ухода камеры от найденной по силуэту


# ——— камера ———
def cam_basis(az: float, el: float, d: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    a, e = np.radians(az), np.radians(el)
    C = d * np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])
    fwd = -C / d
    right = np.array([np.cos(a), 0.0, -np.sin(a)])
    up = np.cross(right, fwd)
    return C, right, up, fwd


def project(P: np.ndarray, cam: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Точки куба → (x, y, Z): x, y в долях стороны кадра (0…1, y вниз), Z — глубина вдоль оси камеры."""
    C, right, up, fwd = cam_basis(cam['az'], cam['el'], cam['d'])
    rel = P - C
    Z = rel @ fwd
    Zs = np.maximum(Z, 1e-6)
    return cam['cx'] + cam['f'] * (rel @ right) / Zs, cam['cy'] - cam['f'] * (rel @ up) / Zs, Z


# ——— фото ———
def photo_canvas(alpha: np.ndarray, margin: float = MARGIN) -> dict:
    """Квадрат вокруг силуэта фото (в пикселях фото): x0, y0, side; кадр n×n ↔ фото: x_фото = x0 + x·side/n."""
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        raise ValueError('у фото нет альфы')
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    side = max(bx1 - bx0, by1 - by0) * (1 + 2 * margin)
    return {'x0': float((bx0 + bx1) / 2 - side / 2), 'y0': float((by0 + by1) / 2 - side / 2), 'side': float(side)}


def canvas_P(cv: dict, n: int) -> np.ndarray:
    """Обратная карта кадр → фото (как `stage_loss.register_photo`: `photo(P·x_кадра)`)."""
    s = cv['side'] / n
    return np.array([[s, 0, cv['x0']], [0, s, cv['y0']], [0, 0, 1.0]], np.float64)


def canvas_mask(alpha: np.ndarray, cv: dict, n: int) -> np.ndarray:
    import stage_loss as SL
    return SL.warp_inv(alpha.astype(np.float32), canvas_P(cv, n), (n, n)) > 0.5


# ——— силуэт по облаку вершин (быстро) ———
def splat_mask(P: np.ndarray, cam: dict, n: int) -> np.ndarray:
    import cv2
    x, y, Z = project(P, cam)
    ok = Z > 1e-3
    xi, yi = np.floor(x[ok] * n).astype(np.int64), np.floor(y[ok] * n).astype(np.int64)
    ins = (xi >= 0) & (xi < n) & (yi >= 0) & (yi < n)
    m = np.bincount(yi[ins] * n + xi[ins], minlength=n * n).reshape(n, n) > 0
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = float((a | b).sum())
    return float((a & b).sum()) / u if u else 0.0


def _bbox_fit(P: np.ndarray, az: float, el: float, d: float, tb: tuple) -> dict:
    """Масштаб и сдвиг по габариту (сходство): проекция с f=1, потом bbox силуэта формы → bbox силуэта фото (в долях кадра)."""
    cam = {'az': az, 'el': el, 'd': d, 'f': 1.0, 'cx': 0.0, 'cy': 0.0}
    x, y, Z = project(P, cam)
    ok = Z > 1e-3
    x0, x1 = np.percentile(x[ok], [0.3, 99.7])
    y0, y1 = np.percentile(y[ok], [0.3, 99.7])
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    s = 0.5 * ((tb[2] - tb[0]) / w + (tb[3] - tb[1]) / h)
    cam['f'] = float(s)
    cam['cx'] = float((tb[0] + tb[2]) / 2 - s * (x0 + x1) / 2)
    cam['cy'] = float((tb[1] + tb[3]) / 2 - s * (y0 + y1) / 2)
    return cam


def _vec(cam: dict) -> np.ndarray:
    return np.array([cam['az'], cam['el'], np.log(cam['d']), np.log(cam['f']), cam['cx'], cam['cy']], np.float64)


def _cam(v: np.ndarray) -> dict:
    return {'az': float(v[0]), 'el': float(v[1]), 'd': float(np.exp(v[2])), 'f': float(np.exp(v[3])), 'cx': float(v[4]), 'cy': float(v[5])}


def fit_camera(P: np.ndarray, Mp: np.ndarray, n: int, topk: int = 4, log=print) -> list:
    """Сетка + Нелдер–Мид. Возвращает кандидатов [{cam, iou, iou_grid}] по убыванию IoU (разные позы)."""
    from scipy.optimize import minimize
    ys, xs = np.nonzero(Mp)
    tb = (xs.min() / n, ys.min() / n, (xs.max() + 1) / n, (ys.max() + 1) / n)
    Pc = P[:: max(1, len(P) // 150000)]                                # ≤ 150 тыс. точек: сетка быстрее, силуэт тот же
    grid = []
    for az in GRID_AZ:
        for el in GRID_EL:
            for d in GRID_D:
                cam = _bbox_fit(Pc, az, el, d, tb)
                grid.append((iou(splat_mask(Pc, cam, n), Mp), cam))
    grid.sort(key=lambda t: -t[0])
    starts = []
    for sc, cam in grid:                                               # лучшие старты, разные по позе
        if all(abs(((cam['az'] - o['az'] + 180) % 360) - 180) > 20 or abs(cam['el'] - o['el']) > 15 for _, o in starts):
            starts.append((sc, cam))
        if len(starts) >= topk:
            break
    out = []
    for sc, cam in starts:
        def f(v):
            c = _cam(v)
            if not (D_MIN <= c['d'] <= D_MAX) or abs(c['el']) > 85:
                return 1.0
            return 1.0 - iou(splat_mask(Pc, c, n), Mp)
        v0 = _vec(cam)
        sim = np.vstack([v0] + [v0 + np.eye(6)[i] * st for i, st in enumerate((6.0, 4.0, 0.2, 0.08, 0.02, 0.02))])
        r = minimize(f, v0, method='Nelder-Mead', options={'initial_simplex': sim, 'maxiter': 500, 'xatol': 1e-3, 'fatol': 1e-5})
        c = _cam(r.x)
        out.append({'cam': c, 'iou': round(1.0 - float(r.fun), 4), 'iou_grid': round(sc, 4)})
        log(f"  старт az={cam['az']:.0f} el={cam['el']:.0f} d={cam['d']:.1f}: IoU {sc:.4f} → az={c['az']:.1f} el={c['el']:.1f} d={c['d']:.2f} IoU {1 - r.fun:.4f} ({r.nit} шагов)")
    out.sort(key=lambda t: -t['iou'])
    return out


# ——— кадр камеры ———
def render_persp(geo: dict, cam: dict, n: int) -> dict:
    """Перспективный кадр n×n: id грани, маска, UV (u, v_flipped), нормаль к камере, cos угла к лучу, глубина Z, длина пикселя (единицы куба). `geo` — в кубе (V, F, UV, N)."""
    import cv2
    V, F, N, UV = geo['V'], geo['F'], geo['N'], geo['UV']
    x, y, Z = project(V, cam)
    sx, sy = x * n, y * n
    tri = np.stack([sx[F], sy[F]], -1)
    zf = Z[F].mean(1)
    order = np.argsort(-zf, kind='stable')                              # дальние первыми, ближние поверх
    k = float(1 << SHIFT)
    pts = np.round(tri * k - 0.5 * k).astype(np.int32)
    ids = np.full((n, n), -1, np.int32)
    for f in order:
        cv2.fillConvexPoly(ids, pts[f], int(f), lineType=cv2.LINE_8, shift=SHIFT)
    mask = ids >= 0
    ys, xs = np.nonzero(mask)
    f = ids[ys, xs].astype(np.int64)
    a, b, c = F[f, 0], F[f, 1], F[f, 2]
    A_, B_, C_ = (np.stack([sx[i], sy[i]], 1) for i in (a, b, c))
    p = np.stack([xs + 0.5, ys + 0.5], 1)
    den = (B_[:, 0] - A_[:, 0]) * (C_[:, 1] - A_[:, 1]) - (B_[:, 1] - A_[:, 1]) * (C_[:, 0] - A_[:, 0])
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    wa = ((B_[:, 0] - p[:, 0]) * (C_[:, 1] - p[:, 1]) - (B_[:, 1] - p[:, 1]) * (C_[:, 0] - p[:, 0])) / den
    wb = ((C_[:, 0] - p[:, 0]) * (A_[:, 1] - p[:, 1]) - (C_[:, 1] - p[:, 1]) * (A_[:, 0] - p[:, 0])) / den
    wc = 1.0 - wa - wb
    wa, wb, wc = (np.clip(w, 0.0, 1.0) for w in (wa, wb, wc))
    qa, qb, qc = wa / np.maximum(Z[a], 1e-6), wb / np.maximum(Z[b], 1e-6), wc / np.maximum(Z[c], 1e-6)     # перспективно-верные веса: ∝ вес/глубина
    s = np.maximum(qa + qb + qc, 1e-12)
    la, lb, lc = qa / s, qb / s, qc / s
    zpix = 1.0 / s
    u = la * UV[a, 0] + lb * UV[b, 0] + lc * UV[c, 0]
    v = la * UV[a, 1] + lb * UV[b, 1] + lc * UV[c, 1]
    uv = np.zeros((n, n, 2), np.float32)
    uv[ys, xs, 0] = u
    uv[ys, xs, 1] = 1.0 - v
    nw = la[:, None] * N[a] + lb[:, None] * N[b] + lc[:, None] * N[c]
    nw /= np.maximum(np.linalg.norm(nw, axis=1, keepdims=True), 1e-12)
    Pw = la[:, None] * V[a] + lb[:, None] * V[b] + lc[:, None] * V[c]
    C0, right, up, fwd = cam_basis(cam['az'], cam['el'], cam['d'])
    vv = C0 - Pw
    vv /= np.maximum(np.linalg.norm(vv, axis=1, keepdims=True), 1e-12)
    cosv = np.abs((nw * vv).sum(1))                                    # |cos| — порядок обхода граней у сеток TRELLIS не всегда «наружу»
    flip = np.where((nw * vv).sum(1, keepdims=True) < 0, -1.0, 1.0)
    ncam = np.zeros((n, n, 3), np.float32)
    nf = nw * flip
    ncam[ys, xs] = np.stack([nf @ right, nf @ up, -(nf @ fwd)], 1)
    cos = np.zeros((n, n), np.float32)
    cos[ys, xs] = cosv
    depth = np.zeros((n, n), np.float32)
    depth[ys, xs] = zpix
    px_len = float(np.median(zpix) / (cam['f'] * n))                    # длина одного пикселя на предмете (единицы куба)
    return {'ids': ids, 'mask': mask, 'uv': uv, 'normal': ncam, 'cos': cos, 'depth': depth, 'px_len': px_len}


def to_cube_geo(geo: dict, yaw: float) -> dict:
    import worker_trellis as W
    P, _c, _s, R = W.to_cube(geo['V'], yaw)
    return {'V': P, 'F': geo['F'], 'UV': geo['UV'], 'N': geo['N'] @ R.T}


def edge_score(geo: dict, cam: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex: np.ndarray, n: int = 768) -> dict:
    """Совпадение кромок фото↔база в кадре этой камеры (без ECC): выбор между кандидатами с почти равным силуэтом."""
    import a1_tone as A
    import pattern_metric as PM
    import photo_front as PFR
    import stage_loss as SL
    r = render_persp(geo, cam, n)
    P = canvas_P(cv, n)
    S = r['mask']
    A_fr = SL.warp_inv(alpha.astype(np.float32), P, (n, n)) > 0.5
    ph = np.clip(SL.warp_inv(photo[..., :3], P, (n, n)), 0, 255).astype(np.uint8)
    cm, width = SL.common_mask(S, A_fr, r['cos'])
    img = A.render_view0(tex, {'uv': r['uv'], 'mask': S})
    L_ph = PM.rgb_to_lab(ph)[..., 0].astype(np.float32)
    L_b = PM.rgb_to_lab(img)[..., 0].astype(np.float32)
    ea = PFR.edge_agreement(L_ph, L_b, S & A_fr, width, PFR.EDGE_MIN_LEN) if width >= 16 else {'agree': -1.0}
    return {'agree': ea['agree'], 'iou_frame': round(iou(S, A_fr), 4), 'width_px': round(float(width), 1)}


def refine_by_edges(geo: dict, cam: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex: np.ndarray, n: int = 512, maxiter: int = 110, log=print) -> tuple[dict, dict]:
    """Силуэт слабо держит азимут/перспективу; внутренние кромки (стыки фасадов, швы, рисунок) держат сильно. Уточнение Нелдера–Мида камеры по цели `W_IOU·(1−IoU кадра) − совпадение кромок` (кадр n px, без ECC),
    старт — найденная по силуэту камера, диапазон ограничен вокруг неё (az ±`R_AZ`°, подъём ±`R_EL`°, ln d ±`R_LND`): возвращает (камера, оценка)."""
    from scipy.optimize import minimize
    v0 = _vec(cam)
    lo = v0 + np.array([-R_AZ, -R_EL, -R_LND, -0.3, -0.08, -0.08])
    hi = v0 + np.array([R_AZ, R_EL, R_LND, 0.3, 0.08, 0.08])
    cache = {}

    def sc(v):
        key = tuple(np.round(v, 5))
        if key not in cache:
            c = _cam(v)
            e = edge_score(geo, c, photo, alpha, cv, tex, n)
            cache[key] = (W_IOU * (1.0 - e['iou_frame']) - e['agree'], e)
        return cache[key][0]

    def f(v):
        if np.any(v < lo) or np.any(v > hi) or not (D_MIN <= np.exp(v[2]) <= D_MAX):
            return 5.0
        return sc(v)
    sim = np.vstack([v0] + [v0 + np.eye(6)[i] * st for i, st in enumerate((3.0, 2.0, 0.1, 0.04, 0.01, 0.01))])
    r = minimize(f, v0, method='Nelder-Mead', options={'initial_simplex': sim, 'maxiter': maxiter, 'xatol': 1e-3, 'fatol': 1e-4})
    best = min(cache.items(), key=lambda kv: kv[1][0])
    c = _cam(np.array(best[0]))
    log(f"  уточнение по кромкам: цель {cache[tuple(np.round(v0, 5))][0]:.4f} → {best[1][0]:.4f}; az={c['az']:.1f} el={c['el']:.1f} d={c['d']:.2f} кромки {best[1][1]['agree']} IoU кадра {best[1][1]['iou_frame']} ({len(cache)} кадров)")
    return c, best[1][1]


def write_stages(r: dict, out_run: str, cam: dict, cv: dict, photo_path: str, yaw: float, px: int, glb: str, extra: dict) -> dict:
    from PIL import Image
    import stage_loss as SL
    st = os.path.join(out_run, 'stages')
    rd = os.path.join(st, 'render_view0')
    os.makedirs(rd, exist_ok=True)
    Image.fromarray(r['mask'].astype(np.uint8) * 255).save(os.path.join(rd, 'mask.png'))
    Image.fromarray(((r['normal'] * 0.5 + 0.5).clip(0, 1) * 255 * r['mask'][..., None]).round().astype(np.uint8)).save(os.path.join(rd, 'normal_cam.png'))
    Image.fromarray((r['cos'] * 65535).round().astype(np.uint16)).save(os.path.join(rd, 'aoi_cos16.png'))
    np.savez_compressed(os.path.join(rd, 'uv.npz'), uv=r['uv'], mask=r['mask'])
    np.savez_compressed(os.path.join(rd, 'depth.npz'), depth=r['depth'], px_len=np.float64(r['px_len']))
    man = {'uv_size': 4096, 'render_px': px, 'yaw_deg': yaw, 'camera': {'kind': 'perspective', **cam}, 'canvas': cv, 'uv_flip_v': True, 'source': 'pose_fit.py (CPU)', 'glb': glb,
           'uv_note': 'uv.npz: uv[y,x]=(u, v_flipped); depth.npz: depth (Z вдоль оси камеры, единицы куба), px_len (куб на пиксель)'}
    json.dump(man, open(os.path.join(st, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    photo = SL.read_rgba(photo_path)
    P = canvas_P(cv, px)
    A_fr = SL.warp_inv((photo[..., 3] > 127).astype(np.float32), P, (px, px)) > 0.5
    reg = {'P': [round(float(x), 8) for x in P.ravel()], 'iou_init': round(iou(r['mask'], A_fr), 4), 'iou': round(iou(r['mask'], A_fr), 4), 'method': 'pose_fit (камера по силуэту)', 'cc': None}
    sl = {'photo': photo_path, 'stages_dir': st, 'frame_px': px, 'registration': reg, 'camera': cam, **extra}
    json.dump(sl, open(os.path.join(out_run, 'stage_loss.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return reg


def main() -> int:
    from PIL import Image
    import cv2
    import a1_tone as A
    import ab_tint as T
    import stage_loss as SL
    import stages_cpu as SC
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--out-run', required=True)
    ap.add_argument('--yaw', type=float, default=0.0)
    ap.add_argument('--px', type=int, default=1536)
    ap.add_argument('--n-fit', type=int, default=256)
    ap.add_argument('--topk', type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out_run, exist_ok=True)
    photo = SL.read_rgba(a.photo)
    alpha = photo[..., 3] > 127
    cv = photo_canvas(alpha)
    n = a.n_fit
    Mp = canvas_mask(alpha, cv, n)
    geo = to_cube_geo(SC.load_geom(a.glb), a.yaw)
    print(f'форма: {len(geo["V"])} вершин, {len(geo["F"])} граней; фото {photo.shape[1]}×{photo.shape[0]}, кадр {a.px}, подбор {n}')
    cands = fit_camera(geo['V'], Mp, n, a.topk)
    j, b = A.read_glb(a.glb)
    tex = T.read_texture(j, b)
    best_iou = cands[0]['iou']
    pool = [c for c in cands if c['iou'] >= best_iou - TIE_IOU]
    for c in pool:
        c['edge'] = edge_score(geo, c['cam'], photo, alpha, cv, tex)
        print(f"  кандидат az={c['cam']['az']:.1f} el={c['cam']['el']:.1f} d={c['cam']['d']:.2f} IoU {c['iou']} кромки до ECC {c['edge']['agree']}")
    for c in pool:                                                     # уточнение по внутренним кромкам: силуэт один, поз с разными кромками много
        c['cam_sil'] = dict(c['cam'])
        c['cam'], c['edge'] = refine_by_edges(geo, c['cam'], photo, alpha, cv, tex)
        c['iou'] = round(iou(splat_mask(geo['V'][:: max(1, len(geo['V']) // 150000)], c['cam'], n), Mp), 4)
        print(f"  после уточнения az={c['cam']['az']:.1f} el={c['cam']['el']:.1f} d={c['cam']['d']:.2f} IoU(силуэт) {c['iou']} кромки до ECC {c['edge']['agree']}")
    pick = max(pool, key=lambda c: c['edge']['agree'])
    cam = pick['cam']
    front = _bbox_fit(geo['V'][:: max(1, len(geo['V']) // 150000)], 0.0, 0.0, 1000.0, (lambda ys, xs: (xs.min() / n, ys.min() / n, (xs.max() + 1) / n, (ys.max() + 1) / n))(*np.nonzero(Mp)))
    iou_front = iou(splat_mask(geo['V'][:: max(1, len(geo['V']) // 150000)], front, n), Mp)
    print(f"выбрана: az={cam['az']:.1f} el={cam['el']:.1f} d={cam['d']:.2f} (IoU подбора {pick['iou']}; фронтальная ортография по габариту {iou_front:.4f})")
    r = render_persp(geo, cam, a.px)
    extra = {'pose': {'picked': pick, 'candidates': cands, 'iou_frontal_ortho_bbox': round(iou_front, 4), 'fov_deg_canvas': round(float(np.degrees(2 * np.arctan(0.5 / cam['f']))), 2)}}
    reg = write_stages(r, a.out_run, cam, cv, a.photo, a.yaw, a.px, a.glb, extra)
    json.dump({'camera': cam, 'canvas': cv, 'picked': pick, 'candidates': cands, 'iou_frontal_ortho_bbox': round(iou_front, 4), 'iou_frame': reg['iou'], 'px': a.px, 'yaw': a.yaw},
              open(os.path.join(a.out_run, 'pose.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    A_fr = SL.warp_inv(alpha.astype(np.float32), canvas_P(cv, a.px), (a.px, a.px)) > 0.5
    ov = np.zeros((a.px, a.px, 3), np.uint8)
    ov[..., 0] = (A_fr * 255).astype(np.uint8)
    ov[..., 1] = (r['mask'] * 255).astype(np.uint8)
    Image.fromarray(cv2.resize(ov, (768, 768), interpolation=cv2.INTER_AREA)).save(os.path.join(a.out_run, 'pose_overlay.png'))
    print(json.dumps({'camera': cam, 'iou_frame': reg['iou'], 'edge_agree_before_ecc': pick['edge']['agree']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
