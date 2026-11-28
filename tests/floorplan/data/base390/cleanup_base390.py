# КОД 390acfbc8 (база до T-171/круг 6), НЕ ПРАВИТЬ. Копия tools/floorplan/cleanup.py: отличие от оригинала — только шапка и переименованные импорты
# (cleanup→cleanup_base390, apartment_cut→apartment_cut_base390, quarter_turn→quarter_turn_base390), чтобы старая и новая функции жили в одном процессе.
# Нужна тесту tests/floorplan/test_deskew_k6flag.py: «флаги выкл = прежнее» сравнивается ПРЯМО, без золота (золото зависело от версии cv2).
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
BG_RING_V_MIN = 100     # яркость кольца по краю листа (медиана) ниже — тёмный фон/рама (чёрный лист, цветной лист застройщика в тёмной рамке): фон не светлим; у фото БТИ на столе кольцо ≥ 109
INK_RATIO = (0.8, 1.3)


def flag_bg() -> bool:
    return os.environ.get('FP_CLEAN_BG', '0') == '1'


def flag_rect() -> bool:
    return os.environ.get('FP_CLEAN_RECT', '0') == '1'


def flag_deskew() -> bool:
    return os.environ.get('FP_CLEAN_DESKEW', '0') == '1'


# ---------------- (0) доворот повёрнутого листа (T-171/vhod, план Fable otvet-33 задача 6) ----------------
DESKEW_MIN = 1.5         # главный угол линий меньше — лист ровный, не трогаем
DESKEW_MAX = 30.0        # больше — не доворот (план «под 45°» — вопрос другого шага), не трогаем
DESKEW_RESID = 1.0       # после поворота угол пересчитан: остаток ≥ этого → откат (оценка угла грубая)
DESKEW_SHARE_MIN = 0.15  # доля длины линий на главном угле и поперёк него (±1,5°): меньше — главного угла у листа нет (рукописный/круглый план)
DESKEW_BALANCE_MIN = 0.04  # …и слабая из двух сторон не меньше этой доли: у плана стены идут в обе стороны, у линейки/рамки листа — в одну
DESKEW_MIN_SEGS = 12


def _fold90(a):
    """угол отрезка 0…180 → −45…45 (по модулю 90°)"""
    return (np.asarray(a, np.float64) + 45.0) % 90.0 - 45.0


DESKEW_THICK = 0.003     # штрих толще этой доли длинной стороны (на рабочем размере ≈ 4 px) — «толстый» (стена): тонкие линии, цифры, штриховка не считаются (Fable otvet-36, круг 6)


