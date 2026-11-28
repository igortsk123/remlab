#!/usr/bin/env python3
"""T-98/5 · ветка А (владелец TG 3216/3222): нейросеть читает лист → plan.v1; здесь — (1) привязка плана к листу и (2) опора на чернила.
  python3 -I vetka_fit.py --plan plan.json --sheet лист.png --out папка [--flipy] [--no-fit] [--frame x0,y0,pxPerCm]
(1) Привязка: подгон масштаба (одного, одинакового по осям) и сдвига так, чтобы стены плана легли на ЧЁРНЫЕ линии листа (чернила = тёмные пиксели больших связных кусков;
    мелочь — текст — отброшена). Цена — средняя усечённая (≤ CAP px) дистанция от точек стен плана до ближайших чернил; поиск — сетка по масштабу, потом Nelder–Mead.
    Пишет fit.json {scale_px_per_unit, shift_px, residual_median_px, inliers_share, start, found}. --frame — известная привязка (x0,y0,pxPerCm в см) для самопроверки.
(2) Опора на чернила: у каждой стены — доля длины, лежащая на чернилах (допуск TOL px от оси); «выдуманная» < 0.35, «неполная» 0.35–0.7, «на линии» ≥ 0.7.
    «Пропущенные» — куски чернил дальше допуска от любой стены плана: связные компоненты длиной ≥ MIN_MISS px. Чернила, покрытые стенами / пропущенные.
    Наложение: стены цветом (синяя — на линии, жёлтая — неполная, красная — выдуманная), чернила зелёные — покрыты, оранжевые — пропущены.
Выход: out/fit.json, out/walls.csv, out/ink.json, out/overlay.png. $0, без сети."""
import argparse
import csv
import json
import math
import os

import cv2
import numpy as np
from scipy.optimize import minimize

CAP = 20.0          # px: усечение цены привязки
TOL_MIN = 3.0       # px: допуск от оси стены до чернил (минимум)
MIN_MISS = 25.0     # px: минимальная длина пропущенного куска
SHIFT_MAX_CM = 40.0     # «сдвинута»: параллельные чернила не дальше 40 см (директор 26.11)
REL_MAX = 190.0         # чернила темнее 75 % местной бумаги
RESID_CM = 15.0        # сдвиг меньше — «остаток подгонки»
SHIFT_MIN_SHARE = 0.6  # доля длины стены на чернилах после сдвига
V2 = os.environ.get('CORRECT_V2') == '1'         # ВЫКЛЮЧАТЕЛЬ Fable 8 (26.11): «между гранями не двигать», «несколько линий — не двигать»; по умолчанию ВЫКЛ
PAIR_INT_CM = 30.0      # внутренняя стена: пара линий — между ними до 30 см (Fable §8, стартовое число)
PAIR_EXT_CM = 80.0      # наружная — до 80 см
PAIR_MIN_SHARE = 0.6    # доля длины стены, на которой ось лежит между двумя линиями
SOFT_INK = os.environ.get('SOFT_INK') == '1'    # выключатель: второй поиск «слабых» чернил для класса «выдуманная» (по умолчанию ВЫКЛ, не в ворота)
SOFT_MIN_AREA = 15      # px: пыль мельче этого не берём
SOFT_MIN_SHARE = float(os.environ.get('SOFT_MIN_SHARE', '0.6'))    # доля длины стены на слабых чернилах → «слабая линия» (штрих допускается: директор предлагал 0.3)
SOFT_REL = float(os.environ.get('SOFT_REL', str(REL_MAX)))    # бледный порог: чернила темнее SOFT_REL/255 местной бумаги (директор: бледнее)
SOFT_GMAX = float(os.environ.get('SOFT_GMAX', '150'))    # потолок яркости слабых чернил
SOFT_BAND = float(os.environ.get('SOFT_BAND', '0'))    # полоса поиска вокруг оси в толщинах стены (0 = допуск TOL px; директор: 1.5)
UNIT = {'cm': 1.0, 'm': 100.0, 'mm': 0.1}


INK_LAYERS = os.environ.get('INK_LAYERS', '')       # ВЫКЛЮЧАТЕЛЬ T-98/21 (Fable 17 §3): два слоя чернил из tools/floorplan/ink_layers.py. '1' — ink=строгий, soft=чуткий; '2' — «на линии» (dt, подгонка) по чуткому, «покрыто/пропущено» по строгому; по умолчанию ВЫКЛ
INK_LAYERS_DIR = os.environ.get('INK_LAYERS_DIR', os.path.expanduser('~/remlab-logs/t98-21-wt/tools/floorplan'))
_LAST = {'path': None}
_LAYERS_CACHE = {}


