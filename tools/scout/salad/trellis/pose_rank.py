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
    """Выбор позы из семейств (только при `--rank-pick`): среди поз НЕ под полом и НЕ зеркальных боевой (yaw+180°) — лучшая по `pose_score`; ничья в пределах tie_score — по Boundary-F(2 px) и меньшему Chamfer; боевая меняется, только если выигрыш Boundary-F ≥ choose.bf_gain и Chamfer не хуже на choose.chamfer_tol_px (пороги пробные, в rules).
    Возвращает {'index': i, 'changed': bool, 'why': str}; если все под полом — остаётся первая (выбранная боевая)."""
    ok = [i for i, f in enumerate(families) if f['floor_ok']]
    if not ok:
        return {'index': 0, 'changed': False, 'why': 'все под полом — остаётся боевая'}
    C = R['choose']
    # зеркальное семейство (yaw+180° боевой позы) НЕ выбираем: Boundary-F и Chamfer не различают перёд и зад (ничья по контуру), решает блок orientation, а не контур
    base = families[0].get('cam')
    flips = [i for i in ok if i != 0 and base is not None and families[i].get('cam') is not None and is_flip_of(base, families[i]['cam'], C['flip_tol'])]
    pool = [i for i in ok if i not in flips]
    if not pool:
        return {'index': 0, 'changed': False, 'why': f'не под полом только зеркальные семейства ({len(flips)}) — остаётся боевая'}
    best = max(families[i]['score'] for i in pool)
    tie = [i for i in pool if families[i]['score'] >= best - R['tie_score']]
    i = max(tie, key=lambda j: (families[j]['bf']['2'], -(families[j]['chamfer_px'] or 1e9)))
    if i != 0 and 0 in pool:
        a, b = families[0], families[i]
        # меняем боевую позу только при заметном выигрыше по Boundary-F и без ухудшения Chamfer: иначе смена на пустом месте
        if b['bf']['2'] - a['bf']['2'] < C['bf_gain'] or (b['chamfer_px'] or 1e9) > (a['chamfer_px'] or 1e9) + C['chamfer_tol_px']:
            return {'index': 0, 'changed': False, 'why': f'не под полом: {len(ok)} из {len(families)}; зеркальных пропущено {len(flips)}; выигрыш Boundary-F/Chamfer мал или Chamfer хуже — остаётся боевая'}
    return {'index': i, 'changed': i != 0, 'why': f'не под полом: {len(ok)} из {len(families)}; зеркальных пропущено {len(flips)}; ничья по оценке: {len(tie)}; выбрана по Boundary-F(2 px) и Chamfer'}


# ---------- с геометрией (вызывается из pose_fit) ----------

def _common(PF, geo: dict, cam: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, n: int):
    """Рендер формы с текстурой с камеры и фото в кадре камеры → (рендер uint8, фото uint8, маска формы, маска фото)."""
    import a1_tone as A
    import stage_loss as SL
    r = PF.render_persp(geo, cam, n)
    S = r['mask']
    P = PF.canvas_P(cv, n)
    A_fr = SL.warp_inv(alpha.astype(np.float32), P, (n, n)) > 0.5
    ph = np.clip(SL.warp_inv(photo[..., :3], P, (n, n)), 0, 255).astype(np.uint8)
    img = A.render_view0(tex, {'uv': r['uv'], 'mask': S})
    return img, ph, S, A_fr


def lab_diff(a: np.ndarray, b: np.ndarray, cm: np.ndarray, blur_px: float = 0.0) -> dict | None:
    """Разность Lab двух кадров (uint8 RGB) по маске cm после вычета общего сдвига тона. blur_px > 0 — разность сглаживается внутри маски (нормированная свёртка): сдвиг мелкого узора
    на пиксель не считается цветовой ошибкой. → {de_med, de_p75} или None, если маска пуста."""
    import cv2
    import pattern_metric as PM
    cm = np.asarray(cm, bool)
    if int(cm.sum()) < 64:
        return None
    d = PM.rgb_to_lab(a).astype(np.float32) - PM.rgb_to_lab(b).astype(np.float32)
    if blur_px > 0:
        w = cm.astype(np.float32)
        k = max(int(round(blur_px * 3)) * 2 + 1, 3)
        den = cv2.GaussianBlur(w, (k, k), blur_px)
        d = np.stack([cv2.GaussianBlur(d[..., c] * w, (k, k), blur_px) / np.maximum(den, 1e-3) for c in range(3)], axis=-1)
    d = d[cm]
    d = d - np.median(d, axis=0, keepdims=True)
    de = np.sqrt((d ** 2).sum(axis=1))
    return {'de_med': round(float(np.median(de)), 3), 'de_p75': round(float(np.percentile(de, 75)), 3)}


def _erode(M: np.ndarray, px: int) -> np.ndarray:
    import cv2
    return cv2.erode(np.asarray(M, bool).astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)).astype(bool) if px > 0 else np.asarray(M, bool)


