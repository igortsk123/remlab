#!/usr/bin/env python3
"""T-20261119-112/2: проверка этапа 04-камера (план `paint-photo-fill-01`, «Проверка на каждом этапе», владелец TG 187).

Вход — папка прогона `pose_fit.py` (`pose.json`, `stage_loss.json`, `stages/render_view0/mask.png`) и фото. Пишет в `<out>/`:
  check.json — общий формат `tools/scout/paint_stage.py` (version 1, писатель — он один): stage `04-camera`; passed = IoU И miss И extra (всего кадра и нижней полосы):
               iou_silhouette (главная), miss («фото не закрыто формой»: доля силуэта фото вне формы), extra («форма вне фото»: доля силуэта формы вне фото), те же две — по нижней
               полосе (15 % высоты силуэта от низа: плита-подложка, ножки); пороги — `tools/scout/rules/camera-check.json`; edge_agree — справочно (пометка edge_below_ref);
               если в `<корень>/<sku>/02-prep/check.json` plate_found=true, а среза нет — камера unreliable (passed=false, причина в extra.unreliable_reason);
               в extra — camera, yaw, pairs, photo (не прошёл — товар идёт нынешним путём, fail-closed);
  frame.png  — «фото поверх рендера»: фото 50 % + рендер формы с камеры 50 %; красный контур — силуэт рендера, зелёный — силуэт фото.
  camera_check.py --run <out-run = <корень прогона>/<sku>> --photo <фото .rgba.png> [--view0 <рендер с камеры .png>] [--yaw N]
Папка этапа — `<корень>/<sku>/04-camera/` (sku = имя папки out-run, корень = её родитель), как у остальных этапов пути покраски.
Рендер: `--view0` (цепочка: `chain/s1-mv12/view0.png`); нет — силуэт формы заливается полупрозрачным красным.
`pairs` — число пар точек: у подбора по силуэту+кромкам их нет (null); поле для RoMa/PoseLib (следующий шаг плана).
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
import stage_loss as SL  # noqa: E402
import paint_stage as PS  # noqa: E402
import legs_check as LC  # noqa: E402
import silhouette_edge_angle as SEA  # noqa: E402

RULES_PATH = os.path.join(HERE, '..', '..', 'rules', 'camera-check.json')


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def silhouette_shares(S: np.ndarray, A: np.ndarray, strip_frac: float) -> dict:
    """Две доли несовпадения силуэтов (маски bool одной формы, S — форма с камеры, A — фото в кадре камеры).
    miss  — доля силуэта ФОТО, не закрытая формой (|A∖S| / |A|); extra — доля силуэта ФОРМЫ вне фото (|S∖A| / |S|).
    Отдельно по нижней полосе: строки от низа объединения S∪A, высота strip_frac × высота объединения. Пустое с одной стороны — 1,0 (не прятать: фото есть, формы нет — miss 1),
    пусто с обеих — 0."""
    S = np.asarray(S, bool)
    A = np.asarray(A, bool)
    if S.shape != A.shape:
        raise ValueError('маски разной формы')

    def sh(num_mask: np.ndarray, den_mask: np.ndarray, other: np.ndarray) -> float:
        den = int(den_mask.sum())
        if den == 0:
            return 1.0 if other.any() else 0.0
        return float(num_mask.sum()) / den

    U = S | A
    rows = np.flatnonzero(U.any(axis=1))
    if rows.size == 0:
        return {'miss': 0.0, 'extra': 0.0, 'miss_bottom': 0.0, 'extra_bottom': 0.0, 'strip_rows': None}
    y1 = int(rows[-1])
    h = y1 - int(rows[0]) + 1
    y0 = max(y1 - max(1, int(round(strip_frac * h))) + 1, 0)
    Sb, Ab = S[y0:y1 + 1], A[y0:y1 + 1]
    St, At = S[:y0], A[:y0]                                              # верх: всё выше нижней полосы (корпус)
    un = float((St | At).sum())
    iou_top = float((St & At).sum()) / un if un else None
    return {'miss': sh(A & ~S, A, S), 'extra': sh(S & ~A, S, A),
            'miss_bottom': sh(Ab & ~Sb, Ab, Sb), 'extra_bottom': sh(Sb & ~Ab, Sb, Ab), 'iou_top': iou_top, 'strip_rows': [y0, y1]}


def _boundary(m: np.ndarray) -> np.ndarray:
    import cv2
    mu = m.astype(np.uint8)
    return (mu > 0) & (cv2.erode(mu, np.ones((3, 3), np.uint8)) == 0)


def thin_metrics(S: np.ndarray, A: np.ndarray, rules: dict) -> dict:
    """Мерка тонкого предмета (rules `thin`, T-188/2). S — форма, A — фото в кадре камеры (bool). thin_share — доля пикселей маски ФОТО не глубже half_frac × высота силуэта фото от её края (EDT);
    eligible = thin_share ≥ share_min. precision — доля контура формы в пределах tau = tau_frac × высота от контура фото; recall — доля контура фото в пределах tau от контура формы;
    passed = eligible-независимо precision ≥ precision_min И recall ≥ recall_min (решение «спасать ли» — по eligible И passed в main)."""
    import cv2
    cfg = rules.get('thin') or {}
    S = np.asarray(S, bool)
    A = np.asarray(A, bool)
    rows = np.flatnonzero(A.any(axis=1))
    if rows.size == 0 or not S.any():
        return {'eligible': False, 'passed': False, 'thin_share': None, 'precision': 0.0, 'recall': 0.0, 'height_px': 0, 'tau_px': 0.0}
    hh = int(rows[-1] - rows[0] + 1)
    d_in = cv2.distanceTransform(A.astype(np.uint8), cv2.DIST_L2, 3)
    share = float((d_in[A] <= float(cfg['half_frac']) * hh).mean())
    bS, bA = _boundary(S), _boundary(A)
    dA = cv2.distanceTransform((~bA).astype(np.uint8), cv2.DIST_L2, 3)
    dS = cv2.distanceTransform((~bS).astype(np.uint8), cv2.DIST_L2, 3)
    tau = float(cfg['tau_frac']) * hh
    prec = float((dA[bS] <= tau).mean()) if bS.any() else 0.0
    rec = float((dS[bA] <= tau).mean()) if bA.any() else 0.0
    return {'eligible': bool(share >= float(cfg['share_min'])), 'passed': bool(prec >= float(cfg['precision_min']) and rec >= float(cfg['recall_min'])), 'thin_share': round(share, 4),
            'precision': round(prec, 4), 'recall': round(rec, 4), 'height_px': hh, 'tau_px': round(tau, 2)}


def shape_mismatch(iou: float, ms: dict | None, rules: dict) -> tuple[bool, dict]:
    """«Форма не совпала с фото, позой не лечится» (стул 13195: все 36 стартов мультистарта сходятся на IoU 0,69–0,71). Признак: мультистарт шёл, `shape_top_k` лучших стартов по оценке лежат в узком коридоре
    (разброс их IoU силуэта ≤ `shape_corridor_eps`) И итоговый IoU кадра ниже iou_min. Отличает «форму» (много разных поз упираются в один потолок) от «не нашли позу» (старты разбросаны).
    Мультистарта не было (хороший обычный подбор) → (False, {}). Такие товары — в список на перегенерацию формы."""
    if not ms or not ms.get('ran') or not ms.get('starts'):
        return False, {}
    k = int(rules.get('shape_top_k', 5))
    top = sorted(ms['starts'], key=lambda s: -s['score'])[:k]
    if len(top) < k:
        return False, {}
    ious = [float(s.get('iou_sil', s['iou'])) for s in top]          # IoU подбора ДО уточнения по кромкам (если записан)
    spread = max(ious) - min(ious)
    info = {'top_k': k, 'iou_spread': round(spread, 4), 'iou_best': round(max(ious), 4), 'eps': rules.get('shape_corridor_eps', 0.03)}
    return bool(spread <= info['eps'] and iou < rules['iou_min']), info


def bottom_shape_mismatch(shares: dict, coarse: bool, rules: dict) -> bool:
    """Форма низа не совпадает с фото (ножки: кресло 1167 — на фото два полоза, у формы четыре ножки), а корпус лёг: доли внизу (extra или miss) выше порога, маска фото внизу НЕ грубая,
    IoU верхней части (выше полосы) ≥ bottom_top_iou_min. Это отдельная причина в check.json (extra.bottom_shape_mismatch): этапы 05/07 не переносят фото на ножки такой формы."""
    if coarse or shares.get('iou_top') is None:
        return False
    low = shares['extra_bottom'] > rules['extra_bottom_max'] or shares['miss_bottom'] > rules['miss_bottom_max']
    return bool(low and shares['iou_top'] >= rules.get('bottom_top_iou_min', rules['iou_min']))


def bottom_mask_quality(rgb: np.ndarray, A: np.ndarray, strip_rows) -> dict:
    """Насколько можно верить нижней полосе фото-маски (комод 13224: ножки бледные, маска грубая блоками — extra/miss внизу шумят и НЕ повод двигать порог).
    thin_share — доля пикселей маски в полосе от (высота полосы × ширина силуэта фото); contrast — |яркость маски − яркость фона| в полосе (0…1; фон — не-маска той же полосы в ширине силуэта).
    Нет полосы/маски → None."""
    if not strip_rows:
        return {'thin_share': None, 'contrast': None}
    y0, y1 = strip_rows
    A = np.asarray(A, bool)
    cols = np.flatnonzero(A.any(axis=0))
    if cols.size == 0:
        return {'thin_share': None, 'contrast': None}
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    sub = A[y0:y1 + 1, x0:x1]
    col = np.asarray(rgb)[y0:y1 + 1, x0:x1].astype(np.float32)
    lum = 0.299 * col[..., 0] + 0.587 * col[..., 1] + 0.114 * col[..., 2]
    area = sub.size
    if area == 0 or not sub.any():
        return {'thin_share': 0.0, 'contrast': None}
    fg = float(lum[sub].mean())
    bg = float(lum[~sub].mean()) if (~sub).any() else fg
    return {'thin_share': round(float(sub.sum()) / area, 4), 'contrast': round(abs(fg - bg) / 255.0, 4)}


def white_plate(photo: np.ndarray, role: str, rules: dict) -> dict:
    """Метка ТИПА «белая плита стола на светлом фоне» (T-20261124-57, П1.160; паспорт «Таргет 80×80»): маска фото у такой плиты слабая, IoU 04 падает не из-за брака верха. Считается по RGBA фото (без позы и формы),
    всегда, прошёл 04 или нет. Применима только к ролям `white_plate.roles` (префикс роли каталога). Верхняя зона = верхние `zone_frac` высоты маски. `value` — доля почти белых пикселей маски в зоне (яркость ≥ lum_min,
    цветность ≤ chroma_max); `weak_edge` — доля границы маски в зоне, где |яркость внутри − снаружи| (окно win) < weak_contrast·255. would_flag: value ≥ share_min И weak_edge ≥ weak_min. Пишет только запись.
    → {applicable, would_flag, value, weak_edge, thr, why}."""
    from scipy import ndimage
    wp = rules.get('white_plate') or {}
    thr = [wp.get('share_min'), wp.get('weak_min')]

    def out(applicable: bool, why: str, value=None, weak=None, would=False) -> dict:
        return {'applicable': applicable, 'would_flag': bool(would), 'value': value, 'weak_edge': weak, 'thr': thr, 'why': why}
    if not any((role or '').startswith(x) for x in (wp.get('roles') or [])):
        return out(False, 'тип без плиты-столешницы (или роль не передана) — не применима')
    a = np.asarray(photo)
    m = a[..., 3] > 127
    if not m.any():
        return out(False, 'маска фото пуста')
    rgb = a[..., :3].astype(np.float32)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    chroma = rgb.max(-1) - rgb.min(-1)
    ys = np.nonzero(m.any(axis=1))[0]
    y0, y1 = int(ys[0]), int(ys[-1])
    zone = np.zeros_like(m)
    zone[y0:y0 + max(int((y1 - y0 + 1) * float(wp['zone_frac'])), 1)] = True
    mz = m & zone
    if not mz.any():
        return out(False, 'верхняя зона маски пуста')
    value = float((mz & (lum >= float(wp['lum_min'])) & (chroma <= float(wp['chroma_max']))).sum() / mz.sum())
    bw = (ndimage.binary_dilation(m, iterations=2) & ~ndimage.binary_erosion(m, iterations=2)) & zone
    if not bw.any():
        return out(True, 'граница верха не найдена', round(value, 3), None, False)
    win = int(wp['win'])
    mf, nf = m.astype(np.float32), (~m).astype(np.float32)
    li = ndimage.uniform_filter(np.where(m, lum, 0.0), win) / np.maximum(ndimage.uniform_filter(mf, win), 1e-3)
    lo = ndimage.uniform_filter(np.where(~m, lum, 0.0), win) / np.maximum(ndimage.uniform_filter(nf, win), 1e-3)
    weak = float((np.abs(li - lo)[bw] < float(wp['weak_contrast']) * 255.0).mean())
    would = value >= float(wp['share_min']) and weak >= float(wp['weak_min'])
    return out(True, ('белая плита на светлом фоне: белое %.2f, слабая граница %.2f' % (value, weak)) if would else '', round(value, 3), round(weak, 3), would)


def prep_plate_unreliable(root: str, sku: str) -> tuple[bool, str]:
    """02-prep: plate_found=true без среза (нет выходного файла и report.written ложно) → камера по такой форме ненадёжна (форма с плитой; IoU по силуэту плиту не видит).
    Нет check.json этапа 02-prep — не знаем, не флажим (False, '')."""
    c = PS.read_check(os.path.join(root, PS.safe_name(sku), '02-prep'))
    if not c:
        return False, ''
    pf = ((c.get('metrics') or {}).get('plate_found') or {}).get('value')
    if pf is None:
        pf = (c.get('extra') or {}).get('plate_found')
    if not pf:
        return False, ''
    rep = (c.get('extra') or {}).get('report') or {}
    cut = bool(c.get('outputs')) or bool(rep.get('written'))
    if cut:
        return False, ''
    return True, '02-prep: plate_found=true, среза нет — форма с плитой-подложкой, камера по ней ненадёжна'


def verdict(iou: float, shares: dict, edge: float | None, rules: dict, unreliable: str = '') -> tuple[bool, str]:
    """→ (ok, причина). Порядок причин: unreliable, IoU, miss/extra кадра, miss/extra нижней полосы. Кромки — только справочная пометка."""
    bad: list[str] = []
    if unreliable:
        bad.append(unreliable)
    if iou < rules['iou_min']:
        bad.append(f"IoU силуэта {iou:.3f} < {rules['iou_min']}")
    for k, lim, what in (('miss', 'miss_max', 'фото не закрыто формой'), ('extra', 'extra_max', 'форма вне фото'),
                         ('miss_bottom', 'miss_bottom_max', 'фото не закрыто формой внизу'), ('extra_bottom', 'extra_bottom_max', 'форма вне фото внизу')):
        if shares[k] > rules[lim]:
            bad.append(f"{what}: {k} {shares[k]:.3f} > {rules[lim]}")
    if bad:
        return False, '; '.join(bad) + ' — товар идёт нынешним путём'
    if edge is None:                                                # кромок нет (общая полоса < 16 px): не число и не «плохие кромки»
        return True, 'камера легла (внутренних кромок для сравнения нет: однотонное / тонкое)'
    return True, 'камера легла' + (f" (внутренние кромки {edge:.3f} < {rules['edge_ref']}: справочно, проверить глазами)" if edge < rules['edge_ref'] else '')


def vertical_convergence(photo: np.ndarray, pose: dict, rules: dict, cv: dict) -> dict:
    """Схождение вертикалей: фото (LSD внутри маски, pose_fit.vertical_axis) против камеры 04. κ = tan φ / f, φ = el − tilt — наклон оси камеры. delta_deg — разница схождения по ширине товара.
    Не измерено (мягкое, круглое, мало линий) → {measured: False, reason}. Порог отчёта report_deg — гипотеза, passed 04 не меняет."""
    R = rules.get('vertical_axis') or {}
    if not R.get('check_enabled', True):
        return {'measured': False, 'reason': 'выключено правилом vertical_axis.check_enabled'}
    try:
        import pose_fit as PF
        cam = pose['camera']
        info = PF.vertical_axis(photo, photo[..., 3] > 127, cv, R)
        if not info['measured']:
            return {'measured': False, 'reason': info['reason'], 'photo': info}
        phi = float(cam['el']) - PF.cam_tilt(cam)
        k_render = float(np.tan(np.radians(phi)) / float(cam['f']))
        delta = float(np.degrees((info['kappa'] - k_render) * info['w_frame']))
        rep = float(R.get('report_deg', 0.5))
        return {'measured': True, 'photo_kappa': info['kappa'], 'render_kappa': round(k_render, 5), 'delta_deg': round(delta, 2), 'photo_parallel': bool(info.get('parallel')),
                'report_deg': rep, 'over_report': bool(abs(delta) > rep), 'photo': info}
    except Exception as e:  # noqa: BLE001 — мерка не роняет этап 4
        return {'measured': False, 'reason': f'сбой мерки: {type(e).__name__}: {str(e)[:100]}'}


def front_edge_dx(photo: np.ndarray, pose: dict, rules: dict, cv: dict, out_dir: str) -> dict:
    """Стык «фронт|бок» (T-20261124-18, владелец TG 2571): front_edge_dx_px — проекция переднего вертикального угла фронтальной плоскости формы ↔ длинная вертикальная кромка фото,
    обе стороны, px фото (junction.front_edge); кадр-наложение junction.png. Не измерено (форма не коробчатая, нет габарита в pose.json, сбой) → {measured: False, reason} — не «прошёл»."""
    import junction as JN
    R = {**JN.DEFAULTS, **(rules.get('junction') or {})}
    if not R.get('check_enabled', True):
        return {'measured': False, 'reason': 'выключено правилом junction.check_enabled'}
    try:
        import cv2
        import pose_fit as PF
        fb = pose.get('form_box')
        box = JN.box_geometry(fb['lo'], fb['hi'], R) if fb else None
        tg = JN.photo_targets(photo, R)
        fe = JN.front_edge(PF, pose['camera'], box, cv, tg, R)
        cv2.imwrite(os.path.join(out_dir, 'junction.png'), cv2.cvtColor(JN.overlay(photo, tg, fe), cv2.COLOR_RGB2BGR))
        fe['over'] = bool(fe.get('measured') and fe['gap_px'] > R['active_gap_px'])
        fe['threshold_px'] = R['active_gap_px']
        return fe
    except Exception as e:  # noqa: BLE001 — мерка не роняет этап 4
        return {'measured': False, 'reason': f'сбой мерки: {type(e).__name__}: {str(e)[:100]}'}


def main() -> int:
    import cv2
    from PIL import Image
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--view0', default=None)
    ap.add_argument('--yaw', type=float, default=None)
    ap.add_argument('--role', default='', help='роль каталога (для метки white_plate; пусто — метка не применима)')
    a = ap.parse_args()
    import time
    t0 = time.time()
    run = a.run.rstrip('/')
    out = PS.stage_dir(os.path.dirname(run), os.path.basename(run), '04-camera')
    pose = json.load(open(os.path.join(a.run, 'pose.json'), encoding='utf-8'))
    sl = json.load(open(os.path.join(a.run, 'stage_loss.json'), encoding='utf-8'))
    reg = sl['registration']
    iou = float(reg['iou'])
    pe = pose['picked']['edge']
    no_edges = bool(pe.get('no_edges'))                                # edge_score при общей полосе < 16 px ставит заглушку agree = −1,0 и no_edges: это не оценка
    edge = None if no_edges else float(pe['agree'])
    rules = load_rules()
    root, sku = os.path.dirname(run), os.path.basename(run)
    unrel, unrel_why = prep_plate_unreliable(root, sku) if rules.get('plate_check', True) else (False, '')

    S = np.asarray(Image.open(os.path.join(a.run, 'stages', 'render_view0', 'mask.png')).convert('L')) > 127
    h, w = S.shape
    photo = SL.read_rgba(a.photo)
    P = np.array(reg['P'], np.float64).reshape(3, 3)
    ph = SL.warp_inv(photo[..., :3], P, (w, h))
    pa = SL.warp_inv((photo[..., 3] > 127).astype(np.uint8) * 255, P, (w, h), interp=cv2.INTER_NEAREST) > 127
    shares = silhouette_shares(S, pa, rules['strip_frac'])
    ok, reason = verdict(iou, shares, edge, rules, unrel_why)
    tm = thin_metrics(S, pa, rules) if (rules.get('thin') or {}).get('enabled') else None
    thin_rescue = bool(tm and not ok and tm['eligible'] and tm['passed'] and not unrel_why)      # тонкий предмет: площадная мерка провалена, контур лёг → годна (только спасает, не отнимает)
    if thin_rescue:
        th = rules['thin']
        ok = True
        reason = ('камера легла по контуру (тонкий предмет: доля тонкого %.2f ≥ %s; контур формы на контуре фото %.2f ≥ %s, контур фото покрыт %.2f ≥ %s; IoU площади %.3f для тонкого не мерка)'
                  % (tm['thin_share'], th['share_min'], tm['precision'], th['precision_min'], tm['recall'], th['recall_min'], iou))
    bq = bottom_mask_quality(ph, pa, shares['strip_rows'])
    coarse = bool(bq['thin_share'] is not None and bq['contrast'] is not None
                  and bq['thin_share'] < rules.get('coarse_thin_max', 0.3) and bq['contrast'] < rules.get('coarse_contrast_max', 0.35))
    coarse_note = 'низ: маска фото грубая (мало пикселей маски в нижней полосе, низкий контраст) — доли внизу шумят, порог под такие не подгонять' if coarse else ''
    if coarse_note:
        reason = reason + '; ' + coarse_note if not ok else reason + ' (' + coarse_note + ')'
    shm, shm_info = shape_mismatch(iou, pose.get('multistart'), rules)
    shm = bool(shm and not thin_rescue)
    if shm:
        reason = ('shape_mismatch: форма не совпадает с фото, позой не лечится (%d лучших из %d стартов в коридоре IoU %.3f–%.3f) — в список на перегенерацию формы, этап 6 не красит; '
                  % (shm_info['top_k'], len(pose['multistart']['starts']), shm_info['iou_best'] - shm_info['iou_spread'], shm_info['iou_best'])) + reason
        ok = False
    try:                                                           # угол прямых кромок силуэта рендер↔фото (T-20261124-18): только запись, passed не меняет (enforce=false)
        edge_angle = SEA.compare(S, pa, rules) if (rules.get('edge_angle') or {}).get('enabled', False) else {'measured': False, 'skip': 'выключено правилом edge_angle'}
    except Exception as e:  # noqa: BLE001 — мерка не роняет этап 4
        edge_angle = {'measured': False, 'skip': f'сбой мерки: {type(e).__name__}: {str(e)[:100]}'}
    vconv = vertical_convergence(photo, pose, rules, pose.get('canvas') or {'x0': float(P[0, 2]), 'y0': float(P[1, 2]), 'side': float(P[0, 0]) * w})                  # схождение вертикалей рендер↔фото (T-20261124-18): только запись, passed не меняет
    fedge = front_edge_dx(photo, pose, rules, pose.get('canvas') or {'x0': float(P[0, 2]), 'y0': float(P[1, 2]), 'side': float(P[0, 0]) * w}, out)     # стык фронт|бок: пишется всегда; ворота — только при junction.enforce
    if (rules.get('junction') or {}).get('enforce', False) and fedge.get('over'):
        reason = ('стык фронта: ребро формы ↔ кромка фото %s px (порог %s) — на фронте будет разрыв узора; ' % (fedge['dx_px'], fedge['threshold_px'])) + reason if not ok else ('стык фронта: ребро формы ↔ кромка фото %s px (порог %s); ' % (fedge['dx_px'], fedge['threshold_px'])) + reason
        ok = False
    wpl = white_plate(photo, a.role, rules) if (rules.get('white_plate') or {}).get('enabled', False) else None          # метка типа «белая плита» (T-20261124-57): только запись, passed не меняет; выключено — ключа в check.json нет
    legs = LC.legs_report(S, pa)                                    # ножки формы против фото (T-191/3): пишется в extra, passed не меняет — решение «ножкам фото не верим» принимает этап 06
    bsm = bottom_shape_mismatch(shares, coarse, rules) and not thin_rescue
    if bsm:
        reason = 'bottom_shape_mismatch: форма низа не совпадает с фото (ножки), корпус лёг (IoU верха %.3f) — фото на ножки не переносить; ' % shares['iou_top'] + reason
        ok = False
    if a.view0 and os.path.exists(a.view0):
        rend = np.asarray(Image.open(a.view0).convert('RGB'))
        if rend.shape[:2] != (h, w):
            rend = cv2.resize(rend, (w, h), interpolation=cv2.INTER_AREA)
    else:
        rend = np.zeros((h, w, 3), np.uint8)
        rend[S] = (255, 0, 0)
    gray = np.full((h, w, 3), 235, np.uint8)
    ph_bg = np.where(pa[..., None], ph, gray)                       # фон фото — светло-серый, не чёрный
    rend_bg = np.where(S[..., None], rend, gray)
    blend = (0.5 * ph_bg.astype(np.float32) + 0.5 * rend_bg.astype(np.float32)).astype(np.uint8)
    for m, col in ((S, (255, 0, 0)), (pa, (0, 200, 0))):
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(blend, cs, -1, col, 2)
    Image.fromarray(blend).save(os.path.join(out, 'frame.png'))

    def lim(name: str, key: str) -> dict:
        return {'value': round(shares[name], 4), 'threshold': rules[key], 'op': '<='}
    res = PS.write_check(out, '04-camera', os.path.basename(run), passed=ok,
                         metric={'name': 'iou_silhouette', 'value': round(iou, 4), 'threshold': rules['iou_min'], 'op': '>='},
                         metrics={'miss': lim('miss', 'miss_max'), 'extra': lim('extra', 'extra_max'),
                                  'miss_bottom': lim('miss_bottom', 'miss_bottom_max'), 'extra_bottom': lim('extra_bottom', 'extra_bottom_max'),
                                  'edge_agree': {'value': None if edge is None else round(edge, 4), **({'no_edges': True} if no_edges else {})}},
                         reason=reason if not ok else '', seconds=round(time.time() - t0, 1), outputs=['frame.png'] + (['junction.png'] if os.path.isfile(os.path.join(out, 'junction.png')) else []), frame='frame.png',
                         edge_ref_min=rules['edge_ref'], edge_below_ref=bool(edge is not None and edge < rules['edge_ref']), no_edges=no_edges, note=reason if ok else '', strip_rows=shares['strip_rows'], strip_frac=rules['strip_frac'],
                         bottom_mask_coarse=coarse, edge_angle=edge_angle, vertical_convergence=vconv, front_edge=fedge, az_sigma=pose.get('az_sigma') or {'applicable': None, 'value': None, 'reason': 'не считалась (rules az_sigma.enabled=false / POSE_AZ_SIGMA)'}, front_edge_dx_px=(fedge.get('dx_px') if fedge.get('measured') else None), bottom_mask=bq, bottom_shape_mismatch=bsm, **LC.extra_fields(legs), shape_mismatch=shm, shape_corridor=shm_info, regen_form=bool(shm), iou_top=None if shares['iou_top'] is None else round(shares['iou_top'], 4),
                         **({'white_plate': wpl} if wpl is not None else {}), bottom_top_iou_min=rules.get('bottom_top_iou_min', rules['iou_min']), thin=tm, thin_rescue=thin_rescue, unreliable=bool(unrel), unreliable_reason=unrel_why, rules_file='tools/scout/rules/camera-check.json',
                         camera=pose['camera'], yaw=a.yaw if a.yaw is not None else pose.get('yaw'), pairs=None, photo=a.photo, method=reg.get('method'),
                         textured=pose.get('textured'), frame_note='фото 50 % + рендер 50 %; красный контур — рендер формы, зелёный — фото')
    print(f"{'OK ' if res['passed'] else 'НЕТ'} IoU {iou:.3f} miss {shares['miss']:.3f}/{shares['miss_bottom']:.3f} extra {shares['extra']:.3f}/{shares['extra_bottom']:.3f} (всё/низ) кромки {'нет' if edge is None else format(edge, '.3f')} — {reason}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