def thick_ink(gray):
    """оставляет только толстые длинные штрихи (стены): чернила по Оцу → открытие эллипсом толщиной DESKEW_THICK → тёмное на белом.
    Тонкие линейки, размерные линии, текст и штриховка тоньше ядра и исчезают."""
    _, t = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = max(3, int(round(DESKEW_THICK * max(gray.shape))))
    op = cv2.morphologyEx(t, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return 255 - op


def main_angle(gray, thick=True):
    """→ (θ | None, info). θ — главный угол линий листа по модулю 90°, градусы −45…45; «+» — линии идут вниз вправо (по часовой в картинке, y вниз).
    Линии — длинные ТОЛСТЫЕ штрихи (`thick_ink`; thick=False — все линии, как было до otvet-36). Гистограмма длины линий, шаг 0,5°, окно ±1°, потом уточнение
    средним по длине в окне ±1,5°. Нет линий / нет главного угла — None с причиной."""
    if thick:
        gray = thick_ink(gray)
    segs = _segments(gray)
    info = {'segs': int(len(segs))}
    if len(segs) < DESKEW_MIN_SEGS:
        info['reason'] = f'мало линий ({len(segs)})'
        return None, info
    a0, ln = _ang(segs), _len(segs)
    a = _fold90(a0)
    tot = max(float(ln.sum()), 1e-9)
    hist = np.zeros(180)
    for ai, li in zip(a, ln):
        hist[int((ai + 45.0) * 2) % 180] += li
    sm = np.convolve(np.concatenate([hist[-2:], hist, hist[:2]]), np.ones(5) / 5, mode='valid')
    cands = []                                                # до 4 самых высоких пиков, разнесённых > 3°: рамки листа и линейки не должны прятать угол плана
    for b in np.argsort(sm)[::-1]:
        p = (float(b) + 0.5) / 2 - 45.0
        if all(abs(float(_fold90(p - c))) > 3.0 for c in cands):
            cands.append(p)
        if len(cands) == 4:
            break
    best = None
    for p in cands:
        near = np.abs(_fold90(a - p)) <= 1.5
        if not near.any():
            continue
        th = float(np.average(_fold90(a[near] - p) + p, weights=ln[near]))
        d = a0 - th
        l1 = float(ln[np.abs((d + 90.0) % 180.0 - 90.0) <= 1.5].sum())      # вдоль θ
        l2 = float(ln[np.abs(d % 180.0 - 90.0) <= 1.5].sum())               # поперёк (θ + 90°)
        sc = min(l1, l2)                                      # у плана есть оба семейства стен; у линейки листа — одно
        if best is None or sc > best[0]:
            best = (sc, th, l1, l2)
    if best is None:
        info['reason'] = 'главного угла нет'
        return None, info
    _, theta, l1, l2 = best
    share, balance = (l1 + l2) / tot, min(l1, l2) / tot
    info['theta'], info['share'], info['balance'] = round(theta, 2), round(share, 3), round(balance, 3)
    if share < DESKEW_SHARE_MIN or balance < DESKEW_BALANCE_MIN:
        info['reason'] = f'главного угла нет: на нём {share:.2f} длины линий (< {DESKEW_SHARE_MIN}), слабая сторона {balance:.2f} (< {DESKEW_BALANCE_MIN})'
        return None, info
    return theta, info


def deskew_lines(bgr):
    """→ (повёрнутый | None, info). Лист поворачивается на главный угол линий (холст расширяется, поле белое); info['H'] — матрица исходный лист → выход.
    Не применяется: лист ровный (< DESKEW_MIN), угол > DESKEW_MAX, главного угла нет, после поворота остаток ≥ DESKEW_RESID."""
    H0, W0 = bgr.shape[:2]
    k = min(1.0, RECT_WORK / max(H0, W0))
    small = cv2.resize(bgr, (round(W0 * k), round(H0 * k)), interpolation=cv2.INTER_AREA) if k < 1 else bgr
    theta, info = main_angle(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    info['ok'] = False
    if theta is None:
        return None, info
    if abs(theta) < DESKEW_MIN:
        info['reason'] = f'лист ровный: главный угол {theta:.2f}° (< {DESKEW_MIN}°)'
        return None, info
    if abs(theta) > DESKEW_MAX:
        info['reason'] = f'главный угол {theta:.1f}° (> {DESKEW_MAX:.0f}°)'
        return None, info
    M = cv2.getRotationMatrix2D((W0 / 2.0, H0 / 2.0), theta, 1.0)       # «+» угол = против часовой: линия, идущая вниз вправо на θ, становится горизонтальной
    c, s = abs(M[0, 0]), abs(M[0, 1])
    nW, nH = int(np.ceil(H0 * s + W0 * c)), int(np.ceil(H0 * c + W0 * s))
    M[0, 2] += nW / 2.0 - W0 / 2.0
    M[1, 2] += nH / 2.0 - H0 / 2.0
    out = cv2.warpAffine(bgr, M, (nW, nH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    ks = min(1.0, RECT_WORK / max(nH, nW))
    out_s = cv2.resize(out, (round(nW * ks), round(nH * ks)), interpolation=cv2.INTER_AREA) if ks < 1 else out
    resid, info2 = main_angle(cv2.cvtColor(out_s, cv2.COLOR_BGR2GRAY))
    info['angle_deg'] = round(theta, 2)
    if resid is None or abs(resid) >= DESKEW_RESID:
        info['reason'] = f'после поворота остаток {"?" if resid is None else round(resid, 2)}° (≥ {DESKEW_RESID}°) — откат'
        return None, info
    info['residual_deg'] = round(resid, 2)
    info['ok'] = True
    info['H'] = np.vstack([M, [0, 0, 1.0]]).tolist()
    return out, info


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
    if float(np.median(ring)) < BG_RING_V_MIN:
        info['reason'] = f'лист в тёмной раме/на тёмном фоне (V по краю {np.median(ring):.0f} < {BG_RING_V_MIN}) — это не бумага скана, фон не светлим'
        return None, info
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


# ---------------- (в) усиление бледных линий БТИ ----------------
LINES_FAINT = 0.35          # типичная («75-й процентиль» по пикселям линий) глубина ниже этого → линии бледные, усиливаем
LINES_TARGET = 0.65         # до какой глубины подтягиваем типичную линию
LINES_GAIN = (1.0, 3.0)
LINES_PAPER_SD = 8.0        # разброс яркости бумаги (верхние 40 % пикселей) больше — фон неровный/тёмный, усиление раздуло бы пятна: не трогаем
LINES_CHANGED = 0.22        # доля потемневших пикселей больше — усилилось слишком много (не линии), откат
LINES_LOW = 0.14            # штрих: глубина не меньше (иначе зерно бумаги)
LINES_SEED = 0.20           # и связан с пикселем не мельче этой глубины
LINES_AREA = (1.0, 2.6)     # площадь «чёрного» после/до: больше — усилился шум/толщина, откат


def flag_lines() -> bool:
    return os.environ.get('FP_CLEAN_LINES', '0') == '1'


def strengthen_lines(bgr):
    """→ (out | None, info). Бледные тонкие линии (серый скан БТИ) делаются темнее; бумага и заливки комнат не меняются, геометрия не меняется.
    Глубина линии s = (местный фон − пиксель) / местный фон; фон — замыкание по большому окну. Усиливаются только пиксели с s > ~0.06 (плавный порог), коэффициент
    подбирается по листу: типичная линия (75-й процентиль s) → LINES_TARGET, но не больше LINES_GAIN. Контраст уже высокий — не трогаем.
    Автопроверки: чернил после/до по площади в LINES_AREA, фон вне линий не темнеет (доля пикселей бумаги, ставших «линией», ≈ 0)."""
    info = {}
    H, W = bgr.shape[:2]
    L = max(H, W)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = max(15, int(0.03 * L)) | 1
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 3.0).astype(np.float32)
    bg = np.maximum(bg, gray.astype(np.float32))
    bg = np.maximum(bg, 1.0)
    s = np.clip((bg - gray.astype(np.float32)) / bg, 0.0, 1.0)
    ink = s > 0.08
    if float(ink.mean()) < 0.002:
        info['reason'] = 'линий почти нет'
        return None, info
    p75 = float(np.percentile(s[ink], 75))                    # типичная глубина линии
    info['depth_before'] = round(p75, 3)
    if p75 >= LINES_FAINT:
        info['reason'] = f'линии уже контрастные (глубина {p75:.2f} ≥ {LINES_FAINT})'
        return None, info
    sd = float(gray[gray > np.percentile(gray, 60)].std())
    info['paper_sd'] = round(sd, 1)
    if sd > LINES_PAPER_SD:
        info['reason'] = f'фон неровный (разброс {sd:.1f} > {LINES_PAPER_SD}) — не трогаем'
        return None, info
    gain = float(np.clip(LINES_TARGET / max(p75, 0.05), *LINES_GAIN))
    info['gain'] = round(gain, 2)
    # только штрихи: пиксели глубже LINES_LOW, связанные с «верной» линией (глубже LINES_SEED); зернистость бумаги (s ~ 0.05–0.14) отдельными пятнами не усиливаем
    low = (s > LINES_LOW).astype(np.uint8)
    nl, lab = cv2.connectedComponents(low, connectivity=8)
    seeded = np.zeros(nl, bool)
    seeded[np.unique(lab[s > max(LINES_SEED, 0.7 * p75)])] = True
    seeded[0] = False
    stroke = seeded[lab].astype(np.uint8)
    if not stroke.any():
        info['reason'] = 'штрихов нет (линии мельче порога) — не трогаем'
        return None, info
    stroke = cv2.GaussianBlur(cv2.dilate(stroke, np.ones((3, 3), np.uint8)).astype(np.float32), (0, 0), 0.8)
    w = np.clip((s - 0.04) / 0.06, 0.0, 1.0) * stroke
    s2 = np.clip(s * (1.0 + (gain - 1.0) * w), 0.0, 1.0)
    delta = (s2 - s) * bg                                     # на сколько уровней серого потемнеть
    out = np.clip(bgr.astype(np.float32) - delta[..., None], 0, 255).astype(np.uint8)
    thr = max(0.12, 0.5 * p75)                                # «линия» = не меньше половины типичной глубины до усиления
    a0 = float((s > thr).sum())
    a1 = float((s2 > thr).sum())
    ratio = a1 / max(a0, 1.0)
    paper = s < 0.04
    leak = float(((s2 > 0.10) & paper).sum() / max(float(paper.sum()), 1.0))
    info.update({'depth_after': round(float(np.percentile(s2[ink], 75)), 3), 'ink_area_ratio': round(ratio, 2), 'paper_leak': round(leak, 5)})
    if a0 < 50 or not (LINES_AREA[0] <= ratio <= LINES_AREA[1]):
        info['reason'] = f'площадь тёмного после/до {ratio:.2f} вне {LINES_AREA} — откат'
        return None, info
    changed = float(((gray.astype(np.float32) - cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)) > 8).mean())
    info['changed'] = round(changed, 3)
    if changed > LINES_CHANGED:
        info['reason'] = f'потемнело {changed:.2f} листа > {LINES_CHANGED} — откат'
        return None, info
    if leak > 0.001:
        info['reason'] = f'фон вне линий потемнел ({leak:.4f}) — откат'
        return None, info
    return out, info


# ---------------- (г) фон «в клетку» / тетрадный лист / сетка редактора ----------------
GRID_MIN_LINES = 5          # не меньше стольких линий по каждой оси
GRID_COVER_WEAK = 0.2       # слабая линия решётки (плану закрыта часть длины): тот же шаг, тот же тон
GRID_COVER = 0.5            # линия сетки: светлый тонкий штрих на такой доле ширины/высоты листа
GRID_DEPTH = (6, 110)       # глубина штриха сетки (уровней серого относительно фона): светлее 6 — шум, темнее 110 (серый ≲145 на белом) — линия плана, не сетка
GRID_THIN = 4               # толщина штриха сетки не больше (px): штриховка и контуры стен толще
GRID_REGULAR = 0.6          # доля зазоров между линиями, совпадающих с типичным (±20 %): сетка регулярна
GRID_DARK_KEEP = 0.98       # тёмных (план) пикселей после/до не меньше
GRID_LEFT = 0.25            # сетки осталось после/до не больше (по числу строк/столбцов-линий)


def flag_grid() -> bool:
    return os.environ.get('FP_CLEAN_GRID', '0') == '1'


def _grid_axis(cand, dep, horizontal, W, H):
    """строки (столбцы) листа с длинным светлым тонким штрихом: «верные» (покрытие ≥ GRID_COVER) + слабые (покрытие ≥ GRID_COVER_WEAK), если лежат на той же решётке и той же глубины тона.
    → (индексы, число верных линий, регулярность верных, маска штрихов)"""
    n = W if horizontal else H
    ker = (max(31, int(0.04 * n)), 1) if horizontal else (1, max(31, int(0.04 * n)))
    sq = cv2.getStructuringElement(cv2.MORPH_RECT, (GRID_THIN + 1, GRID_THIN + 1))
    blobs = cv2.dilate(cv2.morphologyEx(cand, cv2.MORPH_OPEN, sq), np.ones((5, 5), np.uint8))          # толстое (стены, штриховка, подписи) — не сетка
    thin = cand & (1 - blobs)
    run = cv2.morphologyEx(thin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, ker))
    ax = 1 if horizontal else 0
    cov = run.mean(axis=ax)
    idx = np.where(cov >= GRID_COVER)[0]
    if len(idx) == 0:
        return idx, 0, 0.0, run
    groups = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
    centers = np.array([g.mean() for g in groups])
    if len(centers) < 3:
        return idx, len(centers), 0.0, run
    gaps = np.diff(centers)
    med = float(np.median(gaps))
    reg = float((np.abs(gaps - med) <= 0.2 * med + 1).mean())
    if reg >= GRID_REGULAR and len(centers) >= GRID_MIN_LINES:
        # слабые линии (часть длины скрыта планом): та же решётка (шаг — самый частый зазор) и тот же тон
        vals, cnt = np.unique(np.round(gaps).astype(int), return_counts=True)
        pstep = float(vals[int(np.argmax(cnt))])
        if pstep >= 4:
            depsum = (dep * run).sum(axis=ax) / np.maximum(run.sum(axis=ax), 1)
            tone = float(np.median(depsum[idx]))
            weak = np.where((cov >= GRID_COVER_WEAK) & (cov < GRID_COVER))[0]
            keep = [w for w in weak if min(((w - centers[0]) % pstep), pstep - ((w - centers[0]) % pstep)) <= 2 and 0.6 * tone <= depsum[w] <= 1.5 * tone]
            idx = np.union1d(idx, np.array(keep, int))
    return idx, len(centers), reg, run


def remove_grid(bgr):
    """→ (out | None, info). Периодическая сетка светлых тонких линий (клетка тетради, сетка редактора) закрашивается фоном; тёмные линии плана
    не трогаются (закрашиваются только светлые пиксели на линиях сетки), геометрия не меняется.
    Находим длинные светлые штрихи по строкам и столбцам; ≥ GRID_MIN_LINES линий на ось и регулярные зазоры — это сетка, иначе не трогаем.
    Автопроверки: тёмных пикселей после/до ≥ GRID_DARK_KEEP; линий сетки после/до ≤ GRID_LEFT."""
    info = {}
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    L = max(H, W)
    k = max(15, int(0.03 * L)) | 1
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 3.0)
    dep = bg.astype(np.int16) - gray.astype(np.int16)
    cand = ((dep >= GRID_DEPTH[0]) & (dep <= GRID_DEPTH[1])).astype(np.uint8)
    ih, nh, rh, runh = _grid_axis(cand, dep, True, W, H)
    iv, nv, rv, runv = _grid_axis(cand, dep, False, W, H)
    info.update({'lines_h': nh, 'lines_v': nv, 'regular_h': round(rh, 2), 'regular_v': round(rv, 2)})
    if nh < GRID_MIN_LINES or nv < GRID_MIN_LINES:
        info['reason'] = f'сетки нет (линий {nh}×{nv} < {GRID_MIN_LINES})'
        return None, info
    if rh < GRID_REGULAR or rv < GRID_REGULAR:
        info['reason'] = f'линии не регулярны ({rh:.2f}/{rv:.2f} < {GRID_REGULAR}) — не сетка'
        return None, info
    base = np.zeros((H, W), np.uint8)
    base[ih, :] |= runh[ih, :]
    base[:, iv] |= runv[:, iv]
    paper = cv2.GaussianBlur(cv2.morphologyEx(bgr, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), (0, 0), k / 3.0)    # цвет бумаги рядом (тонкое замыкание стирает штрихи)
    d0 = float((gray < 110).sum())
    reason = ''
    for kd in (5, 3):                                         # толщина закраски: сперва с запасом на размытие JPEG, у частой сетки — тоньше
        mask = cv2.dilate(base, np.ones((kd, kd), np.uint8))
        mask &= (dep <= GRID_DEPTH[1]).astype(np.uint8)       # линии плана (темнее) под маску не попадают, даже на пересечении с сеткой
        mask &= (dep >= 3).astype(np.uint8)
        info['mask_share'] = round(float(mask.mean()), 4)
        info['dilate'] = kd
        out = bgr.copy()
        out[mask > 0] = paper[mask > 0]
        g2 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        d1 = float((g2 < 110).sum())
        info['dark_ratio'] = round(d1 / max(d0, 1.0), 3)
        if not (GRID_DARK_KEEP <= d1 / max(d0, 1.0) <= 2 - GRID_DARK_KEEP):
            reason = f'тёмного после/до {d1 / max(d0, 1):.3f} вне {GRID_DARK_KEEP}…{2 - GRID_DARK_KEEP:.2f} — откат'
            continue
        bg2 = cv2.GaussianBlur(cv2.morphologyEx(g2, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), (0, 0), k / 3.0)
        dep2 = bg2.astype(np.int16) - g2.astype(np.int16)
        cand2 = ((dep2 >= GRID_DEPTH[0]) & (dep2 <= GRID_DEPTH[1])).astype(np.uint8)
        _, nh2, _, _ = _grid_axis(cand2, dep2, True, W, H)
        _, nv2, _, _ = _grid_axis(cand2, dep2, False, W, H)
        info.update({'lines_h_after': nh2, 'lines_v_after': nv2})
        if nh2 + nv2 > GRID_LEFT * (nh + nv):
            reason = f'сетка осталась ({nh2}×{nv2} из {nh}×{nv}) — откат'
            continue
        info.pop('reason', None)
        return out, info
    info['reason'] = reason
    return None, info


