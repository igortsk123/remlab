"""Стенд «картинка планировки → стены → серое 3D» (T-20261109-02, план floorplan-raster-bench-01): чистые функции.

Путь OpenCV без нейросети: маска стен (цвет или тёмное + открытие) → панели → закрытие разрывов стен по строкам/столбцам
(с проверкой «торца стены» и стекла окна) → комнаты как связные области свободного места → подписи → масштаб RANSAC →
выпрямление контуров по семействам углов → полосы стен для выдавливания. Без внешних моделей; тесты — tests/floorplan/.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import cv2
import numpy as np


def empty_img(*arrs) -> bool:
    """Хоть один массив нулевой площади (окно вокруг точки за краем листа, пустой срез). OpenCV 5 на таком входе:
    connectedComponents* — авария процесса (segfault, не исключение — T-20261110-06), dilate/erode/morphologyEx/
    warpAffine — cv2.error. Проверять ДО вызова OpenCV от вычисленного окна/среза."""
    return any(a is None or np.ndim(a) < 2 or a.shape[0] == 0 or a.shape[1] == 0 for a in arrs)


# --- маски ------------------------------------------------------------------------------------------------------------

def remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    if empty_img(mask):
        return np.zeros(np.shape(mask), np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[lab].astype(np.uint8)


def wall_mask_blue(img: np.ndarray, min_area: int = 40) -> np.ndarray:
    """Синие стены (план A): тон 95–135 (OpenCV 0–180), насыщенность и яркость не малые."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 50)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return remove_small(m, min_area)


def wall_mask_dark(img: np.ndarray, thr: int, open_px: int, min_area: int = 60) -> np.ndarray:
    """Тёмные стены: порог серого + открытие квадратом `open_px` (тонкие линии, текст, дуги дверей уходят)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    m = (g < thr).astype(np.uint8)
    if open_px > 1:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (open_px, open_px)))
    return remove_small(m, min_area)


# --- маска стен для тонких линий и водяных знаков (T-20261109-09) ------------------------------------------------------
# Порог 125 + открытие 3 теряет стены в 1–2 px (E, F) и стены под полупрозрачным водяным знаком (B: 30 → ~100–140).
# Подходы сравнивались на A/B/C/E/F по корзинам (отчёт T-09, лог плана floorplan-raster-bench-01): «ширина штриха» (открытие по
# измеренной ширине длинных штрихов), «длинные линии» (открытие отрезком по семействам углов + досборка),
# «отрезки LSD» (детектор отрезков OpenCV, Apache-2.0), «гистерезис» (слабое тёмное, связанное с сильным).

def line_kernel(L: int, angle_deg: float) -> np.ndarray:
    """Структурный элемент «отрезок» длины L px под углом (градусы, как в `angle_families`: atan2(dy, dx), y вниз)."""
    L = max(3, int(L)) | 1
    k = np.zeros((L, L), np.uint8)
    c = (L - 1) / 2
    a = math.radians(angle_deg)
    s = c / max(abs(math.cos(a)), abs(math.sin(a)))          # на всю клетку: L px по ведущей оси
    dx, dy = math.cos(a) * s, math.sin(a) * s
    cv2.line(k, (int(round(c - dx)), int(round(c - dy))), (int(round(c + dx)), int(round(c + dy))), 1, 1)
    return k


def long_strokes(m: np.ndarray, L: int, angles=(0.0, 90.0)) -> np.ndarray:
    """Пиксели маски, лежащие на прямом штрихе длиной ≥ L px по одному из направлений (открытие отрезком).
    Текст и штриховка (короче L) уходят при любой толщине линии; стена в 1 px остаётся."""
    m = m.astype(np.uint8)
    out = np.zeros_like(m)
    seen = []
    for a in list(angles) + [0.0, 90.0]:
        a = float(a) % 180
        if any(angdiff(a, b) < 2 for b in seen):
            continue
        seen.append(a)
        out |= cv2.morphologyEx(m, cv2.MORPH_OPEN, line_kernel(L, a))
    return out


def grow_within(seed: np.ndarray, m: np.ndarray, steps: int) -> np.ndarray:
    """Условное наращивание: seed растёт по пикселям m не дальше steps px (углы, торцы и короткие простенки длинной
    линии возвращаются; текст, лишь касающийся стены, — только на steps px)."""
    cur = (seed > 0) & (m > 0)
    k = np.ones((3, 3), np.uint8)
    for _ in range(max(0, int(steps))):
        nxt = (cv2.dilate(cur.astype(np.uint8), k) > 0) & (m > 0)
        if (nxt == cur).all():
            break
        cur = nxt
    return cur.astype(np.uint8)


def hysteresis(gray: np.ndarray, thr: int, thr_hi: int) -> np.ndarray:
    """Тёмное с гистерезисом: сильное (< thr) + слабое (< thr_hi), связное с сильным. Стена под полупрозрачным
    водяным знаком светлее (B: ~100–140), но продолжает тёмную стену вне знака; сам знак (светлый) не связан."""
    strong = (gray < thr).astype(np.uint8)
    weak = (gray < thr_hi).astype(np.uint8)
    n, lab = cv2.connectedComponents(weak, connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(lab[strong > 0])] = True
    keep[0] = False
    return keep[lab].astype(np.uint8)


def long_stroke_width(m: np.ndarray, L: int) -> tuple[float, float]:
    """Длинные штрихи маски (без открытия): (медиана ширины, доля осевых пикселей шириной < 3 px); (0, 0) — нет."""
    ls = long_strokes(m, L)
    if not ls.any():
        return 0.0, 0.0
    # ширину меряем по самой маске (открытие отрезком срезает толщину диагоналей), на осевых пикселях длинных штрихов
    dt = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
    mx = cv2.dilate(dt, np.ones((3, 3), np.uint8))
    ridge = (dt >= 0.5) & (dt >= mx - 1e-6) & (ls > 0)
    v = 2 * dt[ridge]
    if not v.size:
        return 0.0, 0.0
    return float(np.median(v)), float((v < 3).mean())


def lsd_mask(gray: np.ndarray, dark: np.ndarray, L: int, max_gray: int) -> np.ndarray:
    """Отрезки LSD (OpenCV, Apache-2.0) длиной ≥ L px, тёмные вдоль (медиана серого по отрезку ≤ max_gray) →
    тёмные пиксели маски `dark` в полосе ±2 px вокруг отрезка (толщина — по самой картинке)."""
    lsd = cv2.createLineSegmentDetector()
    lines = lsd.detect(gray)[0]
    band = np.zeros(gray.shape, np.uint8)
    if lines is None:
        return band
    H, W = gray.shape
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        Lp = math.hypot(x2 - x1, y2 - y1)
        if Lp < L:
            continue
        n = int(Lp) + 1
        xs = np.clip(np.round(np.linspace(x1, x2, n)).astype(int), 0, W - 1)
        ys = np.clip(np.round(np.linspace(y1, y2, n)).astype(int), 0, H - 1)
        # край тёмной полосы — LSD идёт по границе; ищем тёмное в ±2 px поперёк
        dn = np.array([-(y2 - y1), x2 - x1]) / max(Lp, 1e-6)
        best = 255
        for s in (-2, -1, 0, 1, 2):
            xx = np.clip(np.round(xs + s * dn[0]).astype(int), 0, W - 1)
            yy = np.clip(np.round(ys + s * dn[1]).astype(int), 0, H - 1)
            best = min(best, float(np.median(gray[yy, xx])))
        if best <= max_gray:
            cv2.line(band, (int(round(x1)), int(round(y1))), (int(round(x2)), int(round(y2))), 1, 5)
    return (band & dark).astype(np.uint8)


THIN_SHARE = 0.15
THIN_T3 = 5          # медианная толщина стен после открытия 3 (px): ≤ 5 — лист тонких стен (E, F: 4; A, C, D, G: 6–8)     # «тонкие стены»: доля длинных штрихов уже 3 px


def wall_mask_auto(img: np.ndarray, mode: str, thr: int = 125, min_area: int = 60, thr_hi: int = 170,
                   thin_gray: int = 100) -> tuple[np.ndarray, dict]:
    """Маска стен тёмного листа без настройки под лист (T-09) → (маска, сведения о выборе).
    Общая часть: тёмное с гистерезисом (`hysteresis`, водяной знак), ширина длинных штрихов (`long_stroke_width`):
    толстые (медиана ≥ 12 px) — открытие 5, средние (> THIN_T3) — открытие 3, оба как было, без гистерезиса и
    добавок; режимы ниже включаются только на листе тонких стен (медиана ≤ THIN_T3):
      'base'   — без добавки (порог + открытие, как T-04, но с гистерезисом при thr_hi > thr);
      'width'  — открытие по ширине: P25 ширины длинных штрихов < 3 px → открытие 2 вместо 3;
      'lines'  — + длинные прямые штрихи (открытие отрезком по семействам углов) тёмного ядра (< thin_gray),
                 досборка углов/торцов по маске не дальше 1,5 L;
      'lsd'    — + тёмные пиксели вдоль длинных отрезков LSD."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    dark0 = (g < thr).astype(np.uint8)
    t3 = stroke_thickness(remove_small(cv2.morphologyEx(dark0, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), min_area))
    info = {'mode': mode, 'thr': thr, 'thr_hi': thr_hi, 't3': round(t3, 2)}
    if t3 >= 12:
        # толстые стены (B): открытие 5 — меньше текста; без гистерезиса и добавок: стена держится порогом,
        # а гистерезис наращивает на неё дуги дверей и мебель (B: гардероб 0,95×0,82 залит)
        info.update(open=5, thin=False)
        return remove_small(cv2.morphologyEx(dark0, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)), 120), info
    info['thin'] = t3 <= THIN_T3
    if not info['thin']:
        # средние стены (A, C, D, G: 6–8 px): открытие 3 их держит; добавки и гистерезис только портят (C: lines:170
        # ≤15 18 → 13) — как было
        info['open'] = 3
        return remove_small(cv2.morphologyEx(dark0, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), min_area), info
    # тонкие: гистерезис возвращает сглаженные края штриха (E: ядро стены 6–13, края 74–130)
    dark = hysteresis(g, thr, thr_hi) if thr_hi > thr else dark0
    L = 21
    med, thin_share = long_stroke_width(dark, L)
    info.update(w_med=round(med, 2), thin_share=round(thin_share, 3), open=3)
    m3 = remove_small(cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), min_area)
    base = m3
    if mode == 'width':
        if thin_share >= THIN_SHARE:
            info['open'] = 2
            # открытие 2×2 без сдвига: у чётного ядра morphologyEx сдвигает маску на 1 px — эрозия и дилатация
            # с зеркальными якорями
            k2 = np.ones((2, 2), np.uint8)
            er = cv2.erode(dark, k2, anchor=(0, 0))
            base = remove_small(cv2.dilate(er, k2, anchor=(1, 1)), min_area)
        return base, info
    if mode == 'lines':
        fams = angle_families(m3) if m3.any() else [0.0, 90.0]
        core = (g < thin_gray).astype(np.uint8) & dark
        ls = long_strokes(core, L, fams)
        ls = grow_within(ls, dark, int(1.5 * L))
        info['added_px'] = int(((ls > 0) & (base == 0)).sum())
        return remove_small(base | ls, min_area), info
    if mode == 'lsd':
        ls = lsd_mask(g, dark, L, thin_gray)
        info['added_px'] = int(((ls > 0) & (base == 0)).sum())
        return remove_small(base | ls, min_area), info
    return base, info


def stroke_thickness(mask: np.ndarray) -> float:
    """Медианная толщина штриха маски, px: 2·dt на осевых пикселях (локальные максимумы distance transform)."""
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    mx = cv2.dilate(dt, np.ones((3, 3), np.uint8))
    ridge = (dt > 0.9) & (dt >= mx - 1e-6)
    v = dt[ridge]
    return float(2 * np.median(v)) if v.size else 0.0


# --- залитые стрелки «вход / вверх по лестнице» (T-20261111-13) --------------------------------------------------------
# Британские листы рисуют входы и лестничные марши залитыми чёрными стрелками ~1,5 t × 1 t — после порога и открытия маски это
# отдельный кусок «стены». rgK5… (Nethercote, 23 таких куска — все стрелки): стрелка «→» в коридоре под Bedroom 3 и торец его
# стены давали «дверь» 43 см у угла спальни — ядро её резало (отказ opening_cut_by_core), спальня без мебели; стрелка в проёме
# Bedroom 8 → Playroom делила проём надвое. Признак — форма, не размер: малые отдельные куски бывают и стенами (столб, обрубок
# перегородки — iT0XpK…, 4y0opq…). Стрелка — головка-треугольник (ширина поперёк оси плавно сходит на нет) и древко уже головки.
ARROW_L_T = 3.0       # кусок не длиннее 3 толщин стены листа (стрелки rgK — 1,5 t)
ARROW_HEAD_T = (0.75, 1.6)  # ширина головки в толщинах стены листа (rgK — 1–1,1 t); уже — штрих/полоска (4y0opq, QFfI: 0,5 t)
ARROW_LEN_HEAD = 1.3  # длина стрелки — не меньше стольких ширин головки (rgK — 1,5–1,75; квадратные пятна — ~1,1)
ARROW_TIP = 0.35      # кончик головки — не шире этой доли наибольшей ширины
ARROW_PEAK = 0.85     # «наибольшая ширина» — срезы не уже этой доли максимума
ARROW_RISE = 0.35     # головка нарастает от кончика до наибольшей ширины не меньше чем за эту долю ширины (≥ 3 срезов) — треугольник
ARROW_SHAFT = 0.75    # древко (срезы после головки) — по медиане не шире этой доли наибольшей ширины
ARROW_SHAFT_LEN = 0.3  # древко — не короче этой доли длины
ARROW_FLAT = 0.7      # доля срезов древка в пределах ±max(1 px, 0,15 ширины) от его медианы — древко ровное


