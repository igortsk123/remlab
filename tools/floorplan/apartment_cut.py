"""Вырезать нашу квартиру из листа (T-20261126-98/4, проба 2 → в бой за флагом, решение директора 26.11). По ВЫДЕЛЕНИЮ на листе:
серая заливка квартиры / красный контур / жирный контур / поле вокруг плана залито цветом (голубое). Выделения нет — лист как есть (пометка).
Снаружи маски — белый, кадр обрезается по маске. Флаг `FP_CUT_APT=1`, по умолчанию ВЫКЛ.

Правила (дефекты кадров 9583744 и krasnodar-14769532 → на все листы с выделением):
  • к выделенной квартире присоединяются примыкающие незалитые зоны, если они очерчены тонкой линией (не стеной) и в них есть подпись (≥3 знака) —
    балкон «(1,37)»; автопроверка: подписи внутри выбранного + присоединённого до/после (`labels_sel` == `labels_out`);
  • выемка в контуре, где цветная метка на стене совпала с цветом поля, закрывается цветом стены, не фоном; автопроверка: число выемок до/после (`notches_before` → `notches_after` = 0).

    cut_bgr(bgr) → (bgr, info)          # info['status'] 'cut'|'mark'|'off'; info['transform'] = {'box': [x0,y0,x1,y1], 'scale': 1.0, 'rot': 0.0, 'src': [W,H]}
    cut_sheet(pil_rgb) → (pil_rgb, info) # то, что зовёт pipeline.prepare(); без флага — тот же объект
Обратное преобразование для привязки ответа к исходному листу: x_src = x_cut + x0, y_src = y_cut + y0 (масштаб 1, поворота нет).
Только OpenCV/numpy. Пороги заданы до счёта (`etazhi-walls/vhod/ozhidanie-vyrezka.md`)."""
import os

import cv2
import numpy as np

SHARE = (0.08, 0.90)         # доля маски в листе


def flag_cut() -> bool:
    return os.environ.get('FP_CUT_APT', '0') == '1'


def _inside_from_barrier(barrier):
    """barrier — линии контура (255). → маска «внутри» = всё, что не достижимо от края листа, плюс сам контур"""
    inv = (barrier == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    outside = np.isin(lab, list(border - {0})) & (inv > 0)
    return (~outside).astype(np.uint8) * 255


def _fill_holes(m):
    return _inside_from_barrier(m)


FILL_MAX = 0.35   # серая заливка больше этой доли листа — пол всего плана застройщика (samara-10758856/869: 0,47), не выделение; настоящие 0,19 (kazan-9583744)


def d_fill(bgr):
    """серая плоская заливка квартиры (не касается краёв листа, снаружи светлее)"""
    H, W = bgr.shape[:2]
    L = max(H, W)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cand = ((hsv[..., 1] < 30) & (g >= 100) & (g <= 215)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    per = 2 * (H + W)
    comps = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA] / (H * W)
        if a < 0.004:
            continue
        comp = lab == i
        touch = comp[0].sum() + comp[-1].sum() + comp[:, 0].sum() + comp[:, -1].sum()
        if touch > 0.08 * per:
            continue
        vals = g[comp]
        if 1.4826 * np.median(np.abs(vals - np.median(vals))) > 10:     # робастный разброс: подписи и линии внутри заливки не мешают
            continue
        comps.append((a, i, float(np.median(vals))))
    if not comps:
        return None, {'reason': 'плоской серой заливки нет'}
    a0, i0, med = max(comps)
    if not (0.03 <= a0 <= FILL_MAX):
        return None, {'reason': f'крупнейшая заливка {a0:.2f} листа вне 0,03…{FILL_MAX}'}
    keep = [i for a, i, m in comps if abs(m - med) <= 10]           # заливка рвётся стенами/дверями/подписями на куски одного тона — берём все
    a = sum(a_ for a_, i, m in comps if i in keep)
    if a > FILL_MAX:
        return None, {'reason': f'заливка в сумме {a:.2f} листа > {FILL_MAX} — это цвет пола всего плана, а не выделение нашей квартиры среди соседних'}
    comp = np.isin(lab, keep).astype(np.uint8) * 255
    raw_n = int((comp > 0).sum())
    hole_ratio = float((_fill_holes(comp) > 0).sum() / max(raw_n, 1))
    if hole_ratio > 1.5:
        return None, {'reason': f'это кольцо стен, а не заливка квартиры (внутри пустоты ×{hole_ratio:.1f} от серого)', 'hole_ratio': round(hole_ratio, 2)}
    w = max(6, int(0.012 * L))
    se = lambda k: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))   # noqa: E731
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, se(4 * w))       # склеить куски через стены/двери
    comp = cv2.dilate(comp, se(int(1.8 * w)))
    comp = _fill_holes(comp)
    ring = np.concatenate([g[:5].ravel(), g[-5:].ravel(), g[:, :5].ravel(), g[:, -5:].ravel()])
    if float(np.median(ring)) - med < 30:
        return None, {'reason': f'снаружи не светлее заливки ({np.median(ring):.0f} против {med:.0f})'}
    hsv_ = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    raw = (hsv_[..., 1] < 30) & (np.abs(g.astype(np.int16) - med) <= 10)
    solid = float(raw[comp > 0].sum() / max(int((comp > 0).sum()), 1))
    if solid < 0.5:
        return None, {'reason': f'серое — это стены (заливки {solid:.2f} от маски < 0,5), не заливка квартиры', 'solid': round(solid, 2)}
    if float((comp > 0).mean()) > 0.70:
        return None, {'reason': 'заливка занимает почти весь лист — вырезать нечего'}
    return comp, {'fill_gray': round(med), 'fill_share': round(a, 3), 'solid': round(solid, 2)}


