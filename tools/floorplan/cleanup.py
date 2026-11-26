"""Чистка входа листа плана перед разбором (T-20261126-98/4; решение директора 26.11): два независимых шага, оба ВЫКЛ по умолчанию.

  (б) фон скана/фото листа (серый, жёлтый, градиент света) → белый. Флаг `FP_CLEAN_BG=1`.
      Делим на поле освещённости (полином по верхней огибающей блоков), заливки комнат и линии остаются;
      цветной лист застройщика, белый лист, лист с большой заливкой, ink-ratio вне 0,8…1,3 — не трогаем.
  (а) выпрямление по линиям чертежа (две точки схода → гомография). Флаг `FP_CLEAN_RECT=1`. Применяется, только если
      доля длины линий на осях на отложенных отрезках выросла ≥ 0,08 и стала ≥ 0,55; лист «уже ровный» (≥ 0,80) не трогаем.
Увеличение мелких (в) в бой не несём: польза измерена и равна нулю. Прозрачный PNG → белый — уже в `pipeline._flat_rgb`.

    clean_sheet(pil_rgb) → (pil_rgb, ops)       # то, что зовёт pipeline.prepare(); без флагов — тот же объект, ops = []
    clean_bgr(bgr, rectify, background) → (bgr, ops, info)
Только OpenCV/numpy. Пороги — константы ниже (заданы до счёта, `etazhi-walls/vhod/ozhidanie.md`)."""
import os

import cv2
import numpy as np

# ---- пороги ----
RECT_WORK = 1400        # рабочий размер поиска линий
SEG_MIN_FRAC = 0.06     # минимальная длина отрезка, доля длинной стороны
AX_TOL = 1.5            # допуск «на оси», градусов
SCORE_SKIP = 0.80       # лист уже ровный — не трогаем
SCORE_GAIN = 0.08       # прирост доли «на осях», чтобы применить
SCORE_MIN_AFTER = 0.55
MIN_FAM_SEGS = 4        # сегментов в каждом семействе
ASPECT_MAX = 1.6        # пропорции выхода к входу не больше чем в 1,6 раза
MAX_ROT = 30.0          # поворот главной оси от горизонтали, градусов
BG_S_MAX = 90           # лист «бумажный»: насыщенность медианного пикселя (0..255) не выше
BG_V_WHITE = 247        # …и фон не белый: V ≤ 247, либо тон заметен (S ≥ 25 при V < 250)
BG_INK_MAX = 0.15
INK_RATIO = (0.8, 1.3)


def flag_bg() -> bool:
    return os.environ.get('FP_CLEAN_BG', '0') == '1'


def flag_rect() -> bool:
    return os.environ.get('FP_CLEAN_RECT', '0') == '1'


# ---------------- (а) выпрямление по линиям ----------------
def _segments(gray):
    h, w = gray.shape
    L = max(h, w)
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    ed = cv2.Canny(g, 40, 120)
    ed = cv2.dilate(ed, np.ones((2, 2), np.uint8))
    segs = cv2.HoughLinesP(ed, 1, np.pi / 720, threshold=int(0.04 * L), minLineLength=int(SEG_MIN_FRAC * L), maxLineGap=int(0.012 * L))
    if segs is None:
        return np.zeros((0, 4), np.float64)
    return segs.reshape(-1, 4).astype(np.float64)


def _ang(s):
    return np.degrees(np.arctan2(s[:, 3] - s[:, 1], s[:, 2] - s[:, 0])) % 180.0   # 0..180


def _len(s):
    return np.hypot(s[:, 2] - s[:, 0], s[:, 3] - s[:, 1])


def _axis_score(s):
    if len(s) == 0:
        return 0.0
    a = _ang(s)
    d = np.minimum.reduce([np.abs(a), np.abs(a - 90), np.abs(a - 180)])
    ln = _len(s)
    return float(ln[d <= AX_TOL].sum() / max(ln.sum(), 1e-9))


def _dominant(a, ln):
    """главная ориентация семейства «почти горизонтальных» (в сторону 0…180), по гистограмме длины, окно 3°"""
    hist = np.zeros(180)
    for ai, li in zip(a, ln):
        hist[int(ai) % 180] += li
    ker = np.ones(5) / 5
    sm = np.convolve(np.concatenate([hist[-2:], hist, hist[:2]]), ker, mode='valid')
    return float(np.argmax(sm)) + 0.5