def layers_for(g):
    """→ (чуткий, строгий) для последнего загруженного листа (по файлу; форма должна совпасть с g) или None"""
    p = _LAST['path']
    if not INK_LAYERS or p is None:
        return None
    if p not in _LAYERS_CACHE:
        import sys
        if INK_LAYERS_DIR not in sys.path:
            sys.path.insert(0, INK_LAYERS_DIR)
        import ink_layers
        s, st, pp = ink_layers.layers_of_path(p)
        _LAYERS_CACHE.clear()
        _LAYERS_CACHE[p] = (s, st, pp)
    s, st, _ = _LAYERS_CACHE[p]
    return (s, st) if s.shape == g.shape else None


def load_gray(path):
    _LAST['path'] = path
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return np.array(im.convert('L'))


INK_PALE = os.environ.get('INK_PALE') == '1'       # ВЫКЛЮЧАТЕЛЬ (а): потолок яркости чернил — от листа (бледный скан); по умолчанию ВЫКЛ
INK_THICK = os.environ.get('INK_THICK') == '1'     # ВЫКЛЮЧАТЕЛЬ (в): ядро фона шире — толстые залитые стены не считать бумагой; по умолчанию ВЫКЛ
try:
    INK_CFG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ink_config.json'), encoding='utf-8'))
except (OSError, ValueError):
    INK_CFG = {}


def ink_gray_cap(g, base=150.0):
    """Потолок яркости чернил. Обычно base (150, как было). При INK_PALE=1 и бледном листе (перцентиль pale_pct темнее base — нет) — перцентиль + запас."""
    cap = float(INK_CFG.get('gray_cap', base)) if INK_PALE else base
    if INK_PALE:
        pv = float(np.percentile(g, float(INK_CFG.get('pale_pct', 0.5))))
        if pv > cap:
            cap = pv + float(INK_CFG.get('pale_margin', 12))
    return cap


def ink_rel_max(g, base):
    """Бледный лист (INK_PALE=1 и перцентиль pale_pct светлее gray_cap): «темнее местной бумаги» тоже шире (pale_rel_max) — линии 175–185 на бумаге 240 это 0,73–0,77, а порог 190/255 = 0,745."""
    if INK_PALE and float(np.percentile(g, float(INK_CFG.get('pale_pct', 0.5)))) > float(INK_CFG.get('gray_cap', 150)):
        return float(INK_CFG.get('pale_rel_max', 225))
    return base


def bg_kernel(g):
    frac = float(INK_CFG.get('thick_bg_kernel_frac', 0.08)) if INK_THICK else 0.02
    return max(15, int(frac * max(g.shape)) | 1)


def ink_mask(g):
    """Чернила линий: тёмное (Оцу), без мелочи-текста (компоненты с большей стороной < 6 % листа отброшены)."""
    L = layers_for(g)
    if L is not None:                                   # INK_LAYERS: строгий слой (у «не годен» оба пусты → «чернил не найдено»)
        return L[1] if int(L[1].sum()) >= EMPTY_INK_PX or int(L[0].sum()) < EMPTY_INK_PX else L[0]
    # выравнивание освещения (БТИ 9798362: фото темнеет к краю, клетка тетради): фон = закрытие большим ядром (тонкие линии исчезают), делим
    k = bg_kernel(g)
    bg = cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)), (0, 0), k)
    rel = g.astype(np.float32) * 255.0 / np.maximum(bg.astype(np.float32), 1)     # яркость относительно местной бумаги
    thr, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    thr = min(thr, ink_gray_cap(g, 150.0))
    m = ((g < thr) & (rel < ink_rel_max(g, REL_MAX))).astype(np.uint8)       # чернила: тёмные И заметно темнее местной бумаги (убирает тёмный край фото)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros(n, bool)
    lim = 0.06 * max(g.shape)
    for i in range(1, n):
        if max(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]) >= lim:
            keep[i] = True
    return keep[lab]


