#!/usr/bin/env python3
"""Аудит «поза или форма» для этапа 04-camera (T-183/Ш2б(в), отчёт советника §4): отдельный шаг-проверка, НЕ меняет pose_fit / camera_check.

ЗАЧЕМ. IoU 0,83 не значит «камера плохая»: лучшая камера не лечит придуманную форму. Нужно отличить «не нашли позу / поза неоднозначна» от «форма не совпала с фото» и сказать этапу 06,
что из проекции фото безопасно (корпус — да, ножки — нет: `LIMIT_PROJECTION`), вместо общего отказа.

КАК (три теста + воздержание; пороги — в `rules/pose-shape-qa.json`, откалиброваны на «легших» камерах, `calibrate`):
  A. Поза. Мультистарт `on` (36 стартов; обычно идёт только при IoU < 0,90). Старты с оценкой в зазоре δ от лучшей сравниваются по сдвигу проекций ВИДИМЫХ вершин и по
     согласию «какая область поверхности лежит под пикселем» (растр треугольников, не IoU). Почти равный старт через ~180° → ORIENTATION_AMBIGUOUS; иная нестабильность → POSE_UNCERTAIN.
  B. Остаток. Карты miss/extra по растру треугольников, связные компоненты с зоной (низ/верх/край), доля остатка, которую снимает лучший сдвиг+масштаб (общий сдвиг → REFINE).
  C. Проба деформации при закреплённой камере: ОДНО семейство за раз (высота ножек; ширина по полосам высоты), штраф на величину, G_shape = (L_жёсткая − L_штраф)/L_жёсткая;
     обязательные контроли: перефит камеры на жёсткой форме и невязка без штрафа на отложенных строках. «Форма» — только если деформация выигрывает у перефита камеры.
  Вердикт shape_status: LIKELY_OK | INDETERMINATE | SHAPE_MISMATCH_LIKELY (последнее — только при хорошей позе и согласии B и C на откалиброванных порогах).
Метрики контура (Chamfer, Boundary-F, высота камеры, перёд/зад) считает `pose_rank.py` (р.4) — здесь только вердикты; нет pose_rank — минимальная замена `_contour_metrics`.

Запуск (процессор, тяжёлое — под heavy-slot):
  pose_shape_qa.py audit --glb <n1024.glb> --photo <фото.rgba.png> --out <папка> [--rules файл] [--no-probe]
  pose_shape_qa.py calibrate --reports <report.json ...> --out <rules.calibrated.json>
Выход audit: <out>/qa.json (pose_status, shape_status, projection_safe, safe_zone, recommendation, метрики, кадр) и <out>/qa_sheet.png (лист для проверки глазами за минуту).
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
RULES_PATH = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'pose-shape-qa.json'))


def load_rules(path: str = RULES_PATH, calibrated: str | None = None) -> dict:
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    cal = calibrated or os.path.splitext(path)[0] + '.calibrated.json'
    if os.path.exists(cal):
        with open(cal, encoding='utf-8') as f:
            c = json.load(f)
        r['thresholds'] = {**r['thresholds'], **c.get('thresholds', {})}
        r['calibration'] = c.get('calibration', {})
    return r


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = float((a | b).sum())
    return float((a & b).sum()) / u if u else 0.0


# ——— метрики контура: pose_rank (р.4), иначе минимальная замена ———
def _contour_metrics(S: np.ndarray, A: np.ndarray) -> dict:
    try:
        import pose_rank as PR  # type: ignore
        return PR.contour_metrics(S, A)
    except Exception:
        import cv2

        def edge(M):
            m = M.astype(np.uint8)
            return (m - cv2.erode(m, np.ones((3, 3), np.uint8))) > 0

        eS, eA = edge(S), edge(A)
        if not eS.any() or not eA.any():
            return {'chamfer_px': None, 'chamfer_pct': None, 'bf': {}, 'source': 'fallback'}
        dA = cv2.distanceTransform((~eA).astype(np.uint8), cv2.DIST_L2, 3)
        dS = cv2.distanceTransform((~eS).astype(np.uint8), cv2.DIST_L2, 3)
        ch = 0.5 * (float(dA[eS].mean()) + float(dS[eA].mean()))
        bf = {}
        for t in (1, 2, 4, 8):
            p, r = float((dA[eS] <= t).mean()), float((dS[eA] <= t).mean())
            bf[str(t)] = round(2 * p * r / (p + r), 4) if p + r else 0.0
        return {'chamfer_px': round(ch, 3), 'chamfer_pct': round(100 * ch / float(np.hypot(*S.shape)), 3), 'bf': bf, 'source': 'fallback'}


# ——— A. поза ———
def region_bins(centroids: np.ndarray, bins: int = 8) -> np.ndarray:
    """Номер ячейки (bins³) по центру грани: грубая «область поверхности»."""
    lo, hi = centroids.min(0), centroids.max(0)
    q = np.clip(((centroids - lo) / np.maximum(hi - lo, 1e-9) * bins).astype(np.int64), 0, bins - 1)
    return q[:, 0] * bins * bins + q[:, 1] * bins + q[:, 2]


def region_disagreement(ids_a: np.ndarray, ids_b: np.ndarray, cent: np.ndarray, diag: float, q: float = 90.0) -> float:
    """Расхождение поверхности под пикселем между двумя камерами: q-й процентиль 3D-расстояния между центрами граней, видимых в этом пикселе, в долях диагонали предмета
    (0 — под пикселем одна и та же точка поверхности). Не корзины: малый поворот камеры плоскую грань «сдвигает» по корзинам, а расстояние остаётся малым."""
    both = (ids_a >= 0) & (ids_b >= 0)
    if not both.any():
        return 1.0
    d = np.linalg.norm(cent[ids_a[both]] - cent[ids_b[both]], axis=1) / max(diag, 1e-9)
    return float(np.percentile(d, q))


def render_zbuf(geo: dict, cam: dict, n: int) -> dict:
    """Честный z-buffer (попиксельная глубина) для проверки: `pose_fit.render_persp` рисует грани по СРЕДНЕЙ глубине (painter), и id видимой грани у пересекающихся/длинных граней может врать.
    → {ids (−1 фон), depth (inf фон)}. Глубина в пикселе — перспективно-верная 1/∑(w/Z). Покрытие — по центрам пикселей (чуть иное на кромке, чем fillConvexPoly)."""
    import pose_fit as PF
    V, F = geo['V'], geo['F']
    x, y, Z = PF.project(V, cam)
    sx, sy = x * n, y * n
    ids = np.full((n, n), -1, np.int32)
    dep = np.full((n, n), np.inf, np.float64)
    ax, ay, bx, by, cx, cy = sx[F[:, 0]], sy[F[:, 0]], sx[F[:, 1]], sy[F[:, 1]], sx[F[:, 2]], sy[F[:, 2]]
    za, zb, zc = np.maximum(Z[F[:, 0]], 1e-6), np.maximum(Z[F[:, 1]], 1e-6), np.maximum(Z[F[:, 2]], 1e-6)
    den = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    x0 = np.clip(np.floor(np.minimum(np.minimum(ax, bx), cx)).astype(np.int64), 0, n - 1)
    x1 = np.clip(np.ceil(np.maximum(np.maximum(ax, bx), cx)).astype(np.int64), 0, n - 1)
    y0 = np.clip(np.floor(np.minimum(np.minimum(ay, by), cy)).astype(np.int64), 0, n - 1)
    y1 = np.clip(np.ceil(np.maximum(np.maximum(ay, by), cy)).astype(np.int64), 0, n - 1)
    for f in np.flatnonzero(np.abs(den) > 1e-12):
        xs = np.arange(x0[f], x1[f] + 1) + 0.5
        ys = np.arange(y0[f], y1[f] + 1) + 0.5
        px, py = np.meshgrid(xs, ys)
        wa = ((bx[f] - px) * (cy[f] - py) - (by[f] - py) * (cx[f] - px)) / den[f]
        wb = ((cx[f] - px) * (ay[f] - py) - (cy[f] - py) * (ax[f] - px)) / den[f]
        wc = 1.0 - wa - wb
        ins = (wa >= 0) & (wb >= 0) & (wc >= 0)
        if not ins.any():
            continue
        s = wa / za[f] + wb / zb[f] + wc / zc[f]
        z = np.where(ins, 1.0 / np.maximum(s, 1e-12), np.inf)
        sub = dep[y0[f]:y1[f] + 1, x0[f]:x1[f] + 1]
        win = z < sub
        if win.any():
            sub[win] = z[win]
            ids[y0[f]:y1[f] + 1, x0[f]:x1[f] + 1][win] = f
    return {'ids': ids, 'depth': dep}


def zbuf_check(R_paint: dict, R_z: dict, face_bin: np.ndarray) -> dict:
    """Растр по средней глубине против честного z-buffer: доля пикселей (там, где видят оба), где id грани разный / область поверхности разная; доля пикселей, закрытых только у одного из них."""
    a, b = R_paint['ids'], R_z['ids']
    both = (a >= 0) & (b >= 0)
    n = int(both.sum())
    if n == 0:
        return {'id_diff': 1.0, 'region_diff': 1.0, 'cover_diff': 1.0}
    return {'id_diff': round(float((a[both] != b[both]).mean()), 4), 'region_diff': round(float((face_bin[a[both]] != face_bin[b[both]]).mean()), 4),
            'cover_diff': round(float(((a >= 0) ^ (b >= 0)).sum()) / float(((a >= 0) | (b >= 0)).sum()), 4)}


def vis_vertices(ids: np.ndarray, F: np.ndarray) -> np.ndarray:
    f = np.unique(ids[ids >= 0])
    return np.unique(F[f].ravel())


def cam_displacement(V: np.ndarray, cam_a: dict, cam_b: dict, n: int, scale_px: float) -> float:
    """Среднеквадратичный сдвиг проекций вершин V между двумя камерами, в долях размера силуэта."""
    import pose_fit as PF
    xa, ya, _ = PF.project(V, cam_a)
    xb, yb, _ = PF.project(V, cam_b)
    d = np.hypot((xa - xb) * n, (ya - yb) * n)
    return float(np.sqrt((d ** 2).mean()) / max(scale_px, 1e-9))


def az_flip(a: dict, b: dict, tol: float) -> bool:
    d = abs(((a['az'] - b['az'] + 180.0) % 360.0) - 180.0)
    return abs(d - 180.0) <= tol or d >= 180.0 - tol


def near_best(starts: list, delta: float) -> tuple[dict, list]:
    best = max(starts, key=lambda s: s['score'])
    return best, [s for s in starts if s['score'] >= best['score'] - delta and s is not best]


def flip_gap(starts: list, best: dict, tol: float):
    """Лучший старт «через ~180°» и его отставание по оценке: (gap, старт) или (None, None)."""
    fl = [s for s in starts if az_flip(best['cam'], s['cam'], tol)]
    if not fl:
        return None, None
    f = max(fl, key=lambda s: s['score'])
    return round(best['score'] - f['score'], 4), f


def better_camera(ref: dict, starts: list, th: dict, bottom_fn) -> dict:
    """Есть ли соперник лучше ПРОИЗВОДСТВЕННОЙ камеры `ref` (старт со `score`). Правила директора 22.11:
    • перевёрнутый на ~180° соперник (az_flip) «лучше по IoU» НЕ считается — зеркальную семью решает ориентация/тень (флаг ORIENTATION_AMBIGUOUS остаётся отдельно);
    • соперник того же поворота, но с другими d/f (отношение расстояний ≥ focal_ratio_min) — `focal_distance_ambiguous` (слабая перспектива), прирост и низ — справкой;
    • `better` = выигрыш оценки ≥ better_gain_min И низ проходит гейт этапа 04. bottom_fn(cam) → (низ_ок, strip-метрики)."""
    same = [s for s in starts if s is not ref and not az_flip(ref['cam'], s['cam'], th['flip_az_tol'])]
    out = {'better': False, 'focal_distance_ambiguous': False, 'gain': None, 'cam': None, 'bottom_ok': None, 'strip': None, 'd_ratio': None,
           'n_flip_better': sum(1 for s in starts if s is not ref and az_flip(ref['cam'], s['cam'], th['flip_az_tol']) and s['score'] > ref['score'])}
    if not same:
        return out
    c = max(same, key=lambda s: s['score'])
    gain = round(float(c['score'] - ref['score']), 4)
    dr = max(c['cam']['d'] / ref['cam']['d'], ref['cam']['d'] / c['cam']['d'])
    ok, st = bottom_fn(c['cam'])
    out.update({'gain': gain, 'cam': c['cam'], 'bottom_ok': bool(ok), 'strip': st, 'd_ratio': round(float(dr), 3)})
    out['focal_distance_ambiguous'] = bool(dr >= th['focal_ratio_min'] and gain > 0)
    out['better'] = bool(gain >= th['better_gain_min'] and ok)
    return out


def pose_verdict(flip_gap_v, max_disp: float, max_region: float, th: dict, edge_agree: float | None = None) -> str:
    """edge_agree — согласие кромок ПРОИЗВОДСТВЕННОЙ позы (pose.json picked.edge.agree). Почти равный старт через ~180° — ORIENTATION_AMBIGUOUS («глазам»),
    только если запас по кромкам мал: edge_agree < th['edge_agree_min'] (порог из распределения, не под товар) или его нет. Кромки подтвердили ориентацию → флаг не ставим."""
    if flip_gap_v is not None and flip_gap_v <= th['flip_gap_max']:
        em = th.get('edge_agree_min')
        if not (em is not None and edge_agree is not None and edge_agree >= em):
            return 'ORIENTATION_AMBIGUOUS'
    if max_disp > th['disp_max'] or max_region > th['region_max']:
        return 'POSE_UNCERTAIN'
    return 'GOOD'


# ——— B. остаток ———
def residual_components(S: np.ndarray, A: np.ndarray, rules: dict) -> dict:
    from scipy import ndimage
    ys, xs = np.nonzero(A | S)
    if len(ys) == 0:
        return {'components': [], 'share': {}, 'local_share': 0.0, 'bottom_share': 0.0}
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    h, w = y1 - y0, x1 - x0
    area = max(1, int(A.sum()))
    zr = rules['zones']
    comps, tot = [], 0.0
    for sign, M in (('miss', A & ~S), ('extra', S & ~A)):
        M = ndimage.binary_opening(M, iterations=1) if M.sum() > 50 else M
        lab, k = ndimage.label(M)
        for i in range(1, k + 1):
            m = lab == i
            a = int(m.sum()) / area
            if a < zr['min_area_share']:
                continue
            cy, cx = ndimage.center_of_mass(m)
            yn, xn = (cy - y0) / h, (cx - x0) / w
            zone = 'bottom' if yn > 1 - zr['bottom_frac'] else ('top' if yn < zr['top_frac'] else 'middle')
            edge = 'side' if (xn < zr['side_frac'] or xn > 1 - zr['side_frac']) else 'centre'
            comps.append({'sign': sign, 'area_share': round(a, 4), 'zone': zone, 'edge': edge, 'cy_n': round(float(yn), 3), 'cx_n': round(float(xn), 3)})
            tot += a
    share = {}
    for c in comps:
        share[c['zone']] = round(share.get(c['zone'], 0.0) + c['area_share'], 4)
    allres = float((A ^ S).sum()) / area
    return {'components': comps, 'share': share, 'residual_share': round(allres, 4), 'local_share': round(tot, 4), 'bottom_share': share.get('bottom', 0.0),
            'non_bottom_share': round(tot - share.get('bottom', 0.0), 4)}


def global_shift_explained(S: np.ndarray, A: np.ndarray, rules: dict) -> dict:
    """Какую долю несовпадения (XOR) снимает лучший общий сдвиг + масштаб рендера: близко к 1 — «сдвинута вся фигура» (REFINE), близко к 0 — местная ошибка."""
    import cv2
    base = float((S ^ A).sum())
    if base == 0:
        return {'explained': 0.0, 'dx': 0, 'dy': 0, 'scale': 1.0}
    ys, xs = np.nonzero(S)
    if len(ys) == 0:
        return {'explained': 0.0, 'dx': 0, 'dy': 0, 'scale': 1.0}
    cy, cx = ys.mean(), xs.mean()
    Sf = S.astype(np.float32)
    g = rules['shift']
    best = (base, 0, 0, 1.0)
    for sc in g['scales']:
        for dy in g['shifts_px']:
            for dx in g['shifts_px']:
                M = np.array([[sc, 0, cx - sc * cx + dx], [0, sc, cy - sc * cy + dy]], np.float32)
                W = cv2.warpAffine(Sf, M, (S.shape[1], S.shape[0]), flags=cv2.INTER_LINEAR) > 0.5
                v = float((W ^ A).sum())
                if v < best[0]:
                    best = (v, dx, dy, sc)
    return {'explained': round(1.0 - best[0] / base, 4), 'dx': best[1], 'dy': best[2], 'scale': best[3]}


# ——— C. проба ограниченной деформации ———
def deform_legs(V: np.ndarray, s: float, ymin: float, ymax: float, frac: float) -> np.ndarray:
    """Высота ножек: масштаб по Y ниже уровня крепления cut = ymin + frac·высота (выше cut точки не двигаются)."""
    cut = ymin + frac * (ymax - ymin)
    W = V.copy()
    low = V[:, 1] < cut
    W[low, 1] = cut + (V[low, 1] - cut) * s
    return W


def deform_bands(V: np.ndarray, ss: np.ndarray, ymin: float, ymax: float, centre: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Ширина по полосам высоты: сдвиг вдоль экранной оси «вправо» пропорционален s(y)−1, s(y) — линейная интерполяция по k узлам."""
    k = len(ss)
    t = np.clip((V[:, 1] - ymin) / max(ymax - ymin, 1e-9), 0, 1) * (k - 1)
    s_y = np.interp(t, np.arange(k), ss)
    off = ((V - centre) @ right)[:, None] * (s_y - 1.0)[:, None] * right[None, :]
    return V + off