def _axis_profile(ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Ширина пятна поперёк главной оси: число пикселей в каждом срезе толщиной 1 px вдоль неё."""
    pts = np.column_stack([xs, ys]).astype(float)
    c = pts.mean(0)
    if len(pts) < 3:
        return np.zeros(0, int)
    _, v = np.linalg.eigh(np.cov((pts - c).T))
    s = np.round((pts - c) @ v[:, 1]).astype(int)
    return np.bincount(s - s.min())


def arrow_profile(prof, t: float | None = None) -> bool:
    """Профиль ширины (`_axis_profile`) — стрелка: кончик ≤ ARROW_TIP ширины, головка плавно (≥ ARROW_RISE ширины срезов, без
    сужений) нарастает до наибольшей ширины, держит её не дольше, чем нарастала (±1 срез), затем ровное древко (≥ ARROW_SHAFT_LEN длины,
    медиана ≤ ARROW_SHAFT ширины). С `t` — ширина головки в ARROW_HEAD_T толщин стены. Прямоугольник (столб, обрубок стены) —
    ширина постоянна; уступ (Г-обрубок) — головка без нарастания; квадратное пятно — короче ARROW_LEN_HEAD ширин."""
    prof = np.asarray(prof, float)
    n = len(prof)
    if n < 5:
        return False
    m = float(prof.max())
    if n < ARROW_LEN_HEAD * m:
        return False
    if t and not (ARROW_HEAD_T[0] * t <= m <= ARROW_HEAD_T[1] * t):
        return False
    tol = max(1.0, 0.15 * m)
    for p in (prof, prof[::-1]):                      # кончик — в начале p
        if p[0] > ARROW_TIP * m:
            continue
        peak = np.flatnonzero(p >= ARROW_PEAK * m)
        j, k = int(peak[0]), int(peak[-1])
        if j < max(3, ARROW_RISE * m) or k - j > j:
            continue
        if np.any(np.diff(p[:j + 1]) < -max(1.0, 0.1 * m)):
            continue
        shaft = p[k + 1:]
        if len(shaft) < ARROW_SHAFT_LEN * n:
            continue
        med = float(np.median(shaft))
        if med <= ARROW_SHAFT * m and np.mean(np.abs(shaft - med) <= tol) >= ARROW_FLAT:
            return True
    return False


def arrow_glyphs(wall: np.ndarray, gray: np.ndarray, thr: int, t: float) -> np.ndarray:
    """Отдельные куски маски стен — залитые стрелки (`arrow_profile`) → маска к снятию. Форма — по пикселям серого темнее порога
    маски (`thr`) у куска, а не по маске: открытие маски скругляет кончик головки."""
    out = np.zeros(np.shape(wall), np.uint8)
    if empty_img(wall, gray) or t <= 0:
        return out
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall.astype(np.uint8), connectivity=8)
    H, W = wall.shape
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if max(w, h) > ARROW_L_T * t:
            continue
        X0, Y0, X1, Y1 = max(0, x - 2), max(0, y - 2), min(W, x + w + 2), min(H, y + h + 2)
        dark = (gray[Y0:Y1, X0:X1] < thr).astype(np.uint8)
        k, lk = cv2.connectedComponents(dark, connectivity=8)
        ids = np.unique(lk[(lab[Y0:Y1, X0:X1] == i) & (dark > 0)])
        ys, xs = np.nonzero(np.isin(lk, ids[ids > 0]))
        if len(ys) and arrow_profile(_axis_profile(ys, xs), t):
            out[Y0:Y1, X0:X1][lab[Y0:Y1, X0:X1] == i] = 1
    return out


THIN_PART_REL = 0.4     # T-20261110-33: перегородки тоньше этой доли t листа — «смешанная толщина» (aRQVC9: 8–10 px при t 34)
THIN_PART_MIN_PX = 4.0   # тоньше — волосяные линии, не стены
THIN_PART_SHARE = 0.03   # доля пикселей стен в таких перегородках, ниже — шум маски


def thin_partition_t(wall: np.ndarray, t: float) -> float | None:
    """T-20261110-33: толщина тонких перегородок листа (px), если на листе стены двух толщин: наружные/несущие t (медиана всех)
    и межкомнатные заметно тоньше (< THIN_PART_REL·t). Тонкое — то, что открытие ядром ~0,6·t стирает. None — толщина одна."""
    k = max(3, int(round(0.6 * t))) | 1
    w = (wall > 0).astype(np.uint8)
    thick = cv2.morphologyEx(w, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    part = (w > 0) & (thick == 0)
    if part.sum() < THIN_PART_SHARE * max(1, int(w.sum())):
        return None
    tp = stroke_thickness(part)
    return tp if THIN_PART_MIN_PX <= tp < THIN_PART_REL * t else None


GREY_HI = 165            # T-20261110-38: серые перегородки (Этажи: 132–148 при чёрных наружных 47 и паркете/знаке ≥ 180)
GREY_THICK_T = 12        # только на листе толстых тёмных стен (как открытие 5 в `bench.auto_cfg`)
GREY_L_T = 2.5           # прямой штрих ≥ 2,5 толщины наружной стены (мебель, текст и штриховка короче или тоньше)
GREY_SHARE = 0.03        # добавка ≥ 3 % пикселей тёмных стен — иначе шум, лист не трогаем
GREY_T_REL = 0.6         # и тоньше 0,6 наружной: перегородка, а не стена под водяным знаком


def grey_partitions(gray: np.ndarray, dark: np.ndarray, thr: int, hi: int = GREY_HI) -> tuple[np.ndarray, dict]:
    """T-20261110-38: межкомнатные перегородки СЕРЫМ при толстых чёрных наружных стенах (планы застройщиков РФ: порог тёмного
    125 их не видит — квартира выходила одной комнатой). Серое (< hi) без волосяных линий (открытие 3: мебель, дуги, плитка в
    1–2 px уходят) → только длинные прямые штрихи по семействам углов стен (`long_strokes`, ≥ GREY_L_T·t) → без кромок самих
    тёмных стен (открытие 3 добавки: сглаженный край чёрной стены — 1–2 px). Берётся, только если лист толстых стен,
    добавки ≥ GREY_SHARE тёмного и её толщина в [THIN_PART_MIN_PX; GREY_T_REL·t). → (добавка 0/1, сведения)."""
    d = (dark > 0).astype(np.uint8)
    t = stroke_thickness(d)
    info = {'t': round(t, 2), 'used': False}
    if t < GREY_THICK_T or thr >= hi:
        return np.zeros_like(d), info
    grey = cv2.morphologyEx((gray < hi).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fams = angle_families(d) if d.any() else [0.0, 90.0]
    L = max(3, int(round(GREY_L_T * t)))
    ls = long_strokes(grey, L, fams)
    # короткие куски перегородок (косяк двери у стены, простенок 0,3 м) — досборка от длинных штрихов и тёмных стен по серому
    # не дальше L: без них у проёма нет фланга и дверь не закрывается
    ls = grow_within(((ls > 0) | (d > 0)).astype(np.uint8), grey | d, L)
    add = ((ls > 0) & (d == 0)).astype(np.uint8)
    add = cv2.morphologyEx(add, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    add = drop_wall_gap_fill(add, d, t)
    tp = stroke_thickness(add) if add.any() else 0.0
    share = float(add.sum()) / max(1, int(d.sum()))
    info.update(tp=round(tp, 2), share=round(share, 3))
    if share < GREY_SHARE or not THIN_PART_MIN_PX <= tp < GREY_T_REL * t:
        return np.zeros_like(d), info
    info['used'] = True
    return add, info


GREY_GAP_RUN_T = 2.0     # тёмная стена за обоими концами серого штриха по его оси — не короче 2 толщин: штрих лежит в проёме


def drop_wall_gap_fill(add: np.ndarray, dark: np.ndarray, t: float) -> np.ndarray:
    """T-20261110-38 (регресс rpJz…/yb3…): прямой серый штрих, который по своей оси с ОБОИХ концов упирается в продолжение
    тёмной стены (≥ GREY_GAP_RUN_T·t вдоль оси), лежит в разрыве стены — это значок окна или порог двери, а не перегородка:
    взятый, он заделывал все окна и двери листа серых стен. Перегородка примыкает к стене торцом (за концом — толщина
    стены поперёк, потом комната) — остаётся. Изогнутые и угловые куски не трогаем. → добавка без таких штрихов."""
    n, cc, stats, _ = cv2.connectedComponentsWithStats(add, connectivity=8)
    if n <= 1:
        return add
    reach = max(3, int(round(GREY_GAP_RUN_T * t)))
    H, W = dark.shape
    out = add.copy()
    for i in range(1, n):
        x0, y0, w, h = stats[i, :4]
        ys, xs = np.nonzero(cc[y0:y0 + h, x0:x0 + w] == i)
        if len(xs) < 3:
            continue
        pts = np.column_stack([xs + x0, ys + y0]).astype(np.float64)
        c = pts.mean(axis=0)
        ev, evec = np.linalg.eigh(np.cov((pts - c).T))
        u = evec[:, 1]
        pr = (pts - c) @ u
        width = float(len(xs)) / max(1.0, float(pr.max() - pr.min() + 1))
        if pr.max() - pr.min() + 1 < 3 * width:
            continue                                   # не прямой штрих
        fill = True
        for end, s in ((pr.max(), 1.0), (pr.min(), -1.0)):
            run = 0
            for k in range(1, reach + 4):
                x, y = (c + (end + s * k) * u).round().astype(int)
                if not (0 <= x < W and 0 <= y < H):
                    break
                if dark[y, x]:
                    run += 1
                    if run >= reach:
                        break
                elif run or k > 3:
                    break                              # тёмное кончилось (или не началось у конца) — не продолжение стены
            if run < reach:
                fill = False
                break
        if fill:
            out[cc == i] = 0
    return out


# --- разрывы стен (двери, окна) ------------------------------------------------------------------------------------------

def _runs(row: np.ndarray):
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def perp_reach(wall: np.ndarray):
    """Для каждого пикселя — расстояние до ближайшей стены вверх и вниз по столбцу (inf, если стены нет)."""
    H = wall.shape[0]
    ar = np.arange(H)[:, None].repeat(wall.shape[1], 1)
    up = np.maximum.accumulate(np.where(wall > 0, ar, -1), axis=0)
    dn = np.minimum.accumulate(np.where(wall > 0, ar, H + 10)[::-1], axis=0)[::-1]
    du = np.where(up >= 0, ar - up, np.inf)
    dd = np.where(dn <= H, dn - ar, np.inf)
    return du, dd


def bridge_lines(wall: np.ndarray, max_gap: int, min_flank: int, both_flanks: bool = False,
                 reach: float | None = None) -> np.ndarray:
    """Закрыть разрывы ≤ max_gap ВДОЛЬ СТРОК: пиксели между двумя кусками стены на одной строке, если хотя бы один
    (или оба — `both_flanks`) кусок длиннее `min_flank` — то есть это торец стены, идущей вдоль строки, а не поперечная
    стена коридора. `reach`: поперёк разрыва хотя бы в одну сторону должна быть стена ближе reach px — иначе это
    пустота между отдельными панелями/постройками (с обеих сторон наружа), а не проём. Для столбцов — на `wall.T`."""
    add = np.zeros_like(wall, dtype=np.uint8)
    du = dd = None
    if reach is not None:
        du, dd = perp_reach(wall)
    for y in range(wall.shape[0]):
        row = wall[y]
        if not row.any():
            continue
        s, e = _runs(row)
        L = e - s
        longs = np.flatnonzero(L >= min_flank)
        for i in range(len(s) - 1):
            gap = s[i + 1] - e[i]
            if gap <= 0 or gap > max_gap:
                continue
            lf, rf = L[i], L[i + 1]
            if both_flanks:
                ok = min(lf, rf) >= min_flank
            else:
                ok = max(lf, rf) >= min_flank
                if not ok and len(longs):
                    # дверь между двумя короткими кусками (угол, Т-стык), но линия стены рядом есть: длинный кусок
                    # на этой же строке не дальше max_gap от разрыва — это стена вдоль строки, а не коридор поперёк
                    d = np.where(e[longs] <= e[i], e[i] - e[longs], s[longs] - s[i + 1])
                    ok = bool((d <= max_gap).any())
            if ok and du is not None:
                mid = (e[i] + s[i + 1]) // 2
                ok = min(du[y, mid], dd[y, mid]) <= reach
            if ok:
                add[y, e[i]:s[i + 1]] = 1
    return add


def extend_corners(wall: np.ndarray, reach: int, min_flank: int, skip: np.ndarray | None = None) -> np.ndarray:
    """Достроить угол, у которого нет вершины (угол спрятан под элементом интерфейса, как у A слева сверху, или
    окно в самом углу): висячий конец длинного куска стены продлевается вдоль строки (столбца) на ≤ reach, и
    продление остаётся только до самого дальнего пересечения с продлением перпендикулярной стены.
    skip — концы, которые не продлеваем (T-20261110-03/2: торцы со скосом, `bevel_end_zone` — строки скоса и точки-косяка
    иначе продлеваются поперёк проёма: прямая дверь делится надвое, косая — замыкается каморкой)."""
    H, W = wall.shape

    def segs(m, sk):
        out = []
        for y in range(m.shape[0]):
            row = m[y]
            if not row.any():
                continue
            s, e = _runs(row)
            for i in range(len(s)):
                if e[i] - s[i] < min_flank:
                    continue
                nxt = s[i + 1] if i + 1 < len(s) else None
                prv = e[i - 1] if i > 0 else None
                if (nxt is None or nxt - e[i] > reach) and not (sk is not None and sk[y, e[i] - 1]):
                    out.append((y, e[i], min(m.shape[1], e[i] + reach), +1))
                if (prv is None or s[i] - prv > reach) and not (sk is not None and sk[y, s[i]]):
                    out.append((y, max(0, s[i] - reach), s[i], -1))
        return out

    sh, sv = segs(wall, skip), segs(wall.T, None if skip is None else skip.T)
    eh = np.zeros((H, W), np.uint8)
    ev = np.zeros((W, H), np.uint8)
    for y, a, b, _ in sh:
        eh[y, a:b] = 1
    for x, a, b, _ in sv:
        ev[x, a:b] = 1
    cross = eh & ev.T
    add = np.zeros((H, W), np.uint8)
    for y, a, b, d in sh:
        c = np.flatnonzero(cross[y, a:b])
        if c.size:
            if d > 0:
                add[y, a:a + c.max() + 1] = 1
            else:
                add[y, a + c.min():b] = 1
    addT = np.zeros((W, H), np.uint8)
    crossT = cross.T
    for x, a, b, d in sv:
        c = np.flatnonzero(crossT[x, a:b])
        if c.size:
            if d > 0:
                addT[x, a:a + c.max() + 1] = 1
            else:
                addT[x, a + c.min():b] = 1
    return ((add | addT.T) & (wall == 0)).astype(np.uint8)


def xy_cut(mask: np.ndarray, min_gap: int, box=None, depth: int = 0, max_open: int | None = None) -> list[tuple]:
    """Рекурсивная нарезка листа по пустым полосам (нет ни одного пикселя стены) шириной ≥ min_gap → рамки
    (x0, y0, x1, y1). Проёмы и окна полосы через всю панель не дают — режутся только отдельные планы.
    T-20261111-11: у узкой постройки окно и ворота друг напротив друга (гараж bs30: окно 1,5 м сверху, ворота 1,9 м снизу)
    дают пустую полосу через всю постройку — её края не стены вдоль полосы, а торцы стен поперёк неё, попарно на одной линии
    (`opening_band`). Такая полоса не шире `max_open` — проёмы, а не промежуток между планами: не режем (None — режем всё,
    как прежде)."""
    if box is None:
        box = (0, 0, mask.shape[1], mask.shape[0])
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    if not sub.any():
        return []
    ys, xs = np.nonzero(sub)
    x0, x1, y0, y1 = x0 + xs.min(), x0 + xs.max() + 1, y0 + ys.min(), y0 + ys.max() + 1
    sub = mask[y0:y1, x0:x1]
    if depth > 12:
        return [(x0, y0, x1, y1)]
    for axis in (0, 1):
        prof = sub.any(axis=axis)            # axis=0 → по столбцам
        s, e = _runs(~prof)
        cuts = [(a, b) for a, b in zip(s, e) if b - a >= min_gap and a > 0 and b < len(prof)
                and not (max_open and b - a <= max_open and opening_band(sub if axis == 0 else sub.T, a, b, min_gap))]
        if cuts:
            out, prev = [], 0
            for a, b in cuts + [(len(prof), len(prof))]:
                nb = (x0 + prev, y0, x0 + a, y1) if axis == 0 else (x0, y0 + prev, x1, y0 + a)
                out += xy_cut(mask, min_gap, nb, depth + 1, max_open)
                prev = b
            return out
    return [(x0, y0, x1, y1)]


FRAG_T = 4.0         # кусок xy_cut меньше 4 толщин стены по меньшей стороне — в нём не поместится комната: обломок стены, не план
FRAG_STROKE_T = 3.0   # «стена»: прямой штрих длиной ≥ 3 t …
FRAG_THICK = (0.5, 1.6)  # … и толщиной 0,5–1,6 t (буквы, роза ветров, тонкая рамка — не стены)


def merge_fragments(mask: np.ndarray, regions: list[tuple], t: float, angles=(0.0, 90.0)) -> list[tuple]:
    """T-20261111-09: обломки стены, отрезанные `xy_cut`, — к ближайшему куску. Окна во всю толщину стены (Giraffe360 рисует их
    белым прямоугольником) рвут стену; у гостиной TGva… окна в левой и правой стене на одной высоте — полоса без стены через всю
    панель, и верхняя стена гостиной ушла в отдельные «планы» 2,1 t и 2,6 t высотой: окна между кусками не закрывались, наружа
    залила гостиную и прихожую, все двери стали «наружными» → окнами. Кусок — обломок, если по меньшей стороне < FRAG_T·t (комната
    не поместится) и это стена: прямой штрих ≥ FRAG_STROKE_T·t толщиной FRAG_THICK·t. Буквы, роза ветров — остаются отдельно.
    Слитый кусок — общей рамкой с ближайшим (по зазору рамок); повтор, пока сливается."""
    if t <= 0 or len(regions) < 2:
        return list(regions)
    regs = [tuple(int(v) for v in r) for r in regions]

    def fragment(r):
        x0, y0, x1, y1 = r
        if min(x1 - x0, y1 - y0) >= FRAG_T * t:
            return False
        m = np.pad(mask[y0:y1, x0:x1] > 0, 1)          # рамка — по краю стены: без поля толщина у края удваивается
        ls = long_strokes(m, int(round(FRAG_STROKE_T * t)), angles)
        if not ls.any():
            return False
        th = stroke_thickness(ls)
        return FRAG_THICK[0] * t <= th <= FRAG_THICK[1] * t

    def gap(a, b):
        dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
        dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
        return math.hypot(dx, dy)

    changed, merged = True, False
    while changed and len(regs) > 1:
        changed = False
        for i, r in enumerate(regs):
            if not fragment(r):
                continue
            j = min((k for k in range(len(regs)) if k != i), key=lambda k: gap(r, regs[k]))
            o = regs[j]
            u = (min(r[0], o[0]), min(r[1], o[1]), max(r[2], o[2]), max(r[3], o[3]))
            regs = [q for k, q in enumerate(regs) if k not in (i, j)] + [u]
            changed = merged = True
            break
    return regs if merged else list(regions)


OPEN_EDGE_MAX = 0.5    # полоса-проём: строки с торцами с обеих сторон — не больше половины высоты постройки


def opening_band(sub: np.ndarray, a: int, b: int, min_gap: int) -> bool:
    """Пустая полоса столбцов [a, b) маски `sub` — проём(ы) одной постройки (T-20261111-11): строки, где стена есть у края
    полосы с ОБЕИХ сторон (в полосе шириной min_gap/2), — это торцы стен поперёк полосы на одной линии; их ≥ 2 куска (стена
    сверху и снизу) и вместе ≤ OPEN_EDGE_MAX высоты. Два отдельных плана рядом: их боковые стены вдоль полосы дают общие
    строки сплошь (один кусок на большую часть высоты). Край — min_gap/2, не сама кромка: проёмы напротив бывают разной
    ширины (гараж bs30: окно 1,5 м, ворота 1,9 м — торец ворот на 0,3 м дальше края полосы); боковая стена узкой постройки
    в ту же полосу попадает только с одной стороны.
    Торцы — по краям постройки: первый кусок у начала, последний у конца того, что есть у краёв полосы (стены по бокам
    проёма). Надпись над планом (заголовок «First Floor» напротив верхней стены с окнами) стоит посередине — это не проём
    (T-11/2: лист 4y0opq склеивал заголовок и подвал с планом)."""
    k = max(3, min_gap // 2)
    left = sub[:, max(0, a - k):a].any(axis=1)
    right = sub[:, b:b + k].any(axis=1)
    span = int(np.count_nonzero(sub.any(axis=1)))
    both = left & right
    if not span or both.sum() > OPEN_EDGE_MAX * span:
        return False
    s, e = _runs(both)
    if len(s) < 2:
        return False
    ext = np.flatnonzero(left | right)
    return bool(s[0] <= ext[0] + 2 * k and e[-1] >= ext[-1] + 1 - 2 * k)


def rotate_mask(m: np.ndarray, angle_deg: float, shape=None, inverse_of=None):
    """Поворот маски вокруг центра с расширением холста; возвращает (маска, матрица). Обратный — `unrotate_mask`."""
    h, w = m.shape
    c = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(c, angle_deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    M[0, 2] += nw / 2 - c[0]
    M[1, 2] += nh / 2 - c[1]
    r = cv2.warpAffine(m.astype(np.uint8), M, (nw, nh), flags=cv2.INTER_NEAREST)
    return r, M


def unrotate_mask(r: np.ndarray, M: np.ndarray, shape) -> np.ndarray:
    Mi = cv2.invertAffineTransform(M)
    return cv2.warpAffine(r.astype(np.uint8), Mi, (shape[1], shape[0]), flags=cv2.INTER_NEAREST)


def bridge_parts(wall: np.ndarray, max_gap: int, min_flank: int, angles=(0.0,), both_flanks=False,
                 reach: float | None = None) -> list[np.ndarray]:
    """Разрывы вдоль строк и вдоль столбцов для каждого семейства углов (0 — оси картинки; диагональ C — свой угол)
    — ОТДЕЛЬНЫМИ масками: две соседние двери из разных проходов не должны слиться в одно пятно до проверки."""
    parts = []
    for a in angles:
        if abs(a) < 0.5:
            parts.append(bridge_lines(wall, max_gap, min_flank, both_flanks, reach))
            parts.append(bridge_lines(wall.T, max_gap, min_flank, both_flanks, reach).T.copy())
        else:
            r, M = rotate_mask(wall, a)
            parts.append(unrotate_mask(bridge_lines(r, max_gap, min_flank, both_flanks, reach), M, wall.shape))
            parts.append(unrotate_mask(bridge_lines(r.T, max_gap, min_flank, both_flanks, reach).T.copy(), M, wall.shape))
    return [(p & (wall == 0)).astype(np.uint8) for p in parts]


ISLE_ASPECT = 1.3   # стрелка вытянута (7×12, 9×13 px); угол стены между двумя проёмами, колонна — почти квадрат (13×13)
ISLE_FILL = 0.9     # и не сплошной прямоугольник (стрелки 0,65–0,89); простенок между стеклянными дверьми — 0,90–0,97


def islands(wall: np.ndarray, max_px: float) -> np.ndarray:
    """Отдельные куски маски стены не больше max_px по обеим сторонам рамки, вытянутые и не сплошные, — значки на полу
    (стрелки высоты скоса и лестниц), не стена: от них проём не закрываем (T-20261111-09/3). Квадратный кусок (угол стены
    между дверью и окном — rgK5… Pool room, колонна) и сплошной простенок — стена. → маска значков."""
    n, lab, st, _ = cv2.connectedComponentsWithStats((wall > 0).astype(np.uint8), connectivity=8)
    w, h, a = st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_HEIGHT], st[1:, cv2.CC_STAT_AREA]
    lo, hi = np.minimum(w, h), np.maximum(w, h)
    small = np.zeros(n, bool)
    small[1:] = (hi <= max_px) & (hi >= ISLE_ASPECT * lo) & (a < ISLE_FILL * w * h)
    return small[lab]


def bridge_all(wall: np.ndarray, max_gap: int, min_flank: int, angles=(0.0,), both_flanks=False,
               reach: float | None = None) -> np.ndarray:
    add = np.zeros_like(wall, dtype=np.uint8)
    for p in bridge_parts(wall, max_gap, min_flank, angles, both_flanks, reach):
        add |= p
    return add


# --- T-20261110-03: косая дверь в углу комнаты ------------------------------------------------------------------------------
# Дверь срезает угол комнаты наискось: обе стены угла кончаются, не дойдя до вершины, проём — между их торцами (~45°).
# Закрытие вдоль строк/столбцов (`bridge_lines`) его не видит: ни на одной строке нет стены по обе стороны разрыва; `extend_corners`
# достраивает угол, только если оба торца ближе 0,6 м к вершине (у двери 0,8–0,9 м по диагонали ноги ~0,6 м — мимо).
# Кандидат — отрезок между торцами двух перпендикулярных стен, чьи продолжения сходятся в свободной вершине угла; приёмка
# (ширина, дуга створки) — у вызывающего, как у прямой двери (`bench._analyze`).

def _end_faces(m: np.ndarray, min_flank: int, t: float) -> list[dict]:
    """Торцы кусков стены вдоль строк: подряд идущие строки, где кусок длиной ≥ min_flank кончается в одном месте (±2 px
    на строку — торец со скосом). → [{d: +1 свободно справа / −1 слева, y0, y1, tip — крайний px торца}]."""
    faces, live = [], []
    for y in range(m.shape[0]):
        row = m[y]
        if not row.any():
            live = []
            continue
        s, e = _runs(row)
        ends = [(+1, b - 1) for a, b in zip(s, e) if b - a >= min_flank and b < m.shape[1]]
        ends += [(-1, a) for a, b in zip(s, e) if b - a >= min_flank and a > 0]
        nxt = []
        for d, x in ends:
            f = next((f for f in live if f['d'] == d and abs(f['x'] - x) <= 2 and f['y1'] == y - 1), None)
            if f is None:
                f = {'d': d, 'y0': y, 'y1': y, 'x': x, 'tip': x}
                faces.append(f)
            f['y1'], f['x'] = y, x
            f['tip'] = max(f['tip'], x) if d > 0 else min(f['tip'], x)
            nxt.append(f)
        live = nxt
    hi = 3 * max(float(t), 1.0) + 2
    H = m.shape[0]
    out = []
    for f in faces:
        if not 2 <= f['y1'] - f['y0'] + 1 <= hi:
            continue
        # стена идёт ВДОЛЬ строки: за торцом на min_flank — сплошная полоса, строки над и под ней свободны. Ступеньки стены
        # другого семейства (в этой рамке — наклонной) дают «торцы» на каждой строке, но над/под ними та же стена со сдвигом
        a, b = (f['tip'] - min_flank + 1, f['tip'] + 1) if f['d'] > 0 else (f['tip'], f['tip'] + min_flank)
        a, b = max(0, a), min(m.shape[1], b)
        if b - a < 2 or m[f['y0']:f['y1'] + 1, a:b].mean() < 0.9:
            continue
        # край стены рваный на 1 px (сжатие, поворот листа) — строка через одну от грани уже свободна; у ступенек наклонной
        # стены обе соседние строки заняты на ≥ 0,5
        side = [min(m[y, a:b].mean() if 0 <= y < H else 0.0 for y in (y0 + k, y0 + 2 * k))
                for y0, k in ((f['y0'], -1), (f['y1'], +1))]
        if any(s > 0.3 for s in side):
            continue
        out.append(f)
    return out


def _corner_pairs(w: np.ndarray, closed: np.ndarray, max_px: float, min_flank: int, t: float) -> list[tuple]:
    """Пары «торец стены вдоль строк × торец стены вдоль столбцов» (рамка уже повёрнута к семейству): продолжения обеих стен
    сходятся в вершине угла за торцами, полосы продолжений до вершины свободны в `closed` (стены + принятые закрытия: угол
    не нарисован и прямым закрытием не закрыт), между торцами ≤ max_px и по линии между ними нет стен. Каждый торец — в одной
    паре, ближние первыми. → [четырёхугольник (4 точки x, y)]: от грани торца одной стены до грани торца другой — как
    прямоугольник прямого закрытия между косяками (примыкает к обеим граням целиком, щели вдоль торца нет)."""
    hs, vs = _end_faces(w, min_flank, t), _end_faces(w.T, min_flank, t)
    if not hs or not vs:
        return []
    H, W = w.shape
    cands = []
    for i, h in enumerate(hs):
        yc = (h['y0'] + h['y1']) / 2
        for j, v in enumerate(vs):                       # у v строки — это столбцы x0..x1, tip — y торца
            x0, x1 = v['y0'], v['y1']
            gh = x0 - h['tip'] - 1 if h['d'] > 0 else h['tip'] - x1 - 1   # свободно от торца h до полосы v
            gv = h['y0'] - v['tip'] - 1 if v['d'] > 0 else v['tip'] - h['y1'] - 1
            if gh < 1 or gv < 1 or math.hypot(gh, gv) > max_px:
                continue
            bh = closed[h['y0']:h['y1'] + 1, h['tip'] + 1:x1 + 1] if h['d'] > 0 else closed[h['y0']:h['y1'] + 1, x0:h['tip']]
            bv = closed[v['tip'] + 1:h['y1'] + 1, x0:x1 + 1] if v['d'] > 0 else closed[h['y0']:v['tip'], x0:x1 + 1]
            if not bh.size or not bv.size or bh.mean() > 0.05 or bv.mean() > 0.05:
                continue
            xc = (x0 + x1) / 2
            quad = [(h['tip'], h['y0']), (h['tip'], h['y1']), (x0, v['tip']), (x1, v['tip'])]
            a1 = (h['tip'] + h['d'], yc)                 # сам проём: от грани торца до грани торца
            a2 = (xc, v['tip'] + v['d'])
            n = int(math.hypot(a2[0] - a1[0], a2[1] - a1[1])) + 2
            xs = np.clip(np.round(np.linspace(a1[0], a2[0], n)).astype(int), 0, W - 1)
            ys = np.clip(np.round(np.linspace(a1[1], a2[1], n)).astype(int), 0, H - 1)
            if closed[ys, xs].any():
                continue
            cands.append((math.hypot(gh, gv), i, j, quad))
    out, used_h, used_v = [], set(), set()
    for _, i, j, quad in sorted(cands, key=lambda c: c[:3]):
        if i in used_h or j in used_v:
            continue
        used_h.add(i)
        used_v.add(j)
        out.append(quad)
    return out


def corner_cut_doors(wall: np.ndarray, closed: np.ndarray, max_px: float, min_flank: int, t: float,
                     angles=(0.0,)) -> list[np.ndarray]:
    """Кандидаты закрытия косого проёма в углу (по каждому семейству углов, как `bridge_parts`): четырёхугольник между гранями
    торцов двух стен угла → отдельные маски, только пиксели вне `closed` (стены + уже принятые закрытия)."""
    out = []
    for a in angles:
        if abs(a) < 0.5:
            rw, rc, M = wall, closed, None
        else:
            rw, M = rotate_mask(wall, a)
            rc, _ = rotate_mask(closed, a)
        pairs = _corner_pairs(rw, rc, max_px, min_flank, t)[:255]
        if not pairs:
            continue
        cand = np.zeros(rw.shape, np.uint8)
        for k, quad in enumerate(pairs, 1):
            cv2.fillConvexPoly(cand, cv2.convexHull(np.array(quad, np.int32)), k)
        if M is not None:
            cand = unrotate_mask(cand, M, wall.shape)
        for k in range(1, len(pairs) + 1):
            m = ((cand == k) & (closed == 0)).astype(np.uint8)
            if m.any():
                out.append(m)
    return out


# --- T-20261110-03/2: торец стены со скосом (рисунок PlanUp и британских агентств) -----------------------------------------
# Прямая стена не обрывается торцом, а в конце поворачивает коротким скосом ~45° (1–1,5 толщины) к проёму, на конце скоса —
# точка-косяк; у косой двери оба скоса лежат на диагонали угла, проём — между точками. Торцы «вдоль строк» (`_end_faces`) такой
# конец не видят (грань — не ровная полоса). Торец ищем по скелету стены: конец скелета — точка торца (центр точки-косяка),
# направление последних ~t px — направление скоса, отрезок дальше (2–3,5 t) — направление самой стены.

_NB8 = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))   # соседи P2..P9 (y, x), по часовой от севера


def _nb_luts():
    """Таблицы по 8-битному коду соседей: два подшага утончения Чжана–Суэня и «конец линии» (сосед один или два смежных)."""
    zs1, zs2, end = np.zeros(256, bool), np.zeros(256, bool), np.zeros(256, bool)
    for c in range(256):
        p = [(c >> i) & 1 for i in range(8)]
        b = sum(p)
        a = sum(1 for i in range(8) if not p[i] and p[(i + 1) % 8])
        end[c] = b == 1 or (b == 2 and a == 1)
        if 2 <= b <= 6 and a == 1:
            P2, P4, P6, P8 = p[0], p[2], p[4], p[6]
            zs1[c] = not (P2 and P4 and P6) and not (P4 and P6 and P8)
            zs2[c] = not (P2 and P4 and P8) and not (P2 and P6 and P8)
    return zs1, zs2, end


_ZS1, _ZS2, _END = _nb_luts()


def _nb_code(s: np.ndarray) -> np.ndarray:
    H, W = s.shape
    p = np.pad(s, 1)
    c = np.zeros((H, W), np.uint8)
    for bit, (dy, dx) in enumerate(_NB8):
        c |= p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] << bit
    return c


def skeleton(m: np.ndarray, max_iter: int = 64) -> np.ndarray:
    """Скелет маски (утончение Чжана–Суэня, numpy). max_iter — предел проходов: стена толщиной t утончается за ~t/2,
    толстые пятна (заливки, легенды) не доутончаются — концов линий у них нет, для поиска торцов это не мешает."""
    s = (m > 0).astype(np.uint8)
    for _ in range(max_iter):
        n = 0
        for lut in (_ZS1, _ZS2):
            d = lut[_nb_code(s)] & (s > 0)
            k = int(d.sum())
            if k:
                s[d] = 0
                n += k
        if not n:
            break
    return s


def _fill_small_holes(m: np.ndarray, max_area: float) -> np.ndarray:
    """Дырки маски площадью ≤ max_area залить (точка-косяк кружком: иначе скелет — кольцо, конца у стены нет)."""
    inv = (m == 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    H, W = m.shape
    x, y, w, h, a = st[:, 0], st[:, 1], st[:, 2], st[:, 3], st[:, 4]
    small = (a <= max_area) & (x > 0) & (y > 0) & (x + w < W) & (y + h < H)
    small[0] = False                                       # метка 0 — сама стена
    out = (m > 0).astype(np.uint8)
    if small[1:].any():
        out[small[lab] & (inv > 0)] = 1
    return out


def _trace(s: np.ndarray, y: int, x: int, n: int) -> list[tuple[int, int]]:
    """Путь по скелету от конца линии: до n px, до развилки (соседи не смежны между собой) или до конца."""
    H, W = s.shape
    path, seen = [(y, x)], {(y, x)}
    while len(path) < n:
        cy, cx = path[-1]
        nb = [(cy + dy, cx + dx) for dy, dx in _NB8
              if 0 <= cy + dy < H and 0 <= cx + dx < W and s[cy + dy, cx + dx] and (cy + dy, cx + dx) not in seen]
        if not nb:
            break
        if any(max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1 for a in nb for b in nb):
            break                                          # развилка: стык стен, а не торец
        q = min(nb, key=lambda q: abs(q[0] - cy) + abs(q[1] - cx))   # ступенька 8-связной линии — сперва 4-сосед
        path.append(q)
        seen.add(q)
    return path


_ENDS_CACHE: dict = {}


def wall_ends(wall: np.ndarray, t: float) -> list[dict]:
    """Торцы стен в любой ориентации, со скосом и без: конец скелета, за которым ≥ 3,5 t стены толщиной ≥ 0,6 t (не
    текст и не штрих). → [{p: точка торца (x, y), d: направление скоса (последние ~0,8 t, наружу), w: направление стены
    за скосом (2–3,5 t от конца, наружу)}]. У торца без скоса d ≈ w; у скоса 45° — угол между ними ~45°.
    Запоминается по самой маске: разбор листа зовёт его на каждую гипотезу масштаба с той же стеной — скелет один раз."""
    import hashlib
    key = (wall.shape, round(float(t), 3), hashlib.blake2b(np.packbits(wall > 0).tobytes(), digest_size=16).digest())
    if key in _ENDS_CACHE:
        return _ENDS_CACHE[key]
    out = _wall_ends(wall, t)
    if len(_ENDS_CACHE) >= 8:
        _ENDS_CACHE.pop(next(iter(_ENDS_CACHE)))
    _ENDS_CACHE[key] = out
    return out


def _wall_ends(wall: np.ndarray, t: float) -> list[dict]:
    t = max(float(t), 2.0)
    f = _fill_small_holes(wall, 4 * t * t)
    s = skeleton(f, int(2 * t) + 4)
    kb, k1, k2 = max(2, round(0.8 * t)), max(4, round(2 * t)), max(6, round(3.5 * t))
    ys, xs = np.nonzero((s > 0) & _END[_nb_code(s)])
    if not len(ys):
        return []
    dist = cv2.distanceTransform(f, cv2.DIST_L2, 3)
    out = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        path = _trace(s, y, x, k2 + 1)
        if len(path) <= k2:
            continue
        body = [2 * dist[q] for q in path[k1:k2 + 1]]
        if np.median(body) < 0.6 * t:
            continue
        P = np.array(path, float)[:, ::-1]
        d, w = P[0] - P[kb], P[k1] - P[k2]
        nd, nw = np.hypot(*d), np.hypot(*w)
        if nd < 1 or nw < 1:
            continue
        out.append({'p': P[0], 'd': d / nd, 'w': w / nw})
    return out


BEVEL_TURN_COS = math.cos(math.radians(25))   # торец со скосом: скос повёрнут от стены на 25–65° (рисуют ~45°); поворот
BEVEL_MAX_COS = math.cos(math.radians(65))    # ~90° — Г-образный угол или короткий отросток, не скос


def _bevelled(e: dict) -> bool:
    return BEVEL_MAX_COS <= e['d'] @ e['w'] <= BEVEL_TURN_COS


def _straight_bevel_pair(a: dict, b: dict, max_px: float, t: float) -> bool:
    """Прямая дверь со скошенными торцами: стены на одной линии навстречу друг другу, скосы — зеркально в одну сторону от
    линии стены (оба к проёму), между точками ≤ max_px."""
    v = b['p'] - a['p']
    D = float(np.hypot(*v))
    if D < 2 or D > max_px + 2 * t:
        return False
    u = v / D
    if a['w'] @ b['w'] > -0.9 or a['w'] @ u < 0.8 or -(b['w'] @ u) < 0.8:
        return False
    ca = a['w'][0] * a['d'][1] - a['w'][1] * a['d'][0]
    cb = b['w'][0] * b['d'][1] - b['w'][1] * b['d'][0]
    return ca * cb < 0


def bevel_end_zone(wall: np.ndarray, t: float, max_px: float = 0.0) -> np.ndarray:
    """Зона торцов со скосом, у которых есть пара (проём): прямая дверь (`_straight_bevel_pair`) или косая в углу
    (`_corner_bevel_pair`). Круг 2 t вокруг конца скоса (скос до 1,5 t + точка-косяк + грань стены, где скос начинается):
    здесь `extend_corners` не продлевает — проём закрывают `bridge_lines` (прямая дверь) или `bevel_corner_doors` (угол).
    Одиночный «скос» (Г-угол, развилка скелета у толстого торца) — не трогаем: там всё как раньше."""
    z = np.zeros(wall.shape, np.uint8)
    ends = [e for e in wall_ends(wall, t) if _bevelled(e)]
    r = int(round(2 * max(float(t), 2.0)))
    for i, a in enumerate(ends):
        for b in ends[i + 1:]:
            if _straight_bevel_pair(a, b, max_px, t) or _straight_bevel_pair(b, a, max_px, t) or \
                    _corner_bevel_pair(a, b, max_px, t) is not None:
                for e in (a, b):
                    cv2.circle(z, tuple(int(round(v)) for v in e['p']), r, 1, -1)
    return z


BEVEL_FACE_COS = math.cos(math.radians(30))   # скос смотрит на соседний торец (±30°)
BEVEL_PERP_COS = math.cos(math.radians(65))   # стены угла перпендикулярны (90 ± 25°)


def _corner_bevel_pair(a: dict, b: dict, max_px: float, t: float):
    """Косая дверь в углу: стены торцов перпендикулярны, скосы смотрят друг на друга по линии между точками, продолжения стен
    сходятся за торцами (вершина угла снаружи проёма) не дальше max_px. → расстояние между точками или None."""
    v = b['p'] - a['p']
    D = float(np.hypot(*v))
    if D < 2 or D > max_px + 2 * t:
        return None
    u = v / D
    if abs(a['w'] @ b['w']) > BEVEL_PERP_COS or a['d'] @ u < BEVEL_FACE_COS or -(b['d'] @ u) < BEVEL_FACE_COS:
        return None
    det = -a['w'][0] * b['w'][1] + b['w'][0] * a['w'][1]          # p_a + s·w_a = p_b + r·w_b
    if abs(det) < 1e-6:
        return None
    s_ = (-v[0] * b['w'][1] + b['w'][0] * v[1]) / det
    r_ = (a['w'][0] * v[1] - a['w'][1] * v[0]) / det
    return D if 0 < s_ <= max_px and 0 < r_ <= max_px else None


def bevel_corner_doors(wall: np.ndarray, closed: np.ndarray, max_px: float, t: float, ends=None) -> list[tuple]:
    """Косая дверь между торцами со скосом (T-20261110-03/2): два торца, чьи стены перпендикулярны (один угол), скосы смотрят
    друг на друга по линии между точками торцов, продолжения стен сходятся за торцами (вершина угла — снаружи проёма), между
    точками ≤ max_px и по линии между ними нет стен и закрытий (`closed`). Прямая дверь со скошенными торцами — стены на одной
    линии, не угол: сюда не попадает (её закрывает `bridge_lines`, как без скосов). Каждый торец — в одной паре, ближние первыми.
    ends — торцы `wall_ends` в координатах `wall` (готовые — у вызывающего, по всему листу; иначе считаются здесь).
    → [(маска кандидата — полоса толщиной ~t между точками торцов, без пикселей `closed`; p1, p2 — точки торцов (x, y))]."""
    ends = [e for e in (wall_ends(wall, t) if ends is None else ends) if _bevelled(e)]
    if len(ends) < 2:
        return []
    H, W = wall.shape
    cands = []
    for i in range(len(ends)):
        a = ends[i]
        for j in range(i + 1, len(ends)):
            b = ends[j]
            D = _corner_bevel_pair(a, b, max_px, t)
            if D is None:
                continue
            n = int(D) + 2
            xs = np.clip(np.round(np.linspace(a['p'][0], b['p'][0], n)).astype(int), 0, W - 1)
            ys = np.clip(np.round(np.linspace(a['p'][1], b['p'][1], n)).astype(int), 0, H - 1)
            on = closed[ys, xs] > 0
            k0 = int(np.argmin(on)) if not on.all() else n
            k1 = n - int(np.argmin(on[::-1])) if not on.all() else n
            if k0 >= k1 or on[k0:k1].any():
                continue                                   # проём уже закрыт или по линии стена
            cands.append((D, i, j))
    out, used = [], set()
    th = max(3, int(round(t)))
    for D, i, j in sorted(cands):
        if i in used or j in used:
            continue
        used.update((i, j))
        p1, p2 = ends[i]['p'], ends[j]['p']
        m = np.zeros((H, W), np.uint8)
        cv2.line(m, tuple(int(round(c)) for c in p1), tuple(int(round(c)) for c in p2), 1, th)
        m[closed > 0] = 0
        nl, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        if nl < 2:
            continue
        m = (lab == 1 + int(np.argmax(st[1:, 4]))).astype(np.uint8)
        out.append((m, p1, p2))
    return out


@dataclass
class Gap:
    id: int
    cx: float
    cy: float
    length: float          # px вдоль стены
    depth: float           # px поперёк (≈ толщина стены)
    kind: str              # door | window | opening
    glaze: float           # доля «не белого» внутри разрыва (стекло окна)
    exterior: bool
    bbox: tuple
    leaves: int = 1        # створок у наружной двери: 2 — на листе пара дуг (T-20261112-48, `bench._analyze`)


# T-36: проём проходит стену насквозь — глубина разрыва ~ толщина стены (у дверей стенда A/B 0,5–1 t). Полоска в 1–3 px вдоль
# грани стены — зазубрина маски (водяной знак осветлил край стены, сжатие JPEG), её закрытие строк/столбцов — не проём.
NOTCH_REL = 0.35          # глубина < 0,35 t (и < 2 px всегда) — зазубрина
# Самая узкая межкомнатная дверь по норме — полотно ~0,6 м (UK: 610 мм — наименьшая комнатная, 457/533 — шкафы; РФ: ГОСТ 6629-88
# — проём от 7 дм, полотно 600). Ширина разрыва по листу бывает недомерена (наличник, дуга у торца) — порог с запасом.
DOOR_MIN_M = 0.45


def is_notch(g: 'Gap', t: float) -> bool:
    """Разрыв не пересекает стену, а лежит вдоль её грани: глубина < max(2 px, NOTCH_REL·t)."""
    return g.depth < max(2.0, NOTCH_REL * float(t))


def passes_through(wall: np.ndarray, ys: np.ndarray, xs: np.ndarray, k: int = 3) -> bool:
    """T-20261110-33: разрыв пересекает стену насквозь — поперёк него (по нормали за глубину + k px) с ОБЕИХ сторон не стена,
    в ≥ 2 из 3 точек вдоль. `t` листа — толщина наружных стен; тонкая межкомнатная при толстых наружных (aRQVC9: 8–10 px при t 34,
    глубина проёма < NOTCH_REL·t) — всё равно проём. У зазубрины грани с одной стороны — тело стены."""
    c, u, n, L, d = gap_axes(ys, xs)
    H, W = wall.shape
    hit = 0
    for s in (-0.25, 0.0, 0.25):
        p = c + s * L * u
        ok = True
        for sg in (-1.0, 1.0):
            x, y = np.round(p + sg * (d / 2 + k) * n).astype(int)
            if not (0 <= x < W and 0 <= y < H) or wall[y, x]:
                ok = False
        hit += ok
    return hit >= 2


# T-20261111-03: клин вдоль грани стены. Закрытие по семейству углов листа, наклонённому на 3–4° к стенам куска (rgK5…: семейство
# 3,2° от повёрнутого флигеля), идёт вдоль грани стены, выходит из неё и входит обратно через ≤ Ls — треугольник/трапеция длиной
# 1,4–1,7 м с одной стороной на грани стены. Дверь пересекает стену: стена у неё по ТОРЦАМ (вдоль длины), а обе длинные стороны
# открыты в помещения; у клина одна длинная сторона целиком лежит на стене, другая открыта в комнату.
FACE_ON = 0.8      # доля длины, где сразу за длинной стороной стена: не меньше — сторона лежит на грани стены
FACE_OFF = 0.2     # и не больше этого у другой стороны — она открыта в комнату (щель между двумя стенами — не клин)
FACE_ELONG = 0.35  # глубина не больше этой доли длины: вытянут вдоль грани (слитые косые закрытия глубже — не трогаем)
# T-20261111-03/2: грань ищем на 1..3 px за краем разрыва, не 1..2. Между клином и НАРИСОВАННОЙ стеной бывает шов в 2 px (rgK5… p3
# Bedroom 5: клин 1,55 м вдоль правой стены касается её на 0,42 длины при k=2 и на 1,00 при k=3 — «дверь» резала ядро спальни).
# Продления торцов (`extend_corners`) шов тоже закрывают, но они же ложатся вдоль настоящей двери (QFfI… Bedroom 2: 0,05 → 0,89).
FACE_K = 3


def face_contact(wall: np.ndarray, ys: np.ndarray, xs: np.ndarray, k: int = 2) -> tuple[float, float]:
    """Доля длины разрыва (19 срезов поперёк в пределах ±0,45 L), где сразу за краем разрыва по нормали (1..k px) стена, — по
    каждой из двух длинных сторон. Край — свой на каждом срезе (у клина глубина меняется вдоль длины)."""
    c, u, n, L, d = gap_axes(ys, xs)
    H, W = wall.shape
    P = np.column_stack([xs, ys]).astype(float) - c
    a, b = P @ u, P @ n
    out = []
    for sg in (-1.0, 1.0):
        hit = tot = 0
        for s in np.linspace(-0.45, 0.45, 19):
            sel = np.abs(a - s * L) <= 1.0
            if not sel.any():
                continue
            edge = b[sel].max() if sg > 0 else b[sel].min()
            tot += 1
            for j in range(1, k + 1):
                x, y = np.round(c + s * L * u + (edge + sg * j) * n).astype(int)
                if 0 <= x < W and 0 <= y < H and wall[y, x]:
                    hit += 1
                    break
        out.append(hit / tot if tot else 0.0)
    return out[0], out[1]


def along_face(wall: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> bool:
    """T-20261111-03: разрыв лежит вдоль грани стены, а не поперёк неё (клин): вытянут (глубина ≤ FACE_ELONG·L), одна длинная
    сторона на стене (≥ FACE_ON длины), другая открыта (≤ FACE_OFF). Дверь сквозь стену — стена только у торцов: обе стороны
    открыты; проём в толстой стене (глубина ~ длина) — не вытянут."""
    if len(ys) < 3:
        return False
    _, _, _, L, d = gap_axes(ys, xs)
    if d > FACE_ELONG * L:
        return False
    f1, f2 = face_contact(wall, ys, xs, FACE_K)
    return max(f1, f2) >= FACE_ON and min(f1, f2) <= FACE_OFF


TAIL_MIN_M = 0.25   # хвост-клин короче — не срезаем (скругление косяка, 1–2 среза у торца есть у любой двери)


def wedge_tails(wall: np.ndarray, ys: np.ndarray, xs: np.ndarray, ppm: float, k: int = 2) -> np.ndarray | None:
    """T-20261111-03: дверь, слитая с клином вдоль грани стены (rgK5… Bedroom 3: дверь 0,75 м + клин 0,9 м = «дверь» 1,7 м,
    ядро спальни резалось). Срезы поперёк оси (шаг 1 px): у проёма сразу за обоими краями среза — не стена (помещения), у клина
    хотя бы с одной стороны — стена. Проём — самый длинный сплошной ряд срезов без стены (не короче DOOR_MIN_M); хвост за ним
    длиннее TAIL_MIN_M, где срезы со стеной — большинство, — клин. Ответ — маска пикселей хвостов (по ys/xs) или None."""
    if len(ys) < 3:
        return None
    c, u, n, L, d = gap_axes(ys, xs)
    H, W = wall.shape
    P = np.column_stack([xs, ys]).astype(float) - c
    a = np.round(P @ u).astype(int)
    b = P @ n
    ss = np.arange(a.min(), a.max() + 1)
    walled = np.zeros(len(ss), bool)
    present = np.zeros(len(ss), bool)
    dep = np.zeros(len(ss))
    for i, s in enumerate(ss):
        sel = a == s
        if not sel.any():
            continue
        present[i] = True
        dep[i] = b[sel].max() - b[sel].min() + 1
        for sg, e in ((-1.0, b[sel].min()), (1.0, b[sel].max())):
            for j in range(1, k + 1):
                x, y = np.round(c + s * u + (e + sg * j) * n).astype(int)
                if 0 <= x < W and 0 <= y < H and wall[y, x]:
                    walled[i] = True
                    break
    best, run, best_end = 0, 0, -1
    for i in range(len(ss)):
        run = run + 1 if present[i] and not walled[i] else 0
        if run > best:
            best, best_end = run, i
    if best < DOOR_MIN_M * ppm:
        return None
    i0, i1 = best_end - best + 1, best_end
    d_run = np.median(dep[i0:i1 + 1])
    drop = np.zeros(len(ss), bool)
    for lo, hi in ((0, i0), (i1 + 1, len(ss))):
        seg = slice(lo, hi)
        m = present[seg]
        # хвост не толще проёма: клин сходит на нет вдоль грани; толстый «хвост» — колено Г-образного закрытия, не клин
        if hi - lo >= TAIL_MIN_M * ppm and m.any() and walled[seg][m].mean() >= 0.5 and np.median(dep[seg][m]) <= d_run:
            drop[seg] = True
    if not drop.any():
        return None
    return drop[a - ss[0]]


def regap(g: Gap, ys: np.ndarray, xs: np.ndarray) -> Gap:
    """Геометрия разрыва заново по его пикселям (после среза хвоста) — как в gap_components."""
    (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
    g.cx, g.cy, g.length, g.depth = float(cx), float(cy), float(max(w, h) + 1), float(min(w, h) + 1)
    g.bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return g


def split_composite(lab_g: np.ndarray, gaps: list, kid: np.ndarray, dark: np.ndarray, outside: np.ndarray,
                    min_depth: float) -> tuple[np.ndarray, list]:
    """T-20261111-09: разрыв глубже `min_depth` (толще стены) и в SPLIT_RATIO раз глубже своих кусков — не один проём, а несколько
    закрытий, сросшихся углами (TGva…: вход, дверь спальни 2 и перемычки узкой прихожей — одна «наружная» фигура 2,6 × 1,7 м,
    итог — «окно»; без перемычек — вход и дверь спальни 2, 1,2 м × 85 px). Делим по
    номеру закрытия `kid` (кто его поставил в `bench._analyze`); пиксели без номера — к ближайшему куску. Геометрия, «рама» и
    «наружный» — заново, как в `gap_components`. Разрыв из одного закрытия и внутренний не трогаем: широкий внутренний проём
    закрывают несколькими перемычками, и по номерам он дробился на «двери» (4y0o… спальня 1: дверей 2 → 3, ядро — отказ).
    → (lab_g, gaps) с новыми кусками."""
    out = []
    near_out = None
    nid = int(lab_g.max()) + 1
    for g in gaps:
        if g.depth <= min_depth or not g.exterior:
            out.append(g)
            continue
        ys, xs = np.nonzero(lab_g == g.id)
        ids = kid[ys, xs]
        uniq = [int(i) for i in np.unique(ids) if i > 0]
        if len(uniq) < 2:
            out.append(g)
            continue
        if (ids == 0).any():                        # без номера — к ближайшему пикселю с номером
            y0, x0 = ys.min(), xs.min()
            crop = np.zeros((ys.max() - y0 + 1, xs.max() - x0 + 1), np.int32)
            crop[ys - y0, xs - x0] = ids
            src = (crop == 0).astype(np.uint8)
            _, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            zy, zx = np.nonzero(src == 0)             # нули src (пиксели с номером) — в порядке строк, как метки 1..n
            lut = np.concatenate(([0], crop[zy, zx]))
            ids = lut[labels[ys - y0, xs - x0]]
        if near_out is None:
            near_out = cv2.dilate(outside.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        pieces = []
        for i in uniq:
            sel = ids == i
            if sel.sum() < 3:
                continue
            py, px = ys[sel], xs[sel]
            pieces.append((py, px, regap(Gap(0, 0.0, 0.0, 0.0, 0.0, '', frame_coverage(py, px, dark),
                                             bool(near_out[py, px].any()), ()), py, px)))
        # куски вдоль одной линии (окно, закрытое двумя проходами) — один проём; делим, только если фигура много глубже кусков
        if len(pieces) < 2 or g.depth <= SPLIT_RATIO * max(p.depth for _, _, p in pieces):
            out.append(g)
            continue
        for py, px, p in pieces:
            lab_g[py, px] = nid
            p.id = nid
            out.append(p)
            nid += 1
    return lab_g, out


SPLIT_RATIO = 1.5     # `split_composite`: фигура глубже самого глубокого куска в 1,5 раза — куски сошлись углом, не в линию


TEXT_H_M = (0.06, 0.35)   # высота буквы или слова подписи в метрах плана (TGva…: 0,16–0,24 м)
TEXT_ROW_H = 1.4          # строка (буквы с хвостами вниз) — до 1,4 наибольшей высоты буквы (TGva «Hallway»: 0,28 м)
TEXT_GAP_M = 0.12         # буквы и слова одной строки — через ≤ 12 см по горизонтали (пробел «2'11" x 12'5"»)
TEXT_ASPECT = 2.5         # строка вытянута по горизонтали: ширина ≥ 2,5 высоты
TEXT_RUNS = 0.7           # и пересекает свою середину часто: штрихов ≥ 0,7 на высоту строки по ширине (у «Hallway» ~2,5,
                          # у прямой линии створки с засечкой 1, у верха дуги 2 на всю ширину)


def text_mask(thin: np.ndarray, ppm: float) -> np.ndarray:
    """T-20261111-09: тонкие линии, которые — строки подписей (буквы, цифры размеров), а не дуги и створки дверей. Буква или
    слово — кусок высотой TEXT_H_M; куски, сросшиеся по горизонтали через ≤ TEXT_GAP_M, — строка, если она вытянута (ширина
    ≥ TEXT_ASPECT высоты) и середину её пересекает много вертикальных штрихов (TEXT_RUNS). Строка берётся прямоугольником с
    полем 0,03 м — с ней уходят и крапины сглаживания вокруг букв. У прихожей TGva… подпись «Hallway 2'11" x 12'5" 0.90 x 3.80 m»
    давала перемычке поперёк прохода «дугу» 0,95. Дуга двери строкой не станет: она выше TEXT_H_M или пересекается дважды."""
    on = (thin > 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(on, connectivity=8)
    hmin, hmax = TEXT_H_M[0] * ppm, TEXT_H_M[1] * ppm
    out = np.zeros(thin.shape, bool)
    h_ = st[1:, cv2.CC_STAT_HEIGHT]
    ok = np.zeros(n, bool)
    ok[1:] = (h_ >= hmin) & (h_ <= hmax)
    if not ok.any():
        return out
    k = max(3, int(round(TEXT_GAP_M * ppm)))
    row = cv2.dilate(ok[lab].astype(np.uint8), np.ones((1, k), np.uint8))
    m, _, rs, _ = cv2.connectedComponentsWithStats(row, connectivity=8)
    pad = max(1, int(round(0.03 * ppm)))
    H, W = thin.shape
    for i in range(1, m):
        x, y, w, h = rs[i, cv2.CC_STAT_LEFT], rs[i, cv2.CC_STAT_TOP], rs[i, cv2.CC_STAT_WIDTH], rs[i, cv2.CC_STAT_HEIGHT]
        if h < hmin or h > TEXT_ROW_H * hmax or w < TEXT_ASPECT * h:
            continue
        box = on[y:y + h, x:x + w]
        runs = max(int((np.diff(np.r_[0, box[int(f * h)], 0].astype(np.int8)) == 1).sum()) for f in (0.35, 0.5, 0.65))
        if runs >= max(3, TEXT_RUNS * w / h):
            out[max(0, y - pad):min(H, y + h + pad), max(0, x - pad):min(W, x + w + pad)] = True
    return out & (on > 0)


def thin_lines(gray: np.ndarray, wall: np.ndarray, delta: int = 15, k: int = 7) -> np.ndarray:
    """Тонкая графика (рамы окон, дуги дверей, мебель, текст): «чёрная шляпа» — линия темнее своего фона на delta
    и уже k px; мягкие тени у стен и заливки комнат сюда не попадают. Минус стены."""
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    return ((bh >= delta) & (wall == 0)).astype(np.uint8)


def gap_components(add: np.ndarray, dark: np.ndarray, outside: np.ndarray | None):
    """Добавленные пиксели → разрывы: длина/глубина по minAreaRect, «стекло» — доля тонких линий внутри разрыва
    (окно нарисовано рамой внутри толщины стены, проём двери пуст)."""
    n, lab, st, cen = cv2.connectedComponentsWithStats(add.astype(np.uint8), connectivity=8)
    out = []
    near_out = cv2.dilate(outside.astype(np.uint8), np.ones((5, 5), np.uint8)) if outside is not None else None
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < 3:
            continue
        (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        length, depth = max(w, h) + 1, min(w, h) + 1
        glaze = frame_coverage(ys, xs, dark)
        ext = bool(near_out[ys, xs].any()) if near_out is not None else False
        out.append(Gap(i, float(cx), float(cy), float(length), float(depth), '', glaze, ext,
                       tuple(int(v) for v in st[i, :4])))
    return lab, out


def frame_coverage(ys: np.ndarray, xs: np.ndarray, line: np.ndarray) -> float:
    """Рама окна: есть ли внутри разрыва линия ВДОЛЬ него. Пиксели разрыва — по слоям поперёк (шаг 1 px); у слоя —
    доля длины, покрытая линией; ответ — лучший слой (0..1). Пустой проём двери ≈ 0, окно с рамой ≈ 1."""
    if len(xs) < 3:
        return 0.0
    c, u, n, L, d = gap_axes(ys, xs)
    P = np.column_stack([xs, ys]).astype(float) - c
    a = np.round(P @ u).astype(int)
    b = np.round(P @ n).astype(int)
    hit = line[ys, xs] > 0
    best = 0.0
    for k in np.unique(b):
        sel = b == k
        tot = np.unique(a[sel]).size
        if tot < max(3, 0.5 * L):
            continue
        best = max(best, np.unique(a[sel & hit]).size / tot)
    return float(best)


STAIR_LINES = 3          # T-20261111-11: столько параллельных разрыву линий по одну сторону — ступени марша
STAIR_REACH_M = 0.8      # ищем их на этой глубине от грани разрыва, м
STAIR_COVER = 0.75       # линия: покрыта ≥ 75 % средней части разрыва (рама эркера — частично, ~0,6)
STAIR_STEP_M = 0.15      # линии ближе этого (м) друг к другу — одна (рама окна, эркер bs30: 0,16 м), ступени дальше (0,2–0,3)


def stair_edge(thin: np.ndarray, c, u, n, L: float, depth: float, ppm: float) -> bool:
    """Край марша: по одну сторону разрыва — ≥ STAIR_LINES параллельных ему линий (ступени) в STAIR_REACH_M. Линия в самом
    разрыве у верха лестницы — первая ступень, не рама: внутренний разрыв с такой «рамой» не закрываем (T-20261111-11, bs30:
    верх лестницы отрезан от площадки и назван «Cupboard»)."""
    H, W = thin.shape
    c, u, n = (np.asarray(v, float) for v in (c, u, n))
    t = np.linspace(-0.4 * L, 0.4 * L, max(5, int(0.8 * L)))
    for s in (n, -n):
        rows = []
        for o in np.arange(depth / 2 + 2, depth / 2 + STAIR_REACH_M * ppm):
            P = c[None, :] + s[None, :] * o + u[None, :] * t[:, None]
            xi, yi = np.rint(P[:, 0]).astype(int), np.rint(P[:, 1]).astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            hit = np.zeros(len(t), bool)
            hit[ok] = thin[yi[ok], xi[ok]] > 0
            rows.append(hit.mean() >= STAIR_COVER)
        if not rows:
            continue
        st = _runs(np.array(rows))[0]
        # ступени — через 0,2–0,3 м; линии рамы окна (двойные, тройные) — через несколько px: их считаем одной
        n_lines, last = 0, -1e9
        for a in st:
            if a - last >= STAIR_STEP_M * ppm:
                n_lines, last = n_lines + 1, a
        if n_lines >= STAIR_LINES:
            return True
    return False


def gap_axes(ys: np.ndarray, xs: np.ndarray):
    """Пиксели разрыва → центр, единичный вектор вдоль разрыва (главная ось), нормаль, длина, глубина."""
    P = np.column_stack([xs, ys]).astype(float)
    c = P.mean(axis=0)
    if len(P) < 3:
        return c, np.array([1.0, 0.0]), np.array([0.0, 1.0]), 1.0, 1.0
    w, v = np.linalg.eigh(np.cov((P - c).T))
    u = v[:, 1]
    n = np.array([-u[1], u[0]])
    a, b = (P - c) @ u, (P - c) @ n
    c = c + u * (a.max() + a.min()) / 2 + n * (b.max() + b.min()) / 2
    return c, u, n, float(a.max() - a.min() + 1), float(b.max() - b.min() + 1)


def mouth_strip(comp: np.ndarray, wall: np.ndarray, t: float):
    """Перемычка залила целиком маленькую каморку: оставить только «устье» — полосу толщиной ~t у свободного места
    вне компоненты (там дверной проём). → (ys, xs) самой крупной полосы или None."""
    ys, xs = np.nonzero(comp)
    if not len(ys):
        return None
    m = int(2 * t + 4)
    H, W = comp.shape
    y0, y1, x0, x1 = max(0, ys.min() - m), min(H, ys.max() + m + 1), max(0, xs.min() - m), min(W, xs.max() + m + 1)
    c = comp[y0:y1, x0:x1].astype(bool)
    free = (wall[y0:y1, x0:x1] == 0) & ~c
    if not free.any():
        return None
    dt = cv2.distanceTransform((~free).astype(np.uint8), cv2.DIST_L2, 5)
    strip = (c & (dt <= t)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(strip, connectivity=8)
    if n < 2:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    sy, sx = np.nonzero(lab == k)
    return sy + y0, sx + x0


def cavity_mouth(comp: np.ndarray, wall: np.ndarray, depth: float, min_len: float, min_free: float, angles=(0.0,)):
    """T-20261112-48: перемычка залила целиком каморку (шкаф, кладовка) — у каморки ОДНО устье: полоса куска глубиной `depth`
    у свободного места снаружи куска. Свободное место считается, если его кусок в окне не меньше `min_free` px (щель в углу
    каморки, недолитая перемычкой, — не устье); полоса — не короче `min_len` px. Устьев два и больше (отросток комнаты,
    проход) или ни одного — None. → (ys, xs) устья."""
    ys, xs = np.nonzero(comp)
    if not len(ys):
        return None
    m = int(2 * depth + max(min_len, 4))
    H, W = comp.shape
    y0, y1, x0, x1 = max(0, ys.min() - m), min(H, ys.max() + m + 1), max(0, xs.min() - m), min(W, xs.max() + m + 1)
    c = comp[y0:y1, x0:x1].astype(bool)
    free = (wall[y0:y1, x0:x1] == 0) & ~c
    n, lab, st, _ = cv2.connectedComponentsWithStats(free.astype(np.uint8), connectivity=4)
    big = np.zeros(n, bool)
    big[1:] = st[1:, cv2.CC_STAT_AREA] >= min_free
    free = big[lab]
    if not free.any():
        return None
    # глубина — по свободному месту (через проём), не по прямой: сквозь тонкую стену каморки прямая мера дотягивается до
    # соседнего помещения и даёт «устье» вдоль стены
    near = grow_within(free, (wall[y0:y1, x0:x1] == 0), int(round(depth))) > 0
    strip = (c & near).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(strip, connectivity=8)
    ok = [k for k in range(1, n) if max(st[k, cv2.CC_STAT_WIDTH], st[k, cv2.CC_STAT_HEIGHT]) >= min_len]
    if len(ok) != 1:
        return None
    sy, sx = np.nonzero(lab == ok[0])
    # устье — самое узкое место полосы (проём между косяками), слои поперёк не шире него на 2 px; каморка за косяками
    # шире проёма — её пол не закрываем
    cc, u, nn, _, _ = gap_axes(sy, sx)
    # слои — по направлению стен листа (наклон minAreaRect в 1–2° даёт по краям полосы слои-огрызки)
    dirs = [np.array([math.cos(math.radians(a_ + k)), math.sin(math.radians(a_ + k))]) for a_ in angles for k in (0.0, 90.0)]
    u = max(dirs, key=lambda v: abs(float(v @ u)))
    nn = np.array([-u[1], u[0]])
    P = np.column_stack([sx, sy]).astype(float) - cc
    a, b = np.round(P @ u).astype(int), np.round(P @ nn).astype(int)
    bs = np.unique(b)
    wid = np.array([np.unique(a[b == k]).size for k in bs])
    if not (wid >= min_len).any():
        return None
    i0 = int(np.argmin(np.where(wid >= min_len, wid, np.iinfo(np.int64).max)))
    lo = hi = i0
    while lo > 0 and wid[lo - 1] <= wid[i0] + 2:
        lo -= 1
    while hi < len(bs) - 1 and wid[hi + 1] <= wid[i0] + 2:
        hi += 1
    sel = (b >= bs[lo]) & (b <= bs[hi])
    return sy[sel] + y0, sx[sel] + x0


def door_evidence(thin: np.ndarray, c, u, n, L: float, depth: float, step_deg: int = 5, tangent_only: bool = False,
                  want_px: bool = False, wall: np.ndarray | None = None, pure_check: bool = True, want_how: bool = False):
    """Есть ли у разрыва дуга двери: доля углов 0–90°, где на радиусе створки от петли (конец разрыва, грань стены)
    лежит тонкая линия. Створка одна (радиус L) или две (по L/2 от каждого конца, обе дуги). → лучшая доля 0..1.
    `tangent_only` — только «вогнутая» дуга створки, нарисованной закрытой в линии стены (T-20261110-11): касается грани
    у торца, центр в комнате на глубине R; её первые ~35° (у самой грани, где лежат линии рамы окна) не считаются.
    `want_px` → (доля, пиксели рисунка `_evidence_px`) — для «одна дуга — одна дверь» (T-20261111-11).
    `wall` (маска стен) — створка вплотную к грани стены (ближе LEAF_WALL·R) не засчитывается: это обвод стены или
    тетива лестницы у неё, а «разрыв» упирается в стену поперёк (T-20261111-11, bs30: площадка у санузла, верх лестницы).
    `pure_check=False` — прежнее правило без «чистоты» (запасная дверь комнаты без дверей, `bench.doorless_doors`, T-11/3).
    `want_how` → (доля, рисунок лучшего: 'arc' | 'double' | 'leaf' | None) — число створок наружной двери (T-20261112-48);
    'double' — только при проверке «чистоты» (на заштрихованном полу и при `pure_check=False` — None)."""
    if tangent_only:
        v = _tangent_evidence(thin, c, u, n, L, depth, step_deg)
        return (v, frozenset()) if want_px else v
    H, W = thin.shape
    th = np.radians(np.arange(0, 91, step_deg))
    c = np.asarray(c, float)
    # T-20261111-11: один вырез вокруг разрыва, расширенный на окно 5×5 (точка «у линии» — линия в её окне; за краем листа
    # пусто) — как у `_tangent_evidence`; точки дальше выреза — за краем листа
    m = int(2.5 * L + depth) + 8
    cx, cy = int(round(float(c[0]))), int(round(float(c[1])))
    ox, oy = max(0, cx - m), max(0, cy - m)
    crop = np.pad((thin[oy:min(H, cy + m + 1), ox:min(W, cx + m + 1)] > 0).astype(np.uint8), 2)
    dil = cv2.dilate(crop, np.ones((5, 5), np.uint8)) > 0
    hh, ww = dil.shape
    pure = arc_pure() if pure_check else None
    wcrop = None
    if wall is not None and pure:
        wcrop = np.pad(wall[oy:min(H, cy + m + 1), ox:min(W, cx + m + 1)] > 0, 2)
    # T-11/2: пол заштрихован целиком (паркет «ёлочкой», лист aOv8kT: пунктирная дуга тонет в штриховке) — линии на 0,8R/1,2R
    # и по бокам створки есть везде, «чистота» гасит любую дверь: прежнее правило. Ступени и надписи (bs30) — пятно, не весь пол
    if pure and (dil[~wcrop] if wcrop is not None else dil).mean() >= FLOOR_HATCH:
        pure, wcrop = None, None

    def on(P, src=None):
        src = dil if src is None else src
        xi = np.rint(P[..., 0]).astype(int) - ox + 2
        yi = np.rint(P[..., 1]).astype(int) - oy + 2
        ok = (xi >= 0) & (xi < ww) & (yi >= 0) & (yi < hh)
        r = np.zeros(xi.shape, bool)
        r[ok] = src[yi[ok], xi[ok]]
        return r

    def arc_pts(h, d, s, R):
        return h[None, :] + R * (np.cos(th)[:, None] * d[None, :] + np.sin(th)[:, None] * s[None, :])

    def cov_mask(h, d, s, R):
        """Засчитанные точки дуги. T-20261111-11: «чистая дуга» — на том же луче от петли на 0,8R и 1,2R линий нет вместе
        (`ARC_PURE`): текст подписи и ступени лестницы — сплошная штриховка, задевают все три радиуса (bs30: «двери» площадки
        по надписи Landing и по ступеням)."""
        hit = on(arc_pts(h, d, s, R))
        if pure:
            # у малой дуги (дверца 0,4 м, R ~ 15 px) 0,2R внутри окна 5×5 самой линии — сдвиг не меньше PURE_MIN_PX
            k = max(PURE_MIN_PX, (1 - pure[0]) * R)
            hit &= ~(on(arc_pts(h, d, s, R - k)) & on(arc_pts(h, d, s, R + k)))
        return hit

    def cov(h, d, s, R):
        return float(cov_mask(h, d, s, R).mean())

    def leaf_pts(h, s, R):
        return h[None, :] + s[None, :] * np.linspace(0.15 * R, 0.95 * R, 12)[:, None]

    def leaf_mask(h, s, R, w):
        """Засчитанные точки створки. T-20261111-11: «чистая» — сбоку (вдоль стены, ±LEAF_PURE·R) линий нет вместе: текст и
        ступени лестницы — сплошные, их «створка» задевает обе стороны."""
        Q = leaf_pts(h, s, R)
        hit = on(Q)
        if pure:
            k = max(PURE_MIN_PX, LEAF_PURE * R)
            hit &= ~(on(Q + w[None, :] * k) & on(Q - w[None, :] * k))
        if wcrop is not None:
            for t in (0.5, 1.0):
                for sg in (1, -1):
                    hit &= ~on(Q + sg * t * LEAF_WALL * R * w[None, :], wcrop)
        return hit

    def leaf(h, s, R, w):
        """Створка: прямая тонкая линия от петли поперёк стены длиной ~R (доля покрытых точек)."""
        return float(leaf_mask(h, s, R, w).mean())

    best, how = 0.0, None
    for s in (n, -n):
        face = c + s * depth / 2
        for j in (0.0, 0.1, 0.2, 0.3):               # петля чуть внутри разрыва (торец рисуют с наличником)
            e1, e2 = face - u * L * (0.5 - j), face + u * L * (0.5 - j)
            for f in np.arange(0.5, 1.06, 0.05):
                R = f * L
                m1, m2 = cov_mask(e1, u, s, R), cov_mask(e2, -u, s, R)
                a1, a2 = float(m1.mean()), float(m2.mean())
                d1, d2 = cov(e1, u, s, R / 2), cov(e2, -u, s, R / 2)
                for v, w in ((a1, ('arc', e1, u, s, R)), (a2, ('arc', e2, -u, s, R)),
                             (min(d1, d2), ('double', e1, e2, u, s, R / 2))):
                    if v > best:
                        best, how = v, w
                # второй признак: створка у петли + дуга хотя бы частично (её конец бывает срезан стеной)
                if best < LEAF_SCORE:
                    for a, e, d in ((a1, e1, u), (a2, e2, -u)):
                        if a >= LEAF_ARC_MIN and leaf(e, s, R, u) >= LEAF_MIN:
                            best, how = LEAF_SCORE, ('leaf', e, d, s, R, s, u)
                # T-20261111-11: створка приоткрыта (дверцы шкафов, bs30: шкаф у площадки — на ~37°) — дуга 0–φ почти целиком
                # и прямая створка под углом φ (HALF_ANGLES)
                if best < LEAF_SCORE and pure:
                    for m_, e, d in ((m1, e1, u), (m2, e2, -u)):
                        for phi in HALF_ANGLES:
                            k = phi // step_deg + 1
                            if k > len(m_) or m_[:k].mean() < HALF_ARC_MIN:
                                continue
                            a_ = np.radians(phi)
                            q = np.cos(a_) * d + np.sin(a_) * s
                            wq = np.sin(a_) * d - np.cos(a_) * s
                            if leaf(e, q, R, wq) >= LEAF_MIN:
                                best, how = LEAF_SCORE, ('leaf', e, d, s, R, q, wq)
                                break
    if want_px:
        return best, _evidence_px(thin, how, cov_mask, arc_pts, leaf_mask, leaf_pts)
    if want_how:
        kind = how[0] if how else None
        if kind == 'double' and not pure:
            # пол заштрихован (паркет «ёлочкой», aOv8 вход: одна створка наружу) — без «чистоты» пару малых дуг даёт сама
            # штриховка (1,0 у любой пары): число створок по ней не читаем
            kind = None
        return best, kind
    return best


def _evidence_px(thin, how, cov_mask, arc_pts, leaf_mask, leaf_pts) -> frozenset:
    """Пиксели тонкой графики, на которых держится лучший рисунок `door_evidence` (дуга, две дуги или створка с дугой):
    линии в окнах 5×5 засчитанных точек → множество индексов y·W + x листа (для «одна дуга — одна дверь», `bench`)."""
    if how is None:
        return frozenset()
    pts = []
    if how[0] == 'double':
        _, e1, e2, u, s, R = how
        for h, d in ((e1, u), (e2, -u)):
            P = arc_pts(h, d, s, R)
            pts.append(P[cov_mask(h, d, s, R)])
    else:
        _, h, d, s, R = how[:5]
        P = arc_pts(h, d, s, R)
        pts.append(P[cov_mask(h, d, s, R)])
        if how[0] == 'leaf':
            q, wq = how[5:]
            pts.append(leaf_pts(h, q, R)[leaf_mask(h, q, R, wq)])
    H, W = thin.shape
    out = set()
    for P in pts:
        for x, y in np.rint(P).astype(int):
            y0, y1, x0, x1 = max(0, y - 2), min(H, y + 3), max(0, x - 2), min(W, x + 3)
            if y1 > y0 and x1 > x0:
                yy, xx = np.nonzero(thin[y0:y1, x0:x1])
                out.update(((yy + y0) * W + xx + x0).tolist())
    return frozenset(out)


ARC_PURE = (0.8, 1.2)   # T-20261111-11: радиусы проверки «чистой дуги» у `door_evidence` (как TANGENT_PURE у «вогнутой»)
LEAF_PURE = 0.2         # T-20261111-11: сдвиг вбок (доля R) для проверки «чистой створки»
PURE_MIN_PX = float(os.environ.get('FP_PURE_MIN_PX', '6'))   # T-20261111-11: сдвиг проверки «чистоты» не меньше 6 px (окно 5×5 + толщина линии с JPEG)
FLOOR_HATCH = float(os.environ.get('FP_FLOOR_HATCH', '0.4'))   # T-11/2: тонкая графика (окно 5×5) покрывает ≥ 40 % пола у разрыва — пол заштрихован (паркет), «чистота» не различает
LEAF_WALL = 0.12        # T-20261111-11: створка ближе этой доли R к грани стены — обвод стены, не створка
HALF_ARC_MIN = 0.75     # T-20261111-11: приоткрытая створка (угол φ) — дуга 0–φ покрыта не меньше чем на 75 %
HALF_ANGLES = tuple(range(30, 61, 5))   # углы приоткрытой створки, °


def arc_pure():
    """Радиусы «чистой дуги» `door_evidence`; FP_ARC_PURE=0 — без проверки (прежнее правило, сравнение)."""
    return None if os.environ.get('FP_ARC_PURE', '1') == '0' else ARC_PURE


def _tangent_evidence(thin: np.ndarray, c, u, n, L: float, depth: float, step_deg: int = 5) -> float:
    """«Вогнутая» дуга створки, нарисованной закрытой в линии стены (наш пример /try, T-20261110-11): касается грани стены
    у торца, центр в комнате на глубине R (h + s·R), идёт от грани к точке напротив другого торца. Петля и R перебираются
    как в `door_evidence`. Точка засчитана — только чистая дуга: на том же луче на 0,8R и 1,2R линий нет вместе (поперечная
    линия — край ванны, раковина, штриховка — задевает все три радиуса; листы B и T). Окно 5×5 вокруг точки — как у
    `door_evidence`: один раз расширенный вырез вокруг разрыва и выборка массивом. → лучшая доля 0..1."""
    H, W = thin.shape
    th = np.radians(np.arange(TANGENT_FROM_DEG, 91, step_deg))
    rad = np.array((1.0,) + TANGENT_PURE)
    m = int(3 * L + depth) + 8                      # дальше всех точек: L/2 + R + 1,2R при R ≤ 1,05 L
    cx, cy = int(round(float(c[0]))), int(round(float(c[1])))
    x0, y0 = max(0, cx - m), max(0, cy - m)
    crop = np.pad((thin[y0:min(H, cy + m + 1), x0:min(W, cx + m + 1)] > 0).astype(np.uint8), 2)
    dil = cv2.dilate(crop, np.ones((5, 5), np.uint8))   # точка «у линии» — линия в её окне 5×5 (за краем листа — пусто)
    hh, ww = dil.shape
    fs = np.arange(0.5, 1.06, 0.05) * L                 # R
    js = np.array((0.0, 0.1, 0.2, 0.3))
    best = 0.0
    for s in (n, -n):
        face = c + s * depth / 2
        for sign in (-1.0, 1.0):                         # петля у одного торца, дуга — к другому
            d = -sign * u
            e = face[None, :] + sign * u[None, :] * (L * (0.5 - js))[:, None]                 # (J, 2)
            o = e[:, None, :] + s[None, None, :] * fs[None, :, None]                          # (J, F, 2)
            ray = -np.cos(th)[:, None] * s[None, :] + np.sin(th)[:, None] * d[None, :]       # (A, 2)
            P = (o[:, :, None, None, :] + (fs[None, :, None, None, None] * rad[None, None, None, :, None])
                 * ray[None, None, :, None, :])                                               # (J, F, A, 3, 2)
            xi = np.rint(P[..., 0]).astype(int) - x0 + 2
            yi = np.rint(P[..., 1]).astype(int) - y0 + 2
            ok = (xi >= 0) & (xi < ww) & (yi >= 0) & (yi < hh)
            on = np.zeros(xi.shape, bool)
            on[ok] = dil[yi[ok], xi[ok]] > 0
            good = on[..., 0] & ~(on[..., 1] & on[..., 2])                                   # (J, F, A)
            # дуга, а не прямая (T-20261110-33/2, aRQVC9: окно лестницы стало дверью — точки «дуги» легли вдоль прямой линии
            # ступени, окно 5×5 её прощает): середина хорды между концами дуги (35° и 90°) у настоящей дуги — в стороне от линии
            # на ~0,11 R, у прямой — на самой линии. Прогиб меньше TANGENT_CHORD_MIN_PX окно 5×5 от прямой не отличит (малый R,
            # мелкие листы) — тогда прямая ещё и продолжается за конец дуги по хорде (ступень тянется дальше), а дуга заворачивает
            # хорда — между крайними ПАРАМИ соседних засчитанных точек (прямая может не дойти до конца дуги, одиночная точка
            # у грани — линия стены/рамы, не продолжение прямой; aRQVC9: R = 41)
            A = good.shape[2]
            g2 = good[..., :-1] & good[..., 1:]
            has = g2.any(axis=2)
            ia = g2.argmax(axis=2)
            ib = A - 1 - g2[..., ::-1].argmax(axis=2)
            arc = P[..., 0, :]                                                               # (J, F, A, 2)
            a0 = np.take_along_axis(arc, ia[:, :, None, None], axis=2)[:, :, 0, :]           # (J, F, 2)
            a1 = np.take_along_axis(arc, ib[:, :, None, None], axis=2)[:, :, 0, :]

            def line_at(fr):                                                                 # линия в точках хорды → (J, F, len)
                Q = a0[:, :, None, :] + (a1 - a0)[:, :, None, :] * fr[None, None, :, None]
                qx = np.rint(Q[..., 0]).astype(int) - x0 + 2
                qy = np.rint(Q[..., 1]).astype(int) - y0 + 2
                qok = (qx >= 0) & (qx < ww) & (qy >= 0) & (qy < hh)
                qon = np.zeros(qx.shape, bool)
                qon[qok] = dil[qy[qok], qx[qok]] > 0
                return qon.all(axis=2)
            mid = line_at(TANGENT_CHORD)
            ext = line_at(1.0 + TANGENT_EXT)     # только за дальним концом (от стены): назад к грани — линия стены у любой дуги
            sag = fs[None, :] * (1 - np.cos(np.radians(step_deg) * (ib - ia) / 2))         # прогиб дуги над этой хордой, px
            score = good.mean(axis=2)
            score[has & mid & ((sag >= TANGENT_CHORD_MIN_PX) | ext)] = 0.0
            best = max(best, float(score.max()))
    return best


TANGENT_FROM_DEG = 35  # «вогнутая» дуга: углы с 35° — дальше ~0,18 R от грани стены, мимо линий рамы окна
TANGENT_PURE = (0.8, 1.2)  # радиусы проверки «чистой дуги» (линий нет на обоих разом)
TANGENT_CHORD = np.array((0.45, 0.5, 0.55))  # середина хорды «вогнутой» дуги: линия во всех трёх — прямая, не дуга
TANGENT_CHORD_MIN_PX = 4.0  # прогиб дуги не меньше — хватает середины хорды (окно 5×5 ± полтолщины линии)
TANGENT_EXT = np.array((0.3, 0.5))  # продолжение хорды за конец дуги (доли хорды): линия в обеих точках — прямая идёт дальше
LEAF_MIN = 0.8        # створка: ≥ 80 % её длины — тонкая линия
LEAF_ARC_MIN = 0.4    # при створке хватает 40 % дуги
LEAF_SCORE = 0.8      # «дверь по створке» — выше порога дуги (0,75)


FALSE_MAX_M = 4.0      # ложная стена — короткая (до 4 м)
FALSE_FLANK_M = 1.0    # стена за концом отрезка тянется ≥ 1 м по той же линии — это продолжение настоящей стены
FALSE_THIN = 0.7       # тоньше 0,7 типичной внутренней стены — штрих мебели/лестницы, не стена
FALSE_ADD = 0.8        # или почти целиком наша перемычка (дверь «по мусору»), а не нарисованная стена


def _flank_run(final: np.ndarray, sep: np.ndarray, p, u, max_px: int) -> int:
    """Сколько px стены подряд по направлению u от точки p (за пределами самого отрезка sep)."""
    H, W = final.shape
    run, started = 0, False
    for k in range(1, max_px + 1):
        x, y = int(round(p[0] + u[0] * k)), int(round(p[1] + u[1] * k))
        if not (0 <= x < W and 0 <= y < H) or not final[y, x]:
            break
        if sep[y, x] and not started:
            continue
        started = True
        run += 1
    return run


def _flood_from_seeds(m: np.ndarray, seeds: list) -> np.ndarray:
    """Водораздел по высоте «−расстояние до стены»: заливка с приоритетом от каждой подписи (метки k+2), поэтому
    встречаются на горлах проёмов. (cv2.watershed считает по перепадам цвета соседей, а не по высоте — не подходит.)"""
    import heapq
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    mm = np.pad(m[y0:y1, x0:x1], 1)
    dist = cv2.distanceTransform(mm.astype(np.uint8), cv2.DIST_L2, 3)
    lab = np.zeros(mm.shape, np.int32)
    heap = []
    for k, (x, y) in enumerate(seeds):
        yy, xx = y - y0 + 1, x - x0 + 1
        if 0 <= yy < mm.shape[0] and 0 <= xx < mm.shape[1]:
            if not mm[yy, xx]:                         # подпись на тексте/у края — ближайший пиксель области
                cand = np.argwhere(mm[max(0, yy - 6):yy + 7, max(0, xx - 6):xx + 7])
                if not len(cand):
                    continue
                yy, xx = cand[0][0] + max(0, yy - 6), cand[0][1] + max(0, xx - 6)
            lab[yy, xx] = k + 2
            heapq.heappush(heap, (-float(dist[yy, xx]), yy, xx))
    while heap:
        _, y, x = heapq.heappop(heap)
        k = lab[y, x]
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if mm[ny, nx] and lab[ny, nx] == 0:
                lab[ny, nx] = k
                heapq.heappush(heap, (-float(dist[ny, nx]), ny, nx))
    out = np.zeros(m.shape, np.int32)
    out[y0:y1, x0:x1] = lab[1:-1, 1:-1]
    return out


def split_by_labels(lab: np.ndarray, rooms: list, pts: list, ppm: float, r: int = 6):
    """Подписи как опора (обратное к merge_false_splits): в одной области ≥2 подписей (комнаты соединены широким
    проёмом без двери) → делим по самым узким местам: водораздел по расстоянию до стен от каждой подписи.
    Граница проходит по горлу проёма; стены не дорисовываются (в 3D проём остаётся открытым). → (lab, rooms, log)"""
    lab = lab.copy()
    rooms = list(rooms)
    H, W = lab.shape
    log = []
    nxt = int(lab.max()) + 1
    for rid in list(rooms):
        m = lab == rid
        seeds = []
        for (px, py) in pts:
            x, y = int(round(px)), int(round(py))
            y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
            if m[y0:y1, x0:x1].any():
                seeds.append((x, y))
        if len(seeds) < 2:
            continue
        markers = _flood_from_seeds(m, seeds)
        parts = []
        for k in range(len(seeds)):
            pk = (markers == k + 2) & m
            if pk.sum() >= 0.3 * ppm * ppm:
                parts.append(pk)
        if len(parts) < 2:
            continue
        for pk in parts[1:]:
            lab[pk] = nxt
            rooms.append(nxt)
            nxt += 1
        log.append({'room': int(rid), 'labels': len(seeds), 'parts': len(parts)})
        # линия водораздела (−1) остаётся у исходной комнаты
    return lab, rooms, log


def merge_false_splits(lab: np.ndarray, rooms: list, final: np.ndarray, wall: np.ndarray, add: np.ndarray,
                       pts: list, ppm: float, passes: int = 3):
    """Подписи как опора: кусок БЕЗ подписи, отрезанный от комнаты С подписью ложной стеной, сливается обратно.
    Ложная стена: общий отрезок двух комнат короче FALSE_MAX_M, не продолжает линию другой стены (за его концами стены
    нет ≥ FALSE_FLANK_M) и либо тоньше FALSE_THIN·толщины внутренних стен (штрих), либо это наша перемычка (add).
    Куски без подписи за настоящими стенами (санузлы, коридоры) не трогаются. → lab, final, rooms, журнал слияний."""
    lab, final, rooms = lab.copy(), final.copy(), list(rooms)
    # толщина ВНУТРЕННИХ стен: осевые пиксели нарисованных стен, не прилегающих к наруже (наружные толще и сбивают медиану)
    _, _, outside = free_components(final)
    dto = cv2.distanceTransform((~outside).astype(np.uint8), cv2.DIST_L2, 5)
    dtw = cv2.distanceTransform((wall > 0).astype(np.uint8), cv2.DIST_L2, 5)
    ridge = (dtw > 0.9) & (dtw >= cv2.dilate(dtw, np.ones((3, 3), np.uint8)) - 1e-6)
    inner = ridge & (dto > dtw + 2)
    t_int = float(2 * np.median(dtw[inner])) if inner.sum() > 20 else stroke_thickness(wall)
    dtf = cv2.distanceTransform((final > 0).astype(np.uint8), cv2.DIST_L2, 5)
    ridge_f = (dtf > 0.5) & (dtf >= cv2.dilate(dtf, np.ones((3, 3), np.uint8)) - 1e-6)
    H, W = lab.shape
    log = []

    def labelled():
        out = set()
        for x, y in pts:
            xi, yi = int(round(x)), int(round(y))
            r = max(6, int(0.25 * ppm))
            win = lab[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1]
            ids = [v for v in np.unique(win) if v in rooms]
            if 0 <= yi < H and 0 <= xi < W and lab[yi, xi] in rooms:
                out.add(int(lab[yi, xi]))
            elif ids:
                out.add(int(ids[0]))
        return out

    for _ in range(passes):
        lab_ids = labelled()
        changed = False
        for p in [r for r in rooms if r not in lab_ids]:
            P = lab == p
            if not P.any():
                continue
            ys, xs = np.nonzero(P)
            m = int(2 * t_int + 4)
            y0, y1, x0, x1 = max(0, ys.min() - m), min(H, ys.max() + m + 1), max(0, xs.min() - m), min(W, xs.max() + m + 1)
            sl = (slice(y0, y1), slice(x0, x1))
            d = 1.2 * max(t_int, 2.0) + 1.5
            dP = cv2.distanceTransform((~P[sl]).astype(np.uint8), cv2.DIST_L2, 3)
            ring = (final[sl] > 0) & (dP <= d)
            best = None
            for q in np.unique(lab[sl][cv2.dilate(ring.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0]):
                if q not in lab_ids:
                    continue
                dQ = cv2.distanceTransform((lab[sl] != q).astype(np.uint8), cv2.DIST_L2, 3)
                S = ring & (dQ <= d)
                if S.sum() < 4:
                    continue
                sy, sx = np.nonzero(S)
                c, u, n, L, dep = gap_axes(sy + y0, sx + x0)
                # толщина — по оси (гребню distance transform) внутри отрезка; медиана: стыки с настоящими стенами — меньшинство
                rS = S & ridge_f[sl]
                thick = 2 * float(np.median(dtf[sl][rS])) if rS.any() else 2 * float(dtf[sl][S].max())
                add_frac = float(add[sl][S].mean())
                Sg = np.zeros_like(final, bool)
                Sg[sl] = S
                fl = max(_flank_run(final, Sg, c + u * L / 2, u, int(1.5 * ppm)),
                         _flank_run(final, Sg, c - u * L / 2, -u, int(1.5 * ppm)))
                st = {'piece': int(p), 'room': int(q), 'L_m': round(L / ppm, 2), 'thick': round(thick, 1),
                      't_int': round(t_int, 1), 'add': round(add_frac, 2), 'flank_m': round(fl / ppm, 2),
                      'area_m2': round(P.sum() / ppm / ppm, 2)}
                false = (L <= FALSE_MAX_M * ppm and fl < FALSE_FLANK_M * ppm
                         and (thick <= FALSE_THIN * t_int or add_frac >= FALSE_ADD))
                st['false'] = bool(false)
                log.append(st)
                if false and (best is None or S.sum() > best[0]):
                    # сам штрих — пиксели, лежащие вплотную между двумя кусками (грани соседних стен не трогаем)
                    best = (S.sum(), q, S & (dP <= thick + 1) & (dQ <= thick + 1))
            if best:
                _, q, Sthin = best
                lab[P] = q
                final[sl][Sthin] = 0
                lab[sl][Sthin] = q
                rooms.remove(p)
                changed = True
        if not changed:
            break
    return lab, final, rooms, log


def free_components(wall: np.ndarray):
    """Свободные области: метки (4-связность), наружная область = всё, что касается края картинки."""
    free = (wall == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(free, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
    outside = np.isin(lab, list(border)) & (free > 0)
    return n, lab, outside


# --- углы: семейства направлений ------------------------------------------------------------------------------------------

def angle_families(wall: np.ndarray, min_share: float = 0.06, merge_deg: float = 4.0) -> list[float]:
    """Направления стен (mod 180, градусы): гистограмма направлений рёбер контуров с весом длины → пики.
    Всегда есть 0 и 90; диагональ добавляется, если её доля ≥ min_share."""
    cnts, _ = cv2.findContours(wall.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    hist = np.zeros(180)
    for c in cnts:
        if len(c) < 20:
            continue
        ap = cv2.approxPolyDP(c, 1.5, True).reshape(-1, 2).astype(float)
        for p, q in zip(ap, np.roll(ap, -1, axis=0)):
            d = q - p
            L = math.hypot(*d)
            if L < 12:
                continue
            a = math.degrees(math.atan2(d[1], d[0])) % 180
            hist[int(round(a)) % 180] += L
    sm = np.convolve(np.concatenate([hist[-3:], hist, hist[:3]]), np.ones(3) / 3, 'valid')[2:-2]
    tot = sm.sum() or 1
    fams = []
    for a in np.argsort(-sm):
        if sm[a] / tot * 3 < min_share:
            break
        if all(min(abs(a - f), 180 - abs(a - f)) > merge_deg for f in fams):
            fams.append(float(a))
    for base in (0.0, 90.0):
        if all(min(abs(base - f), 180 - abs(base - f)) > merge_deg for f in fams):
            fams.append(base)
    # уточнить пик взвешенным средним в ±2°
    ref = []
    for f in fams:
        idx = [(int(f) + k) % 180 for k in range(-2, 3)]
        w = hist[idx]
        if w.sum() > 0:
            offs = np.array(range(-2, 3))
            ref.append((f + float((offs * w).sum() / w.sum())) % 180)
        else:
            ref.append(f)
    return ref


FAM_MIN_SEP = 8.0     # семейства углов панели ближе 8° — одно (T-09: крыло C 0,5°/5,7° — два близких направления)


def panel_families(wall: np.ndarray, min_len_px: float, sep_deg: float = 15.0,
                   min_sep: float = FAM_MIN_SEP) -> list[float]:
    """Семейства углов панели (T-04): `angle_families` по стенам панели + наклоны, у которых суммарная длина граней
    ≥ min_len_px, даже если их доля мала (эркер 45° на большом этаже); новый наклон — не ближе sep_deg к уже
    найденным (лесенка косой стены в 3–6° не становится «семейством»)."""
    fams = angle_families(wall) if wall.any() else [0.0, 90.0]
    cnts, _ = cv2.findContours(wall.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    hist = np.zeros(180)
    for c in cnts:
        if len(c) < 20:
            continue
        ap = cv2.approxPolyDP(c, 1.5, True).reshape(-1, 2).astype(float)
        for p, q in zip(ap, np.roll(ap, -1, axis=0)):
            d = q - p
            L = math.hypot(*d)
            if L < 12:
                continue
            hist[int(round(math.degrees(math.atan2(d[1], d[0])) % 180)) % 180] += L
    win = np.array([hist[(a - 1) % 180] + hist[a] + hist[(a + 1) % 180] for a in range(180)])
    for a in np.argsort(-win):
        if win[a] < min_len_px:
            break
        if all(angdiff(float(a), f) >= sep_deg for f in fams):
            idx = [(int(a) + k) % 180 for k in (-1, 0, 1)]
            w = hist[idx]
            fams.append((float(a) + float((np.array([-1, 0, 1]) * w).sum() / max(1e-9, w.sum()))) % 180)
    return separate_families(fams, hist, min_sep)


def separate_families(fams: list[float], hist: np.ndarray, min_sep: float = FAM_MIN_SEP) -> list[float]:
    """Семейства с минимальным разносом (T-09): из близких (< min_sep) остаётся то, у которого больше длина граней
    (гистерезис ±2° по `hist` — длины рёбер по углу 0–179). Иначе грань в 3° от «лишнего» семейства не считалась
    косой (метрика обманута), а выпрямление тянуло соседние стены к двум разным углам (косой пол)."""
    def weight(f):
        return float(sum(hist[(int(round(f)) + k) % 180] for k in range(-2, 3)))
    out = []
    for f in sorted(fams, key=lambda f: -weight(f)):
        if all(angdiff(f, g) >= min_sep for g in out):
            out.append(f)
    return out


def angdiff(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


# --- размеры комнаты ----------------------------------------------------------------------------------------------------

def _max_runs(m: np.ndarray, axis: int) -> np.ndarray:
    """Длина самого длинного непрерывного куска в каждой строке (axis=1) или столбце (axis=0)."""
    mm = m if axis == 1 else m.T
    out = []
    for row in mm:
        if not row.any():
            continue
        s, e = _runs(row)
        out.append(int((e - s).max()))
    return np.array(out, float)


def largest_rect(m: np.ndarray) -> tuple[float, float]:
    """Наибольший вписанный прямоугольник по осям (гистограммы по строкам + стек) → (ширина, высота) px."""
    h = np.zeros(m.shape[1], int)
    best, bw, bh = 0, 0, 0
    for row in m:
        h = np.where(row > 0, h + 1, 0)
        st = []
        for i in range(len(h) + 1):
            cur = h[i] if i < len(h) else 0
            start = i
            while st and st[-1][1] >= cur:
                start, hh = st.pop()
                a = hh * (i - start)
                if a > best:
                    best, bw, bh = a, i - start, hh
            st.append((start, cur))
    return float(bw), float(bh)


def room_extents(room: np.ndarray, angle_deg: float = 0.0, core: bool = False) -> dict:
    """Кандидаты размеров комнаты, px вдоль осей комнаты (угол — семейство стен): P95 хорды, медиана хорд, габарит;
    core=True — ещё «главное тело»: наибольший вписанный прямоугольник (подпись агентства часто без ниши/эркера)."""
    ys, xs = np.nonzero(room)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = room[y0:y1, x0:x1].astype(np.uint8)
    m = np.pad(m, 4)
    if abs(angle_deg) > 0.5:
        m, _ = rotate_mask(m, angle_deg)
    hx, vy = _max_runs(m, 1), _max_runs(m, 0)
    ys2, xs2 = np.nonzero(m)
    out = {'p95': (float(np.percentile(hx, 95)), float(np.percentile(vy, 95))),
           'med': (float(np.median(hx)), float(np.median(vy))),
           'bbox': (float(xs2.max() - xs2.min() + 1), float(ys2.max() - ys2.min() + 1))}
    if core:
        out['core'] = largest_rect(m[ys2.min():ys2.max() + 1, xs2.min():xs2.max() + 1])
    return out


# --- масштаб: RANSAC по подписям ------------------------------------------------------------------------------------------

CANDS = ('p95', 'med', 'bbox')


def _pred(ext: dict, cand: str, perm: int, s: float):
    wx, wy = ext.get(cand, ext['p95'])
    return (s * wx, s * wy) if perm == 0 else (s * wy, s * wx)   # perm 0: первое число подписи — по горизонтали


def _err(o: dict, s: float, cand: str, perm: int):
    pa, pb = _pred(o['ext'], cand, perm, s)
    a, b = o['dims']
    return max(abs(pa - a), abs(pb - b)), (pa, pb)


def _tol(dims, tol_abs, tol_rel):
    return max(tol_abs, tol_rel * max(dims))


def fit_scale(obs: list[dict], tol_abs: float = 0.12, tol_rel: float = 0.04, cands=CANDS) -> dict | None:
    """obs: [{'id', 'dims': (a, b) м, 'ext': room_extents(...)}] → масштаб м/px RANSAC (гипотеза — одна сторона одной
    комнаты; инлаер — комната, у которой какой-то кандидат и перестановка дают обе стороны в допуске); итог — медиана
    отношений по инлаерам (их выбранные кандидат/перестановка). Также sx/sy — отдельно по горизонтали/вертикали."""
    if not obs:
        return None
    hyps = set()
    for o in obs:
        for c in cands:
            wx, wy = o['ext'][c]
            for v in o['dims']:
                for w in (wx, wy):
                    if w > 0:
                        hyps.add(v / w)
    best = None
    for s in sorted(hyps):
        inl = []
        for o in obs:
            tol = _tol(o['dims'], tol_abs, tol_rel)
            opts = [(_err(o, s, c, p)[0], ci, p, c) for ci, c in enumerate(cands) for p in (0, 1)]
            e, _, p, c = min(opts)
            if e <= tol:
                inl.append((o, c, p, e))
        score = (len(inl), -sum(x[3] for x in inl))
        if best is None or score > best[0]:
            best = (score, s, inl)
    _, s0, inl = best
    if not inl:
        return None
    rx, ry = [], []
    for o, c, p, _ in inl:
        wx, wy = o['ext'][c]
        a, b = o['dims']
        if p == 0:
            rx.append(a / wx); ry.append(b / wy)
        else:
            rx.append(b / wx); ry.append(a / wy)
    s = float(np.median(rx + ry))
    return {'s': s, 's0': s0, 'sx': float(np.median(rx)), 'sy': float(np.median(ry)),
            'inliers': [(o['id'], c, p) for o, c, p, _ in inl], 'n': len(obs)}


def convention(fit: dict) -> tuple[str, int, float]:
    """Принятая на панели манера подписи: самый частый (кандидат, перестановка) среди инлаеров и его доля."""
    from collections import Counter
    cnt = Counter((c, p) for _, c, p in fit['inliers'])
    (c, p), n = cnt.most_common(1)[0]
    return c, p, n / max(1, len(fit['inliers']))


NEAR_FLAG_M = 0.15     # ни один кандидат не ближе — «подпись без ниши/эркера» (или мерили иначе): флаг, не подгонка


def leave_one_out(obs: list[dict], **kw) -> list[dict]:
    """Каждую комнату с подписью убираем из калибровки, масштаб и манеру — по остальным, затем предсказываем её
    стороны (кандидат и перестановка — манера остальных, НЕ подгонка под ответ)."""
    res = []
    for i, o in enumerate(obs):
        rest = obs[:i] + obs[i + 1:]
        f = fit_scale(rest, **kw)
        if f is None or len(rest) < 2:
            res.append({'id': o['id'], 'ok': False, 'why': 'мало комнат для калибровки'})
            continue
        c, p, share = convention(f)
        _, (pa, pb) = _err(o, f['s'], c, p)
        a, b = o['dims']
        # ближайший к подписи кандидат при масштабе остальных (порядок чисел — манера панели)
        near = min((_err(o, f['s'], cc, p)[0], cc) for cc in o['ext'])
        _, (na, nb) = _err(o, f['s'], near[1], p)
        res.append({'id': o['id'], 'ok': True, 's': f['s'], 'cand': c, 'perm': p, 'share': share,
                    'pred': (round(pa, 3), round(pb, 3)), 'gold': (a, b),
                    'err': (round(abs(pa - a), 3), round(abs(pb - b), 3)),
                    'rel': (abs(pa - a) / a, abs(pb - b) / b),
                    'near_cand': near[1], 'near_pred': (round(na, 3), round(nb, 3)),
                    'near_err': (round(abs(na - a), 3), round(abs(nb - b), 3)),
                    'near_rel': (abs(na - a) / a, abs(nb - b) / b),
                    'flag_label': near[0] > NEAR_FLAG_M})
    return res


def loo_summary(rows: list[dict], mode: str = 'conv') -> dict:
    """conv — кандидат по манере панели; near — ближайший кандидат (все комнаты); near_clean — без флага подписи."""
    ok = [r for r in rows if r.get('ok')]
    if mode != 'conv':
        ok = [r for r in ok if mode == 'near' or not r.get('flag_label')]
    ke, kr = ('err', 'rel') if mode == 'conv' else ('near_err', 'near_rel')
    e = [x for r in ok for x in r[ke]]
    rel = [x for r in ok for x in r[kr]]
    if not e:
        return {'n_dims': 0}
    return {'n_dims': len(e), 'mae': float(np.mean(e)), 'p95': float(np.percentile(e, 95)), 'max': float(max(e)),
            'mean_rel': float(np.mean(rel))}


# --- подписи: метры ↔ футы ------------------------------------------------------------------------------------------------

def feet_to_m(s: str) -> float:
    """«13'6"» → метры."""
    s = s.replace('’', "'").replace('”', '"').replace('″', '"').replace('′', "'").strip()
    ft, _, rest = s.partition("'")
    inch = rest.replace('"', '').strip() or '0'
    return (int(ft) * 12 + float(inch)) * 0.0254


def check_feet(dims_m, dims_ft, tol_in: float = 2.0) -> list[float]:
    """Расхождение метров и футов подписи, дюймы (UK-листы округляют дюймы вниз — допуск 2")."""
    return [round((m - feet_to_m(f)) / 0.0254, 2) for m, f in zip(dims_m, dims_ft)]


# --- выпрямление контуров -------------------------------------------------------------------------------------------------

def _line_isect(p1, d1, p2, d2):
    A = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]], float)
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t = np.linalg.solve(A, np.array(p2, float) - np.array(p1, float))
    return np.array(p1, float) + t[0] * np.array(d1, float)