def soft_ink_mask(g):
    """ВЫКЛЮЧАТЕЛЬ SOFT_INK=1 (директор 26.11, лист 2): те же «тёмные чернила», но БЕЗ фильтра «мелочь-текст» — тонкие линии вырезки дробятся на куски 3×25…5×35 px
    (JPEG, серый фон), а фильтр режет всё короче 6 % листа. Куски площадью < SOFT_MIN_AREA px (пыль) отбрасываются. Используется ТОЛЬКО для проверки стен класса «выдуманная»."""
    L = layers_for(g)
    if L is not None:                                   # INK_LAYERS: чуткий слой
        return L[0]
    k = bg_kernel(g)
    bg = cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)), (0, 0), k)
    rel = g.astype(np.float32) * 255.0 / np.maximum(bg.astype(np.float32), 1)
    thr, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = ((g < min(thr, ink_gray_cap(g, SOFT_GMAX))) & (rel < ink_rel_max(g, SOFT_REL))).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= SOFT_MIN_AREA:
            keep[i] = True
    return keep[lab]


def segs_of(plan):
    """→ (segments [(x0,y0,x1,y1,thick)] в СМ, имя уровня). Берём все уровни (один лист — обычно один)."""
    k = UNIT.get(plan.get('units', 'cm'), 1.0)
    out = []
    for lv in plan['levels']:
        for w in lv.get('walls', []):
            th = float(w['thickness']) * k if w.get('thickness') else {'exterior': 30.0, 'partition': 8.0}.get(w.get('kind'), 12.0)   # SPEC plan.v1: по виду стены
            out.append((w['from'][0] * k, w['from'][1] * k, w['to'][0] * k, w['to'][1] * k, th, w.get('id', '')))
    return out


def sample(segs, step_cm):
    P, owner = [], []
    for i, (x0, y0, x1, y1, th, _) in enumerate(segs):
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(2, int(L / step_cm) + 1)
        t = np.linspace(0, 1, n)
        P.append(np.stack([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t], 1))
        owner += [i] * n
    return np.vstack(P), np.array(owner)


def cost(params, P, dt, flipy):
    s, tx, ty = params
    if s <= 0:
        return CAP
    Q = P.copy()
    if flipy:
        Q[:, 1] = -Q[:, 1]
    x = Q[:, 0] * s + tx
    y = Q[:, 1] * s + ty
    H, W = dt.shape
    xi, yi = np.round(x).astype(int), np.round(y).astype(int)
    inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    d = np.full(len(x), CAP)
    d[inside] = np.minimum(dt[yi[inside], xi[inside]], CAP)
    return float(d.mean())


def fit(P, dt, ink, flipy):
    ys, xs = np.nonzero(ink)
    ib = (xs.min(), ys.min(), xs.max(), ys.max())
    Q = P.copy()
    if flipy:
        Q[:, 1] = -Q[:, 1]
    pb = (Q[:, 0].min(), Q[:, 1].min(), Q[:, 0].max(), Q[:, 1].max())
    s0 = min((ib[2] - ib[0]) / max(pb[2] - pb[0], 1e-6), (ib[3] - ib[1]) / max(pb[3] - pb[1], 1e-6))
    c_i = ((ib[0] + ib[2]) / 2, (ib[1] + ib[3]) / 2)
    c_p = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2)
    best = None
    starts = []
    for f in np.linspace(0.6, 1.4, 17):
        s = s0 * f
        t0 = (c_i[0] - c_p[0] * s, c_i[1] - c_p[1] * s)
        starts.append((cost((s, *t0), P, dt, flipy), s, t0))
    starts.sort(key=lambda a: a[0])
    for c, s, t0 in starts[:5]:
        r = minimize(cost, [s, t0[0], t0[1]], args=(P, dt, flipy), method='Nelder-Mead',
                     options={'xatol': 0.01, 'fatol': 1e-4, 'maxiter': 600, 'initial_simplex': np.array([[s, *t0], [s * 1.03, *t0], [s, t0[0] + 12, t0[1]], [s, t0[0], t0[1] + 12]])})
        if best is None or r.fun < best.fun:
            best = r
    return best.x, float(best.fun), (s0, c_i, c_p)


FIT_V3 = os.environ.get('FIT_V3') == '1'                # У2 (Fable 10): поворот ±3° в привязке, мягкая цена вместо обрезанной, отрыв первого старта от второго
ROT_MAX_DEG = 3.0