def photo_color_diff(PF, geo: dict, cam: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, n: int = 768, erode_px: int = 3, blur_frac: float = 1 / 128) -> dict | None:
    """Цвет рендера формы (с текстурой) против фото в общей области кадра: разность Lab после вычета общего сдвига тона (рендер без света, фото со светом), попиксельная и
    сглаженная (σ = blur_frac·n) → {de_med, de_p75, de_blur_med, area}; меньше — лучше. Нет текстуры → None."""
    if tex is None:
        return None
    img, ph, S, A_fr = _common(PF, geo, cam, photo, alpha, cv, tex, n)
    cm = _erode(S & A_fr, erode_px)
    a = lab_diff(ph, img, cm)
    if a is None:
        return {'de_med': None, 'de_p75': None, 'de_blur_med': None, 'area': 0.0}
    b = lab_diff(ph, img, cm, blur_px=blur_frac * n)
    return {**a, 'de_blur_med': b['de_med'], 'area': round(float(cm.sum()) / max(int(A_fr.sum()), 1), 3)}


def orientation_cues(PF, geo: dict, cam: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, n: int = 768, blur_frac: float = 1 / 128) -> dict:
    """Сигналы «перед или зад» для одной позы: цвет (photo_color_diff) и геометрия фасада (кромки карты нормалей рендера против кромок фото — без текстуры, `edge_score(tex=None)`)."""
    c = photo_color_diff(PF, geo, cam, photo, alpha, cv, tex, n, blur_frac=blur_frac)
    g = PF.edge_score(geo, cam, photo, alpha, cv, None, n)
    return {'color': c, 'geom_edge': g['agree'], 'geom_no_edges': g['no_edges']}


def render_pair_diff(PF, geo: dict, cam_a: dict, cam_b: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, n: int = 768, erode_px: int = 3,
                     blur_frac: float = 1 / 128) -> dict | None:
    """Чем отличаются ДВА рендера — с позы cam_a и с позы cam_b (например, выбранной и yaw+180°) — друг от друга в общей области формы:
    • цвет (с текстурой): разность Lab, сглаженная; нет текстуры → de_med None;
    • форма (без текстуры): средний модуль разности затенения по нормалям, 0–255 (`shade_mad`) — видит ручки, щели, рельеф фасада, даже если предмет однотонный;
    • mask_iou — совпадение масок.
    Все три малы → у предмета «лицо» и «изнанка» неотличимы (стол, ваза): какой стороной положить фото, не важно. Определяется по виду, а не по названию или категории."""
    ra, rb = PF.render_persp(geo, cam_a, n), PF.render_persp(geo, cam_b, n)
    Sa, Sb = ra['mask'], rb['mask']
    cm = _erode(Sa & Sb, erode_px)
    if int(cm.sum()) < 64:
        return None
    ga, gb = PF.shade_view(ra)[..., 0].astype(np.float32), PF.shade_view(rb)[..., 0].astype(np.float32)
    out = {'de_med': None, 'de_p75': None, 'shade_mad': round(float(np.abs(ga - gb)[cm].mean()), 2), 'mask_iou': round(float((Sa & Sb).sum()) / max(int((Sa | Sb).sum()), 1), 4)}
    if tex is not None:
        ia, _, _, _ = _common(PF, geo, cam_a, photo, alpha, cv, tex, n)
        ib, _, _, _ = _common(PF, geo, cam_b, photo, alpha, cv, tex, n)
        d = lab_diff(ia, ib, cm, blur_px=blur_frac * n)
        if d is not None:
            out['de_med'], out['de_p75'] = d['de_med'], d['de_p75']
    return out


def _vote(gap, thr: float) -> str:
    if gap is None:
        return 'нет'
    return 'за' if gap >= thr else ('против' if gap <= -thr else '—')


def orientation_votes(gap_sil, cues_pick: dict, cues_flip: dict | None, R: dict, dino: dict | None = None) -> dict:
    """Голоса сигналов за выбранную позу против yaw+180°: силуэт (разрыв оценки), цвет (de сглаженный: у +180° − у выбранной), геометрия (кромки: у выбранной − у +180°).
    Порог цвета — max(color_rel·de выбранной, color_abs); геометрии — geom_gap; силуэта — sil_gap. Все — в `rules/pose-rank.json` → orientation."""
    O = R['orientation']
    out = {'silhouette': _vote(gap_sil, O['sil_gap']), 'color': 'нет', 'geom': 'нет', 'dino': 'нет', 'gap': {'silhouette': gap_sil, 'color': None, 'geom': None, 'dino': None}}
    if dino and dino.get('pick') is not None and dino.get('flip') is not None:        # DINOv2: косинус CLS с фото у выбранной позы минус у +180° (pose_dino; считается отдельным шагом)
        g = round(dino['pick'] - dino['flip'], 4)
        out['gap']['dino'] = g
        out['dino'] = _vote(g, R['dino']['gap'])
    if not cues_flip:
        return out
    pc, fc = (cues_pick.get('color') or {}), (cues_flip.get('color') or {})
    if pc.get('de_blur_med') is not None and fc.get('de_blur_med') is not None:
        g = round(fc['de_blur_med'] - pc['de_blur_med'], 3)
        out['gap']['color'] = g
        out['color'] = _vote(g, max(O['color_rel'] * pc['de_blur_med'], O['color_abs']))
    if cues_pick.get('geom_edge') is not None and cues_flip.get('geom_edge') is not None:
        g = round(cues_pick['geom_edge'] - cues_flip['geom_edge'], 4)
        out['gap']['geom'] = g
        out['geom'] = _vote(g, O['geom_gap'])
    return out