# ---------------- (д) слои: цветная мебель и размерные линии отдельно от стен (класс Г) ----------------
LAYER_MEAN_SAT = 8.0         # средняя насыщенность листа выше — фото/цветная заливка (у чистых CAD-листов 1…3, у фото 18…35)
LAYER_PAPER = 200            # медианная яркость листа ниже — не белая бумага
LAYER_GREEN = (35, 90)       # оттенок (OpenCV H 0…179) мебели
LAYER_BLUE = (100, 130)      # оттенок размерных линий
LAYER_SAT = 40              # «цветной» пиксель: насыщенность выше (и яркость > 60)
LAYER_FURN_MIN = 0.04       # цветная связная фигура мебели: большая сторона не меньше этой доли длинной стороны листа (подписи — мельче)
LAYER_WALL_COLOURED = 0.25  # цветных длинных толстых штрихов больше — стены цветные (оранжевые/синие), мебель не трогаем
LAYER_BRIDGE = 0.006         # радиус склейки цветных кусков через разрыв (подпись поверх линии), доля длинной стороны
LAYER_CLOSE_SPAN = 0.08     # цветная фигура, касающаяся стен в двух местах дальше этой доли друг от друга, замыкает помещение — не стираем
LAYER_FURN_SIDE = 0.025   # и меньшая сторона не меньше этой доли: цветные цифры и подписи комнат остаются
DIM_MIN = 0.035             # размерная линия: длина не меньше (доля длинной стороны)
DIM_TEXT_R = 0.016          # цифра размера должна лежать рядом с серединой линии (доля длинной стороны)
DIM_TWIN = 0.010            # рядом вдоль линии есть «двойник» (параллельная линия ближе этого) — это стена/контур, не размерная
LAYER_CHANGED = (0.0, 0.85) # доля стёртых от всех «чернил» — вне этого откат (мебель бывает 75 % чернил, kazan-7666695; стены защищены отдельно: толстое и «двойники»)