def _vp(segs, c, L):
    """точка схода семейства (однородные координаты, центр и масштаб убраны), 3 прохода с отсевом"""
    keep = np.ones(len(segs), bool)
    v = None
    for _ in range(4):
        S_ = segs[keep]
        if len(S_) < 3:
            return None, keep
        p1 = np.c_[(S_[:, 0] - c[0]) / L, (S_[:, 1] - c[1]) / L, np.ones(len(S_))]
        p2 = np.c_[(S_[:, 2] - c[0]) / L, (S_[:, 3] - c[1]) / L, np.ones(len(S_))]
        l = np.cross(p1, p2)
        l /= np.maximum(np.hypot(l[:, 0], l[:, 1]), 1e-12)[:, None]
        w = _len(S_)
        M = (l * w[:, None]).T @ l
        ev, evec = np.linalg.eigh(M)
        v = evec[:, 0]
        # отсев: угол между отрезком и направлением к точке схода
        mid = (p1 + p2) / 2
        vx = v[:2] / v[2] if abs(v[2]) > 1e-9 else None
        idx = np.where(keep)[0]
        res = np.zeros(len(idx))
        for k, (mm, ss) in enumerate(zip(mid, S_)):
            d_seg = np.array([ss[2] - ss[0], ss[3] - ss[1]])
            d_seg /= np.linalg.norm(d_seg) + 1e-12
            if vx is None:
                d_vp = v[:2] / (np.linalg.norm(v[:2]) + 1e-12)
            else:
                d_vp = vx - mm[:2]
                d_vp /= np.linalg.norm(d_vp) + 1e-12
            res[k] = np.degrees(np.arccos(np.clip(abs(float(np.dot(d_seg, d_vp))), 0, 1)))
        bad = res > 3.0
        if not bad.any():
            break
        keep[idx[bad]] = False
    return v, keep


