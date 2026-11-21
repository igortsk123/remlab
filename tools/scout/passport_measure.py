#!/usr/bin/env python3
"""Код ЗАМЕРА сторожей паспортов типов — К1 (потеря изголовья кровати) и К3 (однотонность подушки). План mesh-type-passports-01, задача 2.

Переехал из разового `measure.py` замера T-20261120-151/1 в репозиторий, чтобы замер воспроизводился. ТОЛЬКО ПИКСЕЛИ → ЧИСЛА: решений здесь нет,
вердикт по числам и порогам паспорта — `cutout_guards.py` (политика). Без изображений не работает. Зависимости: numpy, opencv (cv2); без torch и сети.

К1 (кровать): `hb_back` — высота изголовья над линией матраса (только подтип, не вердикт); потеря изголовья — сравнение ИСХОДНИКА с вырезкой: чужое (ΔE00 от
фона ≥ `loss_de`) над/у верха вырезки вне её. Смещение вырезки в кадре — `object_xy` из `cutout_sync.crop_box`; нет (старые строки) — `register` (matchTemplate с
маской альфы); не совместилось (ошибка > `register_err_max`) — исход `ambiguous`, не `ok`.
К3 (подушка): однотонность по Lab a,b без света (p95 ΔE00 на внутренней области, второй цветовой кластер, цветовые границы) — мягкая метка, не гейт.

  python tools/scout/passport_measure.py --selftest
"""
import sys

import numpy as np

try:
    import cv2
except ImportError:  # без cv2 модуль не работает; ловится сторожем (исход guard_error), а не падением импорта у соседей
    cv2 = None


# ------------------------------------------------------------------ цвет
def de00(l1, a1, b1, l2, a2, b2):
    """CIEDE2000 (поэлементно, numpy)."""
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)))
    a1p = (1 + g) * a1
    a2p = (1 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1 = np.degrees(np.arctan2(b1, a1p)) % 360
    h2 = np.degrees(np.arctan2(b2, a2p)) % 360
    dl = l2 - l1
    dc = c2p - c1p
    dh = h2 - h1
    dh = np.where(dh > 180, dh - 360, dh)
    dh = np.where(dh < -180, dh + 360, dh)
    dh = np.where(c1p * c2p == 0, 0, dh)
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2)
    lm = (l1 + l2) / 2
    cmp_ = (c1p + c2p) / 2
    hm = np.where(np.abs(h1 - h2) > 180, (h1 + h2 + 360) / 2, (h1 + h2) / 2) % 360
    hm = np.where(c1p * c2p == 0, h1 + h2, hm)
    t = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm))
         + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    sl = 1 + 0.015 * (lm - 50) ** 2 / np.sqrt(20 + (lm - 50) ** 2)
    sc = 1 + 0.045 * cmp_
    sh = 1 + 0.015 * cmp_ * t
    dth = 30 * np.exp(-(((hm - 275) / 25) ** 2))
    rc = 2 * np.sqrt(cmp_ ** 7 / (cmp_ ** 7 + 25 ** 7))
    rt = -np.sin(np.radians(2 * dth)) * rc
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh))


def lab(rgb):
    """uint8 RGB → float Lab (L 0..100, a,b ±128)."""
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)


# ------------------------------------------------------------------ К1
def k1_hb_back(cut_rgba) -> dict:
    """Высота изголовья над линией матраса: hb_back = (y линии по 80 % макс. ширины светлого постельного − верх вырезки) / высота вырезки.
    Светлого постельного нет — hb_back = None, note 'no_bright' (линию не найти). Подтип `hb_low` решает политика по порогу паспорта."""
    a = np.asarray(cut_rgba)
    al = a[:, :, 3] > 128
    ys = np.where(al.any(1))[0]
    if not len(ys):
        return {'H': 0, 'W': 0, 'hb_back': None, 'note': 'empty'}
    y0, y1 = int(ys.min()), int(ys.max())
    H = y1 - y0 + 1
    hsv = cv2.cvtColor(a[:, :, :3], cv2.COLOR_RGB2HSV)
    bright = al & (hsv[:, :, 1] < 0.20 * 255) & (hsv[:, :, 2] > 0.68 * 255)
    c = bright.sum(1).astype(float)
    c[:y0] = 0
    mx = c.max()
    W = int(al.any(0).sum())
    if mx < 0.08 * al.sum(1).max():
        return {'H': int(H), 'W': W, 'hb_back': None, 'note': 'no_bright'}
    yb = int(np.where(c >= 0.8 * mx)[0][0])
    return {'H': int(H), 'W': W, 'hb_back': round((yb - y0) / H, 4), 'note': ''}