def flag_layers() -> bool:
    return os.environ.get('FP_CLEAN_LAYERS', '0') == '1'


def separate_layers(bgr):
    """→ (walls_bgr | None, info, masks). Убираем с листа цветную мебель (тонкие цветные контуры крупных фигур) и размерные линии (тонкие
    одиночные прямые с цифрой у середины, без параллельного «двойника»); остаётся «стены + подписи комнат». masks = {'furniture', 'dims'} (uint8 0/255)
    — слои можно отдать нейросети отдельно. Геометрия не меняется. Цветные подписи (мелкие фигуры) и цветные стены не трогаем.
    Автопроверка: стёрто не больше LAYER_CHANGED от всех чернил, ни одной тёмной толстой связной фигуры (стены) не задето."""
    info = {}
    H, W = bgr.shape[:2]
    L = max(H, W)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mean_sat, med_g = float(hsv[..., 1].mean()), float(np.median(gray))
    info['mean_sat'], info['median_gray'] = round(mean_sat, 1), int(med_g)
    if mean_sat > LAYER_MEAN_SAT or med_g < LAYER_PAPER:       # фото, цветной фон/заливка комнат, чёрный фон: цвет на листе ненадёжен или это данные — не трогаем
        info['reason'] = 'цвет листа ненадёжен (фото/цветная заливка/тёмный фон)'
        return None, info, {}
    k = max(15, int(0.03 * L)) | 1
    bg = cv2.GaussianBlur(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), (0, 0), k / 3.0)
    dep = bg.astype(np.int16) - gray.astype(np.int16)
    ink = (dep > 40).astype(np.uint8)
    col = ((hsv[..., 1] > LAYER_SAT) & (hsv[..., 2] > 60)).astype(np.uint8)
    hue = hsv[..., 0]
    green = col & ((hue >= LAYER_GREEN[0]) & (hue <= LAYER_GREEN[1]))      # мебель редакторов планов — зелёная; красное/синее/сиреневое на листах — данные (площади, метки, заливка комнат): не трогаем
    blue = col & ((hue >= LAYER_BLUE[0]) & (hue <= LAYER_BLUE[1]))         # размерные линии редакторов — синие
    t = max(3, int(0.004 * L)) | 1
    thick = cv2.morphologyEx(ink | col, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (t + 2, t + 2)))
    n_thick = int(thick.sum())
    info['ink_px'] = int((ink | col).sum())
    if info['ink_px'] < 200:
        info['reason'] = 'нет линий'
        return None, info, {}
    ln_ = max(9, int(0.06 * L)) | 1
    long_ = cv2.morphologyEx(thick, cv2.MORPH_OPEN, np.ones((1, ln_), np.uint8)) | cv2.morphologyEx(thick, cv2.MORPH_OPEN, np.ones((ln_, 1), np.uint8))
    wall_col = float((long_ & col).sum() / max(int(long_.sum()), 1))   # цвет СТЕН: доля цветного среди длинных толстых прямых штрихов (мебель — короткие/тонкие)
    info['wall_coloured'] = round(wall_col, 3)
    furn = np.zeros((H, W), np.uint8)
    if wall_col <= LAYER_WALL_COLOURED:
        thin_col = green & (1 - cv2.dilate(thick, np.ones((3, 3), np.uint8)))           # зелёное, но не толстая заливка/стена
        d = cv2.dilate(thin_col, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        # стены: тёмные НЕцветные штрихи крупных связных фигур (подписи и мебель сюда не попадают)
        wall0 = (ink > 0) & (hsv[..., 1] < LAYER_SAT) & (gray < 150)
        nw, labw, stw, _ = cv2.connectedComponentsWithStats(wall0.astype(np.uint8), connectivity=8)
        big = [j for j in range(1, nw) if max(stw[j, cv2.CC_STAT_WIDTH], stw[j, cv2.CC_STAT_HEIGHT]) >= 0.15 * L]
        wall_m = np.isin(labw, big).astype(np.uint8) if big else np.zeros((H, W), np.uint8)
        wall_d = cv2.dilate(wall_m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        # «замыкающие»: цветные куски, связанные через разрывы (подпись поверх линии) в фигуру, чьи концы касаются стен в двух местах далеко друг от друга
        d2 = cv2.dilate(thin_col, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * max(3, int(LAYER_BRIDGE * L)) + 1,) * 2))
        n2, lab2, st2, _ = cv2.connectedComponentsWithStats(d2, connectivity=8)
        closing = np.zeros((H, W), bool)
        for j in range(1, n2):
            x0_, y0_, w2, h2 = st2[j, 0], st2[j, 1], st2[j, 2], st2[j, 3]
            if max(w2, h2) < LAYER_FURN_MIN * L:
                continue
            cj = (lab2[y0_:y0_ + h2, x0_:x0_ + w2] == j)
            touch = cj & (wall_d[y0_:y0_ + h2, x0_:x0_ + w2] > 0)
            nt, _, stt, cet = cv2.connectedComponentsWithStats(touch.astype(np.uint8), connectivity=8)
            ends = [cet[q] for q in range(1, nt) if stt[q, cv2.CC_STAT_AREA] >= 4]
            long_ax = 0 if w2 >= h2 else 1                                        # вдоль длинной стороны: касания должны быть у ДВУХ КОНЦОВ фигуры
            ext = max(w2, h2)
            at_ends = lambda u, v: abs(u[long_ax] - v[long_ax]) >= LAYER_CLOSE_SPAN * L and abs(u[long_ax] - v[long_ax]) >= 0.8 * ext   # noqa: E731
            if any(at_ends(u, v) and min(u[long_ax], v[long_ax]) <= 0.15 * ext and max(u[long_ax], v[long_ax]) >= 0.85 * ext for k_, u in enumerate(ends) for v in ends[k_ + 1:]):
                closing[y0_:y0_ + h2, x0_:x0_ + w2] |= cj
        n, lab, st, _ = cv2.connectedComponentsWithStats(d, connectivity=8)
        kept_walls = 0
        for i in range(1, n):
            w_, h_ = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
            if max(w_, h_) >= LAYER_FURN_MIN * L and min(w_, h_) >= LAYER_FURN_SIDE * L:        # подписи (красное S=5,94, синее H=270) — низкие: не трогаем
                if closing[lab == i].any():                      # линия замыкает помещение: оба конца у стены (балкон, лоджия) — граница комнаты, не мебель
                    kept_walls += 1
                    continue
                furn[(lab == i) & (thin_col > 0)] = 255
        info['kept_closing'] = kept_walls
    else:
        info['furniture_skipped'] = f'стены цветные ({wall_col:.2f}) — цвет не трогаем'
    # размерные линии: тонкая прямая, одиночная, цифра у середины
    dims = np.zeros((H, W), np.uint8)
    # только СИНИЕ размерные линии: серые тонкие на БТИ неотличимы от перегородок (проба: стёрла стены у 14 листов), красное — данные листа
    thin_ink = (blue & (1 - cv2.dilate(thick, np.ones((3, 3), np.uint8)))).astype(np.uint8)
    segs = cv2.HoughLinesP(thin_ink * 255, 1, np.pi / 180, threshold=int(0.03 * L), minLineLength=int(DIM_MIN * L), maxLineGap=max(2, int(0.004 * L)))
    small = cv2.connectedComponentsWithStats(cv2.dilate(thin_ink, np.ones((3, 3), np.uint8)), connectivity=8)
    n_s, lab_s, st_s, cen_s = small
    textlike = np.zeros(n_s, bool)
    for i in range(1, n_s):
        w_, h_ = st_s[i, cv2.CC_STAT_WIDTH], st_s[i, cv2.CC_STAT_HEIGHT]
        textlike[i] = 3 <= max(w_, h_) <= 0.03 * L and min(w_, h_) >= 3 and st_s[i, cv2.CC_STAT_AREA] >= 6
    n_dims = 0
    if segs is not None:
        for x1, y1, x2, y2 in segs.reshape(-1, 4):
            ang = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
            if not (ang < 3 or abs(ang - 90) < 3 or abs(ang - 180) < 3):
                continue
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            r = max(6, int(DIM_TEXT_R * L))
            y0, y1b, x0, x1b = max(my - r, 0), min(my + r + 1, H), max(mx - r, 0), min(mx + r + 1, W)
            ids = np.unique(lab_s[y0:y1b, x0:x1b])
            if not any(textlike[j] for j in ids if j > 0):
                continue                                                      # у середины нет цифры
            # «двойник»: параллельная тёмная линия ближе DIM_TWIN по обе стороны вдоль линии
            tw = max(3, int(DIM_TWIN * L))
            horizontal = abs(y2 - y1) <= abs(x2 - x1)
            xs = np.linspace(x1, x2, 9).astype(int).clip(0, W - 1)
            ys = np.linspace(y1, y2, 9).astype(int).clip(0, H - 1)
            twin = 0
            for sgn in (-1, 1):
                hit = 0
                for xx, yy in zip(xs, ys):
                    for off in range(3, tw + 1):
                        yy2, xx2 = (min(max(yy + sgn * off, 0), H - 1), xx) if horizontal else (yy, min(max(xx + sgn * off, 0), W - 1))
                        if ink[yy2, xx2]:
                            hit += 1
                            break
                twin += hit >= 6
            if twin >= 1:
                continue
            cv2.line(dims, (int(x1), int(y1)), (int(x2), int(y2)), 255, 3)
            n_dims += 1
    dims &= (cv2.dilate(thin_ink, np.ones((3, 3), np.uint8)) * 255).astype(np.uint8)       # стираем только сами тонкие штрихи под линией
    info['dim_lines'] = n_dims
    info['furniture_px'] = int((furn > 0).sum())
    allm = (furn > 0) | (dims > 0)
    if not allm.any():
        info['reason'] = 'мебели и размерных линий не найдено'
        return None, info, {}
    out = bgr.copy()
    paper = cv2.GaussianBlur(cv2.morphologyEx(bgr, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), (0, 0), k / 3.0)
    m = (cv2.dilate((furn > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) | (cv2.dilate((dims > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)   # ореол сглаживания цветной линии тоже
    m &= (hsv[..., 1] > 25) | (dims > 0)                                     # стены рядом с мебелью — серые: цветом их отличаем
    m &= ~(thick > 0)                                                         # толстое (стены) под стирание не попадает
    out[m] = paper[m]
    share = float(m.sum() / max(info['ink_px'], 1))
    info['erased_share'] = round(share, 3)
    if not (LAYER_CHANGED[0] <= share <= LAYER_CHANGED[1]):
        info['reason'] = f'стёрто {share:.2f} чернил вне {LAYER_CHANGED} — откат'
        return None, info, {}
    return out, info, {'furniture': furn, 'dims': dims}


def clean_bgr(bgr, rectify=True, background=True, lines=False, grid=False, layers=False, deskew=False):
    """→ (bgr, ops, info). ops ⊂ ['deskew', 'rectify', 'background', 'grid', 'layers', 'lines']; ничего не применилось — тот же массив."""
    ops, info, cur = [], {}, bgr
    if deskew:                                                # доворот — первым: выпрямление ниже видит уже ровный лист (≥ 0,80 на осях → пропуск)
        d_, inf = deskew_lines(cur)
        info['deskew'] = {k: v for k, v in inf.items() if k != 'H'}
        if d_ is not None:
            cur = d_
            ops.append('deskew')
            info['deskew_H'] = inf['H']
    if rectify:
        if 'deskew_H' in info:                                # после доворота выпрямление не шагает: две геометрии подряд — матрицы не склеены
            info['rect'] = {'ok': False, 'reason': 'лист довёрнут (deskew) — выпрямление не применяется'}
            rectify = False
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
    if grid:                                                  # сетку — до усиления линий (иначе усилили бы и клетку)
        g_, inf = remove_grid(cur)
        info['grid'] = inf
        if g_ is not None:
            cur = g_
            ops.append('grid')
    if layers:                                                # слои (мебель, размерные) — после сетки, до усиления линий
        y_, inf, _m = separate_layers(cur)
        info['layers'] = inf
        if y_ is not None:
            cur = y_
            ops.append('layers')
    if lines:
        l_, inf = strengthen_lines(cur)
        info['lines'] = inf
        if l_ is not None:
            cur = l_
            ops.append('lines')
    return cur, ops, info


def clean_sheet_steps(sheet, flags=None):
    """PIL RGB → (PIL RGB, ops, steps). steps — геометрия для обратного преобразования (исходный лист ← выход):
    [{'op': 'rectify', 'H': 3×3 исходный→выход, 'in': [W, H], 'out': [w, h]}]; фон и усиление линий геометрию не меняют. Выключено/не применилось — тот же объект, [], []."""
    if flags is None:
        rect, bg, ln, gr, ly, dk = flag_rect(), flag_bg(), flag_lines(), flag_grid(), flag_layers(), flag_deskew()
    else:                                                     # явный набор (служба с потоками): окружение не читаем
        rect, bg, ln, gr, ly, dk = (bool(flags.get(k)) for k in ('rect', 'bg', 'lines', 'grid', 'layers', 'deskew'))
    if not (rect or bg or ln or gr or ly or dk):
        return sheet, [], []
    from PIL import Image
    try:
        bgr = cv2.cvtColor(np.asarray(sheet.convert('RGB')), cv2.COLOR_RGB2BGR)
        out, ops, info = clean_bgr(bgr, rectify=rect, background=bg, lines=ln, grid=gr, layers=ly, deskew=dk)
    except Exception:  # noqa: BLE001 — чистка не должна ронять разбор: лист как есть
        return sheet, [], []
    if not ops:
        return sheet, [], []
    steps = []
    if 'deskew' in ops and 'deskew_H' in info:
        d = info['deskew']
        steps.append({'op': 'deskew', 'H': info['deskew_H'], 'angle_deg': d['angle_deg'], 'residual_deg': d['residual_deg'],
                      'in': [bgr.shape[1], bgr.shape[0]], 'out': [out.shape[1], out.shape[0]]})
    if 'rectify' in ops and 'rect_H' in info:
        steps.append({'op': 'rectify', 'H': info['rect_H'], 'in': [bgr.shape[1], bgr.shape[0]], 'out': [out.shape[1], out.shape[0]]})
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), ops, steps


def clean_sheet(sheet):
    """PIL RGB → (PIL RGB, ops) по флагам окружения; выключено/не применилось — тот же объект. Любой сбой шага — лист как есть."""
    out, ops, _ = clean_sheet_steps(sheet)
    return out, ops