def rectify_lines(bgr, f_force=None):
    """→ (warped | None, info). info: score_before/after, f, reason"""
    H0, W0 = bgr.shape[:2]
    k = min(1.0, RECT_WORK / max(H0, W0))
    small = cv2.resize(bgr, (round(W0 * k), round(H0 * k)), interpolation=cv2.INTER_AREA) if k < 1 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    L = float(max(h, w))
    c = np.array([w / 2, h / 2])
    info = {'ok': False}
    segs = _segments(gray)
    info['segs'] = int(len(segs))
    if len(segs) < 12:
        info['reason'] = f'мало линий ({len(segs)})'
        return None, info
    fit, test = segs[::2], segs[1::2]
    sb = _axis_score(test)
    info['score_before'] = round(sb, 3)
    if sb >= SCORE_SKIP:
        info['reason'] = f'лист уже ровный: {sb:.2f} длины на осях'
        return None, info
    a, ln = _ang(fit), _len(fit)
    th = _dominant(a, ln)
    th_n = th if th <= 90 else th - 180      # −90…90
    if abs(th_n) > 45:
        th_n = th_n - 90 if th_n > 0 else th_n + 90
    info['dominant_deg'] = round(th_n, 1)
    if abs(th_n) > MAX_ROT:
        info['reason'] = f'главная ось {th_n:.0f}° от горизонтали (> {MAX_ROT:.0f}°)'
        return None, info
    d1 = np.minimum(np.abs(a - th), 180 - np.abs(a - th))
    d2 = np.minimum(np.abs(a - (th + 90) % 180), 180 - np.abs(a - (th + 90) % 180))
    fam1, fam2 = fit[d1 <= 25], fit[d2 <= 25]
    info['fam'] = [int(len(fam1)), int(len(fam2))]
    if len(fam1) < MIN_FAM_SEGS or len(fam2) < MIN_FAM_SEGS:
        info['reason'] = f'мало линий в семействах ({len(fam1)}/{len(fam2)})'
        return None, info
    v1, k1 = _vp(fam1, c, L)
    v2, k2 = _vp(fam2, c, L)
    if v1 is None or v2 is None:
        info['reason'] = 'точка схода не найдена'
        return None, info
    info['fam_kept'] = [int(k1.sum()), int(k2.sum())]
    if k1.sum() < MIN_FAM_SEGS or k2.sum() < MIN_FAM_SEGS:
        info['reason'] = f'после отсева мало линий ({k1.sum()}/{k2.sum()})'
        return None, info
    # фокус: f² = −(v1−c)·(v2−c) (нормированные координаты: c=0, масштаб L)
    f = None
    if abs(v1[2]) > 1e-6 and abs(v2[2]) > 1e-6:
        p1, p2 = v1[:2] / v1[2], v2[:2] / v2[2]
        f2 = -float(np.dot(p1, p2))
        if 0.25 ** 2 <= f2 <= 3.0 ** 2:
            f = float(np.sqrt(f2))
    info['f_est'] = None if f is None else round(f, 2)
    if f_force is not None:
        f = f_force
    if f is None:
        f = 0.9
        info['f_default'] = True
    K = np.array([[f, 0, 0], [0, f, 0], [0, 0, 1.0]])
    Ki = np.linalg.inv(K)
    d1v, d2v = Ki @ v1, Ki @ v2
    d1v /= np.linalg.norm(d1v)
    d2v /= np.linalg.norm(d2v)
    if d1v[0] < 0:
        d1v = -d1v
    if d2v[1] < 0:
        d2v = -d2v
    # d1 и d2 должны быть почти ортогональны: берём ортогонализацию (нормаль n = d1 × d2)
    n = np.cross(d1v, d2v)
    if np.linalg.norm(n) < 1e-3:
        info['reason'] = 'направления вырождены'
        return None, info
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    r1 = d1v - n * float(np.dot(d1v, n))
    r1 /= np.linalg.norm(r1)
    r2 = np.cross(n, r1)
    if r2[1] < 0:
        r2 = -r2
        r1 = np.cross(r2, n)
    Rm = np.c_[r1, r2, n]            # столбцы — оси листа в системе камеры
    Hn = K @ Rm.T @ Ki               # в нормированных координатах (c=0, масштаб L)
    # → в пиксели рабочей картинки
    T = np.array([[1 / L, 0, -c[0] / L], [0, 1 / L, -c[1] / L], [0, 0, 1.0]])
    Hs = np.linalg.inv(T) @ Hn @ T
    corners = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], float).T
    pc = Hs @ corners
    if (pc[2] <= 1e-6).any():
        info['reason'] = 'угол кадра уходит за линию горизонта'
        return None, info
    pc = (pc[:2] / pc[2]).T
    x0, y0 = pc.min(0)
    x1, y1 = pc.max(0)
    if (x1 - x0) > 3 * w or (y1 - y0) > 3 * h or (x1 - x0) < 0.3 * w or (y1 - y0) < 0.3 * h:
        info['reason'] = 'гомография слишком сильная (границы выхода вне 0,3…3× кадра)'
        return None, info
    # после — на отложенных отрезках: преобразуем их концы
    def tr(s):
        p = np.c_[s[:, 0], s[:, 1], np.ones(len(s))].T
        q = np.c_[s[:, 2], s[:, 3], np.ones(len(s))].T
        p2_, q2_ = Hs @ p, Hs @ q
        return np.c_[(p2_[:2] / p2_[2]).T, (q2_[:2] / q2_[2]).T]
    sa = _axis_score(tr(test))
    info['score_after'] = round(sa, 3)
    if sa < SCORE_MIN_AFTER or sa - sb < SCORE_GAIN:
        info['reason'] = f'не улучшает: на осях {sb:.2f} → {sa:.2f} (нужно ≥ +{SCORE_GAIN} и ≥ {SCORE_MIN_AFTER})'
        return None, info
    # полный размер: матрица для исходных пикселей = S · Hs · S^-1, S — масштаб рабочего размера
    Sk = np.diag([k, k, 1.0])
    Hf = np.linalg.inv(Sk) @ Hs @ Sk
    cf = np.array([[0, 0, 1], [W0, 0, 1], [W0, H0, 1], [0, H0, 1]], float).T
    pf = Hf @ cf
    pf = (pf[:2] / pf[2]).T
    fx0, fy0 = pf.min(0)
    fx1, fy1 = pf.max(0)
    # масштаб выхода: площадь ≈ площади исходной картинки (не растим), потолок 2000
    area_k = np.sqrt((W0 * H0) / max((fx1 - fx0) * (fy1 - fy0), 1.0))
    area_k = min(area_k, 2000 / max(fx1 - fx0, fy1 - fy0) * 1.0, 1.5)
    Tt = np.array([[area_k, 0, -fx0 * area_k], [0, area_k, -fy0 * area_k], [0, 0, 1.0]])
    Hout = Tt @ Hf
    ow, oh = int(round((fx1 - fx0) * area_k)), int(round((fy1 - fy0) * area_k))
    asp = (ow / oh) / (W0 / H0)
    info['aspect_change'] = round(float(asp), 2)
    if not (1 / ASPECT_MAX <= asp <= ASPECT_MAX):
        info['reason'] = f'пропорции листа меняются в {asp:.2f}× (допуск {1 / ASPECT_MAX:.2f}…{ASPECT_MAX}) — гомография сомнительна'
        info['ok'] = False
        return None, info
    m = max(3, int(0.02 * min(H0, W0)))
    ringpx = np.concatenate([bgr[:m].reshape(-1, 3), bgr[-m:].reshape(-1, 3), bgr[:, :m].reshape(-1, 3), bgr[:, -m:].reshape(-1, 3)])
    fillc = tuple(int(x) for x in np.median(ringpx, axis=0))      # поля клина — цвет рамки исходника (бумага → бумага, голубой фон → голубой)
    warped = cv2.warpPerspective(bgr, Hout, (ow, oh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=fillc)
    info.update({'ok': True, 'out_size': [ow, oh], 'H': Hout.tolist()})
    return warped, info



def _illum(ch):
    """поле освещённости/тона бумаги: полином 2-й степени по верхней огибающей блоков, итеративно отбрасывая блоки темнее подгонки (заливки, линии)
    — заливки комнат остаются, уходит только плавный тон и градиент света"""
    H, W = ch.shape
    G = 32
    small = cv2.resize(ch, (G, G), interpolation=cv2.INTER_AREA).astype(np.float32)
    small = cv2.dilate(small, np.ones((3, 3), np.uint8))          # верхняя огибающая блоков
    ys, xs = np.mgrid[0:G, 0:G].astype(np.float32)
    x, y = (xs / (G - 1) * 2 - 1).ravel(), (ys / (G - 1) * 2 - 1).ravel()
    A = np.c_[np.ones_like(x), x, y, x * x, x * y, y * y]
    v = small.ravel()
    w = np.ones_like(v, bool)
    coef = None
    for _ in range(6):
        coef, *_ = np.linalg.lstsq(A[w], v[w], rcond=None)
        fit = A @ coef
        w2 = v >= fit * 0.94
        if w2.sum() < 0.3 * len(v):
            break
        w = w2
    gx, gy = np.meshgrid(np.linspace(-1, 1, W, dtype=np.float32), np.linspace(-1, 1, H, dtype=np.float32))
    return (coef[0] + coef[1] * gx + coef[2] * gy + coef[3] * gx * gx + coef[4] * gx * gy + coef[5] * gy * gy).astype(np.float32)

# ---------------- (б) фон скана ----------------
def clean_background(bgr):
    """→ (out | None, info)"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    info = {}
    medS = float(np.median(hsv[..., 1]))
    medV = float(np.median(hsv[..., 2]))
    info.update({'medS': round(medS, 1), 'medV': round(medV, 1)})
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ink0 = cv2.adaptiveThreshold(cv2.GaussianBlur(gray, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    inkfrac = float((ink0 > 0).mean())
    info['ink_frac'] = round(inkfrac, 4)
    if not (medV <= 247 or (medS >= 25 and medV < 250)):
        info['reason'] = f'фон уже белый (V {medV:.0f})'
        return None, info
    # бумага занимает весь кадр: кольцо по краю того же тона, что медиана; иначе внутри белого поля цветная заливка (лист застройщика) — не бумага
    Hh, Ww = bgr.shape[:2]
    m = max(3, int(0.02 * min(Hh, Ww)))
    ring = np.concatenate([hsv[:m, :, 2].ravel(), hsv[-m:, :, 2].ravel(), hsv[:, :m, 2].ravel(), hsv[:, -m:, 2].ravel()])
    info['ringV'] = round(float(np.median(ring)), 1)
    if float(np.median(ring)) - medV > 18:
        info['reason'] = f'по краю светлее, чем в середине (V {np.median(ring):.0f} против {medV:.0f}) — заливка внутри белого листа, не бумага'
        return None, info
    if medS > BG_S_MAX:
        info['reason'] = f'цветной лист застройщика (насыщенность {medS:.0f} > {BG_S_MAX}) — не трогаем'
        return None, info
    sel = hsv[..., 1] > 25
    medH = float(np.median(hsv[..., 0][sel])) if sel.any() else 0.0
    info['medH'] = round(medH, 1)
    if medS > 40 and not (medH <= 32 or medH >= 165):
        info['reason'] = f'фон цветной не-бумажного тона (оттенок {medH:.0f}, насыщенность {medS:.0f}) — лист застройщика, не скан — не трогаем'
        return None, info
    if inkfrac > BG_INK_MAX:
        info['reason'] = f'много тёмного/заливки ({inkfrac:.2f} > {BG_INK_MAX}) — не трогаем'
        return None, info
    H, W = gray.shape
    out = np.zeros_like(bgr)
    for ch in range(3):
        fld = _illum(bgr[..., ch])
        out[..., ch] = np.clip(bgr[..., ch].astype(np.float32) / np.maximum(fld, 1.0) * 255.0, 0, 255).astype(np.uint8)
    # лёгкое подтягивание уровней: фон → 255 (бумага после деления ≈ 245-255)
    g2 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    ink1 = cv2.adaptiveThreshold(cv2.GaussianBlur(g2, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    ratio = float((ink1 > 0).sum() / max((ink0 > 0).sum(), 1))
    info['ink_ratio'] = round(ratio, 2)
    info['bg_after'] = round(float(np.median(g2)), 1)
    if not (INK_RATIO[0] <= ratio <= INK_RATIO[1]):
        info['reason'] = f'чернил после/до {ratio:.2f} вне {INK_RATIO} — откат (чистка испортила бы линии)'
        return None, info
    return out, info


def clean_bgr(bgr, rectify=True, background=True):
    """→ (bgr, ops, info). ops ⊂ ['rectify', 'background']; ничего не применилось — тот же массив."""
    ops, info, cur = [], {}, bgr
    if rectify:
        w_, inf = rectify_lines(cur)
        info['rect'] = {k: v for k, v in inf.items() if k != 'H'}
        if w_ is not None:
            cur = w_
            ops.append('rectify')
            info['rect_H'] = inf['H']      # матрица исходный лист → выпрямленный (нужна для обратного преобразования)
    if background:
        b_, inf = clean_background(cur)
        info['bg'] = inf
        if b_ is not None:
            cur = b_
            ops.append('background')
    return cur, ops, info


def clean_sheet_steps(sheet):
    """PIL RGB → (PIL RGB, ops, steps). steps — геометрия для обратного преобразования (исходный лист ← выход):
    [{'op': 'rectify', 'H': 3×3 исходный→выход, 'in': [W, H], 'out': [w, h]}]; фон геометрию не меняет. Выключено/не применилось — тот же объект, [], []."""
    rect, bg = flag_rect(), flag_bg()
    if not (rect or bg):
        return sheet, [], []
    from PIL import Image
    try:
        bgr = cv2.cvtColor(np.asarray(sheet.convert('RGB')), cv2.COLOR_RGB2BGR)
        out, ops, info = clean_bgr(bgr, rectify=rect, background=bg)
    except Exception:  # noqa: BLE001 — чистка не должна ронять разбор: лист как есть
        return sheet, [], []
    if not ops:
        return sheet, [], []
    steps = []
    if 'rectify' in ops and 'rect_H' in info:
        steps.append({'op': 'rectify', 'H': info['rect_H'], 'in': [bgr.shape[1], bgr.shape[0]], 'out': [out.shape[1], out.shape[0]]})
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), ops, steps


def clean_sheet(sheet):
    """PIL RGB → (PIL RGB, ops) по флагам окружения; выключено/не применилось — тот же объект. Любой сбой шага — лист как есть."""
    out, ops, _ = clean_sheet_steps(sheet)
    return out, ops