def register(src_rgb, cut_rgba):
    """Смещение вырезки в кадре: matchTemplate по RGB с маской альфы (вырезка — обрезка кадра без масштаба). → (x, y, ошибка на пиксель) | None."""
    a = np.asarray(cut_rgba)
    al = (a[:, :, 3] > 128).astype(np.uint8)
    t = a[:, :, :3]
    s = np.asarray(src_rgb)
    if t.shape[0] > s.shape[0] or t.shape[1] > s.shape[1] or not al.any():
        return None
    m3 = np.repeat(al[:, :, None], 3, 2).astype(np.float32)
    res = cv2.matchTemplate(s.astype(np.float32), t.astype(np.float32), cv2.TM_SQDIFF, mask=m3)
    res = np.nan_to_num(res, nan=1e30, posinf=1e30)
    mn = np.unravel_index(np.argmin(res), res.shape)
    return int(mn[1]), int(mn[0]), float(res[mn] / max(1, al.sum() * 3))


def _err_at(src_rgb, cut_rgba, x, y) -> float | None:
    """Ошибка совмещения в ЗАДАННОМ месте (когда `object_xy` известен): средний квадрат расхождения RGB по непрозрачным пикселям."""
    a = np.asarray(cut_rgba)
    s = np.asarray(src_rgb)
    h, w = a.shape[:2]
    if x < 0 or y < 0 or y + h > s.shape[0] or x + w > s.shape[1]:
        return None
    al = a[:, :, 3] > 128
    if not al.any():
        return None
    d = (s[y:y + h, x:x + w].astype(np.float32) - a[:, :, :3].astype(np.float32)) ** 2
    return float(d[al].sum() / max(1, al.sum() * 3))


