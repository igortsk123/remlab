#!/usr/bin/env python3
"""Стык «фронт|бок» (T-20261124-18; владелец 24.11, TG 2571: «на фронте не должно быть разрывов — фронт самое главное»).

Зачем. Силуэт при почти фронтальном виде не различает «боковина видна / нет» (камера внутри габарита по ширине: d·sin φ < ½ширины), и 04 выбирает позу
без боковины, хотя на фото бок 26 px — 06 кладёт полосу бока на фронт (пара 7, Монблан). Мерка не рендерит: вертикальные углы фронтальной плоскости
коробчатой формы проецируются камерой и сравниваются с длинными вертикальными кромками фото.

  box_geometry(lo, hi)                      → ось фронта (меньший горизонтальный размах = глубина), коробчатость (ширина/глубина ≥ min_aspect)
  photo_targets(photo)                      → контур и длинные вертикальные кромки фото (LSD), px фото
  front_edge(PF, cam, box, cv, tg, R)       → {measured, dx_px: {l, r}, kind, gap_px} — мерка для check 04 (`front_edge_dx_px`) и для «спасателя»
  rescue(PF, ...)                           → спасатель: если |dx| > active_gap_px — совместная подгонка az/el/d/f/cx/cy от семейств-кандидатов (цель: силуэт + стык);
                                              выбор — IoU не хуже поза−iou_drop_max и минимум стыка; нечем лечить камерой → «форма не та» (б)
  overlay(photo, tg, fe)                    → кадр-наложение: форма (красный) и кромка фото (зелёный), подписи dx
Неприменимо (форма не коробчатая, нет вертикальных кромок и нет контура) → measured False, «не измерено», не «прошёл»."""
from __future__ import annotations

import numpy as np

DEFAULTS = {'enabled': False, 'check_enabled': True, 'enforce': False, 'min_aspect': 1.3, 'window_frac': 0.15, 'min_edge_px': 6.0, 'min_len_frac': 0.3, 'active_gap_px': 3.0,
            'contour_extra_px': 2.0, 'iou_drop_max': 0.005, 'w_gap': 20.0, 'hinge_px': 2.0, 'az_range': 40.0, 'lnd_range': 1.8, 'max_starts': 16, 'good_iou_gap': 0.001,
            'grid_az': [-12.0, 12.0], 'grid_d': [2.0, 3.0, 5.0], 'max_points': 150000, 'interior_px': 6, 'interior_frac': 0.85, 'max_dyaw_deg': 60.0,
            'max_del_deg': 8.0, 'bottom_worse_max': 0.10, 'miss_bottom_max': None, 'extra_bottom_max': None}      # пороги низа — из camera-check.json (miss_bottom_max/extra_bottom_max), вносит вызывающий


def rules(R: dict | None = None) -> dict:
    return {**DEFAULTS, **(R or {})}


def box_geometry(lo, hi, R: dict | None = None) -> dict:
    p = rules(R)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    ext = hi - lo
    depth = 0 if ext[0] < ext[2] else 2
    width = 2 if depth == 0 else 0
    aspect = float(ext[width] / max(ext[depth], 1e-9))
    return {'boxy': bool(aspect >= p['min_aspect']), 'width_axis': width, 'depth_axis': depth, 'lo': lo, 'hi': hi, 'aspect': round(aspect, 3)}


def _interior(al: np.ndarray, x1: float, y1: float, x2: float, y2: float, p: dict) -> bool:
    """Кромка стыка — внутренняя: по обе стороны от неё маска предмета (фронт и бок). Ножка, контур, просвет — с одной стороны фон: это не стык фронта с боком."""
    H, W = al.shape
    k = 0
    m = 0
    off = int(p['interior_px'])
    for t in np.linspace(0.1, 0.9, 17):
        x, y = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < H and off <= xi < W - off:
            m += 1
            k += int(al[yi, xi - off] and al[yi, xi + off])
    return m >= 8 and k >= p['interior_frac'] * m


