#!/usr/bin/env python3
"""T-173/3 Ш2б(а): РАЗНЫЕ семейства поз в top-K, обязательная гипотеза yaw+180°, расстояние контуров (Chamfer) и Boundary-F, «камера не под полом», слабая перспектива.
Идеи — отчёт советника (21.11.2026, P0): IoU силуэта не различает перёд/зад у ящиков и не видит форму контура; пять почти одинаковых точек у одного максимума top-K не дают.
ВХОЛОСТУЮ по умолчанию: `pose_fit.py --rank` кладёт блок `rank` в pose.json и в лог; выбранная поза не меняется (кроме флага `--rank-pick`, см. `choose`). Пороги — `rules/pose-rank.json`.

Что считает (всё в кадре 768 px, как `edge_score`; пиксельные меры приведены к 768):
  • семейство = группа поз, различающихся азимутом > fam_sep_az° ИЛИ подъёмом > fam_sep_el°; из пула кандидатов, мультистарта и поиска берутся лучшие по `pose_score`, не более fam_k;
  • гипотеза yaw+180°: локальный подбор из позы с азимутом +180° (то же ядро Нелдера–Мида, что у мультистарта); в `flip` — её оценки и разрыв с выбранной позой;
  • у каждой позы: IoU по треугольникам, Chamfer контуров (средняя симметричная дистанция, px и доля диагонали фото), Boundary-F при допуске 1/2/4/8 px, совпадение кромок, высота центра камеры над опорой;
  • «камера не под полом»: высота центра камеры над низом формы ≥ floor_margin высот предмета (а не угол к центру: высокий шкаф снимают камерой ниже его центра, пока она выше пола);
  • `weak`: подбор с прибитым d (слабая перспектива) против свободного (f и d вместе); выигрыш < weak_gain_eps → перспектива в кадре не различима: `focal_distance_ambiguous`, `camera_model`='weak_perspective'.
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'rules', 'pose-rank.json')
if not os.path.exists(RULES):
    RULES = os.path.join(HERE, 'rules', 'pose-rank.json')


def rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


# ---------- чистое ядро (numpy + cv2) ----------

def boundary(M: np.ndarray) -> np.ndarray:
    import cv2
    m = np.asarray(M, bool).astype(np.uint8)
    return (m - cv2.erode(m, np.ones((3, 3), np.uint8))).astype(bool)


def _dist_to(B: np.ndarray) -> np.ndarray:
    """Расстояние (px) от каждого пикселя до ближайшей точки контура B."""
    import cv2
    return cv2.distanceTransform((~B).astype(np.uint8), cv2.DIST_L2, 3)


def contour_metrics(S: np.ndarray, A: np.ndarray, tols=(1, 2, 4, 8), n_ref: int = 768) -> dict:
    """Расстояние между контурами силуэта формы S и фото A (булевы маски одного кадра): {chamfer_px, chamfer_pct, bf: {tol: F}}, px — приведены к кадру n_ref, pct — к диагонали фото.
    Boundary-F(t) = F1 из точности (доля контура формы в t px от контура фото) и полноты (наоборот)."""
    n = S.shape[0]
    k = n_ref / float(n)
    bs, ba = boundary(S), boundary(A)
    if not bs.any() or not ba.any():
        return {'chamfer_px': None, 'chamfer_pct': None, 'bf': {str(t): 0.0 for t in tols}}
    da, ds = _dist_to(ba), _dist_to(bs)
    d_sa, d_as = da[bs] * k, ds[ba] * k
    ys, xs = np.nonzero(A)
    diag = float(np.hypot(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)) * k
    cham = 0.5 * (float(d_sa.mean()) + float(d_as.mean()))
    bf = {}
    for t in tols:
        p, r = float((d_sa <= t).mean()), float((d_as <= t).mean())
        bf[str(t)] = round(0.0 if p + r == 0 else 2 * p * r / (p + r), 4)
    return {'chamfer_px': round(cham, 2), 'chamfer_pct': round(100.0 * cham / max(diag, 1e-9), 3), 'bf': bf}


def cam_height_rel(cam: dict, ymin: float, ymax: float, cam_basis) -> float:
    """Высота центра камеры над низом формы в долях высоты предмета (куб: Y вверх, опора — самая нижняя точка формы)."""
    C = cam_basis(cam['az'], cam['el'], cam['d'])[0]
    return float((C[1] - ymin) / max(ymax - ymin, 1e-9))


def separate(recs: list, k: int, sep_az: float, sep_el: float, key=lambda r: r['cam']) -> list:
    """Жадно: лучшие записи (уже по убыванию оценки), каждая отличается от выбранных азимутом > sep_az ИЛИ подъёмом > sep_el."""
    out: list = []
    for r in recs:
        c = key(r)
        if all(abs(((c['az'] - key(o)['az'] + 180) % 360) - 180) > sep_az or abs(c['el'] - key(o)['el']) > sep_el for o in out):
            out.append(r)
        if len(out) >= k:
            break
    return out


def is_flip_of(a: dict, b: dict, tol: float = 30.0) -> bool:
    """b — это a, перевёрнутая на 180° по азимуту (в пределах tol°)."""
    return abs(((a['az'] + 180 - b['az'] + 180) % 360) - 180) <= tol


def choose(families: list, R: dict) -> dict:
    """Выбор позы из семейств (только при `--rank-pick`): среди поз НЕ под полом — лучшая по `pose_score`; ничья в пределах tie_score — по Boundary-F(2 px) и меньшему Chamfer.
    Возвращает {'index': i, 'changed': bool, 'why': str}; если все под полом — остаётся первая (выбранная боевая)."""
    ok = [i for i, f in enumerate(families) if f['floor_ok']]
    if not ok:
        return {'index': 0, 'changed': False, 'why': 'все под полом — остаётся боевая'}
    best = max(families[i]['score'] for i in ok)
    tie = [i for i in ok if families[i]['score'] >= best - R['tie_score']]
    i = max(tie, key=lambda j: (families[j]['bf']['2'], -(families[j]['chamfer_px'] or 1e9)))
    return {'index': i, 'changed': i != 0, 'why': f'не под полом: {len(ok)} из {len(families)}; ничья по оценке: {len(tie)}; выбрана по Boundary-F(2 px) и Chamfer'}


# ---------- с геометрией (вызывается из pose_fit) ----------

def rank_poses(PF, geo: dict, pick: dict, cands: list, ms_info: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, Mp: np.ndarray, n: int, log=print, R: dict | None = None) -> dict:
    """Блок `rank` для pose.json (см. шапку). PF — модуль pose_fit (передаётся, чтобы не импортировать его циклом)."""
    import stage_loss as SL
    R = R or rules()
    V = geo['V']
    ymin, ymax = float(V[:, 1].min()), float(V[:, 1].max())
    Pc = V[:: max(1, len(V) // 150000)]
    Mp_blur = PF._blur(Mp, n)
    N768 = 768
    P768 = PF.canvas_P(cv, N768)
    A_fr = SL.warp_inv(alpha.astype(np.float32), P768, (N768, N768)) > 0.5

    def evaluate(cam: dict, with_edge: bool = True) -> dict:
        r = PF.render_persp(geo, cam, N768)
        S = r['mask']
        m = PF.pose_score(PF.splat_mask(Pc, cam, n), Mp)
        rec = {'cam': {k: round(float(v), 4) for k, v in cam.items()}, 'score': m['score'], 'iou': m['iou'], 'iou_tri': round(PF.iou(S, A_fr), 4),
               **contour_metrics(S, A_fr, tuple(R['bf_tols']), N768)}
        h = cam_height_rel(cam, ymin, ymax, PF.cam_basis)
        rec['cam_height_rel'] = round(h, 3)
        rec['floor_ok'] = bool(h >= R['floor_margin'])
        if with_edge:
            rec['edge'] = PF.edge_score(geo, cam, photo, alpha, cv, tex, N768)['agree']
        return rec

    # 1) семейства: выбранная поза первой, дальше лучшие по оценке из пула, поиска и мультистарта, различающиеся по азимуту/подъёму
    pool = [{'cam': pick['cam'], 'score': pick.get('score', 0.0), 'src': 'pick'}]
    for c in sorted(list(cands) + list(ms_info.get('starts') or []), key=lambda t: -t.get('score', -9)):
        pool.append({'cam': c['cam'], 'score': c.get('score', 0.0), 'src': 'pool' if 'start_az' not in c else 'start'})
    fam = separate(pool, int(R['fam_k']), R['fam_sep_az'], R['fam_sep_el'])
    families = []
    for i, f in enumerate(fam):
        e = evaluate(f['cam'])
        e.update({'id': i, 'src': f['src'], 'is_pick': i == 0})
        families.append(e)
        log(f"  семейство {i}: az={e['cam']['az']:.0f} el={e['cam']['el']:.0f} d={e['cam']['d']:.2f} IoU(тр.) {e['iou_tri']} Chamfer {e['chamfer_px']} px BF1/2/4/8 {'/'.join(str(e['bf'][str(t)]) for t in R['bf_tols'])} "
            f"высота над полом {e['cam_height_rel']} {'' if e['floor_ok'] else 'ПОД ПОЛОМ'} кромки {e['edge']}")

    # 2) гипотеза yaw+180°: если среди семейств есть перевёрнутая — берём её, иначе локальный подбор из позы +180°
    flip_rec = next((f for f in families[1:] if is_flip_of(families[0]['cam'], f['cam'])), None)
    flip_src = 'family'
    if flip_rec is None:
        cam0 = dict(pick['cam'])
        cam0['az'] = (cam0['az'] + 180.0) % 360.0
        c, nit = PF.nm_two_stage(Pc, Mp, Mp_blur, n, cam0)
        flip_rec = evaluate(c)
        flip_rec.update({'id': 'flip', 'src': 'local+180', 'steps': nit, 'is_pick': False})
        flip_src = 'local+180'
    pk = families[0]
    flip = {'source': flip_src, **{k: flip_rec[k] for k in ('cam', 'score', 'iou_tri', 'chamfer_px', 'bf', 'edge', 'cam_height_rel', 'floor_ok')},
            'gap_score': round(pk['score'] - flip_rec['score'], 4), 'gap_bf2': round(pk['bf']['2'] - flip_rec['bf']['2'], 4), 'gap_edge': round(pk['edge'] - flip_rec['edge'], 4)}
    log(f"  yaw+180°: оценка {flip_rec['score']} (боевая {pk['score']}, разрыв {flip['gap_score']:+.4f}), BF2 {flip_rec['bf']['2']} (боевая {pk['bf']['2']}), кромки {flip_rec['edge']} (боевая {pk['edge']})")

    # 3) слабая перспектива: тот же подбор с прибитым d (≈ ортография), f пересчитан под тот же масштаб
    saved = PF.D_MIN
    try:
        PF.D_MIN = PF.D_MAX - 1.0
        cw = dict(pick['cam'])
        cw['f'] = cw['f'] * PF.D_MAX / cw['d']
        cw['d'] = PF.D_MAX
        cw, nit = PF.nm_two_stage(Pc, Mp, Mp_blur, n, cw)
    finally:
        PF.D_MIN = saved
    sw = PF.pose_score(PF.splat_mask(Pc, cw, n), Mp)
    gain = round(pk['score'] - sw['score'], 4)
    weak = {'cam': {k: round(float(v), 4) for k, v in cw.items()}, 'score': sw['score'], 'iou': sw['iou'], 'gain_free_over_weak': gain,
            'focal_distance_ambiguous': bool(gain < R['weak_gain_eps']), 'camera_model': 'weak_perspective' if gain < R['weak_gain_eps'] else 'perspective',
            'd_free': round(float(pick['cam']['d']), 3), 'dd_az': round(float(((cw['az'] - pick['cam']['az'] + 180) % 360) - 180), 2), 'dd_el': round(float(cw['el'] - pick['cam']['el']), 2)}
    log(f"  слабая перспектива: оценка {sw['score']} против свободной {pk['score']} (выигрыш свободной {gain:+.4f}) → {weak['camera_model']}, f и расстояние {'не различимы' if weak['focal_distance_ambiguous'] else 'различимы'}")

    out = {'version': R['version'], 'dry_run': True, 'families': families, 'flip': flip, 'weak': weak,
           'floor': {'pick_height_rel': pk['cam_height_rel'], 'pick_ok': pk['floor_ok'], 'under_floor': [f['id'] for f in families if not f['floor_ok']]}}
    out['choose'] = choose(families, R)
    return out