def k1_loss(src_rgb, cut_rgba, object_xy=None, loss_de: float = 2.5, register_err_max: float = 40.0, top: int = 3) -> dict:
    """Потеря изголовья: исходник против вырезки. Метрики (все ЧИСЛА, вердикт — политика): registered, reg_err, object_xy_src ('crop'|'matched'),
    lost_share (всё чужое в полосе / площадь bbox), comps — до `top` крупнейших связных областей [{area_share, width_share}] (доля bbox и доля ширины).
    Область — «чужое» (ΔE00 от медианного фона по рамке кадра ≥ `loss_de`) над верхней границей вырезки и в верхней трети, вне вырезки, в столбцах кровати ±20 % W."""
    a = np.asarray(cut_rgba)
    s = np.asarray(src_rgb)
    al = a[:, :, 3] > 128
    if object_xy is not None:
        ox, oy = int(object_xy[0]), int(object_xy[1])
        err = _err_at(s, a, ox, oy)
        how = 'crop'
        if err is None or err > register_err_max:
            # боевой путь: смещение известно точно, но совпадения нет (цветокоррекция цепочки) — пробуем найти самим
            rg = register(s, a)
            if rg is not None and (err is None or rg[2] < err):
                ox, oy, err = rg
                how = 'matched'
    else:
        rg = register(s, a)
        ox = oy = err = None
        how = 'matched'
        if rg is not None:
            ox, oy, err = rg
    if err is None or err > register_err_max or not al.any():
        return {'registered': False, 'reg_err': None if err is None else round(err, 1), 'object_xy_src': how, 'lost_share': None, 'comps': []}
    Hs, Ws = s.shape[:2]
    full = np.zeros((Hs, Ws), bool)
    full[oy:oy + al.shape[0], ox:ox + al.shape[1]] = al
    ys = np.where(al.any(1))[0]
    y0 = oy + int(ys.min())
    H = int(ys.max() - ys.min() + 1)
    xs = np.where(full.any(0))[0]
    x0, x1 = int(xs.min()), int(xs.max())
    W = x1 - x0 + 1
    b = max(4, int(0.04 * min(Hs, Ws)))
    border = np.concatenate([s[:b].reshape(-1, 3), s[-b:].reshape(-1, 3), s[:, :b].reshape(-1, 3), s[:, -b:].reshape(-1, 3)])
    bgc = np.median(border, 0)
    lb = lab(bgc.reshape(1, 1, 3).astype(np.uint8))[0, 0]
    ls = lab(s)
    de = de00(lb[0], lb[1], lb[2], ls[:, :, 0], ls[:, :, 1], ls[:, :, 2])
    nonbg = de >= float(loss_de)
    near = cv2.dilate(full.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    lost = nonbg & ~near
    band = np.zeros_like(lost)
    ytop = max(0, y0 - int(0.35 * H))
    band[ytop:y0 + int(0.35 * H), max(0, x0 - int(0.2 * W)):x1 + int(0.2 * W) + 1] = True
    lost &= band
    lost = cv2.morphologyEx(lost.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    n, _lb, st, _c = cv2.connectedComponentsWithStats(lost.astype(np.uint8), 8)
    bbox_area = max(1, W * H)
    comps = sorted(({'area_share': round(float(st[i, cv2.CC_STAT_AREA]) / bbox_area, 4),
                     'width_share': round(float(st[i, cv2.CC_STAT_WIDTH]) / max(1, W), 4)} for i in range(1, n)),
                   key=lambda c: -c['area_share'])[:top]
    return {'registered': True, 'reg_err': round(float(err), 1), 'object_xy_src': how,
            'lost_share': round(float(lost.sum()) / bbox_area, 4), 'comps': comps}


def k1_measure(src_rgb, cut_rgba, object_xy=None, loss_de: float = 2.5, register_err_max: float = 40.0) -> dict:
    """Все числа К1 одной кровати: hb_back + потеря изголовья."""
    m = k1_hb_back(cut_rgba)
    m.update(k1_loss(src_rgb, cut_rgba, object_xy, loss_de, register_err_max))
    return m


# ------------------------------------------------------------------ К3
def k3_measure(cut_rgba, edge_erode: float = 0.03) -> dict:
    """Однотонность подушки: срез края `edge_erode` короткой стороны (мин. 6 px), вычесть плавное поле света (σ = 5 % ширины), остаток только по Lab a,b.
    Числа: p95_total (цвет против медианы), p95_coarse (масштаб ≥ 1 % ширины = рисунок), p95_fine (мельче = микротекстура), cluster2 (доля второго цветового
    кластера при разнесении ≥ 6 ΔE), cluster_sep, boundary (доля крупных цветовых границ 1–5 % ширины). Детерминированно (зерно k-means фиксировано)."""
    a = np.asarray(cut_rgba)
    al = a[:, :, 3] > 128
    h, w = al.shape
    short = min(h, w)
    er = max(6, int(round(float(edge_erode) * short)))
    inner = cv2.erode(al.astype(np.uint8), np.ones((2 * er + 1, 2 * er + 1), np.uint8)) > 0
    if inner.sum() < 400:
        return {'note': 'tiny_inner'}
    L = lab(a[:, :, :3])
    m = inner.astype(np.float32)

    def nblur(ch, s):
        num = cv2.GaussianBlur(ch * m, (0, 0), s)
        den = cv2.GaussianBlur(m, (0, 0), s) + 1e-6
        return num / den
    mL = float(np.median(L[:, :, 0][inner]))
    ma = float(np.median(L[:, :, 1][inner]))
    mb = float(np.median(L[:, :, 2][inner]))
    A, B = L[:, :, 1], L[:, :, 2]
    d_total = de00(mL, ma, mb, mL, A, B)[inner]
    s1 = max(1.0, 0.01 * w)
    A1 = nblur(A, s1)
    B1 = nblur(B, s1)
    d_coarse = de00(mL, ma, mb, mL, A1, B1)[inner]
    d_fine = de00(mL, A1, B1, mL, A, B)[inner]
    pts = np.stack([A[inner], B[inner]], 1).astype(np.float32)
    if len(pts) > 20000:
        pts = pts[np.random.RandomState(7).choice(len(pts), 20000, replace=False)]
    cv2.setRNGSeed(7)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, lab_, cen = cv2.kmeans(pts, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    sep = float(de00(mL, cen[0, 0], cen[0, 1], mL, cen[1, 0], cen[1, 1]))
    share2 = float(min((lab_ == 0).mean(), (lab_ == 1).mean())) if sep >= 6 else 0.0
    A5 = nblur(A, 0.05 * w)
    B5 = nblur(B, 0.05 * w)
    d_bound = de00(mL, A1, B1, mL, A5, B5)[inner]
    return {'p95_total': round(float(np.percentile(d_total, 95)), 3), 'p95_coarse': round(float(np.percentile(d_coarse, 95)), 3),
            'p95_fine': round(float(np.percentile(d_fine, 95)), 3), 'cluster2': round(share2, 4), 'cluster_sep': round(sep, 2),
            'boundary': round(float((d_bound > 4).mean()), 4), 'note': ''}


# ------------------------------------------------------------------ самотест
def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    if cv2 is None:
        print('  ✗ нет opencv (pip install opencv-python-headless)')
        return 1
    rng = np.random.RandomState(1)
    # ΔE00: известные пары (Sharma 2005): (50, 2.6772, -79.7751) ↔ (50, 0, -82.7485) = 2.0425
    ok('ΔE00 по таблице Sharma (2,0425)', abs(float(de00(50.0, 2.6772, -79.7751, 50.0, 0.0, -82.7485)) - 2.0425) < 1e-3)
    # синтетическая кровать: белое изголовье на светло-сером фоне, вырезка теряет верхнюю полосу изголовья
    H, W = 300, 400
    bg = np.full((H, W, 3), 235, np.uint8)
    src = bg.copy()
    src[60:120, 100:300] = (250, 250, 250)         # изголовье (светлее фона на ΔE ≈ 4)
    src[120:240, 80:320] = (120, 90, 60)           # тело
    full = np.zeros((H, W), np.uint8)
    full[120:240, 80:320] = 255                    # вырезка без изголовья
    cut = np.dstack([src[120:240, 80:320], full[120:240, 80:320]])
    m = k1_measure(src, cut, object_xy=(80, 120), loss_de=2.5)
    ok('К1: изголовье потеряно — найдена крупная область (≥ 4 % bbox, ≥ 20 % ширины)',
       m['registered'] and m['comps'] and m['comps'][0]['area_share'] >= 0.04 and m['comps'][0]['width_share'] >= 0.2)
    m8 = k1_measure(src, cut, object_xy=(80, 120), loss_de=8.0)
    ok('К1: тот же случай при ΔE 8 — не ловится (белое на белом)', not m8['comps'] or m8['comps'][0]['area_share'] < 0.04)
    cut_ok = np.dstack([src[60:240, 80:320], np.where(np.any(src[60:240, 80:320] != 235, axis=2), 255, 0).astype(np.uint8)])
    ok('К1: вырезка с изголовьем — потери нет', (lambda r: r['registered'] and (not r['comps'] or r['comps'][0]['area_share'] < 0.04))(
        k1_measure(src, cut_ok, object_xy=(80, 60))))
    mm = k1_measure(src, cut, object_xy=None)
    ok('К1: без object_xy смещение находится совмещением и даёт ту же область', mm['registered'] and mm['object_xy_src'] == 'matched'
       and mm['comps'] and mm['comps'][0]['area_share'] >= 0.04)
    other = rng.randint(0, 255, (H, W, 3)).astype(np.uint8)
    mo = k1_measure(other, cut, object_xy=None)
    ok('К1: несовместимый кадр → не совместилось (ambiguous у политики)', mo['registered'] is False)
    # К3: однотонная и пёстрая подушка
    h, w = 200, 200
    plain = np.full((h, w, 3), (180, 60, 70), np.uint8)
    plain = np.clip(plain.astype(int) + rng.randint(-3, 4, plain.shape), 0, 255).astype(np.uint8)
    alpha = np.full((h, w), 255, np.uint8)
    k3p = k3_measure(np.dstack([plain, alpha]))
    pat = plain.copy()
    pat[::40, :] = (30, 160, 60)
    pat[:, ::40] = (30, 160, 60)
    pat[60:140, 60:140] = (240, 220, 40)
    k3t = k3_measure(np.dstack([pat, alpha]))
    ok('К3: однотонная — p95 < 4, второго кластера нет', k3p['p95_total'] < 4 and k3p['cluster2'] < 0.05)
    ok('К3: с рисунком — p95 ≥ 4', k3t['p95_total'] >= 4)
    ok('К3: повтор даёт те же числа (детерминизм)', k3_measure(np.dstack([pat, alpha])) == k3t)
    tiny_a = np.zeros((48, 48), np.uint8)
    tiny_a[14:34, 14:34] = 255       # реальная вырезка — с прозрачным полем (trim_alpha оставляет 8 px)
    ok('К3: слишком малая внутренняя область → note tiny_inner', k3_measure(np.dstack([plain[:48, :48], tiny_a]))['note'] == 'tiny_inner')
    print(f'passport_measure selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