def rot_about(Q, deg, c):
    """Повернуть точки плана (N×2, см) на deg градусов вокруг c."""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    d = Q - np.array(c)
    return np.stack([c[0] + d[:, 0] * ca - d[:, 1] * sa, c[1] + d[:, 0] * sa + d[:, 1] * ca], 1)


def cost3(params, P, dt, c):
    """Мягкая цена: CAP·tanh(d/CAP) (гладко насыщается, вместо жёсткого min(d, CAP)) + штраф за поворот за пределом ±3°."""
    s, tx, ty, th = params
    if s <= 0:
        return 1e6
    Q = rot_about(P, th, c)
    x = Q[:, 0] * s + tx
    y = Q[:, 1] * s + ty
    H, W = dt.shape
    xi, yi = np.round(x).astype(int), np.round(y).astype(int)
    inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    d = np.full(len(x), 4 * CAP)
    d[inside] = np.minimum(dt[yi[inside], xi[inside]], 4 * CAP)
    pen = 100.0 * max(0.0, abs(th) - ROT_MAX_DEG)
    return float(np.mean(CAP * np.tanh(d / CAP))) + pen


def fit3(P, dt, ink):
    """Как fit(), но 4 параметра (масштаб, сдвиг, поворот ±3°) и мягкая цена; несколько стартов, запоминаем отрыв лучшего от второго (другой «бассейн»)."""
    ys, xs = np.nonzero(ink)
    ib = (xs.min(), ys.min(), xs.max(), ys.max())
    pb = (P[:, 0].min(), P[:, 1].min(), P[:, 0].max(), P[:, 1].max())
    s0 = min((ib[2] - ib[0]) / max(pb[2] - pb[0], 1e-6), (ib[3] - ib[1]) / max(pb[3] - pb[1], 1e-6))
    c_i = ((ib[0] + ib[2]) / 2, (ib[1] + ib[3]) / 2)
    c_p = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2)
    starts = []
    for f in np.linspace(0.6, 1.4, 17):
        s = s0 * f
        t0 = (c_i[0] - c_p[0] * s, c_i[1] - c_p[1] * s)
        starts.append((cost3((s, *t0, 0.0), P, dt, c_p), s, t0))
    starts.sort(key=lambda a: a[0])
    runs = []
    plan_starts = [(s, t0, 0.0) for c, s, t0 in starts[:5]] + [(s, t0, th) for c, s, t0 in starts[:3] for th in (-2.0, 2.0)]
    for s, t0, th in plan_starts:
        r = minimize(cost3, [s, t0[0], t0[1], th], args=(P, dt, c_p), method='Nelder-Mead',
                     options={'xatol': 0.01, 'fatol': 1e-4, 'maxiter': 900, 'initial_simplex': np.array([[s, *t0, th], [s * 1.03, *t0, th], [s, t0[0] + 12, t0[1], th], [s, t0[0], t0[1] + 12, th], [s, *t0, th + 1.0]])})
        runs.append((float(r.fun), r.x))
    runs.sort(key=lambda a: a[0])
    best = runs[0]
    second = None
    for f_, x in runs[1:]:
        if abs(x[0] / best[1][0] - 1) > 0.02 or abs(x[1] - best[1][1]) > 8 or abs(x[2] - best[1][2]) > 8 or abs(x[3] - best[1][3]) > 0.5:
            second = (f_, x)
            break
    gap = None if second is None else round(second[0] - best[0], 3)
    return best[1], best[0], (s0, c_i, c_p), {'отрыв_первого_от_второго_px': gap, 'второй_найден': second is not None, 'стартов': len(runs)}


EMPTY_INK_PX = 200                                       # меньше стольких «чернильных» пикселей — маска пуста