def regularize_contour(cnt: np.ndarray, fams: list[float], tol_deg: float = 3.0, eps: float = 1.2,
                       max_shift: float = 4.0):
    """Контур (N×2, px) → выпрямленный многоугольник + рёбра для метрики углов.
    Ребро approxPolyDP → прямая МНК по исходным пикселям участка; если её угол в tol_deg от семейства — поворот
    к семейству вокруг центра участка; соседние коллинеарные — слияние; вершины — пересечения соседних прямых."""
    c = cnt.reshape(-1, 2)
    if len(c) < 4:
        return c.astype(float), []
    ap = cv2.approxPolyDP(c.reshape(-1, 1, 2), eps, True).reshape(-1, 2)
    if len(ap) < 3:
        return c.astype(float), []
    idx_of = {}
    for i, p in enumerate(c):
        idx_of.setdefault((int(p[0]), int(p[1])), i)
    idx = [idx_of[(int(p[0]), int(p[1]))] for p in ap]
    n = len(c)
    segs = []
    for k in range(len(idx)):
        i0, i1 = idx[k], idx[(k + 1) % len(idx)]
        span = c[i0:i1 + 1] if i1 >= i0 else np.vstack([c[i0:], c[:i1 + 1]])
        if len(span) < 2:
            continue
        pts = span.astype(np.float32)
        L = float(np.hypot(*(span[-1] - span[0])))
        if len(pts) >= 3 and L >= 3:
            vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        else:
            d = span[-1] - span[0]
            nrm = math.hypot(*d) or 1
            vx, vy = d / nrm
            x0, y0 = span.mean(axis=0)
        raw = math.degrees(math.atan2(vy, vx)) % 180
        fam = min(fams, key=lambda f: angdiff(f, raw)) if fams else raw
        ang = fam if angdiff(fam, raw) <= tol_deg else raw
        segs.append({'p': (float(x0), float(y0)), 'ang': ang, 'raw': raw, 'len': L, 'a': span[0], 'b': span[-1]})
    # слияние соседних коллинеарных
    merged = []
    for s in segs:
        if merged:
            m = merged[-1]
            if angdiff(m['ang'], s['ang']) < 0.5:
                d = (math.cos(math.radians(m['ang'])), math.sin(math.radians(m['ang'])))
                off = abs((s['p'][0] - m['p'][0]) * d[1] - (s['p'][1] - m['p'][1]) * d[0])
                if off < 1.5:
                    w1, w2 = m['len'], s['len']
                    m['p'] = ((m['p'][0] * w1 + s['p'][0] * w2) / (w1 + w2 or 1), (m['p'][1] * w1 + s['p'][1] * w2) / (w1 + w2 or 1))
                    m['b'] = s['b']
                    m['len'] = float(np.hypot(*(m['b'] - m['a'])))
                    continue
        merged.append(dict(s))
    if len(merged) < 3:
        return ap.astype(float), segs
    verts = []
    for k in range(len(merged)):
        s1, s2 = merged[k - 1], merged[k]
        d1 = (math.cos(math.radians(s1['ang'])), math.sin(math.radians(s1['ang'])))
        d2 = (math.cos(math.radians(s2['ang'])), math.sin(math.radians(s2['ang'])))
        q = _line_isect(s1['p'], d1, s2['p'], d2) if angdiff(s1['ang'], s2['ang']) > 10 else None
        orig = s2['a'].astype(float)
        if q is None or np.hypot(*(q - orig)) > max_shift:
            # почти параллельны или далеко — проекция исходной вершины на прямую s2
            p = np.array(s2['p']); dd = np.array(d2)
            q = p + dd * float(np.dot(orig - p, dd))
            if np.hypot(*(q - orig)) > max_shift:
                q = orig
        verts.append(q)
    return np.array(verts), merged