def _soft(S: np.ndarray, Bp: np.ndarray, rows: np.ndarray) -> float:
    import pose_fit as PF
    Bs = PF._blur(S, S.shape[0])
    den = float(np.maximum(Bs, Bp)[rows].sum())
    return 1.0 - (float(np.minimum(Bs, Bp)[rows].sum()) / den if den else 0.0)


def probe_family(Pc: np.ndarray, cam: dict, Mp: np.ndarray, n: int, family: str, rules: dict) -> dict:
    """Семейство деформации при закреплённой камере. Подгонка на чётных строках, проверка без штрафа на нечётных. → G (со штрафом), G отложенных, параметры, штраф."""
    from scipy.optimize import minimize
    import pose_fit as PF
    p = rules['probe']
    ymin, ymax = float(Pc[:, 1].min()), float(Pc[:, 1].max())
    Bp = PF._blur(Mp, n)
    even = (np.arange(n) % 2 == 0)[:, None] * np.ones((1, n), bool)
    odd = ~even
    _, right, _, _ = PF.cam_basis(cam['az'], cam['el'], cam['d'])
    centre = Pc.mean(0)
    if family == 'legs_h':
        x0, dmax = np.array([1.0]), p['legs_h_max']
        mk = lambda x: deform_legs(Pc, float(x[0]), ymin, ymax, p['legs_frac'])
    else:
        k = p['bands']
        x0, dmax = np.ones(k), p['band_w_max']
        mk = lambda x: deform_bands(Pc, np.asarray(x), ymin, ymax, centre, right)

    def L(x, rows):
        return _soft(PF.splat_mask(mk(x), cam, n), Bp, rows)

    def pen(x):
        return float(np.mean(((np.asarray(x) - 1.0) / dmax) ** 2))

    def obj(x):
        if np.any(np.abs(np.asarray(x) - 1.0) > dmax):
            return 9.0
        return L(x, even) + p['lambda'] * pen(x)

    L0, L0ho = L(x0, even), L(x0, odd)
    r = minimize(obj, x0, method='Nelder-Mead', options={'initial_simplex': np.vstack([x0] + [x0 + np.eye(len(x0))[i] * dmax * 0.5 for i in range(len(x0))]), 'maxiter': p['maxiter'], 'xatol': 1e-3, 'fatol': 1e-6})
    x = np.clip(r.x, 1 - dmax, 1 + dmax)
    Ld, Ldho = L(x, even), L(x, odd)
    return {'family': family, 'params': [round(float(v), 4) for v in x], 'pen': round(pen(x), 4), 'L_rigid': round(L0, 4), 'L_def': round(Ld, 4),
            'G_pen': round((L0 - (Ld + p['lambda'] * pen(x))) / max(L0, 1e-9), 4), 'G_heldout': round((L0ho - Ldho) / max(L0ho, 1e-9), 4),
            'hard_iou_before': round(iou(PF.splat_mask(Pc, cam, n), Mp), 4), 'hard_iou_after': round(iou(PF.splat_mask(mk(x), cam, n), Mp), 4)}