def photo_targets(photo: np.ndarray, R: dict | None = None) -> dict:
    """photo — RGBA (H, W, 4) uint8. Контур — медиана крайних точек строк в средней части; кромки — LSD по яркости на светлом фоне, длинные и вертикальные."""
    import cv2
    p = rules(R)
    al = photo[..., 3] > 127
    ys, xs = np.nonzero(al)
    hobj = int(ys.max() - ys.min() + 1)
    y0, y1 = int(ys.min() + 0.2 * hobj), int(ys.max() - 0.2 * hobj)
    sl, sr = [], []
    for y in range(y0, max(y0 + 1, y1), 4):
        a = np.nonzero(al[y])[0]
        if len(a) > 10:
            sl.append(a[0])
            sr.append(a[-1])
    a_ = photo[..., 3:4].astype(np.float32) / 255.0
    g = cv2.cvtColor((photo[..., :3].astype(np.float32) * a_ + 235.0 * (1 - a_)).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    segs = cv2.createLineSegmentDetector(cv2.LSD_REFINE_ADV).detect(g)[0]
    edges = []
    if segs is not None:
        for x1, y1_, x2, y2 in segs.reshape(-1, 4):
            L = float(np.hypot(x2 - x1, y2 - y1_))
            t = abs(np.degrees(np.arctan2(x2 - x1, y2 - y1_))) % 180
            if L >= p['min_len_frac'] * hobj and (t < 8 or t > 172) and _interior(al, x1, y1_, x2, y2, p):
                edges.append(float(0.5 * (x1 + x2)))
    return {'sil_l': float(np.median(sl)) if sl else float(xs.min()), 'sil_r': float(np.median(sr)) if sr else float(xs.max()), 'edges': sorted(edges), 'hobj': hobj,
            'y_top': float(ys.min()), 'y_bot': float(ys.max())}


def front_corners(PF, box: dict, cam: dict, cv: dict) -> tuple:
    """Фото-px x двух вертикальных углов фронтальной плоскости (по возрастанию) и y центра."""
    C = PF.cam_basis(cam['az'], cam['el'], cam['d'], PF.cam_tilt(cam))[0]
    da, wa = box['depth_axis'], box['width_axis']
    pfront = box['hi'][da] if C[da] > 0 else box['lo'][da]
    yc = 0.5 * (box['lo'][1] + box['hi'][1])
    P = np.zeros((2, 3))
    P[:, da] = pfront
    P[:, 1] = yc
    P[0, wa], P[1, wa] = box['lo'][wa], box['hi'][wa]
    x, y, _ = PF.project(P, cam)
    xs = cv['x0'] + x * cv['side']
    return (float(min(xs)), float(max(xs))), float(cv['y0'] + y.mean() * cv['side'])


def front_edge(PF, cam: dict, box: dict | None, cv: dict, tg: dict, R: dict | None = None) -> dict:
    """Мерка стыка. dx_px[l|r] = форма − цель, px фото (знак: + форма правее цели). Цель: ближайшая к контуру длинная вертикальная кромка фото в окне window_frac·ширины, иначе контур
    (бока на фото нет). gap_px = max по сторонам |dx|, у «контура» минус contour_extra_px (задний угол выступает за передний — естественно ≤ ~2 px)."""
    p = rules(R)
    if box is None:
        return {'measured': False, 'reason': 'нет габарита формы в pose.json (form_box)'}
    if not box['boxy']:
        return {'measured': False, 'reason': 'форма не коробчатая (ширина/глубина %.2f < %s)' % (box['aspect'], p['min_aspect'])}
    (xl, xr), _ = front_corners(PF, box, cam, cv)
    W = float(tg['sil_r'] - tg['sil_l'])
    if W <= 20:
        return {'measured': False, 'reason': 'ширина предмета на фото < 20 px'}
    out = {'measured': True, 'dx_px': {}, 'kind': {}, 'target_px': {}, 'form_px': {}}
    gaps = []
    for side, xf, sil in (('l', xl, tg['sil_l']), ('r', xr, tg['sil_r'])):
        if side == 'l':
            c = [e for e in tg['edges'] if sil + p['min_edge_px'] < e < sil + p['window_frac'] * W]
            tgt, kind = (c[0], 'кромка') if c else (sil, 'контур')
        else:
            c = [e for e in tg['edges'] if sil - p['window_frac'] * W < e < sil - p['min_edge_px']]
            tgt, kind = (c[-1], 'кромка') if c else (sil, 'контур')
        dx = xf - tgt
        out['dx_px'][side] = round(dx, 1)
        out['kind'][side] = kind
        out['target_px'][side] = round(tgt, 1)
        out['form_px'][side] = round(xf, 1)
        gaps.append(max(0.0, abs(dx) - (p['contour_extra_px'] if kind == 'контур' else 0.0)))
    out['gap_px'] = round(max(gaps), 1)
    out['width_px'] = round(W, 1)
    out['has_edge'] = bool(any(k == 'кромка' for k in out['kind'].values()))
    if not out['has_edge']:                                                        # нечего сверять: на фото нет внутренней вертикальной кромки (фронт без видимого бока, ножки, мягкое) — «не измерено», не «прошёл»
        return {'measured': False, 'reason': 'на фото нет внутренней вертикальной кромки стыка (фронт без видимого бока / ножки / мягкое)', 'dx_px_contour': out['dx_px']}
    return out


def _dyaw(a: float, b: float) -> float:
    """Угол между азимутами, 0…180°."""
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def pose_gate(cam0: dict, cam1: dict, sc0: dict, sc1: dict, R: dict | None = None) -> tuple:
    """Ворота замены позы (общие для спасателя стыка и шага 3; T-20261124-18, регресс пакета Salad 24.11): новая поза cam1 берётся, только если
    (1) не другая сторона: |Δaz| ≤ max_dyaw_deg; (2) подъём не больше max_del_deg: |Δel| ≤ max_del_deg; (3) низ не хуже: miss_bottom/extra_bottom новой не выше порогов гейта 04
    (miss_bottom_max/extra_bottom_max) И не хуже прежней больше чем на bottom_worse_max. sc — pose_score позы (miss_bottom, extra_bottom). → (ок, [причины отказа])."""
    p = rules(R)
    why = []
    dy = _dyaw(cam1['az'], cam0['az'])
    if dy > p['max_dyaw_deg']:
        why.append('другая сторона: |Δaz| %.0f° > %.0f°' % (dy, p['max_dyaw_deg']))
    de = abs(float(cam1['el']) - float(cam0['el']))
    if de > p['max_del_deg']:
        why.append('подъём камеры |Δel| %.1f° > %.1f°' % (de, p['max_del_deg']))
    for k in ('miss_bottom', 'extra_bottom'):
        lim = p[k + '_max']
        if lim is not None and sc1[k] > lim:
            why.append('низ: %s %.3f > порога %.2f' % (k, sc1[k], lim))
        elif sc1[k] > sc0[k] + p['bottom_worse_max']:
            why.append('низ хуже прежней: %s %.3f → %.3f (допуск +%.2f)' % (k, sc0[k], sc1[k], p['bottom_worse_max']))
    return (not why), why


def _starts(PF, pick_cam: dict, cands: list, p: dict) -> list:
    out, seen = [], set()

    def add(c):
        if _dyaw(c['az'], pick_cam['az']) > p['max_dyaw_deg']:
            return                                                                  # другая сторона (перёд↔зад, az+180°): решает flip_pick/выбор позы, не спасатель стыка
        k = (round(c['az'] / 5.0), round(float(c['d']), 0), round(c['el'] / 5.0))
        if k not in seen:
            seen.add(k)
            out.append(dict(c))
    add(pick_cam)
    for c in cands:
        add(c['cam'])
        if c.get('cam_sil'):
            add(c['cam_sil'])
    for d0 in p['grid_d']:
        for da in p['grid_az']:
            add({**pick_cam, 'az': (pick_cam['az'] + da) % 360, 'd': d0, 'f': pick_cam['f'] * d0 / pick_cam['d']})
    return out[: p['max_starts']]


def rescue(PF, V: np.ndarray, pick: dict, cands: list, box: dict, tg: dict, Mp: np.ndarray, n: int, cv: dict, R: dict | None = None, log=print, apply: bool = True) -> tuple:
    """Спасатель стыка → (pick, info). Включается только при gap_px > active_gap_px у выбранной позы (иначе камера побитово та же). Совместная подгонка 6 параметров Нелдер–Мидом
    от семейств-кандидатов: цель 2·(1 − IoU силуэта) + w_gap·max(0, gap − hinge)/ширина (шарнир: у цели стык не давит на IoU). Выбор: IoU не хуже позы − iou_drop_max и gap ≤ active_gap_px,
    среди них — max IoU; (а) лечится камерой — применено; (б) не лечится — «форма не та»: камера прежняя, info['healable']=False.
    apply=False — только оценка (info), поза не меняется."""
    from scipy.optimize import minimize
    p = rules(R)
    W = max(float(tg['sil_r'] - tg['sil_l']), 1.0)
    cam0 = pick['cam']
    fe0 = front_edge(PF, cam0, box, cv, tg, p)
    info = {'measured': bool(fe0.get('measured')), 'before': fe0, 'applied': False, 'healable': None, 'tried': 0}
    if not fe0.get('measured'):
        info['reason'] = fe0.get('reason', 'не измерено')
        return pick, info
    if fe0['gap_px'] <= p['active_gap_px']:
        info['reason'] = 'стык в норме (%.1f px ≤ %s) — камера не тронута' % (fe0['gap_px'], p['active_gap_px'])
        info['healable'] = True
        return pick, info
    Pc = V[:: max(1, len(V) // int(p['max_points']))]
    iou0 = PF.iou(PF.splat_mask(Pc, cam0, n), Mp)
    sc0 = PF.pose_score(PF.splat_mask(Pc, cam0, n), Mp)                         # низ прежней позы — для ворот pose_gate
    steps = np.array([8.0, 3.0, 0.4, 0.2, 0.02, 0.02])
    results = []
    for k, c in enumerate(_starts(PF, cam0, cands, p)):
        v0 = PF._vec(c)
        lo = v0 + np.array([-p['az_range'], -10, -p['lnd_range'], -1.0, -0.08, -0.08])
        hi = v0 + np.array([p['az_range'], 10, p['lnd_range'], 1.0, 0.08, 0.08])

        def f(v, lo=lo, hi=hi):
            if np.any(v < lo) or np.any(v > hi) or not (PF.D_MIN <= np.exp(v[2]) <= PF.D_MAX):
                return 5.0
            cm = PF._cam(v)
            i_ = PF.iou(PF.splat_mask(Pc, cm, n), Mp)
            fe = front_edge(PF, cm, box, cv, tg, p)
            return 2.0 * (1 - i_) + p['w_gap'] * max(0.0, fe['gap_px'] - p['hinge_px']) / W
        sim = np.vstack([v0] + [v0 + np.eye(6)[i] * steps[i] for i in range(6)])
        res = minimize(f, v0, method='Nelder-Mead', options={'initial_simplex': sim, 'maxiter': 900, 'xatol': 1e-3, 'fatol': 1e-6})
        cm = PF._cam(res.x)
        fe = front_edge(PF, cm, box, cv, tg, p)
        io = PF.iou(PF.splat_mask(Pc, cm, n), Mp)
        gok, gwhy = pose_gate(cam0, cm, sc0, PF.pose_score(PF.splat_mask(Pc, cm, n), Mp), p)
        results.append({'cam': cm, 'iou': round(io, 4), 'gap_px': fe['gap_px'], 'fe': fe, 'start': k, 'gate_ok': gok, 'gate_why': gwhy})
        if gok and fe['gap_px'] <= p['active_gap_px'] and io >= iou0 - p['good_iou_gap']:
            break                                                                  # не хуже прежней и стык в норме — дальше не ищем (время)
    info['tried'] = len(results)
    ok = [r for r in results if r['gap_px'] <= p['active_gap_px'] and r['iou'] >= iou0 - p['iou_drop_max'] and r['gate_ok']]       # ворота: сторона, подъём, низ (pose_gate)
    gate_refused = [r['gate_why'] for r in results if not r['gate_ok'] and r['gap_px'] <= p['active_gap_px']]
    best_any = min(results, key=lambda r: (r['gap_px'], -r['iou']))
    info['iou_before'] = round(iou0, 4)
    info['best_attempt'] = {'cam': best_any['cam'], 'iou': best_any['iou'], 'gap_px': best_any['gap_px']}
    if not ok:
        info['healable'] = False
        if gate_refused:
            info['gate_refused'] = gate_refused[0]            # стык лечился бы, но ворота не пустили: остаётся базовая поза
        info['reason'] = ('не лечится камерой: лучший стык %.1f px при IoU %.4f (прежний %.4f, допуск −%s) — форма не та (глубина/пропорции не дают боковины нужной ширины)'
                          % (best_any['gap_px'], best_any['iou'], iou0, p['iou_drop_max']))
        log('стык фронта: ' + info['reason'])
        return pick, info
    r = max(ok, key=lambda r: r['iou'])
    info['healable'] = True
    info['after'] = r['fe']
    info['iou_after'] = r['iou']
    info['cam_before'] = dict(cam0)
    log('стык фронта: %.1f → %.1f px, IoU %.4f → %.4f, az %.1f→%.1f d %.2f→%.2f (%d стартов)' % (fe0['gap_px'], r['gap_px'], iou0, r['iou'], cam0['az'], r['cam']['az'], cam0['d'], r['cam']['d'], len(results)))
    if not apply:
        info['reason'] = 'вхолостую: лечится камерой, поза не меняется'
        return pick, info
    info['applied'] = True
    return {**pick, 'cam': r['cam'], 'iou': r['iou'], 'junction': info}, info


def overlay(photo: np.ndarray, tg: dict, fe: dict) -> np.ndarray:
    """Кадр-наложение: фото на светло-сером, форма (красные вертикали — углы фронта), кромка/контур фото (зелёные), подписи dx; обрезано по предмету."""
    import cv2
    a_ = photo[..., 3:4].astype(np.float32) / 255.0
    img = (photo[..., :3].astype(np.float32) * a_ + 235.0 * (1 - a_)).astype(np.uint8).copy()
    y0, y1 = int(tg['y_top']), int(tg['y_bot'])
    x0 = int(max(0, tg['sil_l'] - 0.1 * (tg['sil_r'] - tg['sil_l'])))
    x1 = int(min(img.shape[1], tg['sil_r'] + 0.1 * (tg['sil_r'] - tg['sil_l'])))
    for e in tg['edges']:
        cv2.line(img, (int(e), y0), (int(e), y1), (255, 200, 0), 1)
    if fe.get('measured'):
        for s in ('l', 'r'):
            cv2.line(img, (int(round(fe['target_px'][s])), y0), (int(round(fe['target_px'][s])), y1), (0, 200, 0), 2)
            cv2.line(img, (int(round(fe['form_px'][s])), y0), (int(round(fe['form_px'][s])), y1), (255, 0, 0), 2)
            cv2.putText(img, '%s dx %+.1f' % (fe['kind'][s][:3], fe['dx_px'][s]), (int(fe['form_px'][s]) + 4, y0 + 24 + (30 if s == 'r' else 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 0, 0), 2)
    else:
        cv2.putText(img, 'не измерено', (x0 + 10, y0 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (90, 90, 90), 2)
    return img[max(0, y0 - 10):y1 + 10, x0:x1]