def mask_polygons(mask: np.ndarray, fams: list[float], min_area: float = 8.0, straight: bool = False,
                  ref: list | None = None, ref_d: float = 0.0, **kw):
    """Маска → список (внешний контур, [дыры]) выпрямленных многоугольников, px; плюс все рёбра (для метрики углов).
    straight=True — выпрямление T-04 (`straighten_contour`: рёбра к семействам, ступени, снап к линиям `ref`)."""
    cnts, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys, edges = [], []
    if hier is None:
        return polys, edges

    def one(c):
        if straight:
            v, e, _ = straighten_contour(c, fams, ref=ref, ref_d=ref_d, **kw)
            return v, e
        return regularize_contour(c, fams, **{k: v for k, v in kw.items() if k != 'fams_at'})
    hier = hier[0]
    for i, c in enumerate(cnts):
        if hier[i][3] != -1 or cv2.contourArea(c) < min_area:
            continue
        outer, e = one(c)
        edges += e
        holes = []
        j = hier[i][2]
        while j != -1:
            if cv2.contourArea(cnts[j]) >= min_area:
                h, e2 = one(cnts[j])
                holes.append(h)
                edges += e2
            j = hier[j][0]
        polys.append((outer, holes))
    return polys, edges


# --- выпрямление T-04: рёбра к семействам углов панели, ступени вместо косых, снап к стенам ------------------------------