def probe_cam_refit(Pc: np.ndarray, cam: dict, Mp: np.ndarray, n: int, rules: dict) -> dict:
    """Контроль: те же строки, та же цель, но свободна КАМЕРА, форма жёсткая. Если выигрыш камеры не меньше выигрыша деформации — это не форма."""
    from scipy.optimize import minimize
    import pose_fit as PF
    p = rules['probe']
    Bp = PF._blur(Mp, n)
    even = (np.arange(n) % 2 == 0)[:, None] * np.ones((1, n), bool)
    odd = ~even
    v0 = PF._vec(cam)

    def L(v, rows):
        c = PF._cam(v)
        if not (PF.D_MIN <= c['d'] <= PF.D_MAX) or abs(c['el']) > 85:
            return 9.0
        return _soft(PF.splat_mask(Pc, c, n), Bp, rows)

    sim = np.vstack([v0] + [v0 + np.eye(6)[i] * st for i, st in enumerate((2.0, 1.5, 0.06, 0.03, 0.01, 0.01))])
    r = minimize(lambda v: L(v, even), v0, method='Nelder-Mead', options={'initial_simplex': sim, 'maxiter': p['cam_maxiter'], 'xatol': 1e-3, 'fatol': 1e-6})
    L0ho = L(v0, odd)
    return {'G_heldout': round((L0ho - L(r.x, odd)) / max(L0ho, 1e-9), 4), 'cam': PF._cam(r.x)}