def d_color_contour(bgr):
    """красный насыщенный контур → замкнуть → внутри"""
    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red = (((hsv[..., 0] <= 6) | (hsv[..., 0] >= 170)) & (hsv[..., 1] >= 35) & (hsv[..., 2] <= 215)).astype(np.uint8) * 255
    px = int(red.sum() / 255)
    thick_px = int((cv2.erode(red, np.ones((5, 5), np.uint8)) > 0).sum())
    if px >= 0.0008 * H * W and (px > 0.03 * H * W or thick_px > 0.25 * px):
        return None, {'reason': f'красное — заливка/толстые пятна, а не тонкий контур ({px} px, толстого {thick_px / max(px, 1):.2f})', 'red_px': px}
    if px < 0.0008 * H * W:
        return None, {'reason': f'красного контура нет ({px} px)'}
    n_, lab_, st_, _ = cv2.connectedComponentsWithStats(cv2.dilate(red, np.ones((5, 5), np.uint8)), connectivity=8)
    big_ = max((st_[j, cv2.CC_STAT_WIDTH] * st_[j, cv2.CC_STAT_HEIGHT] for j in range(1, n_)), default=0)
    if big_ < 0.2 * H * W:
        return None, {'reason': 'красное — россыпь, одной линии вокруг квартиры нет', 'red_px': px}
    for k in (5, 9, 15, 25, 41, 61):
        bar = cv2.morphologyEx(cv2.dilate(red, np.ones((3, 3), np.uint8)), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        m = _inside_from_barrier(bar)
        sh = float((m > 0).mean())
        if 0.15 <= sh <= SHARE[1]:
            return m, {'red_px': px, 'close': k}
    return None, {'reason': f'красный контур не замкнулся (доля маски {sh:.2f})', 'red_px': px}


def d_bold_contour(bgr):
    """жирный контур при тонких остальных линиях → замкнуть → внутри"""
    H, W = bgr.shape[:2]
    L = max(H, W)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ink = ((g.astype(np.float32) < cv2.GaussianBlur(g, (0, 0), 25).astype(np.float32) - 45)).astype(np.uint8) * 255
    d = max(5, int(round(0.0045 * L)))
    bold = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d)))
    ink_n, bold_n = int((ink > 0).sum()), int((bold > 0).sum())
    if ink_n == 0 or bold_n == 0:
        return None, {'reason': 'жирных линий нет'}
    r = bold_n / ink_n
    if r > 0.60:
        return None, {'reason': f'жирного много ({r:.2f} чернил) — это стены, а не контур', 'bold_ratio': round(r, 2)}
    n, lab, st, _ = cv2.connectedComponentsWithStats(bold, connectivity=8)
    mx = st[1:, cv2.CC_STAT_AREA].max()
    keep = [j for j in range(1, n) if st[j, cv2.CC_STAT_AREA] >= 0.15 * mx]       # контур на фото рвётся на куски — берём все крупные
    big = np.isin(lab, keep).astype(np.uint8) * 255
    ys, xs = np.where(big > 0)
    bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
    if bw * bh < 0.2 * H * W:
        return None, {'reason': f'жирная фигура мала ({bw}×{bh}) для контура квартиры', 'bold_ratio': round(r, 2)}
    sh = 0.0
    for k in (9, 15, 25):
        bar = cv2.morphologyEx(big, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        m = _inside_from_barrier(bar)
        sh = float((m > 0).mean())
        if SHARE[0] <= sh <= SHARE[1]:
            other = (bold > 0) & (cv2.dilate(big, np.ones((2 * d + 1, 2 * d + 1), np.uint8)) == 0) & (m > 0)   # жирное внутри, кроме самого контура
            inb = float(other.sum() / max(bold_n, 1))
            if inb > 0.15:
                return None, {'reason': f'жирное и внутри ({inb:.2f}) — стены, а не контур', 'bold_ratio': round(r, 2)}
            return m, {'bold_ratio': round(r, 2), 'close': k, 'bold_inside': round(inb, 3)}
    return None, {'reason': f'жирный контур не замкнулся (доля маски {sh:.2f})', 'bold_ratio': round(r, 2)}


def d_outer_fill(bgr):
    """поле вокруг плана залито одним насыщенным цветом (голубое) → план = всё, что не поле"""
    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = max(3, int(0.01 * min(H, W)))
    ring = np.concatenate([hsv[:m].reshape(-1, 3), hsv[-m:].reshape(-1, 3), hsv[:, :m].reshape(-1, 3), hsv[:, -m:].reshape(-1, 3)])
    sat = ring[:, 1] > 60
    if sat.mean() < 0.7:
        return None, {'reason': f'по краю нет сплошного цветного поля ({sat.mean():.2f} насыщенных)'}
    hm = np.median(ring[sat, 0])
    if np.abs(ring[sat, 0].astype(int) - hm).mean() > 6:
        return None, {'reason': 'поле по краю разноцветное'}
    dh = np.abs(hsv[..., 0].astype(int) - hm)
    field = ((np.minimum(dh, 180 - dh) <= 8) & (hsv[..., 1] > 40)).astype(np.uint8)
    n, lab = cv2.connectedComponents(field, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
    outside = np.isin(lab, list(border))
    mk = (~outside).astype(np.uint8) * 255
    mk = cv2.morphologyEx(mk, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    sh = float((mk > 0).mean())
    if not (0.2 <= sh <= 0.98):
        return None, {'reason': f'доля плана {sh:.2f} вне 0,2…0,98'}
    return mk, {'field_hue': int(hm)}


DETECTORS = [('заливка', d_fill), ('цветной контур', d_color_contour), ('жирный контур', d_bold_contour), ('заливка снаружи', d_outer_fill)]


def _ink(g):
    return g.astype(np.float32) < cv2.GaussianBlur(g, (0, 0), 25).astype(np.float32) - 35


def _text_blobs(g, L):
    """знаки подписей: тёмные компактные связные пятна размером с цифру → список (cx, cy)"""
    ink = _ink(g).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i in range(1, n):
        w, h, a = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT], st[i, cv2.CC_STAT_AREA]
        if 0.006 * L <= h <= 0.04 * L and w <= 0.05 * L and a >= 0.1 * w * h:
            out.append((float(cen[i][0]), float(cen[i][1])))
    return out


def _wall_notches(g, mask, k):
    """выемки контура шире 4 px и не шире k, у которых края — стена (тёмное): метка на стене, а не вход/эркер. → (метки, список номеров)"""
    close = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    diff = ((close > 0) & (mask == 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
    wall = (g < 130) & (mask > 0)
    idx = []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 4:
            continue
        x, y, w, h = (int(st[i, c]) for c in range(4))
        p = k
        sub = (lab[max(y - p, 0):y + h + p, max(x - p, 0):x + w + p] == i).astype(np.uint8)
        ring = (cv2.dilate(sub, np.ones((7, 7), np.uint8)) > 0) & (mask[max(y - p, 0):y + h + p, max(x - p, 0):x + w + p] > 0)
        if ring.sum() and wall[max(y - p, 0):y + h + p, max(x - p, 0):x + w + p][ring].mean() >= 0.4:
            idx.append(i)
    return lab, idx


def _wall_marks(bgr, mask):
    """цветные метки на стене (кружок, значок): насыщенные компактные пятна, у которых вокруг — стена (тёмное). → маска пятен (с каймой)"""
    H, W = bgr.shape[:2]
    L = max(H, W)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = ((hsv[..., 1] > 150) & (hsv[..., 2] > 60)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sat, connectivity=8)
    wall = cv2.morphologyEx((g < 130).astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0   # стена, не тонкие линии и подписи
    out = np.zeros((H, W), np.uint8)
    for i in range(1, n):
        x, y, w, h, a = (int(st[i, c]) for c in range(5))
        if a < 6 or max(w, h) > 0.025 * L or max(w, h) > 2.0 * min(w, h) + 2:
            continue
        comp = (lab == i).astype(np.uint8)
        ring = (cv2.dilate(comp, np.ones((11, 11), np.uint8)) > 0) & (comp == 0)
        if int(wall[ring].sum()) < 12:
            continue
        out[cv2.dilate(comp, np.ones((5, 5), np.uint8)) > 0] = 255
    return out


def close_notches(bgr, mask):
    """правило (б): цветная метка на стене (совпала с цветом поля — выемка в контуре) → заливаем цветом стены, не фоном.
    → (маска, bgr с закрашенным, выемок до, после, закрашено меток); выемка = дыра контура шире 4 px и не шире 0,03·L, у краёв которой стена"""
    L = max(bgr.shape[:2])
    k = max(9, int(0.03 * L)) | 1
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, idx0 = _wall_notches(g, mask, k)
    before = len(idx0)
    img = bgr.copy()
    out = mask.copy()
    marks = _wall_marks(bgr, mask)
    wallpx = (g < 130) & (marks == 0) & ((cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1]) < 120)
    n, mlab = cv2.connectedComponents(marks, connectivity=8)
    painted = 0
    for i in range(1, n):
        comp = (mlab == i).astype(np.uint8)
        ring = (cv2.dilate(comp, np.ones((15, 15), np.uint8)) > 0) & wallpx
        if ring.any():
            img[comp > 0] = np.median(bgr[ring], axis=0).astype(np.uint8)
            out[comp > 0] = 255
            painted += 1
    lab, idx = _wall_notches(g, out, k)               # что осталось — закрываем замыканием, цветом соседней стены
    wall = (g < 130) & (out > 0)
    for i in idx:
        comp = (lab == i).astype(np.uint8)
        ring = (cv2.dilate(comp, np.ones((7, 7), np.uint8)) > 0) & (out > 0)
        px = bgr[ring & wall] if (ring & wall).any() else bgr[ring]
        if len(px):
            img[comp > 0] = np.median(px, axis=0).astype(np.uint8)
        out[comp > 0] = 255
    _, idx2 = _wall_notches(g, out, k)
    return out, img, before, len(idx2), painted


def apply_mask(bgr, mask):
    H, W = bgr.shape[:2]
    out = np.full_like(bgr, 255)
    out[mask > 0] = bgr[mask > 0]
    ys, xs = np.where(mask > 0)
    mg = int(0.025 * max(H, W))
    x0, x1, y0, y1 = max(xs.min() - mg, 0), min(xs.max() + mg, W), max(ys.min() - mg, 0), min(ys.max() + mg, H)
    return out[y0:y1, x0:x1], [int(x0), int(y0), int(x1), int(y1)]


def cut_bgr(bgr):
    """→ (bgr, info). status: 'cut' | 'mark' (выделения нет или автопроверка не прошла — лист как есть)"""
    H, W = bgr.shape[:2]
    info = {'status': 'mark', 'why': {}}
    for name, fn in DETECTORS:
        m, inf = fn(bgr)
        if m is None:
            info['why'][name] = inf.get('reason', '')
            continue
        m2 = m
        m3, img, nb, na, painted = close_notches(bgr, m2)
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        L = max(H, W)
        blobs = _text_blobs(g, L)
        sel = sum(1 for cx, cy in blobs if m2[int(cy), int(cx)] > 0)
        sheet, box = apply_mask(img, m3)
        out_n = len(_text_blobs(cv2.cvtColor(sheet, cv2.COLOR_BGR2GRAY), L))
        info.update({'method': name, 'mask_share': round(float((m3 > 0).mean()), 3), 'detector': inf,
                     'notches_before': nb, 'notches_after': na, 'marks_painted': painted, 'labels_sel': sel, 'labels_out': out_n})
        if na > 0 or out_n < sel - max(1, round(0.03 * sel)):
            info['status'] = 'mark'
            info['why'][name] = f'автопроверка: выемок после {na}, подписей {sel} → {out_n} — не режу'
            return bgr, info
        info['status'] = 'cut'
        info['transform'] = {'box': box, 'scale': 1.0, 'rot': 0.0, 'src': [W, H]}
        return sheet, info
    return bgr, info


def cut_sheet(sheet, flags=None):
    """PIL RGB → (PIL RGB, info) по флагу FP_CUT_APT; выключено / выделения нет / сбой — тот же объект."""
    if not (flag_cut() if flags is None else bool(flags.get('cut'))):
        return sheet, {'status': 'off'}
    from PIL import Image
    try:
        bgr = cv2.cvtColor(np.asarray(sheet.convert('RGB')), cv2.COLOR_RGB2BGR)
        out, info = cut_bgr(bgr)
    except Exception as e:  # noqa: BLE001 — вырезка не должна ронять разбор: лист как есть
        return sheet, {'status': 'error', 'why': {'error': repr(e)[:200]}}
    if info['status'] != 'cut':
        return sheet, info
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), info


def source_point(steps, x, y):
    """точка на листе-входе разбора (x, y) → точка на исходном листе: шаги входа `source['inputTransform']` разворачиваются с конца."""
    p = np.array([float(x), float(y), 1.0])
    for st in reversed(steps or []):
        if st["op"] == "crop":
            k = st.get("scale", 1.0)
            p = np.array([p[0] / k + st["box"][0], p[1] / k + st["box"][1], 1.0])
        elif st["op"] in ("rectify", "deskew"):
            q = np.linalg.inv(np.array(st["H"], np.float64)) @ p
            p = q / q[2]
    return float(p[0]), float(p[1])