STRAIGHT_TOL = 8.0      # ребро в 8° от семейства — к семейству (косой пол из пиксельной лесенки — 2–6°)
STRAIGHT_EPS = 1.5      # approxPolyDP, px
STRAIGHT_MIN_SEG = 4.0  # короче — не ребро, а стык (уходит в пересечение соседних прямых)
STRAIGHT_STATS = {'calls': 0, 'fallback_none': 0, 'fallback_bad': 0, 'snap_undo': 0}   # счётчик откатов к прежнему (для журнала)


def _unit(a):
    r = math.radians(a)
    return np.array([math.cos(r), math.sin(r)])


def _norm(a):
    r = math.radians(a)
    return np.array([-math.sin(r), math.cos(r)])


ROOM_FAM_MIN_M = 1.5    # T-16: прямое ребро комнаты от 1,5 м задаёт своё направление (перегородка по осям в крыле 5,7°)
ROOM_FAM_SEP = 2.5      # ... если оно дальше 2,5° от семейств панели (ближе — шум МНК длинной лесенки)
ROOM_FAM_RMS = 0.8      # ... и это прямая: остаток пикселей участка ≤ 0,8 px (не дуга эркера, не зубцы)


def room_families(mask: np.ndarray, base: list[float], min_len_px: float, sep: float = ROOM_FAM_SEP,
                  eps: float = STRAIGHT_EPS, max_rms: float = ROOM_FAM_RMS) -> list[float]:
    """Семейства углов КОМНАТЫ (кластера), T-16: семейства панели + направления длинных прямых рёбер контура самой
    комнаты, которых среди семейств панели нет (дальше sep°). Панель C-3: крыло повёрнуто на 5,7°, перегородки
    внутри — по осям листа; общий разнос семейств панели (≥ 8°, T-09) сливал 0° в 5,7°, и перегородки поворачивались
    вместе с крылом. Комната без такого ребра — семейства панели как были (лесенка 2–6° семейством не становится)."""
    out = [float(f) for f in base]
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    extra = []
    for cnt in cnts:
        c = cnt.reshape(-1, 2)
        if len(c) < 20:
            continue
        ap = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2)
        if len(ap) < 3:
            continue
        idx_of = {}
        for i, p in enumerate(c):
            idx_of.setdefault((int(p[0]), int(p[1])), i)
        idx = [idx_of[(int(p[0]), int(p[1]))] for p in ap]
        for k in range(len(idx)):
            i0, i1 = idx[k], idx[(k + 1) % len(idx)]
            span = c[i0:i1 + 1] if i1 >= i0 else np.vstack([c[i0:], c[:i1 + 1]])
            L = float(np.hypot(*(span[-1] - span[0])))
            if L < min_len_px or len(span) < 3:
                continue
            vx, vy, x0, y0 = cv2.fitLine(span.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
            res = (span[:, 0] - x0) * (-vy) + (span[:, 1] - y0) * vx
            if float(np.sqrt(np.mean(res ** 2))) > max_rms:
                continue
            a = math.degrees(math.atan2(vy, vx)) % 180
            if min(angdiff(a, f) for f in out) > sep:
                extra.append((a, L))
    extra.sort(key=lambda t: -t[1])
    for a, L in extra:
        if min(angdiff(a, f) for f in out) > sep:
            out.append(a)
    return out


def contour_lines(cnt: np.ndarray, fams: list[float], tol_deg: float = STRAIGHT_TOL, eps: float = STRAIGHT_EPS,
                  min_seg: float = STRAIGHT_MIN_SEG, short_px: float = 30.0, tol_short: float = 15.0,
                  min_free: float = 12.0, fams_at=None) -> list[dict]:
    """Контур → прямые: участок approxPolyDP → угол МНК; в tol_deg от семейства — угол семейства, смещение —
    медиана проекций пикселей участка на нормаль (робастно к зубцам); короткие участки отбрасываются (стык);
    соседние параллельные прямые с близким смещением сливаются. Прямая: ang, off, a, b (концы участка), len, raw.
    Участок короче short_px — угол МНК ненадёжен: к семейству в tol_short; не попал и короче min_free (фаска угла,
    зубец перемычки) — тоже стык. fams_at(участок) → семейства этого места (комнаты рядом, T-16) — для участков
    от short_px; короткие — к семействам fams (панели)."""
    c = cnt.reshape(-1, 2)
    if len(c) < 4:
        return []
    ap = cv2.approxPolyDP(c.reshape(-1, 1, 2), eps, True).reshape(-1, 2)
    if len(ap) < 3:
        return []
    idx_of = {}
    for i, p in enumerate(c):
        idx_of.setdefault((int(p[0]), int(p[1])), i)
    idx = [idx_of[(int(p[0]), int(p[1]))] for p in ap]
    lines = []
    for k in range(len(idx)):
        i0, i1 = idx[k], idx[(k + 1) % len(idx)]
        span = c[i0:i1 + 1] if i1 >= i0 else np.vstack([c[i0:], c[:i1 + 1]])
        L = float(np.hypot(*(span[-1] - span[0])))
        if len(span) < 2 or L < min_seg:
            continue
        pts = span.astype(np.float32)
        if len(pts) >= 3:
            vx, vy, _, _ = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        else:
            vx, vy = (span[-1] - span[0]) / (L or 1)
        raw = math.degrees(math.atan2(vy, vx)) % 180
        fs = fams
        if fams_at is not None and L >= short_px:
            fs = fams_at(span) or fams
        fam = min(fs, key=lambda f: angdiff(f, raw)) if fs else raw
        snapped = angdiff(fam, raw) <= (tol_short if L < short_px else tol_deg)
        if not snapped and L < min_free:
            continue
        ang = float(fam) % 180 if snapped else raw
        off = float(np.median(span.astype(float) @ _norm(ang)))
        lines.append({'ang': ang, 'off': off, 'a': span[0].astype(float), 'b': span[-1].astype(float), 'len': L,
                      'raw': raw, 'snapped': snapped, 'w': L})
    # слияние соседних параллельных с близким смещением (по кругу)
    merge_off = max(1.0, eps)
    changed = True
    while changed and len(lines) >= 2:
        changed = False
        for k in range(len(lines)):
            s1, s2 = lines[k - 1], lines[k]
            if s1 is s2 or angdiff(s1['ang'], s2['ang']) >= 0.5:
                continue
            o2 = float(s2['off']) if abs(s1['ang'] - s2['ang']) < 90 else -float(s2['off'])
            if abs(s1['off'] - o2) > merge_off:
                continue
            w1, w2 = s1['w'], s2['w']
            s1['off'] = (s1['off'] * w1 + o2 * w2) / (w1 + w2)
            s1['w'] = w1 + w2
            s1['b'] = s2['b']
            s1['len'] = float(np.hypot(*(s1['b'] - s1['a'])))
            lines.pop(k)
            changed = True
            break
    return lines


def lines_polygon(lines: list[dict], max_shift: float = 6.0) -> np.ndarray | None:
    """Прямые по кругу → вершины: соседние непараллельные — пересечение (если оно у стыка, ≤ max_shift);
    параллельные (ступень стены) — две вершины: проекции середины стыка на обе прямые (ступень под прямым углом,
    а не косое ребро через всю длину)."""
    if len(lines) < 3:
        return None
    verts = []
    for k in range(len(lines)):
        s1, s2 = lines[k - 1], lines[k]
        J = (s1['b'] + s2['a']) / 2
        u1, u2 = _unit(s1['ang']), _unit(s2['ang'])
        n1, n2 = _norm(s1['ang']), _norm(s2['ang'])
        p1, p2 = n1 * s1['off'], n2 * s2['off']                  # точки на прямых
        q = None
        if angdiff(s1['ang'], s2['ang']) > 10:
            q = _line_isect(p1, u1, p2, u2)
            # перекос длинной грани сдвигает её прямую (медиана) от угла — допуск растёт с длиной соседних граней
            lim = max(max_shift, 0.15 * min(s1['len'], s2['len'])) if angdiff(s1['ang'], s2['ang']) > 30 else max_shift
            if q is not None and np.hypot(*(q - J)) > lim:
                q = None
        if q is not None:
            verts.append(q)
        else:
            verts.append(p1 + u1 * float(np.dot(J - p1, u1)))
            verts.append(p2 + u2 * float(np.dot(J - p2, u2)))
    out = []
    for v in verts:                                                  # дубли и вершины на прямой — убрать
        if out and np.hypot(*(v - out[-1])) < 0.3:
            continue
        out.append(v)
    if len(out) > 1 and np.hypot(*(out[0] - out[-1])) < 0.3:
        out.pop()
    k = 0
    while len(out) > 3 and k < len(out):
        a, b, c = out[k - 1], out[k], out[(k + 1) % len(out)]
        cr = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if cr < 0.25 * max(1e-6, np.hypot(*(c - a))):
            out.pop(k)
        else:
            k += 1
    return np.array(out) if len(out) >= 3 else None


def snap_lines(lines: list[dict], ref: list[dict], max_d: float, min_overlap: float = 0.3) -> int:
    """Прямые контура (пол комнаты) → на ближайшую параллельную прямую `ref` (грань стены) не дальше max_d px,
    если их проекции вдоль направления перекрываются ≥ min_overlap длины. Меняет на месте; → сколько снапнуто."""
    n = 0
    for s in lines:
        if not s.get('snapped'):
            continue
        u = _unit(s['ang'])
        a0, a1 = sorted((float(s['a'] @ u), float(s['b'] @ u)))
        best = None
        for r in ref:
            if angdiff(r['ang'], s['ang']) >= 0.5:
                continue
            ro = float(r['off']) if abs(r['ang'] - s['ang']) < 90 else -float(r['off'])
            d = abs(ro - s['off'])
            if d > max_d:
                continue
            b0, b1 = sorted((float(r['a'] @ u), float(r['b'] @ u)))
            ov = min(a1, b1) - max(a0, b0)
            if ov < min_overlap * max(1.0, a1 - a0):
                continue
            if best is None or d < best[0]:
                best = (d, ro)
        if best is not None and best[0] > 1e-6:
            s['off'] = best[1]
            n += 1
    return n


def _poly_ok(verts: np.ndarray, c: np.ndarray) -> bool:
    """Выпрямленный многоугольник — простой и близок к исходному контуру: разница площадей (симметричная) не больше
    max(10 % площади, 1,5 px на длину контура — косая на 6° перемычка 1,7 м проходит, потерянный угол комнаты — нет)."""
    try:
        from shapely.geometry import Polygon
    except ImportError:                       # без shapely — только знак и площадь
        a0, a1 = abs(cv2.contourArea(c.astype(np.float32))), abs(cv2.contourArea(verts.astype(np.float32)))
        return abs(a1 - a0) <= max(0.1 * a0, 1.5 * cv2.arcLength(c.astype(np.float32), True))
    try:
        P, Q = Polygon(verts), Polygon(c)
        if not P.is_valid:
            return False
        if not Q.is_valid:
            Q = Q.buffer(0)
        return P.symmetric_difference(Q).area <= max(0.1 * Q.area, 1.5 * Q.length)
    except Exception:                         # noqa: BLE001 — сбой геометрии = «не годится», откат к прежнему
        return False


def straighten_contour(cnt: np.ndarray, fams: list[float], tol_deg: float = STRAIGHT_TOL, eps: float = STRAIGHT_EPS,
                       min_seg: float = STRAIGHT_MIN_SEG, max_shift: float = 6.0, ref: list | None = None,
                       ref_d: float = 0.0, short_px: float = 30.0, min_free: float = 12.0, fams_at=None):
    """Контур → (вершины, рёбра для метрики, прямые). Рёбра к семействам углов, ступени под прямым углом, вершины —
    пересечения; ref — прямые стен для снапа граней пола (ref_d px); fams_at — семейства по месту (`contour_lines`).
    Не прошло проверку (`_poly_ok`) — прежний `regularize_contour` (рёбра — его)."""
    c = cnt.reshape(-1, 2)
    lines = contour_lines(c, fams, tol_deg, eps, min_seg, short_px=short_px, min_free=min_free, fams_at=fams_at)
    STRAIGHT_STATS['calls'] += 1
    v = None
    if ref and ref_d > 0 and lines and len(c) >= 4:
        import copy
        ls = copy.deepcopy(lines)
        if snap_lines(ls, ref, ref_d):
            v = lines_polygon(ls, max_shift + 2 * ref_d)
            if v is not None and _poly_ok(v, c):
                lines = ls
            else:
                v = None
                STRAIGHT_STATS['snap_undo'] += 1
    if v is None:
        v = lines_polygon(lines, max_shift) if lines else None
        if v is None or len(c) < 4 or not _poly_ok(v, c):
            STRAIGHT_STATS['fallback_none' if v is None or len(c) < 4 else 'fallback_bad'] += 1
            v0, e0 = regularize_contour(cnt, fams)
            return v0, e0, []
    edges = []
    for k in range(len(v)):
        p, q = v[k - 1], v[k]
        L = float(np.hypot(*(q - p)))
        if L <= 0:
            continue
        a = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180
        edges.append({'ang': a, 'raw': a, 'len': L, 'a': p, 'b': q})
    return v, edges, lines


def rect_polygons(mask: np.ndarray, fams: list[float], min_area: float = 3.0, tol_deg: float = 12.0,
                  min_fill: float = 0.6, fams_at=None):
    """Перемычки и подоконники (закрытия проёмов) — прямоугольники: minAreaRect куска, угол — к семейству в tol_deg
    (закрытие, проведённое по чужому наклону листа, не косит перемычку). Не прямоугольный кусок (заполнение
    < min_fill) — `straighten_contour`. fams_at(пиксели куска) → семейства по месту (комнаты рядом, T-16).
    → [(вершины, [])] как mask_polygons."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < min_area:
            continue
        ys, xs = np.nonzero(lab == i)
        (cx, cy), (w, h), a = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        w, h = w + 1, h + 1                              # пиксель — квадрат 1×1, а не точка
        if len(xs) >= min_fill * w * h:
            fs = (fams_at(np.column_stack([xs, ys])) or fams) if fams_at is not None else fams
            f = min(fs, key=lambda q: angdiff(q, a)) if fs else a
            if angdiff(f, a) <= tol_deg:
                d = (f - a + 90) % 180 - 90
                a = a + d
            box = cv2.boxPoints(((cx, cy), (w, h), a))
            out.append((box.astype(float), []))
            continue
        sub, _ = mask_polygons((lab == i).astype(np.uint8), fams, min_area, straight=True, fams_at=fams_at)
        out += sub
    return out


def polygon_lines(polys: list, fams: list[float], min_len: float = 3.0) -> list[dict]:
    """Рёбра готовых многоугольников (внешние и дыры) → прямые для `snap_lines` (ang, off, a, b)."""
    out = []
    for outer, holes in polys:
        for v in [outer] + list(holes):
            v = np.asarray(v, float)
            for k in range(len(v)):
                p, q = v[k - 1], v[k]
                L = float(np.hypot(*(q - p)))
                if L < min_len:
                    continue
                a = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180
                out.append({'ang': a, 'off': float(p @ _norm(a)), 'a': p, 'b': q, 'len': L})
    return out


def skew_stats(polys: list, fams: list[float], min_len: float, tol_deg: float = 3.0, fams_of=None) -> dict:
    """Метрика косых граней (T-04): по рёбрам многоугольников длиной ≥ min_len — доля длины, чей угол дальше tol_deg
    от любого семейства панели; число многоугольников, где такое ребро есть (у пола — «косой пол»).
    fams_of(номер многоугольника, p, q) → семейства этого ребра (комнаты, T-16), иначе — fams панели."""
    tot = off = 0.0
    bad_polys = 0
    worst = 0.0
    for pk, (outer, holes) in enumerate(polys):
        bad = False
        for v in [outer] + list(holes):
            v = np.asarray(v, float)
            for k in range(len(v)):
                p, q = v[k - 1], v[k]
                L = float(np.hypot(*(q - p)))
                if L < min_len:
                    continue
                a = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180
                fs = (fams_of(pk, p, q) or fams) if fams_of is not None else fams
                d = min(angdiff(a, f) for f in fs) if fs else 0.0
                tot += L
                if d > tol_deg:
                    off += L
                    bad = True
                    worst = max(worst, d)
        bad_polys += int(bad)
    return {'polys': len(polys), 'skew_polys': bad_polys, 'off_share': round(off / tot, 4) if tot else 0.0,
            'worst_deg': round(worst, 1)}