# ——— вердикты ———
def shape_verdict(pose_status: str, iou_tri: float, res: dict, shift: dict, probe: dict | None, th: dict, calibrated: bool, bottom_ok: bool = True) -> tuple[str, dict]:
    ev = {'t_res': bool(res['non_bottom_share'] + res['bottom_share'] >= th['local_res_min'] and shift['explained'] <= th['shift_expl_max']),
          't_def': False, 'gain_over_cam': None}
    if probe and probe.get('best'):
        b = probe['best']
        gain = b['G_heldout'] - probe['cam']['G_heldout']
        ev['gain_over_cam'] = round(gain, 4)
        ev['t_def'] = bool(gain >= th['gain_min'] and b['pen'] <= th['pen_max'])
    small = iou_tri >= th['iou_ok'] and res['local_share'] < th['local_res_min'] and bottom_ok     # «ок» только если и нижняя полоса прошла гейт этапа 04 (ножки тонкие: в долях всей площади их ошибка мала, а форма низа — неверна)
    if small and pose_status == 'GOOD':
        return 'LIKELY_OK', ev
    if calibrated and pose_status == 'GOOD' and ev['t_res'] and ev['t_def']:
        return 'SHAPE_MISMATCH_LIKELY', ev
    return 'INDETERMINATE', ev