def orientation_verdict(votes: dict, pair: dict | None, R: dict) -> dict:
    """Итог «перед или зад» (ТЕНЬ: метка и журнал, поза и `projection_safe` не меняются):
      symmetric        — рендеры с выбранной позы и с yaw+180° почти не отличаются ни по форме (shade_mad < sym_shade), ни по цвету (de_med < sym_de, если текстура есть),
                         маски совпадают (≥ sym_iou): сторона не важна, отказа нет;
      front_silhouette — силуэт выбранной позы лучше на ≥ sil_gap и ни цвет, ни геометрия не против;
      front_cues       — силуэт ничья, цвет и геометрия оба «за» (need_votes = 2; при 1 — хватит любого «за» без «против»);
      flip_suggested   — силуэт хуже на ≥ sil_gap и ни цвет, ни геометрия не «за»; либо ничья и все ответившие сигналы (≥ need_votes) «против»;
      ambiguous        — иначе, в т.ч. сигналы спорят между собой (ORIENTATION_AMBIGUOUS).  ambiguous=True только у `ambiguous`."""
    O = R['orientation']
    need = int(O['need_votes'])
    cues = [votes['color'], votes['geom'], votes.get('dino', 'нет')]      # DINO — необязательный третий голос: нет данных → «нет», на счёт не влияет
    pro, con = cues.count('за'), cues.count('против')
    sym = False
    if pair is not None and pair.get('mask_iou', 0.0) >= O['sym_iou'] and pair.get('shade_mad') is not None and pair['shade_mad'] < O['sym_shade']:
        sym = pair.get('de_med') is None or pair['de_med'] < O['sym_de']
    if sym:
        v = 'symmetric'
    elif votes['silhouette'] == 'за':
        v = 'front_silhouette' if con == 0 else 'ambiguous'
    elif votes['silhouette'] == 'против':
        v = 'flip_suggested' if pro == 0 else 'ambiguous'
    elif pro >= need and con == 0:
        v = 'front_cues'
    elif con >= need and pro == 0:
        v = 'flip_suggested'
    else:
        v = 'ambiguous'
    return {'verdict': v, 'ambiguous': v == 'ambiguous', 'code': 'ORIENTATION_AMBIGUOUS' if v == 'ambiguous' else None, 'votes': {k: votes[k] for k in ('silhouette', 'color', 'geom', 'dino') if k in votes},
            'gap': votes['gap'], 'pair': pair, 'shadow': True}


def rank_poses(PF, geo: dict, pick: dict, cands: list, ms_info: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, Mp: np.ndarray, n: int, log=print, R: dict | None = None) -> dict:
    """Блок `rank` для pose.json (см. шапку). PF — модуль pose_fit (передаётся, чтобы не импортировать его циклом)."""
    import time
    import stage_loss as SL
    t_start = time.time()
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

    # 2б) перёд или зад (ТЕНЬ): сигналы цвета и геометрии у выбранной позы и у yaw+180°, вид двух рендеров друг против друга, голоса и итог
    cues_pick = orientation_cues(PF, geo, pick['cam'], photo, alpha, cv, tex, N768, R['orientation']['blur_frac'])
    cues_flip = orientation_cues(PF, geo, flip_rec['cam'], photo, alpha, cv, tex, N768, R['orientation']['blur_frac'])
    pair = render_pair_diff(PF, geo, pick['cam'], flip_rec['cam'], photo, alpha, cv, tex, N768, blur_frac=R['orientation']['blur_frac'])
    votes = orientation_votes(flip['gap_score'], cues_pick, cues_flip, R)
    orient = orientation_verdict(votes, pair, R)
    orient['cues'] = {'pick': cues_pick, 'flip': cues_flip}
    log(f"  перёд/зад (тень): {orient['verdict']} · голоса силуэт/цвет/геометрия {votes['silhouette']}/{votes['color']}/{votes['geom']} · рендеры друг от друга ΔE {pair and pair['de_med']}")

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

    out = {'version': R['version'], 'dry_run': True, 'families': families, 'flip': flip, 'orientation': orient, 'weak': weak,
           'floor': {'pick_height_rel': pk['cam_height_rel'], 'pick_ok': pk['floor_ok'], 'under_floor': [f['id'] for f in families if not f['floor_ok']]}}
    out['choose'] = choose(families, R)
    out['sec'] = round(time.time() - t_start, 1)               # цена ранжирования на товар (семейства, +180°, сигналы), без базового подбора
    return out