def not_verified(plan, g, out, reason):
    """Пустая маска чернил: fit.json/walls.csv/ink.json с классом «не проверено» и причиной; код возврата 0 (раньше — ValueError на xs.min())."""
    H, W = g.shape
    segs = segs_of(plan)
    json.dump({'found': 'не проверено', 'причина': reason, 'sheet_px': [W, H], 'самый_тёмный_0.1%': int(np.percentile(g, 0.1))},
              open(f'{out}/fit.json', 'w'), ensure_ascii=False, indent=1)
    with open(f'{out}/walls.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, ['стена', 'длина_px', 'доля_на_чернилах', 'класс', 'причина'])
        w.writeheader()
        for i, (x0, y0, x1, y1, th, wid) in enumerate(segs):
            w.writerow({'стена': wid or f'#{i}', 'длина_px': '', 'доля_на_чернилах': '', 'класс': 'не проверено', 'причина': reason})
    json.dump({'не_проверено': True, 'причина': reason, 'стен': len(segs)}, open(f'{out}/ink.json', 'w'), ensure_ascii=False, indent=1)
    print(f'не проверено: {reason} (стен {len(segs)})')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--sheet', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--flipy', action='store_true')
    ap.add_argument('--no-fit', action='store_true', help='не подгонять: взять --frame x0,y0,pxPerCm (см)')
    ap.add_argument('--frame')
    ap.add_argument('--rot', help='deg,cx,cy — повернуть план (см) вокруг (cx,cy), с --no-fit')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    plan = json.load(open(a.plan, encoding='utf-8'))
    g = load_gray(a.sheet)
    ink = ink_mask(g)
    if int(ink.sum()) < EMPTY_INK_PX:                   # пустая маска (бледный скан: самые тёмные пиксели светлее порога) — не падать, а «не проверено»
        return not_verified(plan, g, a.out, 'чернил не найдено')
    dt = cv2.distanceTransform((~(soft_ink_mask(g) if INK_LAYERS == '2' else ink)).astype(np.uint8), cv2.DIST_L2, 3)       # '2': «на линии» и подгонка — по чуткому слою
    dt_soft = cv2.distanceTransform((~soft_ink_mask(g)).astype(np.uint8), cv2.DIST_L2, 3) if SOFT_INK else None
    segs = segs_of(plan)
    kinds = [w.get('kind', 'interior') for lv in plan['levels'] for w in lv.get('walls', [])]
    P, owner = sample(segs, 5.0)                        # точка каждые 5 см плана — только для подгонки
    rot_info = None
    if a.no_fit:
        x0, y0, ppc = (float(v) for v in a.frame.split(','))
        s, tx, ty = ppc, -x0 * ppc, -y0 * ppc
        found = 'frame'
        res_cost = cost((s, tx, ty), P, dt, a.flipy)
        start = None
    else:
        if FIT_V3 and not a.flipy:
            (s, tx, ty, th_), res_cost, (s0, c_i, c_p), v3info = fit3(P, dt, ink)
            found = 'fit-v3'
            start = dict({'s0': round(s0, 4)}, **v3info)
            rot_info = (float(th_), c_p)
        else:
            (s, tx, ty), res_cost, (s0, c_i, c_p) = fit(P, dt, ink, a.flipy)
            found = 'fit'
            start = {'s0': round(s0, 4)}
    if a.no_fit and a.rot:
        _d, _cx, _cy = (float(v) for v in a.rot.split(','))
        rot_info = (_d, (_cx, _cy))
    if rot_info is not None and abs(rot_info[0]) > 1e-9:    # дальше всё считается по повёрнутому плану (стены и точки), fit.json хранит угол и центр
        th_r, c_r = rot_info
        P = rot_about(P, th_r, c_r)
        segs = [tuple(rot_about(np.array([[x0_, y0_], [x1_, y1_]]), th_r, c_r).ravel()) + (th_, wid_) for (x0_, y0_, x1_, y1_, th_, wid_) in segs]
    # точки в пикселях
    Qd = P.copy()
    if a.flipy:
        Qd[:, 1] = -Qd[:, 1]
    px = Qd * s + [tx, ty]
    H, W = g.shape
    d_all = []
    for p in px:
        xi, yi = int(round(p[0])), int(round(p[1]))
        d_all.append(dt[yi, xi] if 0 <= xi < W and 0 <= yi < H else CAP)
    d_all = np.array(d_all)
    fit_info = {'found': found, 'scale_px_per_unit_cm': round(float(s), 5), 'shift_px': [round(float(tx), 1), round(float(ty), 1)],
                'residual_mean_px_capped': round(res_cost, 2), 'residual_median_px': round(float(np.median(d_all)), 2),
                'inliers_share_le_3px': round(float((d_all <= 3).mean()), 3), 'flipy': a.flipy, 'sheet_px': [W, H], 'start': start,
                'rot_deg': round(rot_info[0], 3) if rot_info else 0.0, 'rot_center_cm': [round(float(rot_info[1][0]), 2), round(float(rot_info[1][1]), 2)] if rot_info else None}
    json.dump(fit_info, open(f'{a.out}/fit.json', 'w'), ensure_ascii=False, indent=1)

    # --- опора на чернила, по стенам (точки каждые 2 px листа)
    rows, covered_mask = [], np.zeros((H, W), np.uint8)
    for i, (x0, y0, x1, y1, th, wid) in enumerate(segs):
        A = np.array([x0, y0], float)
        B = np.array([x1, y1], float)
        if a.flipy:
            A[1], B[1] = -A[1], -B[1]
        pa, pb = A * s + [tx, ty], B * s + [tx, ty]
        L = float(np.hypot(*(pb - pa)))
        tol = TOL_MIN + 1.0                              # ось стены должна лежать на чернилах (внутри толстой линии dt=0)
        band = 0.5 * th * s + TOL_MIN                    # полоса «стена покрывает чернила»: половина толщины + допуск
        n = max(2, int(L / 2) + 1)
        t = np.linspace(0, 1, n)
        pts = pa[None] + (pb - pa)[None] * t[:, None]
        on = []
        for p in pts:
            xi, yi = int(round(p[0])), int(round(p[1]))
            on.append(bool(0 <= xi < W and 0 <= yi < H and dt[yi, xi] <= tol))
        share = float(np.mean(on))
        cls = 'на линии' if share >= 0.7 else ('неполная' if share >= 0.35 else 'выдуманная')
        shift_cm, shift_share, shift_dxy = '', '', ('', '')
        between = ''
        if V2 and share < 0.7 and L > 0:
            # Fable §3 п.2 (вопрос 8): ось ВНУТРИ пары параллельных линий (внутр. ≤30 см между ними, наружн. ≤80 см) — стена «на линии», не двигать
            nrm_b = np.array([-(pb - pa)[1], (pb - pa)[0]]) / L
            gap_px = (PAIR_EXT_CM if kinds[i] == 'exterior' else PAIR_INT_CM) * s
            R_ = int(gap_px) + 1
            ok_b = []
            for p in pts:
                lo = hi = None
                for d_ in range(1, R_ + 1):
                    if lo is None:
                        xi, yi = int(round(p[0] - nrm_b[0] * d_)), int(round(p[1] - nrm_b[1] * d_))
                        if 0 <= xi < W and 0 <= yi < H and ink[yi, xi]:
                            lo = d_
                    if hi is None:
                        xi, yi = int(round(p[0] + nrm_b[0] * d_)), int(round(p[1] + nrm_b[1] * d_))
                        if 0 <= xi < W and 0 <= yi < H and ink[yi, xi]:
                            hi = d_
                    if lo is not None and hi is not None:
                        break
                ok_b.append(lo is not None and hi is not None and lo + hi <= gap_px)
            if float(np.mean(ok_b)) >= PAIR_MIN_SHARE:
                cls, between = 'на линии', round(float(np.mean(ok_b)), 3)
        if share < 0.7 and L > 0 and not between:
            # правило директора 26.11: стена без опоры, но параллельные чернила в пределах 40 см → «сдвинута на N см»; «выдумана» — только если рядом линии нет
            nrm = np.array([-(pb - pa)[1], (pb - pa)[0]]) / L
            best = (0.0, 0.0)
            shs = {}
            for off in range(-int(round(SHIFT_MAX_CM * s)), int(round(SHIFT_MAX_CM * s)) + 1):
                if abs(off) <= tol:
                    continue
                q = pts + nrm[None] * off
                ok = [bool(0 <= int(round(p[0])) < W and 0 <= int(round(p[1])) < H and dt[int(round(p[1])), int(round(p[0]))] <= tol) for p in q]
                sh = float(np.mean(ok))
                shs[off] = sh
                if sh > best[0]:
                    best = (sh, float(off))
            if best[0] >= SHIFT_MIN_SHARE:
                # линия чернил — это ПОЛОСА смещений (залитая стена) или ДВЕ полосы (двойная линия БТИ): переносим на СЕРЕДИНУ полосы / пары полос (ось, формат plan.v1)
                good = sorted(o for o, v in shs.items() if v >= SHIFT_MIN_SHARE)
                runs, cur = [], [good[0]]
                for o in good[1:]:
                    if o - cur[-1] <= 2:
                        cur.append(o)
                    else:
                        runs.append(cur)
                        cur = [o]
                runs.append(cur)
                r1 = next(r for r in runs if best[1] in r)
                c1 = (r1[0] + r1[-1]) / 2.0
                gap_max = 1.5 * th * s + 4                        # вторая линия пары — не дальше 1.5 толщины стены
                partners = [(abs((r[0] + r[-1]) / 2.0 - c1), (r[0] + r[-1]) / 2.0) for r in runs if r is not r1 and 0 < abs((r[0] + r[-1]) / 2.0 - c1) <= gap_max]
                if V2:        # Fable §3: линий-кандидатов несколько и это не пара → НЕ двигать, пометить (выбор «самой длинной» — угадывание)
                    pair_px = (PAIR_EXT_CM if kinds[i] == 'exterior' else PAIR_INT_CM) * s
                    cand_pairs = [(abs((r[0] + r[-1]) / 2.0 - c1), (r[0] + r[-1]) / 2.0) for r in runs if r is not r1 and 0 < abs((r[0] + r[-1]) / 2.0 - c1) <= pair_px]
                    if len(runs) > 1 and len(runs) != 2:
                        cls = 'несколько линий'
                    elif len(runs) == 2 and not cand_pairs:
                        cls = 'несколько линий'
                    partners = cand_pairs
                target = (c1 + min(partners)[1]) / 2.0 if partners else c1
                best = (best[0], target)
                if cls == 'несколько линий':
                    n_cand = len(runs)
                    shift_cm, shift_share = '', ''
                    best = None
            if best is not None and best[0] >= SHIFT_MIN_SHARE and cls != 'несколько линий':
                shift_cm, shift_share = round(abs(best[1]) / s, 1), round(best[0], 3)
                dpx = nrm * best[1]                                         # смещение на лист (px) → в систему плана (см): делим на масштаб, у при --flipy зеркалим
                shift_dxy = (round(float(dpx[0]) / s, 2), round(float(dpx[1]) / s * (-1 if a.flipy else 1), 2))
                cls = 'сдвинута' if shift_cm >= RESID_CM else 'остаток подгонки'      # директор: <15 см — остаток общей подгонки, не ошибка нейросети
        soft_share = ''
        if SOFT_INK and cls == 'выдуманная' and L > 0:           # сильных чернил рядом нет → ищем слабые (тонкие дроблёные линии) вдоль оси
            ptsw = pa[None] + (pb - pa)[None] * np.linspace(0, 1, max(2, int(L / 2) + 1))[:, None]
            okw = [bool(0 <= int(round(p[0])) < W and 0 <= int(round(p[1])) < H and dt_soft[int(round(p[1])), int(round(p[0]))] <= max(tol, SOFT_BAND * th * s)) for p in ptsw]
            soft_share = round(float(np.mean(okw)), 3)
            if soft_share >= SOFT_MIN_SHARE:
                cls = 'слабая линия'
        rows.append({'стена': wid or f'#{i}', 'длина_px': round(L, 1), 'доля_на_чернилах': round(share, 3), 'класс': cls, 'допуск_px': round(tol, 1), 'доля_на_слабых_чернилах': soft_share, 'между_гранями': between,
                     'сдвиг_см': shift_cm, 'доля_на_чернилах_после_сдвига': shift_share, 'сдвиг_dx_см': shift_dxy[0], 'сдвиг_dy_см': shift_dxy[1]})
        cv2.line(covered_mask, tuple(np.round(pa).astype(int)), tuple(np.round(pb).astype(int)), 1, int(2 * band + 1))
    with open(f'{a.out}/walls.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, list(rows[0].keys()) if rows else ['стена'])
        w.writeheader()
        w.writerows(rows)
    total_len = sum(r['длина_px'] for r in rows) or 1.0
    inv_len = sum(r['длина_px'] for r in rows if r['класс'] == 'выдуманная')
    part_len = sum(r['длина_px'] for r in rows if r['класс'] == 'неполная')
    # --- пропущенные чернила
    cov = covered_mask.astype(bool)
    missed = ink & ~cov
    missed = cv2.morphologyEx(missed.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    n, lab, st, _ = cv2.connectedComponentsWithStats(missed.astype(np.uint8), 8)
    miss_comps = []
    miss_keep = np.zeros(n, bool)
    for i in range(1, n):
        ln = float(math.hypot(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]))
        if ln >= MIN_MISS:
            miss_keep[i] = True
            miss_comps.append({'x': int(st[i, 0]), 'y': int(st[i, 1]), 'w': int(st[i, 2]), 'h': int(st[i, 3]), 'длина_px': round(ln, 1)})
    missed_final = miss_keep[lab]
    ink_px = int(ink.sum())
    ink_info = {'чернил_px': ink_px, 'покрыто_стенами_доля': round(float((ink & cov).sum() / max(ink_px, 1)), 3),
                'пропущено_доля': round(float(missed_final.sum() / max(ink_px, 1)), 3), 'пропущенных_кусков': len(miss_comps),
                'стен': len(rows), 'на_линии': sum(r['класс'] == 'на линии' for r in rows), 'неполных': sum(r['класс'] == 'неполная' for r in rows),
                'выдуманных': sum(r['класс'] == 'выдуманная' for r in rows), 'сдвинутых': sum(r['класс'] == 'сдвинута' for r in rows), 'остаток_подгонки': sum(r['класс'] == 'остаток подгонки' for r in rows), 'слабых_линий': sum(r['класс'] == 'слабая линия' for r in rows), 'несколько_линий': sum(r['класс'] == 'несколько линий' for r in rows), 'между_гранями': sum(1 for r in rows if r['между_гранями'] != ''),
                'сдвиги_см': [r['сдвиг_см'] for r in rows if r['класс'] == 'сдвинута'],
                'доля_длины_стен_на_чернилах': round(sum(r['длина_px'] * r['доля_на_чернилах'] for r in rows) / total_len, 3),
                'доля_длины_выдуманных': round(inv_len / total_len, 3), 'доля_длины_неполных': round(part_len / total_len, 3),
                'куски': sorted(miss_comps, key=lambda c: -c['длина_px'])[:30]}
    json.dump(ink_info, open(f'{a.out}/ink.json', 'w'), ensure_ascii=False, indent=1)
    # --- наложение
    over = cv2.cvtColor((255 - (255 - g) // 3).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    over[ink & cov] = (60, 170, 60)                  # зелёный — чернила покрыты стеной плана
    over[missed_final] = (0, 140, 255)               # оранжевый — пропущено
    colors = {'на линии': (200, 90, 20), 'неполная': (0, 215, 255), 'выдуманная': (30, 30, 230), 'сдвинута': (200, 60, 170), 'остаток подгонки': (230, 160, 90), 'слабая линия': (200, 200, 60), 'несколько линий': (120, 120, 120)}
    for r, (x0, y0, x1, y1, th, wid) in zip(rows, segs):
        A = np.array([x0, y0], float)
        B = np.array([x1, y1], float)
        if a.flipy:
            A[1], B[1] = -A[1], -B[1]
        pa, pb = np.round(A * s + [tx, ty]).astype(int), np.round(B * s + [tx, ty]).astype(int)
        cv2.line(over, tuple(pa), tuple(pb), colors[r['класс']], 2)
    txt = [f"привязка: {found}; масштаб {s:.3f} px/см; остаток {fit_info['residual_median_px']} px; доля точек ≤3px {fit_info['inliers_share_le_3px']}",
           f"стен {ink_info['стен']}: на линии {ink_info['на_линии']}, неполных {ink_info['неполных']}, сдвинутых {ink_info['сдвинутых']}, остаток подгонки {ink_info['остаток_подгонки']}, выдуманных {ink_info['выдуманных']}; "
           f"чернил покрыто {ink_info['покрыто_стенами_доля']:.0%}, пропущено {ink_info['пропущено_доля']:.0%}",
           'синяя — на линии · жёлтая — неполная · фиолет. — сдвинута · красная — выдуманная · зелёное — покрыто · оранж. — пропущено']
    band = np.full((22 * len(txt) + 8, W, 3), 255, np.uint8)
    for i, t_ in enumerate(txt):
        from PIL import Image, ImageDraw, ImageFont
        pil = Image.fromarray(band)
        d = ImageDraw.Draw(pil)
        try:
            font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
        except OSError:
            font = ImageFont.load_default()
        d.text((6, 4 + 22 * i), t_, fill=(0, 0, 0), font=font)
        band = np.array(pil)
    cv2.imwrite(f'{a.out}/overlay.png', np.vstack([band, over]))
    print(json.dumps({'fit': fit_info, 'ink': {k: v for k, v in ink_info.items() if k != 'куски'}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