def recommendation(pose_status: str, shape_status: str, res: dict, shift: dict, th: dict, bottom_fail: bool = False, iou_top: float | None = None) -> tuple[str, bool, str]:
    """→ (recommendation, projection_safe, safe_zone). safe_zone: full | body (ниже полосы фото не переносить) | none.
    bottom_fail — нижняя полоса не прошла гейт этапа 04; iou_top — IoU верхней части (выше полосы): корпус лёг, ножки нет → LIMIT_PROJECTION (зона body)."""
    if pose_status != 'GOOD':
        return 'REVIEW_POSE', False, 'none'
    if shape_status == 'LIKELY_OK':
        return 'OK', True, 'full'
    if shift['explained'] >= th['shift_expl_refine']:
        return 'REFINE', False, 'none'
    if bottom_fail and iou_top is not None and iou_top >= th.get('body_iou_min', 0.85):
        return 'LIMIT_PROJECTION', False, 'body'
    if res['non_bottom_share'] <= th['body_res_max'] and res['bottom_share'] >= th['local_res_min'] / 2:
        return 'LIMIT_PROJECTION', False, 'body'
    if shape_status == 'SHAPE_MISMATCH_LIKELY':
        return 'REBUILD_MESH', False, 'none'
    return 'REVIEW_SHAPE', False, 'none'


# ——— сборка по товару ———
def inject_defect(glb: str, out_glb: str, kind: str, mag: float) -> str:
    """Калибровочный дефект на ЛЕГШЕМ меше (глиф формы glb, Y вверх): legs — масштаб высоты нижних 25 %; width — расширение средней полосы по X. Для измерения чувствительности."""
    import trimesh
    sc = trimesh.load(glb, process=False)
    m = sc if isinstance(sc, trimesh.Trimesh) else list(sc.geometry.values())[0]
    V = np.array(m.vertices, np.float64)
    lo, hi = V[:, 1].min(), V[:, 1].max()
    if kind == 'legs':
        V = deform_legs(V, mag, lo, hi, 0.25)
    else:
        t = (V[:, 1] - lo) / max(hi - lo, 1e-9)
        w = np.exp(-((t - 0.5) / 0.2) ** 2)
        V[:, 0] = V[:, 0].mean() + (V[:, 0] - V[:, 0].mean()) * (1 + (mag - 1) * w)
    m.vertices = V
    m.export(out_glb)
    return out_glb


def audit_product(glb: str, photo: str, out: str, rules: dict | None = None, log=print, probe: bool = True, multistart: str = 'on', reuse: bool = False, ref_pose: str | None = None, own_dir: str | None = None) -> dict:
    """ref_pose — pose.json ПРОИЗВОДСТВЕННОЙ камеры (этап 04, runs04): опорная камера = она, 36 стартов аудита (own_dir/pose.json) — соперники;
    в отчёт — `better_camera` (есть ли старт лучше производственной по оценке и как у него низ). Без ref_pose опорная — камера, выбранная перефитом аудита."""
    import cv2
    import pose_fit as PF
    import stage_loss as SL
    import stages_cpu as SC
    rules = rules or load_rules()
    th = rules['thresholds']
    cal = bool(rules.get('calibration', {}).get('n_null'))
    os.makedirs(out, exist_ok=True)
    own = own_dir or out
    pj_path = os.path.join(own, 'pose.json')
    if ref_pose and not os.path.exists(pj_path):
        raise RuntimeError('ref_pose: нет pose.json аудита со стартами: ' + pj_path)
    if reuse and os.path.exists(pj_path) and (json.load(open(pj_path, encoding='utf-8')).get('multistart') or {}).get('ran'):
        log('pose.json есть (мультистарт был) — подбор камеры не повторяю')          # вердикты можно пересчитать без 7-минутного подбора
    else:
        PF.fit_pose(glb, photo, out, multistart=multistart, log=log)
    pj = json.load(open(pj_path, encoding='utf-8'))
    n = rules['n']
    alpha = SL.read_rgba(photo)[..., 3] > 127
    Mp = PF.canvas_mask(alpha, pj['canvas'], n)
    geo = PF.to_cube_geo(SC.load_geom(glb), float(pj.get('yaw', 0.0)))
    V, F = geo['V'], geo['F']
    cam = pj['camera']
    starts = (pj.get('multistart') or {}).get('starts') or []
    if not starts:
        raise RuntimeError('нет стартов мультистарта в pose.json')
    Pc = None
    ref_start = None
    if ref_pose:                                           # опорная — производственная камера; оценки пересчитаны одним способом (облако с поверхности + splat), иначе оценки разных процедур несравнимы
        rp = json.load(open(ref_pose, encoding='utf-8'))
        if rp.get('canvas') != pj.get('canvas') or float(rp.get('yaw', 0.0)) != float(pj.get('yaw', 0.0)):
            raise RuntimeError('ref_pose: canvas/yaw производственной позы не совпадают с позой аудита — сравнивать нельзя')
        cam = rp['camera']
        Pc = PF._surf_points(geo, int(rules.get('surf_n', 200000)))
        starts = [{**s, **PF.pose_score(PF.splat_mask(Pc, s['cam'], n), Mp)} for s in starts]
        ref_start = {'cam': cam, 'ref': True, **PF.pose_score(PF.splat_mask(Pc, cam, n), Mp)}
        starts = [ref_start] + starts
    face_bin = region_bins(V[F].mean(1), rules['region_bins'])
    R0 = PF.render_persp(geo, cam, n)
    S = R0['mask']
    ys, xs = np.nonzero(S | Mp)
    scale_px = float(np.hypot(xs.max() - xs.min(), ys.max() - ys.min()))
    zb = None
    if rules.get('use_zbuf'):                            # диагностика: врёт ли растр по средней глубине; по умолчанию выкл. — растр и его починка у р.4 (pose_fit), вердикты тут идут на её растре
        Rz = render_zbuf(geo, cam, n)
        zb = zbuf_check(R0, Rz, face_bin)
        R0 = {**R0, 'ids': Rz['ids']}
    vv = vis_vertices(R0['ids'], F)
    Vv = V[vv[:: max(1, len(vv) // 20000)]]
    if ref_start is not None:                              # эталон — производственная камера; соперники — все старты не хуже неё минус near_delta
        best = ref_start
        nb = [s for s in starts if s is not ref_start and s['score'] >= ref_start['score'] - th['near_delta']]
    else:
        best, nb = near_best(starts, th['near_delta'])
    gap, flip = flip_gap(starts, {'cam': cam, 'score': best['score']}, th['flip_az_tol'])
    disps, regs, cand = [], [], []
    ref_cam = cam                                          # эталон — ВЫБРАННАЯ камера (pose_fit выбирает из пула по кромкам, не по оценке старта)
    pool_s = [s for s in starts if s['score'] >= best['score'] - th['near_delta']]
    cent = V[F].mean(1)
    diag = float(np.linalg.norm(V.max(0) - V.min(0)))
    rend = (lambda g, c, k: render_zbuf(g, c, k)) if rules.get('use_zbuf') else PF.render_persp
    R_ref = rend(geo, ref_cam, n)
    for s in pool_s[: rules['max_near'] + 1]:
        if az_flip(ref_cam, s['cam'], th['flip_az_tol']) or cam_displacement(Vv, ref_cam, s['cam'], n, scale_px) < 0.005:
            continue                                       # «через 180°» — отдельный тест (flip_gap); та же камера — не соперник
        Rs = rend(geo, s['cam'], n)
        d = cam_displacement(Vv, ref_cam, s['cam'], n, scale_px)
        g = region_disagreement(R_ref['ids'], Rs['ids'], cent, diag)
        disps.append(d)
        regs.append(g)
        cand.append({'cam': s['cam'], 'score': s['score'], 'disp': round(d, 4), 'region_dis': round(g, 4)})
    d_pick = cam_displacement(Vv, ref_cam, cam, n, scale_px)
    edge_prod = ((json.load(open(ref_pose, encoding='utf-8')) if ref_pose else pj).get('picked') or {}).get('edge') or {}   # кромки производственной позы (без ref_pose — позы аудита)
    edge_agree = edge_prod.get('agree')
    if edge_agree is not None and (edge_agree < 0 or edge_prod.get('no_edges')):
        edge_agree = None                                  # «кромок нет» (заглушка −1) — не подтверждение
    pose_status = pose_verdict(gap, max(disps + [0.0]), max(regs + [0.0]), th, edge_agree)
    res = residual_components(S, Mp, rules)
    shift = global_shift_explained(S, Mp, rules)
    iou_tri = iou(S, Mp)
    cm = _contour_metrics(S, Mp)
    if Pc is None:
        Pc = PF._surf_points(geo, int(rules.get('surf_n', 200000)))        # облако с поверхности граней: у плоских граней TRELLIS вершин мало, маска по вершинам дырявая (комод 13224: IoU 0,72 против 0,89)
    pr = None
    disputed = iou_tri < th['iou_ok'] or res['local_share'] >= th['local_res_min'] or pose_status != 'GOOD'
    if probe and (disputed or not rules.get('probe_only_disputed', True)):          # G_shape — только на спорных (директор 21.11); на чистых — нечего проверять
        fams = [probe_family(Pc, cam, Mp, n, f, rules) for f in rules['probe']['families']]
        pr = {'families': fams, 'best': max(fams, key=lambda t: t['G_heldout']), 'cam': probe_cam_refit(Pc, cam, Mp, n, rules)}
    import camera_check as CC
    cc = CC.load_rules()
    sh_ = CC.silhouette_shares(S, Mp, float(cc['strip_frac']))
    bottom_fail = bool(sh_['miss_bottom'] > cc['miss_bottom_max'] or sh_['extra_bottom'] > cc['extra_bottom_max'])
    strip = {'miss_bottom': round(sh_['miss_bottom'], 4), 'extra_bottom': round(sh_['extra_bottom'], 4), 'iou_top': None if sh_['iou_top'] is None else round(sh_['iou_top'], 4), 'bottom_fail_stage04': bottom_fail,
             'limits': {'miss_bottom_max': cc['miss_bottom_max'], 'extra_bottom_max': cc['extra_bottom_max']}}
    bc = None
    if ref_start is not None:
        def _bottom(c):
            Sc = PF.render_persp(geo, c, n)['mask']
            s2 = CC.silhouette_shares(Sc, Mp, float(cc['strip_frac']))
            return (not (s2['miss_bottom'] > cc['miss_bottom_max'] or s2['extra_bottom'] > cc['extra_bottom_max'])), {k: (round(s2[k], 4) if s2[k] is not None else None) for k in ('miss_bottom', 'extra_bottom', 'iou_top')}
        bc = better_camera(ref_start, starts, th, _bottom)
    shape_status, ev = shape_verdict(pose_status, iou_tri, res, shift, pr, th, cal, bottom_ok=not bottom_fail)
    rec, safe, zone = recommendation(pose_status, shape_status, res, shift, th, bottom_fail, sh_['iou_top'])
    rep = {'glb': glb, 'photo': photo, 'rules_version': rules.get('version'), 'calibrated': cal, 'tree_pose_fit': None,
           'pose_status': pose_status, 'shape_status': shape_status, 'projection_safe': safe, 'safe_zone': zone, 'recommendation': rec,
           'camera_model': (pj.get('rank') or {}).get('weak', {}).get('camera_model'), 'focal_distance_ambiguous': (pj.get('rank') or {}).get('weak', {}).get('focal_distance_ambiguous'),
           'silhouette_iou_tri': round(iou_tri, 4), 'silhouette_iou_fit': pj.get('iou_frame'), 'boundary_chamfer_px': cm.get('chamfer_px'), 'boundary_bf': cm.get('bf'),
           'front_back_margin': gap, 'edge_agree_prod': edge_agree, 'flip_cam': (flip or {}).get('cam'), 'near_best': cand, 'cam_pick_vs_ref_disp': round(d_pick, 4),
           'max_disp': round(max(disps + [0.0]), 4), 'max_region_dis': round(max(regs + [0.0]), 4), 'n_starts': len(starts), 'n_near': len(nb),
           'ref_mode': 'production' if ref_start is not None else 'audit_refit', 'ref_score': None if ref_start is None else ref_start['score'], 'better_camera': bc,
           'zbuf_check': zb, 'strip': strip, 'residual': res, 'shift': shift, 'probe': pr, 'evidence': ev, 'camera': cam}
    json.dump(rep, open(os.path.join(out, 'qa.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    try:
        sheet(out, Mp, S, geo, cam, cand, flip, res, pr, Pc, n, rules, rep)
    except Exception as e:  # лист — для глаз; сбой листа не роняет вердикт
        log('лист не построен: %r' % (e,))
    return rep


def sheet(out: str, Mp, S, geo, cam, cand, flip, res, pr, Pc, n, rules, rep) -> None:
    """qa_sheet.png: ① фото-силуэт + контур рендера · ② знаковый остаток (синий — фото не закрыто, красный — форма вне фото) · ③ увеличенный низ · ④ другая камера (ближайшая и «через 180°») · ⑤ проба до/после."""
    import cv2
    import pose_fit as PF

    def contour(M):
        m = M.astype(np.uint8)
        return (m - cv2.erode(m, np.ones((3, 3), np.uint8))) > 0

    def base(A):
        return np.stack([np.where(A, 200, 255)] * 3, -1).astype(np.uint8)

    def tile(img, text):
        t = cv2.resize(img, (384, 384), interpolation=cv2.INTER_NEAREST)
        cv2.putText(t, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        return t

    t1 = base(Mp)
    t1[contour(S)] = (0, 160, 0)
    t2 = np.full((n, n, 3), 255, np.uint8)
    t2[Mp & ~S] = (230, 120, 40)
    t2[S & ~Mp] = (40, 40, 220)
    t2[Mp & S] = (225, 225, 225)
    ys, xs = np.nonzero(Mp | S)
    y1 = ys.max() + 1
    y0 = max(0, int(y1 - 0.3 * (y1 - ys.min())))
    zb = t1[y0:y1, max(0, xs.min() - 4):xs.max() + 4]
    t3 = cv2.resize(zb, (384, max(60, int(384 * zb.shape[0] / max(zb.shape[1], 1)))), interpolation=cv2.INTER_NEAREST)
    t3 = cv2.copyMakeBorder(t3, 0, 384 - t3.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) if t3.shape[0] < 384 else t3[:384]
    cv2.putText(t3, 'bottom x?', (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    other = (flip or {}).get('cam') or (cand[0]['cam'] if cand else None)
    t4 = base(Mp)
    lab4 = 'no 2nd cam'
    if other is not None:
        t4[contour(PF.render_persp(geo, other, n)['mask'])] = (200, 0, 160)
        lab4 = ('flip+180 ' if flip else 'near-best ') + ('gap=%s' % rep['front_back_margin'] if flip else 'disp=%s' % cand[0]['disp'])
    t5 = base(Mp)
    t5[contour(PF.splat_mask(Pc, cam, n))] = (0, 160, 0)
    lab5 = 'probe off'
    if pr and pr.get('best'):
        b = pr['best']
        import pose_shape_qa as Q
        p = rules['probe']
        ymin, ymax = float(Pc[:, 1].min()), float(Pc[:, 1].max())
        if b['family'] == 'legs_h':
            W = Q.deform_legs(Pc, b['params'][0], ymin, ymax, p['legs_frac'])
        else:
            _, right, _, _ = PF.cam_basis(cam['az'], cam['el'], cam['d'])
            W = Q.deform_bands(Pc, np.asarray(b['params']), ymin, ymax, Pc.mean(0), right)
        t5[contour(PF.splat_mask(W, cam, n))] = (200, 0, 160)
        lab5 = '%s G_ho=%s camG=%s' % (b['family'], b['G_heldout'], pr['cam']['G_heldout'])
    head = '%s | %s | safe=%s/%s | %s' % (rep['pose_status'], rep['shape_status'], rep['projection_safe'], rep['safe_zone'], rep['recommendation'])
    row = np.concatenate([tile(t1, 'photo + render contour'), tile(t2, 'residual blue=miss red=extra'), t3, tile(t4, lab4), tile(t5, lab5)], axis=1)
    bar = np.full((28, row.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, head, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(out, 'qa_sheet.png'), np.concatenate([bar, row], axis=0)[..., ::-1])


# ——— калибровка по «легшим» ———
NULL_KEYS = {'max_disp': 'disp_max', 'max_region_dis': 'region_max', 'local_share': 'local_res_min', 'gain_over_cam': 'gain_min'}


def calibrate(reports: list, rules: dict, margin: float = 1.25, quantile: float | None = None) -> dict:
    """Пороги по нулевой выборке (отчёты «легших»): порог = max(нуль) × margin (или квантиль × margin, если задан quantile — выборка «легших» грязная: старая мерка проверяет силуэт, не позу),
    не ниже стартового пола; число нулей и значения — в `calibration`. Чувствительность на внедрённых дефектах — `sensitivity`."""
    vals = {k: [] for k in NULL_KEYS}
    for r in reports:
        vals['max_disp'].append(r['max_disp'])
        vals['max_region_dis'].append(r['max_region_dis'])
        vals['local_share'].append(r['residual']['local_share'])
        g = (r.get('evidence') or {}).get('gain_over_cam')
        if g is not None:
            vals['gain_over_cam'].append(g)
    th = {}
    for k, name in NULL_KEYS.items():
        if vals[k]:
            base = max(vals[k]) if quantile is None else float(np.percentile(vals[k], 100.0 * quantile))
            th[name] = round(max(base * margin, rules['thresholds'].get(name + '_floor', 0.0)), 4)
    return {'thresholds': th, 'calibration': {'n_null': len(reports), 'margin': margin, 'quantile': quantile, 'null_values': vals}}


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    a = sp.add_parser('audit')
    a.add_argument('--glb', required=True)
    a.add_argument('--photo', required=True)
    a.add_argument('--out', required=True)
    a.add_argument('--rules', default=RULES_PATH)
    a.add_argument('--no-probe', action='store_true')
    a.add_argument('--multistart', default='on')
    c = sp.add_parser('calibrate')
    c.add_argument('--reports', nargs='+', required=True)
    c.add_argument('--rules', default=RULES_PATH)
    c.add_argument('--out', required=True)
    x = ap.parse_args()
    rules = load_rules(x.rules)
    if x.cmd == 'audit':
        r = audit_product(x.glb, x.photo, x.out, rules, probe=not x.no_probe, multistart=x.multistart)
        print(json.dumps({k: r[k] for k in ('pose_status', 'shape_status', 'projection_safe', 'safe_zone', 'recommendation', 'silhouette_iou_tri', 'max_disp', 'max_region_dis')}, ensure_ascii=False))
        return 0
    reps = [json.load(open(p, encoding='utf-8')) for p in x.reports]
    json.dump(calibrate(reps, rules), open(x.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('калибровка: нулей', len(reps), '→', x.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
