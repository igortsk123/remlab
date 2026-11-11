#!/usr/bin/env python3
"""Стенд OpenCV-пути (T-20261109-02): картинка планировки → панели → стены/проёмы/комнаты → масштаб по подписям →
метрики против золота `gold/<план>.json` → модель для 3D (`model-<план>.json`) и наложения для глаз.

  python tools/floorplan/bench.py <A|B|C> <папка-вывода> [--inputs /home/pakar/remlab-logs/floorplan-bench/inputs]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpcore as fc  # noqa: E402
import repair  # noqa: E402

HERE = Path(__file__).resolve().parent

# Маска стен по плану: A — синий цвет; B — тёмное с водяным знаком (стена под ним ~100 серого) → порог выше;
# C — чёрное, внутренние стены тонкие (3–5 px) → открытие 3.
CFG = {
    'A': {'mask': ('blue',), 'min_area': 40, 'thin': 15, 'glaze': 215},
    'B': {'mask': ('dark', 135, 5), 'min_area': 120, 'thin': 15, 'glaze': 200},
    'C': {'mask': ('dark', 110, 3), 'min_area': 60, 'thin': 15, 'glaze': 190},
}
H_WALL, SILL, HEAD = 2.6, 0.9, 2.1
GLAZE_MIN = 0.6
DOOR_EV = 0.75
THIN_DOOR_MAX_M = 1.2     # T-20261110-33: дверь в тонкой перегородке (второй проход) — одностворчатая, шире — шум/сантехника
GLAZED_ARC = True         # наружный проём с «рамой» тоже проверяем на дугу (T-20261110-11); False — прежнее «рама → окно»
DOOR_EV_GLAZED = 0.9      # с «рамой» по умолчанию окно: дверь — только при почти целой «вогнутой» дуге (11 точек из 12;
                          # у входов нашего примера 1,0, у окон с мебелью/рамой рядом на A, B, T — 0,75–0,83)
BAY_RECT = 0.85     # эркер — почти прямоугольник по заполнению minAreaRect
ENV_DMAX = float(os.environ.get('FP_ENV_DMAX', '3.0'))   # наибольшая глубина закрытия контура, в толщинах стены (2,5 → 3: C, окно в ступени стены)
FAINT_GRAY = 230  # бледная линия рамы окна (на белом 255 / заливке ~244)
HULL_M = float(os.environ.get('FP_HULL_M', '4.0'))   # грубый контур постройки для снятия перемычек между постройками, м
PANEL_R_M = float(os.environ.get('FP_PANEL_R_M', '2.5'))   # запас контура панели VLM, м (до соседнего контура)
LB_M = float(os.environ.get('FP_LB_M', '6.0'))   # наибольший закрываемый наружный разрыв, м (длиннее 3,6 м — только по раме)
ENV_GEO = os.environ.get('FP_ENV_GEO', '1') != '0'   # T-20261111-09: полоса контура — по свободному месту (0 — по прямой, как до)
SPLIT_DEEP = os.environ.get('FP_SPLIT', '1') != '0'  # T-20261111-09: наружный разрыв из закрытий, сошедшихся углом, — делить (0 — как до)
PS_TAIL = os.environ.get('FP_PS_TAIL', '1') != '0'   # T-20261111-09: малый разрыв без дуги — срезать хвост-клин и проверить снова
TEXT_MASK = os.environ.get('FP_TEXT_MASK', '1') != '0'  # T-20261111-09: дуга внутренней перемычки — без букв подписей
TEXT_EV_MIN = 0.5   # без строк подписей дуги должно остаться хоть половина: прихожая TGva 0,95 → 0,26 (дугу давали буквы);
                    # кухня 4y0o 0,80 → 0,63 (настоящая дверь, разрыв длиннее двери, часть точек попадала на подпись)


# T-20261110-38: тип комнаты из ответа labels4 → имя для комнаты без названия на листе (английское: его понимают
# `pipeline.KIND_RULES`, `listing.match` и перевод заголовков `trial_bundle.room_titles`)
TYPE_NAME = {'living': 'Living room', 'kitchen': 'Kitchen', 'kitchen_living': 'Kitchen-living room', 'bedroom': 'Bedroom',
             'bathroom': 'Bathroom', 'wc': 'WC', 'hall': 'Hall', 'corridor': 'Corridor', 'wardrobe': 'Dressing room',
             'storage': 'Storage', 'study': 'Study', 'balcony': 'Balcony', 'other': 'Room'}
TYPE_SRC = ('name', 'furniture', 'position')


def _m2(v, lo=0.3, hi=500.0):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= float(v) <= hi else None


def room_meta(r: dict) -> dict:
    """Поля labels4 одной комнаты → {'vtype', 'vtype_src', 'area_m2', 'area_reduced_m2'} (непонятное — None).
    Тип вне списка — None; площадь только числом в разумных пределах; пониженная — меньше своей площади."""
    t = str(r.get('type') or '').strip().lower().replace('-', '_').replace(' ', '_')
    a, ar = _m2(r.get('area_m2')), _m2(r.get('area_reduced_m2'), 0.05)
    if ar is not None and (a is None or ar >= a):
        ar = None
    vt = t if t in TYPE_NAME else ('other' if a is not None else None)
    src = str(r.get('type_src') or '').strip().lower()
    return {'vtype': vt, 'vtype_src': src if vt and src in TYPE_SRC else None, 'area_m2': a, 'area_reduced_m2': ar}


def number_type_names(labels: list) -> None:
    """T-20261110-38/2: одно имя из типа у нескольких комнат («Bathroom» ×2 на туре Этажей) → «Bathroom 1», «Bathroom 2» —
    по убыванию площади с листа, без площади — сверху вниз, слева направо. Имена с листа не трогаем. На месте."""
    by = {}
    for q in labels:
        if q.get('name_src') == 'type':
            by.setdefault(q['name'], []).append(q)
    for name, qq in by.items():
        if len(qq) < 2:
            continue
        qq.sort(key=lambda q: (-(q.get('area_m2') or 0.0), q['pt'][1], q['pt'][0]))
        for i, q in enumerate(qq, 1):
            q['name'] = f'{name} {i}'


def load_vlm(plan, vdir, shape):
    """Ответы VLM flash (как в продукте): точки подписей и контуры панелей, сетка 0–1000 → px листа."""
    import vlm
    H, W = shape[:2]
    kx, ky = W / 1000.0, H / 1000.0
    out = {'pts': [], 'panels': [], 'labels': [], 'spaces': [], 'titles': [], 'panels_truncated': False}
    p = Path(vdir) / f'raw-{plan}-{os.environ.get("FP_LABELS", "labels")}.txt'   # T-04: слепые — labels2; T-27 — labels3
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        # T-27: заголовки этажей/построек (labels3) — делёж листа по подписям (`panels_by_titles`)
        out['titles'] = [{'title': ' '.join(str(q.get('title', '')).split()), 'pt': (q['pt'][0] * kx, q['pt'][1] * ky)}
                         for q in d.get('titles') or [] if isinstance(q, dict) and _pt_ok(q.get('pt')) and str(q.get('title', '')).strip()]
        out['pts'] = [(r['pt'][0] * kx, r['pt'][1] * ky) for r in d.get('rooms', []) if r.get('pt')]
        v4 = any(isinstance(r, dict) and ('type' in r or 'area_m2' in r) for r in d.get('rooms', []))
        for r in d.get('rooms', []):
            if not r.get('pt'):
                continue
            dm = r.get('dims_m')
            ok = isinstance(dm, list) and len(dm) == 2 and all(isinstance(v, (int, float)) and 0.5 <= v <= 30 for v in dm)
            q = {'name': ' '.join(str(r.get('name') or '').split()), 'pt': (r['pt'][0] * kx, r['pt'][1] * ky),
                 'dims': tuple(float(v) for v in dm) if ok else None,
                 'unsure': bool(r.get('unsure')), 'note': r.get('note')}
            if v4:                                            # T-20261110-38: ответ labels4 (у старых видов этих полей нет)
                q.update(room_meta(r))
                if not q['name']:
                    if not q.get('vtype'):
                        continue                              # ни названия, ни типа — подписи нет
                    q['name'], q['name_src'] = TYPE_NAME[q['vtype']], 'type'
            out['labels'].append(q)
        number_type_names(out['labels'])
    # T-03: помещения без размеров (имя от VLM) — второй ответ, отдельная папка (FP_VLM2)
    p2 = Path(os.environ.get('FP_VLM2', vdir)) / f'raw-{plan}-unlabeled.txt'
    if p2.exists():
        d = vlm.parse(p2.read_text()) or {}
        out['spaces'] = [{'name': str(s.get('name', '')), 'pt': (s['pt'][0] * kx, s['pt'][1] * ky), 'dims': None}
                         for s in d.get('spaces', []) if s.get('pt')]
    p = Path(vdir) / f'raw-{plan}-panels.txt'
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        # T-27: ответ оборван лимитом — выжили не все этажи (Nethercote: из пяти один «Ground Floor», остальные надписи
        # оставались вне контура и не привязывались) → на контуры не опираемся: куски плана по маске (`panels_of`)
        if d.get('_truncated'):
            out['panels_truncated'] = True
            return out
        for q in d.get('panels', []):
            poly = np.array([[x * kx, y * ky] for x, y in q.get('poly', [])], np.float32)
            if len(poly) >= 3:
                out['panels'].append({'title': q.get('title'), 'poly': poly})
    return out


def _pt_ok(pt):
    return isinstance(pt, (list, tuple)) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt)


def _box_dist(pt, b):
    """Расстояние точки до прямоугольника (x, y, w, h); внутри — 0."""
    x, y, w, h = b
    return math.hypot(max(x - pt[0], 0, pt[0] - x - w), max(y - pt[1], 0, pt[1] - y - h))


TITLE_NEAR_M = 2.0   # T-27/2: заголовок «свой» для куска плана, если не дальше 2 м от его рамки (обычно — под или над этажом)


def norm_title(s):
    return ' '.join(str(s or '').lower().split())


def vlm_groups(panels):
    """T-27/2: контуры VLM с одинаковым заголовком — одна панель (Nethercote: пять «Outbuildings» и два «First Floor» —
    отдельными контурами; по одному они упирались в потолок панелей и резались). Безымянные — каждая своя.
    → [(заголовок, [индексы контуров])] в порядке первого появления"""
    out, at = [], {}
    for i, q in enumerate(panels):
        k = norm_title(q.get('title')) or f'#{i}'
        if k not in at:
            at[k] = len(out)
            out.append((' '.join(str(q.get('title') or '').split()), []))
        out[at[k]][1].append(i)
    return out


def titles_vs_vlm(titles, panels):
    """Сверка контуров VLM с заголовками этажей (labels3): точка заголовка → ближайший контур (знаковое расстояние);
    сходится, если у контура тот же заголовок. Контуры «перепутаны» (Nethercote после повтора с низким «думанием»:
    у «Second Floor» ближайший контур — «Outbuildings») → не сходится. → [(заголовок, заголовок ближайшего контура)]"""
    polys = [np.ascontiguousarray(q['poly'].reshape(-1, 1, 2), np.float32) for q in panels]
    out = []
    for t in titles:
        d = [cv2.pointPolygonTest(pp, (float(t['pt'][0]), float(t['pt'][1])), True) for pp in polys]
        out.append((t['title'], ' '.join(str(panels[int(np.argmax(d))].get('title') or '').split())))
    return out


def panels_by_titles(final, ppm, titles, W, H, flags=None):
    """Делёж листа по подписям этажей (владелец TG 775: этажи на листе всегда подписаны): куски плана по маске
    (`panels_of`) → к ближайшему заголовку (расстояние от точки заголовка до рамки куска; заголовок обычно под или над
    своим этажом); панель = все куски одного заголовка (рамки с запасом 1 м — маска стен панели). Заголовок без кусков —
    панели нет. Не молча (T-27/2, в `flags`): кусок без своего заголовка ближе TITLE_NEAR_M отдан ближайшему —
    `panel_title_guess`; в куске ≥ 2 разных заголовка (слиплись этажи/постройки) — `panel_titles_merged`.
    → [(X0, Y0, X1, Y1, маска, принадлежность точки)], [заголовок панели]"""
    boxes = panels_of(final, ppm)
    if not boxes or not titles:
        return [], []
    flags = [] if flags is None else flags
    own = []
    for b in boxes:
        d = [_box_dist(t['pt'], b) for t in titles]
        near = {norm_title(titles[i]['title']) for i in range(len(titles)) if d[i] <= TITLE_NEAR_M * ppm}
        if not near:
            flags.append('panel_title_guess')
        elif len(near) > 1:
            flags.append('panel_titles_merged')
        own.append(int(np.argmin(d)))
    pad = int(1.0 * ppm)
    padded = [(max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)) for x, y, w, h in boxes]

    def piece(pt):          # кусок точки: среди рамок с запасом, где она лежит, — ближайший без запаса
        cand = [i for i, (a, b_, c, d) in enumerate(padded) if a <= pt[0] < c and b_ <= pt[1] < d]
        return min(cand, key=lambda i: _box_dist(pt, boxes[i])) if cand else None
    names = [t['title'] for t in titles]
    seen = {n: names.count(n) for n in names}
    k = {}
    for i, n in enumerate(names):                         # одинаковые заголовки — различать, как в `blind_gold`
        if seen[n] > 1:
            k[n] = k.get(n, 0) + 1
            names[i] = f'{n} {k[n]}'
    pan, ttl = [], []
    for ti in range(len(titles)):
        mine = [i for i, o in enumerate(own) if o == ti]
        if not mine:
            continue
        pm = np.zeros((H, W), np.uint8)
        for i in mine:
            a, b_, c, d = padded[i]
            pm[b_:d, a:c] = 1
        X0, Y0 = min(padded[i][0] for i in mine), min(padded[i][1] for i in mine)
        X1, Y1 = max(padded[i][2] for i in mine), max(padded[i][3] for i in mine)
        pan.append((X0, Y0, X1, Y1, pm, (lambda pt, mine=frozenset(mine): piece(pt) in mine)))
        ttl.append(names[ti])
    return pan, ttl


THIN_MASK = 'lsd:170'   # T-09: добавка тонких стен «режим[:порог гистерезиса]» (fc.wall_mask_auto); FP_MASK=old — без неё


def thin_mode():
    fm = os.environ.get('FP_MASK', THIN_MASK)
    if not fm or fm == 'old':
        return None
    mode, _, hi = fm.partition(':')
    return mode, int(hi or 0)


def build_mask(img, cfg):
    """Маска стен листа. Тёмные листы — порог и открытие плана; лист тонких стен (медиана толщины ≤ fc.THIN_T3,
    общее правило T-09, не порог под лист) — маска fc.wall_mask_auto с добавкой тонких стен."""
    k = cfg['mask']
    if k[0] == 'blue':
        return fc.wall_mask_blue(img, cfg['min_area'])
    m = fc.wall_mask_dark(img, k[1], k[2], cfg['min_area'])
    tm = thin_mode()
    if tm:
        m2, info = fc.wall_mask_auto(img, tm[0], k[1], cfg['min_area'], tm[1])
        cfg['mask_info'] = info
        if info['thin']:
            cfg['thin_hi'] = tm[1]
            return m2
    if os.environ.get('FP_GREY', '1') != '0' and k[2] >= 5:
        # T-20261110-38: серые перегородки при толстых чёрных стенах (`fpcore.grey_partitions`; FP_GREY=0 — как до T-38)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        add, info = fc.grey_partitions(g, m, k[1])
        cfg['grey_info'] = info
        if info['used']:
            return fc.remove_small(m | add, cfg['min_area'])
    return m


def sheet_arrows(img, wall, cfg, t):
    """T-20261111-13: залитые стрелки входа/лестницы тёмного листа (`fpcore.arrow_glyphs`) → маска листа или None.
    Маска стен не меняется: снятие стрелок с маски перекраивало комнаты rgK (стрелки у лестниц и в открытых зонах держали
    разбиение — кухня, коридор, санузел теряли комнату или двери). Стрелки правят только проёмы (`arrow_doors`).
    FP_ARROWS=0 — как до T-13."""
    if os.environ.get('FP_ARROWS', '1') == '0' or cfg['mask'][0] != 'dark' or cfg.get('thin_hi'):
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    arr = fc.arrow_glyphs(wall, g, cfg['mask'][1], t)
    return arr if arr.any() else None


ARROW_GAP_T = 3.0   # разрыв у стрелки не длиннее 3 t — щель «стена ↔ стрелка»; длиннее — закрытие проёма или зоны, его не трогаем


def arrow_in_opening(g, lab_g, arr, wall, t):
    """T-20261111-13/2: одиночный короткий разрыв у стрелки — стрелка стоит в проёме стены? Идём по линии разрыва за стрелку
    (до ARROW_GAP_T·t): упёрлись в стену (не стрелку) — да, проём от торца до торца: стрелка посреди двери, второй разрыв не нашёлся
    (rgK p1, санузел/Cupboard: дверь 66 см, стрелка «↓» в ней, разрыв только справа 26 см). Нет стены — стрелка на открытом месте
    у торца стены (щель «торец ↔ стрелка»), не проём. → (cx, cy, длина px) или None."""
    ys, xs = np.nonzero(lab_g == g.id)
    ay, ax = np.nonzero(arr)
    if len(ys) < 3 or not len(ay):
        return None
    c, u, n, _, _ = fc.gap_axes(ys, xs)
    v = np.array([ax.mean(), ay.mean()]) - c
    if abs(v @ n) > abs(v @ u):                        # ось разрыва — вдоль стены, к стрелке
        u, n = n, u
    s = 1.0 if v @ u >= 0 else -1.0
    hb = max(float(g.depth), float(t)) / 2.0
    Pg = np.column_stack([xs, ys]) - c
    Pa = np.column_stack([ax, ay]) - c
    ina = np.abs(Pa @ n) <= hb + 1                     # стрелка в полосе стены
    if ina.sum() < 3:
        return None
    ga, aa = s * (Pg @ u), s * (Pa[ina] @ u)
    H, W = wall.shape
    bs = np.arange(-int(hb), int(hb) + 1)
    hit = None
    best = (0.0, 0)
    for d in range(1, int(ARROW_GAP_T * t) + 1):
        p = c[None, :] + u[None, :] * s * (aa.max() + d) + n[None, :] * bs[:, None]
        px, py = np.round(p[:, 0]).astype(int), np.round(p[:, 1]).astype(int)
        ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
        if not ok.any():
            break
        px, py = px[ok], py[ok]
        fr = float(((wall[py, px] > 0) & (arr[py, px] == 0)).mean())
        best = max(best, (fr, d))
        if fr >= 0.5:
            hit = aa.max() + d
            break
    if os.environ.get('FP_ARROW_DBG'):
        print(f'[arrow]   разрыв {g.id}: стрелка в полосе {int(ina.sum())} px, за ней стена {best[0]:.2f} на {best[1]} px, '
              f'hb {hb:.1f}, ось ({u[0]:.2f}, {u[1]:.2f})', file=sys.stderr)
    if hit is None:
        return None
    lo, hi = float(ga.min()), float(hit) - 1.0         # от ближнего торца (край разрыва) до дальнего торца за стрелкой
    # в осях c, u: пролёт [lo, hi] по направлению s·u → по u
    a0, a1 = sorted((s * lo, s * hi))
    return c, u, n, a0, a1, hb


ARC_TRIM = 0.9      # дуга створки короче 0,9 пролёта — дверь шириной по дуге (остальное — простенок/стрелка)
ARC_TRIM_MIN = 0.4  # дугу короче 0,4 пролёта не берём: это чужая дверь или мебель


def arc_trim(thin, c, u, n, a0, a1, hb, thr=None):
    """T-20261111-13/3: пролёт слитой двери [a0, a1] по оси u от c → по дуге створки (если есть): петля у одного конца, радиус R
    по линиям листа (`thin`), как `fpcore.door_evidence` (одна створка, петля на грани стены). Дуга найдена (доля ≥ DOOR_EV) и
    R < ARC_TRIM·пролёта — дверь от петли длиной R (rgK, Cupboard: пролёт со стрелкой 96 см при дуге ~70–80). Нет дуги или
    дуга во весь пролёт — пролёт как был. → (a0, a1, R или None)."""
    if thin is None:
        return a0, a1, None
    thr = DOOR_EV if thr is None else thr
    L = a1 - a0 + 1.0
    H, W = thin.shape
    th = np.radians(np.arange(0, 91, 5))
    cand = []
    for s in (n, -n):
        for end, dsg in ((a0, 1.0), (a1, -1.0)):
            h = c + u * end + s * hb
            d = u * dsg
            for f in np.arange(ARC_TRIM_MIN, 1.06, 0.05):
                R = f * L
                pts = h[None, :] + R * (np.cos(th)[:, None] * d[None, :] + np.sin(th)[:, None] * s[None, :])
                hit = 0
                for x, y in pts:
                    xi, yi = int(round(x)), int(round(y))
                    y0, y1, x0, x1 = max(0, yi - 2), min(H, yi + 3), max(0, xi - 2), min(W, xi + 3)
                    if y1 > y0 and x1 > x0 and thin[y0:y1, x0:x1].any():
                        hit += 1
                cand.append((hit / len(pts), R, end, dsg))
    good = [k for k in cand if k[0] >= thr]
    if not good:
        return a0, a1, None
    top = max(k[0] for k in good)
    sc, R, end, dsg = max((k for k in good if k[0] >= top - 0.05), key=lambda k: k[1])   # окно 5×5 прощает ±2 px — берём больший R
    if R >= ARC_TRIM * L:
        return a0, a1, R
    return (a0, a0 + R - 1.0, R) if dsg > 0 else (a1 - R + 1.0, a1, R)


def _door_quad(c, u, n, a0, a1, hb):
    """Прямоугольник двери: пролёт [a0, a1] по u, ±hb по n → 4 угла (x, y)."""
    return np.array([c + u * a + n * b for a, b in ((a0, -hb), (a1, -hb), (a1, hb), (a0, hb))], float)


JAMB_COS = math.cos(math.radians(30))   # торец стены смотрит в пролёт (±30° от оси слитой двери)


def has_jambs(ends, c, u, n, a0, a1, hb, t):
    """T-20261111-13/4: у слитого проёма с обеих сторон — торцы стен поперёк прохода (стена продолжает линию проёма и кончается
    у края пролёта, `fpcore.wall_ends`). Пролёт упёрся в грань стены, идущей поперёк (rgK p1: тонкая черта через коридор со
    стрелкой — разрывы 43 + 46 см между стенами коридора), — не проём: открытый проход. Торец считается до середины пролёта:
    под разрывом бывает хвост стены (rgK p1 Principal ↔ Dressing: полоска 2 px под проёмом увела конец скелета на 16 px внутрь)."""
    for end, sg in ((a0, 1.0), (a1, -1.0)):
        E = c + u * end
        ok = False
        for e in ends:
            v = np.asarray(e['p'], float) - E
            if abs(v @ n) <= hb + 2 and -(t + 3) <= sg * (v @ u) <= (a1 - a0) / 2.0 and \
                    sg * (np.asarray(e['w'], float) @ u) >= JAMB_COS:
                ok = True
                break
        if not ok:
            return False
    return True


LEAF_R_M = (0.45, 1.05)   # радиус дуги створки у одиночного разрыва — от 45 см до ~1 м (поиск шире самого разрыва)


LEAF_BUSY = 0.25          # дверь по дуге не ставим, если четверть её прямоугольника уже занята другим проёмом (дверь/окно)
LEAF_EMPTY = 0.2          # внутри дуги (r 0,35–0,75 R, углы 15–75°) линий листа не больше 20 % точек: ступени лестницы и
_IN = np.array([(r, a) for r in (0.35, 0.55, 0.75) for a in range(15, 76, 15)], float)   # штриховка дают «дугу» (rgK p0 Hall)
IN_R, IN_TH = _IN[:, 0], np.radians(_IN[:, 1])
LEAF_JAMB_T = 2.5       # торец: стена за гранью (на t вглубь) не шире 2,5 t поперёк проёма — иначе грань длинной стены


def leaf_door(g, thin, dark, arr, t, ppm, angles=(0.0, 90.0)):
    """T-20261111-13/4: одиночный короткий разрыв у стрелки, но рядом на листе — дуга створки (rgK p0 Family ↔ Utility: разрыв
    13 px между стрелкой и проёмом 86 см; p2 Bedroom 8 ↔ Playroom: разрыв у стрелки ступеней в 40 см от настоящей двери).
    Проём: от грани торца стены (по направлениям стен панели `angles`, не дальше R от разрыва) до встречной стены — пусто на R
    (LEAF_R_M), за ним стена; за гранью торца стена узкая (≤ LEAF_JAMB_T·t поперёк). Дуга створки 0–90° радиуса R — с петлёй у
    торца или у встречной стены (Family: петля на грани поперечной стены) — тонкие линии листа ≥ DOOR_EV. Разрыв — в зоне двери
    (до R от линии проёма). `dark` — тёмное листа, а не маска разбора: в ней проём бывает уже закрыт стеной (Family), а у торца со
    ступенькой в скелете нет конца (`fpcore.wall_ends` его не видит). → (cx, cy, R, quad, доля дуги) — дверь шириной R, или None."""
    H, W = thin.shape
    gc = np.array([g.cx, g.cy], float)
    r0, r1 = LEAF_R_M[0] * ppm, LEAF_R_M[1] * ppm
    th = np.radians(np.arange(0, 91, 5))
    solid = (dark > 0) & (arr == 0)
    jw = LEAF_JAMB_T * float(t)

    def near(m, p):
        xi, yi = int(round(p[0])), int(round(p[1]))
        y0, y1, x0, x1 = max(0, yi - 2), min(H, yi + 3), max(0, xi - 2), min(W, xi + 3)
        return y1 > y0 and x1 > x0 and bool(m[y0:y1, x0:x1].any())

    def at(p):
        xi, yi = int(round(p[0])), int(round(p[1]))
        return 0 <= xi < W and 0 <= yi < H and bool(solid[yi, xi])

    def dot(m, p):                                     # окно 3×3
        xi, yi = int(round(p[0])), int(round(p[1]))
        y0, y1, x0, x1 = max(0, yi - 1), min(H, yi + 2), max(0, xi - 1), min(W, xi + 2)
        return y1 > y0 and x1 > x0 and bool(m[y0:y1, x0:x1].any())

    def run(p, v, lim):
        k = 0
        while k < lim and at(p + v * (k + 1)):
            k += 1
        return k

    dirs = []
    for a in angles:
        v = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
        for d in (v, -v, np.array([-v[1], v[0]]), np.array([v[1], -v[0]])):
            if all(float(d @ e) < 0.99 for e in dirs):
                dirs.append(d)
    R1 = int(r1 + t) + 2
    y0, y1, x0, x1 = max(0, int(gc[1]) - R1), min(H, int(gc[1]) + R1 + 1), max(0, int(gc[0]) - R1), min(W, int(gc[0]) + R1 + 1)
    ys, xs = np.nonzero(solid[y0:y1, x0:x1])
    best = None
    for d in dirs:
        nrm = np.array([-d[1], d[0]])
        for qx, qy in zip((xs + x0).tolist(), (ys + y0).tolist()):
            q = np.array([qx, qy], float)
            if at(q + d):
                continue                               # не грань в сторону d
            k = 1
            while k <= r1 + 1 and not at(q + d * k):
                k += 1
            R = float(k - 1)                           # пусто до встречной стены
            if k > r1 + 1 or R < r0:
                continue
            b = q - d * float(t)
            if not at(b) or 1 + run(b, nrm, jw) + run(b, -nrm, jw) > jw:
                continue                               # за гранью не узкий торец, а длинная стена
            seg = q + d * np.clip((gc - q) @ d, 0.0, R)
            if np.hypot(*(gc - seg)) > R:
                continue                               # разрыв не в зоне этой двери
            for s in (nrm, -nrm):
                for hc, dd in ((q, d), (q + d * (R + 1.0), -d)):    # петля у торца / у встречной стены
                    pts = hc[None, :] + R * (np.cos(th)[:, None] * dd[None, :] + np.sin(th)[:, None] * s[None, :])
                    sc = float(np.mean([near(thin, p) for p in pts]))
                    if sc < DOOR_EV or (best is not None and sc <= best[0] + 1e-9):
                        continue
                    ins = hc[None, :] + R * IN_R[:, None] * (np.cos(IN_TH)[:, None] * dd[None, :] +
                                                            np.sin(IN_TH)[:, None] * s[None, :])
                    if np.mean([dot(thin, p) for p in ins]) <= LEAF_EMPTY:   # внутри дуги пусто: не ступени/штриховка
                        best = (sc, q, d, nrm, R)
    if best is None:
        return None
    sc, q, d, nrm, R = best

    def face(v):                                       # грань торца вдоль ±nrm от q: стена, перед ней пусто
        k = 0
        while k < jw and at(q + v * (k + 1)) and not at(q + v * (k + 1) + d):
            k += 1
        return k
    jp, jm = face(nrm), face(-nrm)
    mid = q + nrm * (jp - jm) / 2.0
    quad = _door_quad(mid, d, nrm, 1.0, R, (jp + jm + 1) / 2.0 + 1.0)
    m = mid + d * (R + 1.0) / 2.0
    return float(m[0]), float(m[1]), R, quad, sc


def arrow_doors(gaps, lab_g, arrows, t, wall=None, thin=None, ppm=None, dark=None, angles=None):
    """T-20261111-13: короткие (≤ ARROW_GAP_T·t) дверные разрывы у залитой стрелки. Один такой у стрелки — щель «торец стены ↔
    стрелка», не проём (rgK, Bedroom 3: стрелка «→» в коридоре в 23 см от угла спальни давала «дверь» 43 см, ядро её резало —
    opening_cut_by_core), если только стрелка не стоит в проёме стены (`arrow_in_opening`, нужна маска стен `wall`): тогда дверь —
    проём от торца до торца. Два и больше на одной прямой со стрелкой — стрелка делит проём надвое: один проём (разрывы и стрелка
    вместе). Не на одной прямой — как были. Длинные разрывы (закрытия у лестниц, широкие проёмы) — как были: снятие и слияние их
    меняло ядра (rgK Drawing room) и оставляло комнату без двери (Eaves). Ширина слитой двери — по дуге створки, если она есть
    (`arc_trim`, нужны линии листа `thin`). Прямоугольник двери (quad) — чтобы в 3D снять стрелку из стены в проёме (/3).
    /4 (нужны `wall`, `thin`, `ppm`; `dark` — тёмное листа панели): одиночный разрыв не снимается, если рядом дуга створки — дверь
    по дуге (`leaf_door`);
    слитый проём без торцов стен с обеих сторон (`has_jambs`) — открытый проход: разрывы снимаются, двери нет.
    → (снятые id, слитые [(cx, cy, длина px, exterior, quad 4×2)], id слитых)."""
    drop, merged, used = set(), [], set()
    if arrows is None or not arrows.any() or not t:
        return drop, merged, used
    dbg = os.environ.get('FP_ARROW_DBG')
    ends = None
    if wall is not None:
        w0 = (wall > 0) & (arrows == 0)                # торцы — без стрелок (стрелка у торца продлевает скелет)
        ends = fc.wall_ends(w0.astype(np.uint8), t)
    lw = dark if dark is not None else wall            # дуга створки — по тёмному листа (в маске разбора проём бывает закрыт)

    def by_leaf(g):
        if lw is None or thin is None or not ppm:
            return False
        lf = leaf_door(g, thin, lw, arrows, t, ppm, tuple(angles) if angles else (0.0, 90.0))
        if lf is None:
            return False
        cx, cy, R, quad, sc = lf
        q = np.zeros(lab_g.shape, np.uint8)
        cv2.fillPoly(q, [np.round(quad).astype(np.int32)], 1)
        busy = np.isin(lab_g, [o.id for o in gaps if o.id != g.id and o.kind != 'wall'])
        if (busy & (q > 0)).sum() >= LEAF_BUSY * max(1, int(q.sum())):     # полоска 1 px (рама, «окно» глубиной 1) — не проём
            if dbg:
                print(f'[arrow]   дуга у разрыва {g.id} — на месте другого проёма, не ставим', file=sys.stderr)
            return False
        merged.append((cx, cy, R, g.exterior, quad))
        used.add(g.id)
        if dbg:
            print(f'[arrow] разрыв {g.id} → дверь по дуге R {R:.1f} px (доля {sc:.2f}), центр ({cx:.0f}, {cy:.0f})', file=sys.stderr)
        return True

    def add(c, u, n, a0, a1, hb, ext, ids):
        b0, b1, R = arc_trim(thin, c, u, n, a0, a1, hb)
        m = c + u * (b0 + b1) / 2.0
        merged.append((float(m[0]), float(m[1]), b1 - b0 + 1.0, ext, _door_quad(c, u, n, b0, b1, hb + 1.0)))
        used.update(ids)
        if dbg:
            print(f'[arrow] слита {sorted(ids)} пролёт {a1 - a0 + 1:.1f} → {b1 - b0 + 1:.1f} px, дуга R {R}, '
                  f'центр ({m[0]:.0f}, {m[1]:.0f}), hb {hb:.1f}', file=sys.stderr)
    _, al = cv2.connectedComponents(arrows.astype(np.uint8), connectivity=8)
    near = cv2.dilate(al.astype(np.uint16), np.ones((5, 5), np.uint8))       # метка стрелки на 2 px вокруг неё
    by = {}
    for g in gaps:
        if g.kind != 'door' or g.length > ARROW_GAP_T * t:
            continue
        ids = np.unique(near[lab_g == g.id])
        for a in ids[ids > 0]:
            by.setdefault(int(a), []).append(g)
    for a, gs in by.items():
        if len(gs) == 1:
            g = gs[0]
            d = arrow_in_opening(g, lab_g, al == a, wall, t) if wall is not None else None
            if dbg:
                print(f'[arrow] один разрыв {g.id} L {g.length:.1f} глуб {g.depth:.1f} ({g.cx:.0f}, {g.cy:.0f}) t {t:.1f} → '
                      f'{"в проёме" if d else "снят"}', file=sys.stderr)
            if d is not None:
                add(*d, g.exterior, {g.id})
            elif not by_leaf(g):
                drop.add(g.id)
            continue
        ys, xs = np.nonzero((al == a) | np.isin(lab_g, [g.id for g in gs]))
        c, u, n, L, depth = fc.gap_axes(ys, xs)
        if L < sum(g.length for g in gs) or depth > 1.5 * max(max(g.depth for g in gs), t):
            continue                                   # не на одной прямой — не один проём
        hb = max(max(g.depth for g in gs), float(t)) / 2.0
        a0, a1 = -(L - 1.0) / 2.0, (L - 1.0) / 2.0
        if ends is not None and not has_jambs(ends, c, u, n, a0, a1, hb, t):
            if dbg:
                print(f'[arrow] разрывы {sorted(g.id for g in gs)}: нет торцов стен с обеих сторон — открытый проход, '
                      f'центр ({c[0]:.0f}, {c[1]:.0f})', file=sys.stderr)
            drop.update(g.id for g in gs)
            continue
        add(c, u, n, a0, a1, hb, any(g.exterior for g in gs), {g.id for g in gs})
    return drop - used, merged, used


def sheet_thickness(wall, cfg) -> float:
    """Толщина стен листа t (px) — мера всех порогов в толщинах. С серыми перегородками (T-38) — толщина тёмных стен, как
    без них: медиана по маске с перегородками падает до их толщины (Этажи: 16 → 6), и закрытие окон/дверей мерилось бы ею."""
    gi = cfg.get('grey_info') or {}
    return float(gi['t']) if gi.get('used') else fc.stroke_thickness(wall)


def rot_angles(fams):
    """Повороты для закрытия разрывов: 0 (оси) + каждое семейство, не близкое к 0/90 (приведённое к (-45, 45])."""
    out = [0.0]
    for f in fams:
        a = ((f + 45) % 90) - 45
        if abs(a) > 1.5 and all(abs(a - b) > 1.5 for b in out):
            out.append(a)
    return out


def per_region(fn, wall, regions, pad=2):
    """Вызвать fn(кусок стены) → маска добавок по каждой области листа отдельно (через пустоту между планами
    разрывы не закрываем)."""
    if not regions:
        return fn(wall)
    add = np.zeros_like(wall)
    H, W = wall.shape
    for x0, y0, x1, y1 in regions:
        X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
        add[Y0:Y1, X0:X1] |= fn(wall[Y0:Y1, X0:X1])
    return add


def analyze(img, gray, wall, ppm, fams, t, regions=None, thin_thr=210, glaze_thr=215):
    """Кэш на диске (FP_CACHE=<папка>): тот же вход → тот же результат; ускоряет отладку круга починки (T-03).
    Ключ — байты стены/серого + параметры + хеш исходника analyze (правка кода — новый ключ)."""
    cdir = os.environ.get('FP_CACHE')
    if not cdir:
        return _analyze(img, gray, wall, ppm, fams, t, regions, thin_thr, glaze_thr)
    import hashlib
    import inspect
    import pickle
    h = hashlib.sha1()
    for a in (wall, gray):
        h.update(np.ascontiguousarray(a).tobytes()); h.update(str(a.shape).encode())
    h.update(repr((round(float(ppm), 6), [round(float(f), 4) for f in fams], round(float(t), 4), regions, thin_thr,
                   glaze_thr, ENV_GEO, SPLIT_DEEP, PS_TAIL, TEXT_MASK, TEXT_EV_MIN, 'tm1')).encode())
    h.update(inspect.getsource(_analyze).encode() + inspect.getsource(bay_windows).encode())
    p = Path(cdir) / f'an-{h.hexdigest()[:20]}.pkl'
    if p.exists():
        return pickle.loads(p.read_bytes())
    r = _analyze(img, gray, wall, ppm, fams, t, regions, thin_thr, glaze_thr)
    Path(cdir).mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps(r))
    return r


POCKET_M2 = 0.5     # T-20261110-38: замкнутая полость меньше — не помещение (полость наружной стены Этажей, короб, ниша)
POCKET_W_M = 0.45   # и уже этого (вписанная ширина): полость в толще стены — щель 0,2–0,3 м; шкаф с дверцей — от ~0,6 м
DEV_AREA_LABELS = 2  # = pipeline.area_rerun_ppm: столько подписей площади без размеров — манера листа застройщика РФ


def dev_sheet(cfg: dict, vl: dict | None) -> bool:
    """T-20261110-38/3: лист в манере застройщика РФ («Этажи») — по самому листу, не по имени файла: серые перегородки при
    толстых чёрных стенах (`build_mask` → `grey_info.used`) или ≥ DEV_AREA_LABELS подписей площади комнат без размеров (labels4).
    Только у такого листа работают правила проёмов T-38 — двери в полость стены (`pocket_doors`), закрытия внутри одной
    комнаты (`same_room_gaps`), обрубки короче STUB_M, полость без подписи < POCKET_M2 — не комната (`pipeline.panel_result`):
    на британских листах (контур стен без полостей) они снимали настоящие двери — регресс rgK5…: дверей 162 → 66, у Bedroom 6
    — ни одной. FP_DEV_SHEET=1|0 — принудительно (сравнение)."""
    f = os.environ.get('FP_DEV_SHEET')
    if f in ('0', '1'):
        return f == '1'
    if (cfg.get('grey_info') or {}).get('used'):
        return True
    labs = (vl or {}).get('labels') or []
    return sum(1 for q in labs if q.get('area_m2') is not None and not q.get('dims')) >= DEV_AREA_LABELS


def pocket_doors(gaps, lab_g, lab, final, outside, areas, pocket_px: float, pocket_w_px: float = np.inf) -> None:
    """«Дверь», у которой с одной стороны полость меньше `pocket_px` и уже `pocket_w_px` (не наружа), — стена: на листе
    Этажей наружные стены нарисованы контуром с белыми прямоугольниками внутри, и закрытие у полости давало дверь кухни и
    ванной «в стену» и наружную «дверь» из полости на улицу. Ширина — чтобы не снять дверцу шкафа 0,95×0,82 (регресс, лист
    FYyXHKH4…: по площади он меньше порога); кроме полости по сторонам больше одного помещения — проход между ними остаётся
    (регресс 4y0opq…: общее закрытие спальни, её тамбура и ниши шкафа). Межкомнатная, у которой по сторонам одно помещение, —
    тоже стена (не проход).
    На месте (g.kind)."""
    if not gaps or os.environ.get('FP_POCKET', '1') == '0':
        return
    k = np.ones((3, 3), np.uint8)
    dt = None
    for g in gaps:
        if g.kind != 'door':
            continue                                  # наружная дверь — тоже: изнутри у настоящей всегда помещение
        gm = (lab_g == g.id).astype(np.uint8)
        ring = (cv2.dilate(gm, k, iterations=2) > 0) & (final == 0)
        sides = [int(i) for i in np.unique(lab[ring]) if i > 0]
        small = [i for i in sides if areas[i] < pocket_px and not outside[lab == i].any()]
        if small and np.isfinite(pocket_w_px):
            if dt is None:
                dt = cv2.distanceTransform((final == 0).astype(np.uint8), cv2.DIST_L2, 5)
            small = [i for i in small if 2 * float(dt[lab == i].max()) < pocket_w_px]
        if small and len(sides) - len(small) <= 1:    # закрытие-«Т» между двумя комнатами, задевшее полость, — проход
            g.kind = 'wall'
        elif not g.exterior and len(sides) < 2:
            g.kind = 'wall'                           # межкомнатная с одним помещением по сторонам (закрытие у ванны в стену)


OWN_SHARE = 0.5     # T-20261111-11: заявка, у которой не меньше этой доли рисунка уже у более сильной двери, — не дверь
# T-20261111-11: полоса-проём `fpcore.xy_cut` — не шире малого закрытия (Ls = 1,7 м, его разбор и закрывает: окно и ворота
# гаража bs30 — полоса 1,5 м). Шире — эркер/зимний сад из окон (bs30: боковые окна 2,8 м): там лучше «рамка» починки по подписи,
# поэтому такие полосы режем, как прежде
OPEN_MAX_M = 1.7
OPEN_MAX_T = 8.5    # на всём листе масштаба ещё нет: 8,5 толщин стены ≈ 1,7 м при стене ~0,2 м
STAIR_EDGE = os.environ.get('FP_STAIR_EDGE', '1') != '0'   # T-20261111-11: верх марша не закрываем «рамой» (`fpcore.stair_edge`)
DOORLESS = os.environ.get('FP_DOORLESS', '1') != '0'       # T-11/3: запасная дверь комнаты без дверей (`doorless_doors`); 0 — без неё
BAY_OLD = os.environ.get('FP_BAY_OLD', '1') != '0'         # T-11/3: дверь у «эркера» — прежнее правило (`bay_windows`); 0 — с «чистотой»
DOORLESS_TOL_M = 0.3    # проём «у комнаты» — не дальше от её пола (как ROOM_TOL_CM сравнения `regress`)


def doorless_doors(r: dict, ppm: float) -> list:
    """Страховка на уровне комнаты (T-11/3). «Чистота» дуги (`fpcore.door_evidence`, T-11) снимает ложные двери по тексту
    и ступеням, но на мелком загромождённом листе (rgK5f3, ~30 px/м) — и все двери отдельных комнат: кухня, кладовые, WC
    оставались без единого прохода, в туре недоступны (прогулка, расстановка) — хуже лишней двери. Комнате без двери
    (ни одной двери не дальше DOORLESS_TOL_M от пола) возвращается лучшая по прежнему правилу кандидатка у неё:
    закрытие, снятое только «чистотой» (`alts` из `_analyze`), или наружный разрыв, ставший окном только по ней (`retype`).
    T-11/4 (правило владельца «все элементы, как на плане»; rgK5f3 Tool store): нет таких — окно с «рамой» и дугой открывания
    у этой комнаты (`glazed`: серая заливка проёма — та же «рама», дуга наружу), не меньше половины проёма у её пола; окно
    без дуги в `glazed` не попадает и остаётся окном. Правит r['gaps']/r['lab_g'] на месте → [(id комнаты, доля)]."""
    alts, ret, glz = r.get('alts') or [], r.get('retype') or [], r.get('glazed') or []
    if not DOORLESS or not (alts or ret or glz) or not r.get('rooms'):
        return []
    lab, lab_g, gaps = r['lab'], r['lab_g'], r['gaps']
    byid = {g.id: g for g in gaps}
    cands = [(ys, xs, ev, None, 0) for ys, xs, ev in alts]
    for tier, lst in ((0, ret), (1, glz)):
        for gid, ev in lst:
            if gid in byid and byid[gid].kind == 'window':
                ys, xs = np.nonzero(lab_g == gid)
                if len(ys):
                    cands.append((ys, xs, ev, gid, tier))
    if not cands:
        return []
    # дверь «у комнаты» — по ближайшим пикселям, но лицом, а не краем (T-11/5): часть двери не дальше допуска от пола тянется
    # не меньше чем на половину её ширины. По середине (T-11/4) глубокий проём ванной rgK5f3 p1 (24×24 px, середина в 10,8 px
    # при допуске 9,1) не считался, и её окно с дугой становилось второй дверью; по касанию одного пикселя ложное закрытие
    # углом у пола (rgK5f3 Tool store) или торцом чужая дверь «давали» комнате дверь, которой в туре у неё нет
    doors = [np.nonzero(lab_g == g.id) + (g.length,) for g in gaps if g.kind == 'door']
    if r.get('add_extra') is not None and r['add_extra'].any():
        ne, cl = cv2.connectedComponents(r['add_extra'].astype(np.uint8), connectivity=8)
        for i in range(1, ne):
            ys_, xs_ = np.nonzero(cl == i)
            doors.append((ys_, xs_, fc.gap_axes(ys_, xs_)[3]))
    tol = DOORLESS_TOL_M * ppm

    def faces(ys_, xs_, width, dist, y0, x0):
        h, w = dist.shape
        m = (ys_ >= y0) & (ys_ < y0 + h) & (xs_ >= x0) & (xs_ < x0 + w)
        if not m.any():
            return False
        ys_, xs_ = ys_[m], xs_[m]
        near = dist[ys_ - y0, xs_ - x0] <= tol
        if not near.any():
            return False
        return float(np.hypot(np.ptp(ys_[near]), np.ptp(xs_[near]))) + 1 >= 0.5 * width
    k = 2 * max(2, int(round(DOORLESS_TOL_M * ppm))) + 1
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    out_near = cv2.dilate((r['outside'] > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0 \
        if r.get('outside') is not None else np.zeros(lab.shape, bool)
    added = []
    for rid in r['rooms']:
        ys0, xs0 = np.nonzero(lab == rid)
        if not len(ys0):
            continue
        y0, y1 = max(0, ys0.min() - k), min(lab.shape[0], ys0.max() + k + 1)
        x0, x1 = max(0, xs0.min() - k), min(lab.shape[1], xs0.max() + k + 1)
        zone = np.zeros(lab.shape, bool)
        own = (lab[y0:y1, x0:x1] == rid).astype(np.uint8)
        zone[y0:y1, x0:x1] = cv2.dilate(own, ker) > 0
        dist = cv2.distanceTransform(1 - own, cv2.DIST_L2, 3)       # до пола комнаты, px
        if any(faces(ys_, xs_, w_, dist, y0, x0) for ys_, xs_, w_ in doors):
            continue
        # сперва прежнее правило, окно с дугой — последним; по убыванию доли. Кандидатка, которую не поставить (все её пиксели
        # уже заняты другим разрывом), — следующая (T-11/4: rgK5f3 Cupboard у кухни оставался без двери)
        order = sorted((c for c in cands if zone[c[0], c[1]].any()), key=lambda c: (c[4], -c[2]))
        best = None
        for c in order:
            if c[4] and zone[c[0], c[1]].mean() < 0.5:              # окно с дугой — своё, не соседней комнаты у угла
                continue
            ys, xs, ev, gid, _ = c
            if gid is not None:
                if byid[gid].kind != 'window':
                    continue
                byid[gid].kind = 'door'
            else:
                free = lab_g[ys, xs] == 0
                if not free.any():
                    continue
                ys, xs = ys[free], xs[free]
                gid = int(lab_g.max()) + 1
                lab_g[ys, xs] = gid
                g = fc.regap(fc.Gap(gid, 0.0, 0.0, 0.0, 0.0, 'door', 0.0, bool(out_near[ys, xs].any()), (0, 0, 0, 0)),
                             ys, xs)
                gaps.append(g)
                byid[gid] = g
            best = c
            break
        if best is None:
            continue
        doors.append(np.nonzero(lab_g == gid) + (byid[gid].length,))
        cands = [c for c in cands if c is not best]
        added.append((int(rid), round(best[2], 2)))
    return added


def open_max(px: int) -> int | None:
    """Предел полосы-проёма `fpcore.xy_cut`; FP_OPEN_BAND=0 — режем по любой пустой полосе (прежнее правило)."""
    return None if os.environ.get('FP_OPEN_BAND', '1') == '0' else px


def own_arcs(claims: list, keep_other: np.ndarray, share: float = OWN_SHARE) -> np.ndarray | None:
    """«Одна дуга — одна дверь» (T-20261111-11). Заявки закрытий по дуге (ys, xs, доля, пиксели рисунка `door_evidence`)
    по убыванию доли забирают свой рисунок; заявка, у которой ≥ `share` рисунка уже забрала более сильная, — дугу чужой двери
    приняли за свою: её закрытие снимается. bs30 (площадка 2-го этажа): поперёк коридора у шкафа — «двери» по дуге и створке
    дверцы шкафа (0,8 против 1,0 у самой дверцы), коридор резался на куски, площадка — 0,74 м² вместо L-образной ~4,7.
    → маска снимаемых пикселей (кроме пикселей принятых заявок и закрытий не по дуге `keep_other`) или None.
    FP_ARC_OWN=0 — без правила (сравнение)."""
    if not claims or os.environ.get('FP_ARC_OWN', '1') == '0':
        return None
    order = sorted(range(len(claims)), key=lambda i: -claims[i][2])        # устойчиво: при равной доле — порядок проходов
    owned, lost, kept = set(), [], []
    for i in order:
        px = claims[i][3]
        if px and len(px & owned) >= share * len(px):
            lost.append(i)
        else:
            owned |= px
            kept.append(i)
    if not lost:
        return None
    drop = np.zeros(keep_other.shape, bool)
    for i in lost:
        drop[claims[i][0], claims[i][1]] = True
    for i in kept:
        drop[claims[i][0], claims[i][1]] = False
    drop &= keep_other == 0
    return drop if drop.any() else None


def _analyze(img, gray, wall, ppm, fams, t, regions=None, thin_thr=210, glaze_thr=215):
    """Один проход при гипотезе масштаба ppm (px на метр): разрывы → комнаты → проёмы."""
    ang = rot_angles(fams)
    Ls, Lb, fl = int(1.7 * ppm), int(LB_M * ppm), max(3, int(round(1.5 * t)))   # Lb: окна/французские двери
    # T-20261110-03/2: торцы со скосом (`fpcore.bevel_end_zone`) не продлеваем — их закрывают bridge_lines и шаг косых дверей
    ends = fc.wall_ends(wall, t)                     # скелет — один раз на стену листа (запомнен), не на гипотезу масштаба
    # T-20261111-03: клин ищем у грани НАРИСОВАННОЙ стены. Продление торца (`extend_corners`) — догадка: у QFfI… дверь спальни 2
    # между торцом стены и косяком лежит вдоль продления — по маске с продлениями она «клин», а это дверь
    wall_drawn = wall
    corner = fc.extend_corners(wall, int(0.6 * ppm), fl, fc.bevel_end_zone(wall, t, Ls))
    wall = (wall | corner).astype(np.uint8)
    thin = fc.thin_lines(gray, wall, thin_thr)
    dark = (((gray < glaze_thr) | (thin > 0)) & (wall == 0)).astype(np.uint8)
    max_depth = max(1.6 * t, 0.45 * ppm)         # глубже толщины стены — это не проём, а залитая комната
    def parts(w, L, both):
        return fc.bridge_parts(w, L, fl, ang, both_flanks=both)

    def per_region_parts(L, both):
        if not regions:
            return parts(wall, L, both)
        acc = None
        H, W = wall.shape
        for x0, y0, x1, y1 in regions:
            X0, Y0, X1, Y1 = max(0, x0 - 2), max(0, y0 - 2), min(W, x1 + 2), min(H, y1 + 2)
            ps = parts(wall[Y0:Y1, X0:X1], L, both)
            if acc is None:
                acc = [np.zeros_like(wall) for _ in ps]
            for k, p in enumerate(ps):
                acc[k][Y0:Y1, X0:X1] |= p
        return acc

    ps_s = per_region_parts(Ls, False)
    ps_b = per_region_parts(Lb, True)
    cand_s = np.zeros_like(wall)
    for p in ps_s:
        cand_s |= p
    allb = np.zeros_like(wall)
    for p in ps_b:
        allb |= p
    _, _, out1 = fc.free_components(wall | cand_s | allb)
    near_thin = None
    keep = np.zeros_like(wall)
    kid =np.zeros(wall.shape, np.int32)            # номер закрытия (T-20261111-09: делить сросшиеся углами, `fpcore.split_composite`)

    nkid = [0]

    def mark(ys, xs):
        nkid[0] += 1
        kid[ys, xs] = nkid[0]
        keep[ys, xs] = 1

    no_text = []

    def span_ok(g, c, u, nrm, L, dpt):
        # T-20261111-09: внутренняя перемычка поперёк прохода — «дверь» по буквам подписи (TGva…, прихожая 0,9 м: «Hallway 2'11"…»
        # давала дугу 0,95). Дугу внутренней перемычки мерим по тонким линиям без строк подписей (`fpcore.text_mask`)
        if g.exterior or not TEXT_MASK:
            return True
        if not no_text:
            no_text.append(np.where(fc.text_mask(thin, ppm), 0, thin).astype(thin.dtype))
        return fc.door_evidence(no_text[0], c, u, nrm, L, dpt) >= TEXT_EV_MIN

    # T-20261111-11: закрытия «по дуге» (малые, устье каморки, угловые, тонкие перегородки) — заявки с пикселями рисунка; одна
    # дуга — одна дверь (`own_arcs` ниже). keep_other — закрытия не по дуге (рама окна, большие проёмы): их не трогаем
    claims, keep_other = [], np.zeros_like(wall)

    def ev_of(c_, u_, n_, L_, d_):
        return fc.door_evidence(thin, c_, u_, n_, L_, d_, want_px=True, wall=wall_drawn)

    # T-11/3: закрытие, которое сняла только «чистота» дуги (прежнее правило — дверь), — запасная дверь комнаты, оставшейся
    # без дверей (`doorless_doors`)
    alts = []

    def alt_of(ys_, xs_, c_, u_, n_, L_, d_):
        if not DOORLESS or fc.arc_pure() is None:
            return
        if fc.along_face(wall_drawn, ys_, xs_) or not fc.passes_through(wall_drawn, ys_, xs_):
            # T-11/4: клин вдоль грани стены и закрытие не насквозь стены (с одной стороны тело стены) — не проём (как у
            # классификации T-03): rgK5f3 Tool store получал «двери»-полоски у правой стены вместо своей двери с дугой, Cinema —
            # клин у косой стены
            return
        tail = fc.wedge_tails(wall_drawn, ys_, xs_, ppm)
        if tail is not None:
            if (~tail).sum() < 3:
                return
            ys_, xs_ = ys_[~tail], xs_[~tail]
            c_, u_, n_, L_, d_ = fc.gap_axes(ys_, xs_)
        raw = fc.door_evidence(thin, c_, u_, n_, L_, d_, pure_check=False)
        if raw >= DOOR_EV:
            alts.append((ys_, xs_, float(raw)))

    # малые разрывы: закрываем, только если есть след проёма — рама окна в толщине стены или дуга двери
    for p in ps_s:
        lab_s, gs = fc.gap_components(p, dark, out1)
        for g in gs:
            ys, xs = np.nonzero(lab_s == g.id)
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            win = g.glaze >= GLAZE_MIN and g.exterior and dpt <= 2.2 * t
            if dpt > 2.2 * t:
                continue
            ev, px = ev_of(c, u, nrm, L, dpt)
            if dpt > max_depth and not win and ev < DOOR_EV:
                # каморка (шкаф, кладовка) залита перемычкой целиком — проём ищем только в её «устье» у соседа
                mm = fc.mouth_strip(lab_s == g.id, wall, t)
                if mm is not None:
                    ys2, xs2 = mm
                    c2, u2, n2, L2, d2 = fc.gap_axes(ys2, xs2)
                    if d2 <= max_depth and L2 >= 0.4 * ppm:
                        ev2, px2 = ev_of(c2, u2, n2, L2, d2)
                        if ev2 >= DOOR_EV:
                            mark(ys2, xs2)
                            claims.append((ys2, xs2, ev2, px2))
                        else:
                            alt_of(ys2, xs2, c2, u2, n2, L2, d2)
                continue
            # T-20261111-11: внутренний разрыв с линией у края марша (ступени по одну сторону) — верх лестницы, не рама
            stair = not g.exterior and g.glaze >= GLAZE_MIN and STAIR_EDGE and fc.stair_edge(thin, c, u, nrm, L, dpt, ppm)
            if win or (g.glaze >= GLAZE_MIN and not stair):
                mark(ys, xs)
                keep_other[ys, xs] = 1
            elif ev >= DOOR_EV:
                if not stair and span_ok(g, c, u, nrm, L, dpt):   # T-11/2: не стрелка «Down» поперёк ступеней; T-09: не буквы
                    mark(ys, xs)
                    claims.append((ys, xs, ev, px))
            elif not stair:
                done = False
                if PS_TAIL:
                    # T-20261111-09: дверь в тонкой стене, чей кусок за проёмом тоньше куска над ним, — перемычка шла и вдоль
                    # тонкого куска (щель у его грани), и дуга мерилась по «двери» 1,5 м (TGva…, кухня: 0,73 м двери + 0,77 м щели).
                    # Срезать хвост-клин (`fpcore.wedge_tails`, как у классификации T-03) и проверить дугу у остатка
                    tail = fc.wedge_tails(wall_drawn, ys, xs, ppm)
                    if tail is not None and (~tail).sum() >= 3:
                        ys3, xs3 = ys[~tail], xs[~tail]
                        c3, u3, n3, L3, d3 = fc.gap_axes(ys3, xs3)
                        if d3 <= max_depth:
                            ev3, px3 = fc.door_evidence(thin, c3, u3, n3, L3, d3, want_px=True)
                            if ev3 >= DOOR_EV and span_ok(g, c3, u3, n3, L3, d3):
                                mark(ys3, xs3)
                                claims.append((ys3, xs3, ev3, px3))
                                done = True
                if not done and dpt <= max_depth:
                    alt_of(ys, xs, c, u, nrm, L, dpt)
    # большие (окна, эркеры): обе стороны — длинная стена, снаружи, рама в разрыве или сразу за ним
    for p in ps_b:
        p = p & (cand_s == 0)
        lab_b, gb = fc.gap_components(p, dark, out1)
        for g in gb:
            if not g.exterior or g.depth > 2.2 * t:
                continue
            m = lab_b == g.id
            k = max(int(2 * g.depth), int(1.4 * ppm)) | 1      # эркер: рама в ~0,5 м снаружи стены
            near = cv2.dilate(thin, np.ones((k, k), np.uint8))
            if g.glaze >= GLAZE_MIN or (g.length <= 3.6 * ppm and near[m].mean() >= 0.5):   # шире 3,6 м — только по раме
                mark(*np.nonzero(m))
                keep_other |= m.astype(np.uint8)
    # T-20261110-03: косая дверь в углу комнаты (`fpcore.corner_cut_doors`) — отрезок между торцами двух стен угла. Правило — как у
    # прямой межкомнатной: ширина в [DOOR_MIN_M; Ls] и нарисована дуга/створка (DOOR_EV); проход/арка без створки — не закрываем
    H_, W_ = wall.shape
    for x0, y0, x1, y1 in (regions or [(0, 0, W_, H_)]):
        X0, Y0, X1, Y1 = max(0, x0 - 2), max(0, y0 - 2), min(W_, x1 + 2), min(H_, y1 + 2)
        for m in fc.corner_cut_doors(wall[Y0:Y1, X0:X1], (wall | keep)[Y0:Y1, X0:X1], Ls, fl, t, ang):
            ys, xs = np.nonzero(m)
            if len(ys) < 3:
                continue
            ys, xs = ys + Y0, xs + X0
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            if fc.DOOR_MIN_M * ppm <= L <= Ls:
                ev, px = ev_of(c, u, nrm, L, dpt)
                if ev >= DOOR_EV:
                    mark(ys, xs)
                    claims.append((ys, xs, ev, px))
                else:
                    alt_of(ys, xs, c, u, nrm, L, dpt)
        # T-20261110-03/2: стены угла кончаются скосом 45° с точкой-косяком (`fpcore.bevel_corner_doors`). Правило то же; петля
        # створки — сама точка-косяк, поэтому дуга ищется и от точек торцов (радиус — до другой точки), не только от граней разрыва
        ends_r = [dict(e, p=e['p'] - (X0, Y0)) for e in ends if X0 <= e['p'][0] < X1 and Y0 <= e['p'][1] < Y1]
        for m, p1, p2 in fc.bevel_corner_doors(wall[Y0:Y1, X0:X1], (wall | keep)[Y0:Y1, X0:X1], Ls, t, ends_r):
            ys, xs = np.nonzero(m)
            if len(ys) < 3:
                continue
            ys, xs = ys + Y0, xs + X0
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            if not fc.DOOR_MIN_M * ppm <= L <= Ls:
                continue
            q1, q2 = p1 + (X0, Y0), p2 + (X0, Y0)
            D = float(np.hypot(*(q2 - q1)))
            ut = (q2 - q1) / D
            ev, px = max(ev_of(c, u, nrm, L, dpt), ev_of((q1 + q2) / 2, ut, np.array([-ut[1], ut[0]]), D, 0.0),
                         key=lambda x: x[0])
            if ev >= DOOR_EV:
                mark(ys, xs)
                claims.append((ys, xs, ev, px))
    # T-20261110-33: дверь между короткими выступами ТОНКОЙ перегородки при толстых наружных стенах (aRQVC9: t листа 34 px,
    # перегородки 8–10, косяки двери спальни 3 — выступы 13–22 px при флангах 1,5·t = 51 px — не закрывалась, спальня слипалась
    # с площадкой). Только на листах со смешанной толщиной (`fpcore.thin_partition_t`): фланг — от толщины перегородок, правило
    # двери строже угловой — межкомнатная, ширина в [DOOR_MIN_M; THIN_DOOR_MAX_M], глубина ~ толщина перегородки, насквозь
    # (`fpcore.passes_through`), нарисована дуга (DOOR_EV), к принятому закрытию — только касанием у торца
    tp = fc.thin_partition_t(wall, t)
    thin_keep = np.zeros_like(wall)
    if tp:
        fl2 = max(3, int(round(1.5 * tp)))
        for x0, y0, x1, y1 in (regions or [(0, 0, W_, H_)]):
            X0, Y0, X1, Y1 = max(0, x0 - 2), max(0, y0 - 2), min(W_, x1 + 2), min(H_, y1 + 2)
            for p in fc.bridge_parts(wall[Y0:Y1, X0:X1], Ls, fl2, ang):
                pp = np.zeros_like(wall)
                pp[Y0:Y1, X0:X1] = p
                pp &= ((wall | keep) == 0).astype(pp.dtype)
                near_keep = cv2.dilate(keep.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
                lab_t, gt = fc.gap_components(pp, dark, out1)
                for g in gt:
                    if g.exterior:
                        continue
                    ys, xs = np.nonzero(lab_t == g.id)
                    c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
                    # полоска вдоль грани стены (мельче перегородки), прибавка вдоль уже закрытого проёма, сантехника шире
                    # одностворчатой двери — не дверь. Касание закрытия соседней двери у торца — можно (две двери у одного угла)
                    tk = near_keep[ys, xs]
                    if tk.any():
                        s_ = (np.column_stack([xs[tk], ys[tk]]) - c) @ u
                        if s_.max() - s_.min() > 0.3 * L:
                            continue
                    if not 0.6 * tp <= dpt <= 3 * tp or not fc.DOOR_MIN_M * ppm <= L <= THIN_DOOR_MAX_M * ppm \
                            or not fc.passes_through(wall | keep, ys, xs):
                        continue
                    ev, px = ev_of(c, u, nrm, L, dpt)
                    if ev >= DOOR_EV:
                        mark(ys, xs)
                        thin_keep[ys, xs] = 1
                        claims.append((ys, xs, ev, px))
                    else:
                        alt_of(ys, xs, c, u, nrm, L, dpt)
    drop = own_arcs(claims, keep_other)
    if drop is not None:
        keep[drop] = 0
        kid[drop] = 0
        thin_keep[drop] = 0
    # наружный контур: закрытие ~1,8 м по каждому куску листа — наружные окна/двери закрываются без «следа» проёма
    final0 = (wall | keep).astype(np.uint8)
    _, _, out0 = fc.free_components(final0)
    H, W = wall.shape

    def region_close(src, km):
        k_ = int(km * ppm) | 1
        out = np.zeros_like(wall)
        for x0, y0, x1, y1 in (regions or [(0, 0, W, H)]):
            sub = cv2.copyMakeBorder(src[y0:y1, x0:x1], k_, k_, k_, k_, cv2.BORDER_CONSTANT, value=0)
            out[y0:y1, x0:x1] |= cv2.morphologyEx(sub, cv2.MORPH_CLOSE, np.ones((k_, k_), np.uint8))[k_:-k_, k_:-k_]
        return out                                    # не выходя за кусок

    def env_strip(closed_):
        if ENV_GEO:
            # T-20261111-09: полоса — по свободному месту от наружи (через проём), не по прямой сквозь стену. Пока комната
            # «наружа» (проём ещё не закрыт), у тонкой наружной стены прямая мера давала изнутри щепу ~0,3 t вдоль всей стены;
            # она срасталась с полосой окна в Г, и окно отбрасывалось по глубине (TGva…, окно ванной: Г 2,1 × 1,3 м)
            near = fc.grow_within(closed_ == 0, final0 == 0, int(round(1.3 * t))) > 0
            return (closed_ > 0) & (out0 > 0) & (final0 == 0) & near
        d = cv2.distanceTransform((closed_ > 0).astype(np.uint8), cv2.DIST_L2, 5)
        return (closed_ > 0) & (out0 > 0) & (final0 == 0) & (d <= 1.3 * t)   # только полоса по наружному контуру
    E = env_strip(region_close(final0, 1.8))
    # широкое окно (до 3,6 м) в наружной стене закрывается контуром, только если в разрыве нарисована рама (тонкие линии)
    E2 = env_strip(region_close(final0, 3.6)) & ~cv2.dilate(E.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    n2, lab2 = cv2.connectedComponents(E2.astype(np.uint8), connectivity=4)
    # рама бывает бледной (C: линии 212 на заливке 244) — ниже порога тонких линий; берём любую видимую линию
    thin_near = cv2.dilate(((thin > 0) | ((gray < FAINT_GRAY) & (wall == 0))).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    for i in range(1, n2):
        m2 = lab2 == i
        if os.environ.get('FP_DEBUG_ENV') and m2.sum() >= 10:
            yy, xx = np.nonzero(m2)
            print('E2', wall.shape, xx.min(), yy.min(), xx.max(), yy.max(), 'n', int(m2.sum()), 'fr', round(float(thin_near[m2].mean()), 2))
        if m2.sum() >= 10 and thin_near[m2].mean() >= 0.5:
            E |= m2
    nE, labE = cv2.connectedComponents(E.astype(np.uint8), connectivity=4)
    _, labT, outT = fc.free_components((final0 | E).astype(np.uint8))
    # одна незакрытая дыра делает «наружей» весь этаж; поэтому наружа для проверки сторон — ещё и вне грубого контура
    _, _, outH0 = fc.free_components((final0 | E | region_close((final0 | E).astype(np.uint8), HULL_M)).astype(np.uint8))
    outT = outT & (outH0 > 0)
    ext_ids = []
    if os.environ.get('FP_DEBUG_ENV', '').startswith('/'):
        vis = np.full(wall.shape + (3,), 255, np.uint8)
        vis[outT > 0] = (200, 200, 255)
        vis[final0 > 0] = (0, 0, 0)
        vis[E] = (0, 200, 0)
        cv2.imwrite(os.path.join(os.environ['FP_DEBUG_ENV'], f'env-{W}x{H}-{ppm:.1f}.png'), vis)
    for i in range(1, nE):
        ys, xs = np.nonzero(labE == i)
        if len(ys) < 10:
            continue
        y0_, y1_, x0_, x1_ = max(0, ys.min() - 4), ys.max() + 5, max(0, xs.min() - 4), xs.max() + 5
        ring = cv2.dilate((labE[y0_:y1_, x0_:x1_] == i).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        fr = (labT[y0_:y1_, x0_:x1_] > 0) & ring
        if not (outT[y0_:y1_, x0_:x1_][fr].any() and (~outT[y0_:y1_, x0_:x1_][fr]).any()):
            continue                                  # между двумя постройками (наружа с обеих сторон) — не проём
        c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
        if os.environ.get('FP_DEBUG_ENV'):
            print('ENV', xs.min(), ys.min(), xs.max(), ys.max(), 'L', round(L), 'd', round(dpt), 'ppm', round(ppm, 1))
        # нижняя граница глубины — 2 px, не 0,5t: у французских дверей в тонкой стене (C, гостиная) полоса ~3 px
        if min(2.0, 0.5 * t) <= dpt <= ENV_DMAX * t and 0.4 * ppm <= L <= 3.6 * ppm:
            mark(ys, xs)
            ext_ids.append((c, u, nrm, L, dpt))
    # щель между двумя закрытиями (уже 0,6 м) у наружного контура — не комната, а толща стены
    if ext_ids:
        n0, lab0, out_ = fc.free_components((wall | keep).astype(np.uint8))
        near_env = cv2.dilate(((keep > 0) & E).astype(np.uint8), np.ones((3, 3), np.uint8))
        dtf = cv2.distanceTransform(((wall | keep) == 0).astype(np.uint8), cv2.DIST_L2, 5)
        for i in np.unique(lab0[near_env > 0]):
            if i == 0 or out_[lab0 == i].any():
                continue
            m = lab0 == i
            if 2 * dtf[m].max() < 0.6 * ppm:
                keep[m] = 1
    # перемычка, у которой с обеих сторон наружа, не стена ни одной комнаты (связка между постройками) — снять
    _, labF, outF = fc.free_components((wall | keep).astype(np.uint8))
    # одна незакрытая дыра (C: окно гостиной 3 м) делает «наружей» весь этаж — и снялись бы все закрытия этажа.
    # Поэтому «наружа» для этой проверки — вне грубого контура (закрытие HULL_M по каждому куску листа)
    fk = (wall | keep).astype(np.uint8)
    _, _, outH = fc.free_components((fk | region_close(fk, HULL_M)).astype(np.uint8))
    outF = outF & (outH > 0)
    nk, labK = cv2.connectedComponents(keep.astype(np.uint8), connectivity=8)
    for i in range(1, nk):
        ys, xs = np.nonzero(labK == i)
        y0_, y1_, x0_, x1_ = max(0, ys.min() - 4), ys.max() + 5, max(0, xs.min() - 4), xs.max() + 5
        ring = cv2.dilate((labK[y0_:y1_, x0_:x1_] == i).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        fr = (labF[y0_:y1_, x0_:x1_] > 0) & ring
        if fr.any() and outF[y0_:y1_, x0_:x1_][fr].all():
            if os.environ.get('FP_DEBUG_ENV'):
                print('DROP', wall.shape, xs.min(), ys.min(), xs.max(), ys.max())
            keep[ys, xs] = 0
    bay, bay_in = bay_windows(wall, keep, thin, dark, ppm, t)
    add = (keep | bay).astype(np.uint8)
    final = (wall | add).astype(np.uint8)
    n, lab, outside = fc.free_components(final)
    tk = (thin_keep & add).astype(np.uint8)
    lab_g, gaps = fc.gap_components(add & (tk == 0), dark, outside)
    if tk.any():
        # T-20261110-33: дверь тонкой перегородки, касающаяся у торца закрытия соседней двери, — свой разрыв (иначе две двери
        # у одного угла склеиваются в один проём двойной ширины)
        lab2, g2 = fc.gap_components(tk, dark, outside)
        off = int(lab_g.max())
        for g in g2:
            g.id += off
        lab_g = np.where(lab2 > 0, lab2 + off, lab_g)
        gaps += g2
    if SPLIT_DEEP:
        lab_g, gaps = fc.split_composite(lab_g, gaps, kid, dark, outside, max_depth)
    tails = []                                     # хвосты-клинья, срезанные с дверей (T-20261111-03)
    retype, glazed = [], []
    for g in gaps:
        if bay.any() and bay[lab_g == g.id].any():
            g.kind = 'window'
        elif not g.exterior and fc.is_notch(g, t) and not (g.depth >= fc.THIN_PART_MIN_PX
                                                           and fc.passes_through(wall, *np.nonzero(lab_g == g.id))):
            # T-36: зазубрина грани стены (водяной знак, сжатие) — не проём; наружные не трогаем: рама окна серым в линии стены
            # даёт щель в 1 px. T-20261110-33: мелкий по t листа, но сквозь тонкую межкомнатную стену (по обе стороны — комнаты) — проём;
            # глубина — не мельче самой тонкой стены (щель 2 px между стеной и линией душевой у Nethercote — не дверь)
            g.kind = 'wall'
        elif not g.exterior:
            # T-36: межкомнатная уже нормы (с запасом на недомер) — просвет/шум, не дверь; закрытие остаётся стеной.
            # Нарисована створка (дуга) — дверца кладовки/шкафа (UK 457/533 мм): остаётся дверью.
            g.kind = 'door'
            ys, xs = np.nonzero(lab_g == g.id)
            if fc.along_face(wall_drawn, ys, xs):
                # T-20261111-03: клин вдоль грани стены (закрытие по наклонному семейству углов листа) — не проём: одна длинная
                # сторона на стене, другая в комнате. rgK5…: у Bedroom 8 семь «дверей» при одной настоящей — ядра спален не было
                g.kind = 'wall'
                continue
            tail = fc.wedge_tails(wall_drawn, ys, xs, ppm)
            if tail is not None:
                # T-20261111-03: дверь, слитая с клином вдоль грани (rgK5… Bedroom 3: 0,75 м двери + 0,9 м клина) — клин отдельным
                # разрывом-стеной, дверь — своей шириной (иначе «дверь» 1,5–1,7 м режет ядро спальни)
                nid = int(lab_g.max()) + 1
                lab_g[ys[tail], xs[tail]] = nid
                tails.append(fc.regap(dataclasses.replace(g, id=nid, kind='wall'), ys[tail], xs[tail]))
                ys, xs = ys[~tail], xs[~tail]
                fc.regap(g, ys, xs)
            if g.length < fc.DOOR_MIN_M * ppm:
                c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
                if fc.door_evidence(thin, c, u, nrm, L, dpt, wall=wall_drawn) < DOOR_EV:
                    g.kind = 'wall'
        elif g.glaze >= GLAZE_MIN:
            # наружный с «рамой» — окно. Но створку рисуют и закрытой в линии стены: «рама» есть, а дуга «вогнутая» —
            # касается стены у торца, центр в комнате (наш пример /try, T-20261110-11: входы спальни 1 и санузла 2 были
            # окнами). Прежние рисунки дуги у рам окон ложно доходят до 1,0 (линии рамы, размерные снаружи — листы A, B, T),
            # поэтому здесь проверяется только этот рисунок
            g.kind = 'window'
            if GLAZED_ARC or DOORLESS:
                ys, xs = np.nonzero(lab_g == g.id)
                c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            if GLAZED_ARC and fc.door_evidence(thin, c, u, nrm, L, dpt, tangent_only=True) >= DOOR_EV_GLAZED:
                g.kind = 'door'
            if g.kind == 'window' and DOORLESS:
                # T-11/4: дуга открывания у «окна» (rgK5f3: проёмы залиты серым, дуга наружу) — дверью только у комнаты без
                # дверей (`doorless_doors`): у рам окон прежний рисунок дуги ложно доходит до 1,0 (A, B, T)
                ev = fc.door_evidence(thin, c, u, nrm, L, dpt, wall=wall_drawn)
                if ev >= DOOR_EV:
                    glazed.append((g.id, float(ev)))
        else:                                        # наружный без рамы: дуга створки → дверь, иначе окно
            ys, xs = np.nonzero(lab_g == g.id)
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            g.kind = 'door' if fc.door_evidence(thin, c, u, nrm, L, dpt, wall=wall_drawn) >= DOOR_EV else 'window'
            if g.kind == 'window' and DOORLESS and fc.arc_pure() is not None:
                raw = fc.door_evidence(thin, c, u, nrm, L, dpt, pure_check=False)
                if raw >= DOOR_EV:
                    retype.append((g.id, float(raw)))     # T-11/3: запасная дверь (`doorless_doors`) — окно только по «чистоте»
    gaps += tails
    if os.environ.get('FP_DEBUG_ENV', '').startswith('/'):
        vis = np.full(wall.shape + (3,), 255, np.uint8)
        vis[outside > 0] = (200, 200, 255)
        vis[wall > 0] = (0, 0, 0)
        vis[add > 0] = (0, 200, 0)
        cv2.imwrite(os.path.join(os.environ['FP_DEBUG_ENV'], f'fin-{W}x{H}-{ppm:.1f}.png'), vis)
    areas = np.bincount(lab.ravel(), minlength=n)
    min_room = 0.3 * ppm * ppm
    rooms = [i for i in range(1, n) if areas[i] >= min_room and not outside[lab == i].any()]
    return {'wall': wall, 'final': final, 'add': add, 'lab': lab, 'outside': outside, 'rooms': rooms, 'areas': areas,
            'lab_g': lab_g, 'gaps': gaps, 'ppm': ppm, 'bay_in': bay_in, 'alts': alts, 'retype': retype,
            'glazed': glazed}


def bay_windows(wall, keep, thin, dark, ppm, t):
    """Эркер: снаружи наружной стены замкнутый контур из тонких линий (рамы окон), примыкающий к закрытию-окну в стене.
    Тогда комната продолжается в эркер (закрытие снимается — keep меняется на месте), а контур эркера — стена с окнами.
    Дуги дверей снаружи тоже замыкают контур, но примыкают к проёму без рамы — не берём. → маска контура эркеров."""
    bay = np.zeros_like(wall)
    bay_in = np.zeros(wall.shape, bool)              # сам эркер (+ проём в стене): из мерок комнаты по подписи — исключаем
    fw = (wall | keep).astype(np.uint8)
    _, _, outW = fc.free_components(fw)
    thin_o = cv2.dilate(((thin > 0) & outW).astype(np.uint8), np.ones((3, 3), np.uint8))
    _, _, outB = fc.free_components((fw | thin_o).astype(np.uint8))
    cand = outW & ~outB & (fw == 0) & (thin_o == 0)
    nB, labC, stC, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=4)
    nk, labK = cv2.connectedComponents(keep.astype(np.uint8), connectivity=8)
    for i in range(1, nB):
        if not (0.3 * ppm * ppm <= stC[i, cv2.CC_STAT_AREA] <= 8 * ppm * ppm):
            continue
        m = labC == i
        ys, xs = np.nonzero(m)
        _, _, _, L, dpt = fc.gap_axes(ys, xs)
        if not (0.25 * ppm <= dpt <= 1.6 * ppm):
            continue
        (_, _), (rw, rh), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        if len(xs) < BAY_RECT * (rw + 1) * (rh + 1):     # не прямоугольник (четверть круга от створки ≈ 0,785) — не эркер
            continue
        kr = int(t) + 5                                # через линию рамы вдоль стены — до перемычки в проёме
        ring = cv2.dilate(m.astype(np.uint8), np.ones((kr, kr), np.uint8)) > 0
        ks = sorted(set(np.unique(labK[ring & (keep > 0)])) - {0})
        if not ks:
            continue
        kmask = np.isin(labK, ks)
        kys, kxs = np.nonzero(kmask)
        kc, ku, kn, kL, kd = fc.gap_axes(kys, kxs)
        # проём с дугой створки (дверь) — не эркер. T-11/3: по прежнему правилу, без «чистоты» — она для закрытий в комнате
        # (текст, ступени); здесь ошибка «дверь» лишь оставляет проём проёмом, а снятая ею дверь превращала кладовую в «эркер»
        # (rgK5f3: Store 7,67×2,50 — левая часть за дверью стала наружей)
        if fc.door_evidence(thin, kc, ku, kn, kL, kd, wall=wall, pure_check=not BAY_OLD) >= DOOR_EV:
            continue
        if os.environ.get('FP_DEBUG_ENV'):
            print('BAY', wall.shape, xs.min(), ys.min(), xs.max(), ys.max(), 'keep', kxs.min(), kys.min(), kxs.max(), kys.max())
        keep[kmask] = 0
        bay_in |= m | kmask
        k = max(3, int(t)) | 1
        bay |= ((cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & ~m & outW & (fw == 0)).astype(np.uint8)
    return bay, bay_in


def room_at(lab, rooms, pt, r=6):
    x, y = pt
    H, W = lab.shape
    best = None
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            yy, xx = y + dy, x + dx
            if 0 <= yy < H and 0 <= xx < W and lab[yy, xx] in rooms:
                d = dx * dx + dy * dy
                if best is None or d < best[0]:
                    best = (d, int(lab[yy, xx]))
    return best[1] if best else None


# ВЫНОСКА (T-20261110-12, Berrys «Floor 1»): подпись в рамке СНАРУЖИ дома, тонкая линия от рамки — к точке в комнате. VLM честно
# даёт центр текста (`labels2`: «centre point of the room-name text») — над домом, комнаты под точкой нет, подпись «не найдена».
# Подпись снаружи переносим в конец линии, только если линия видна: в просвете между рамкой и домом (подпись сада/террасы
# снаружи без линии — остаётся, где была), затем сквозь стену — в комнату, до точки на её конце. Линия — по осям листа.
CALLOUT_RAY = 0.3          # дальше доли листа от дома рамку не ищем
CALLOUT_GAP_PX = 4         # линия в просвете рамка → дом — не короче, px
RIDGE_DROP = 30            # линия темнее фона поперёк луча на столько (серое)
RIDGE_W = 4                # и не толще, px


def _ridge(gray, x, y, d, half):
    """Тонкая тёмная линия поперёк луча `d` в точке (x, y): смещение её середины от луча (px) или None."""
    H, W = gray.shape
    nx, ny = -d[1], d[0]
    v = []
    for k in range(-half, half + 1):
        xx, yy = x + nx * k, y + ny * k
        if not (0 <= xx < W and 0 <= yy < H):
            return None
        v.append(int(gray[yy, xx]))
    v = np.array(v)
    idx = np.nonzero(v <= np.percentile(v, 75) - RIDGE_DROP)[0]
    if not len(idx) or idx.max() - idx.min() >= RIDGE_W:
        return None
    return int(round(idx.mean())) - half


def building_hulls(res) -> list:
    """Выпуклые оболочки построек листа (компоненты стен не меньше 2×2 м, как `panels_of`). «Снаружи» для выноски — вне ВСЕХ
    оболочек: комната с воротами наружу (C, «Store» в гараже) на листе сливается с улицей, а её подпись — внутри постройки."""
    final, ppm = res['final'], float(res['ppm'])
    n, lab, st, _ = cv2.connectedComponentsWithStats(final, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w >= 2.0 * ppm and h >= 2.0 * ppm and a >= 0.5 * ppm * ppm:
            ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
            out.append(cv2.convexHull(np.column_stack([xs + x, ys + y]).astype(np.int32)))
    return out


def follow_callout(pt, gray, res, t, hulls=None):
    """Подпись снаружи дома с линией-выноской → (точка в комнате на конце линии, id комнаты) или None (не выноска)."""
    lab, outside, rooms = res['lab'], res['outside'], set(res['rooms'])
    H, W = gray.shape
    x0, y0 = int(round(pt[0])), int(round(pt[1]))
    if not (0 <= x0 < W and 0 <= y0 < H) or not outside[y0, x0] or room_at(lab, rooms, (x0, y0), 6) is not None:
        return None
    hulls = building_hulls(res) if hulls is None else hulls
    if any(cv2.pointPolygonTest(h, (float(x0), float(y0)), False) >= 0 for h in hulls):
        return None                                           # внутри постройки — не выноска (комната открыта наружу)
    smax = int(CALLOUT_RAY * max(H, W))
    hits = []
    for d in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        for s in range(1, smax):
            x, y = x0 + d[0] * s, y0 + d[1] * s
            if not (0 <= x < W and 0 <= y < H):
                break
            if not outside[y, x]:
                hits.append((s, d))
                break
    half = max(RIDGE_W, int(round(t / 2)))
    for sb, d in sorted(hits):
        offs = []
        for s in range(sb - 1, 0, -1):                       # просвет перед домом — назад к рамке, пока видна линия
            o = _ridge(gray, x0 + d[0] * s, y0 + d[1] * s, d, half)
            if o is None:
                break
            offs.append(o)
        if len(offs) < CALLOUT_GAP_PX or max(offs) - min(offs) > 2:
            continue
        off = int(round(float(np.median(offs[:CALLOUT_GAP_PX]))))
        lx, ly = x0 - d[1] * off, y0 + d[0] * off             # ось линии
        rid, last, entry = None, None, None
        for s in range(sb, sb + smax):
            x, y = lx + d[0] * s, ly + d[1] * s
            if not (0 <= x < W and 0 <= y < H):
                break
            v = int(lab[y, x])
            if rid is None:
                if v in rooms:
                    rid, entry = v, s
                elif outside[y, x] or s - sb > 6 * t:           # снова наружу или «стена» толще шести стен — не наш случай
                    break
                continue
            if v != rid:
                break
            if _ridge(gray, x, y, d, 2) is not None or gray[y, x] < 128:
                last = s
            elif last is not None and s - last > 3:          # линия кончилась (точка на её конце пройдена)
                break
        if rid is None:
            continue
        s = last if last is not None and last > entry else entry + 2
        q = (lx + d[0] * s, ly + d[1] * s)
        if room_at(lab, rooms, q, 2) == rid:
            return q, rid
    return None


def callouts_to_rooms(labels, gray, res, t) -> list:
    """Подписи-выноски (`follow_callout`) → точка в комнату: правит `pt` подписей на месте. → журнал переносов."""
    out, hulls = [], None
    for q in labels:
        x, y = int(round(q['pt'][0])), int(round(q['pt'][1]))
        if not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]) or not res['outside'][y, x]:
            continue                                          # подпись в доме — как была (оболочки не считаем зря)
        hulls = building_hulls(res) if hulls is None else hulls
        m = follow_callout(q['pt'], gray, res, t, hulls)
        if m:
            out.append({'name': q['name'], 'from': [round(float(q['pt'][0]), 1), round(float(q['pt'][1]), 1)],
                        'to': [int(m[0][0]), int(m[0][1])]})
            q['pt'] = [int(m[0][0]), int(m[0][1])]
    return out


def room_angle(mask, fams):
    """Ось комнаты: семейство, ближайшее к углу minAreaRect; приведение к (-45, 45]."""
    ys, xs = np.nonzero(mask)
    (_, _), (_, _), a = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
    a = a % 180
    f = min(fams, key=lambda q: fc.angdiff(q, a)) if fams else 0.0
    return ((f + 45) % 90) - 45


def room_body(res, rid):
    """Тело комнаты для мерки: без эркера (подпись агентства — без него); комната целиком внутри эркера — как есть
    (T-09: иначе пустая маска роняла прогон)."""
    lab = res['lab']
    m = lab == rid
    bay = res.get('bay_in')
    if bay is not None and (m & ~bay).any():
        m = m & ~bay
    return m


def match_gold(res, gold_rooms, fams, core=False):
    lab, rooms = res['lab'], res['rooms']
    hit = {}
    for gi, g in enumerate(gold_rooms):
        rid = room_at(lab, rooms, tuple(g['pt']), max(6, int(0.25 * res.get('ppm', 24))))   # подпись жирным попадает в маску
        g['_room'] = rid
        if rid is not None:
            hit.setdefault(rid, []).append(gi)
    obs = []
    for gi, g in enumerate(gold_rooms):
        rid = g['_room']
        if rid is None or 'dims_m' not in g or len(hit[rid]) > 1:
            continue
        m = room_body(res, rid)
        ang = room_angle(m, fams)
        obs.append({'id': g['name'], 'dims': tuple(g['dims_m']), 'ext': fc.room_extents(m, -ang, core), 'angle': ang})
    return hit, obs


def room_dims(groom, hit, obs, loo, ppm_sheet):
    """Каждая подписанная комната: подпись A×B → наше A×B (стороны в порядке подписи) или почему не измерена.
    Масштаб — без самой комнаты: «loo» (по остальным комнатам панели); если их мало — «лист» (масштаб всего листа
    из перебора, кандидат P95)."""
    by_loo = {l['id']: l for l in loo}
    by_obs = {o['id']: o for o in obs}
    out = []
    for g in groom:
        if 'dims_m' not in g:
            continue
        a, b = g['dims_m']
        row = {'id': g['name'], 'gold': [a, b]}
        rid = g.get('_room')
        if rid is None:
            row['status'] = 'не выделилась'
        elif len(hit.get(rid, [])) > 1:
            row['status'] = 'слилась с ' + ', '.join(groom[i]['name'] for i in hit[rid] if groom[i]['name'] != g['name'])
        elif by_loo.get(g['name'], {}).get('ok'):
            pa, pb = by_loo[g['name']]['pred']
            if max(abs(pb - a), abs(pa - b)) < max(abs(pa - a), abs(pb - b)):
                pa, pb = pb, pa                        # стороны — в порядке подписи
            row.update(status='loo', ours=[pa, pb], diff_cm=[round(100 * (pa - a)), round(100 * (pb - b))])
        elif g['name'] in by_obs:
            o = by_obs[g['name']]
            best = min((fc._err(o, 1 / ppm_sheet, 'p95', p) + (p,) for p in (0, 1)), key=lambda x: x[0])
            pa, pb = best[1]
            row.update(status='лист', ours=[round(pa, 3), round(pb, 3)], diff_cm=[round(100 * (pa - a)), round(100 * (pb - b))])
        else:
            row['status'] = 'не измерена'
        out.append(row)
    return out


def unlabeled_dims(res, groom, hit, fams, ppm, fit):
    """Слепой план (T-04): комната найдена, а размер подписи не прочитан (нет в VLM и в тексте) — мерка по масштабу
    панели (кандидат — манера панели, иначе P95), стороны без порядка; статус «мерка без подписи», флаг всегда."""
    c = fc.convention(fit)[0] if fit else 'p95'
    out = []
    for g in groom:
        if 'dims_m' in g:
            continue
        rid = g.get('_room')
        if rid is None or len(hit.get(rid, [])) > 1:
            continue
        m = room_body(res, rid)
        ext = fc.room_extents(m, -room_angle(m, fams), True)
        wx, wy = ext.get(c, ext['p95'])
        out.append({'id': g['name'], 'gold': None, 'status': 'мерка без подписи', 'ours': [round(wx / ppm, 3), round(wy / ppm, 3)],
                    'cand': c, 'flag': 'размер не прочитан', 'flag_level': 1})
    return out


def crosses_wall(wall, p1, p2):
    n = int(max(abs(p2[0] - p1[0]), abs(p2[1] - p1[1]))) + 1
    xs = np.clip(np.round(np.linspace(p1[0], p2[0], n)).astype(int), 0, wall.shape[1] - 1)
    ys = np.clip(np.round(np.linspace(p1[1], p2[1], n)).astype(int), 0, wall.shape[0] - 1)
    return bool(wall[ys, xs].any())


def topology(res, gold_rooms, hit, ppm):
    req = [g for g in gold_rooms if not g.get('optional')]
    missing = [g['name'] for g in req if g['_room'] is None]
    merged, open_plan = [], []
    for v in hit.values():
        req_v = [i for i in v if not gold_rooms[i].get('optional')]
        if len(req_v) < 2:
            continue
        names = [gold_rooms[i]['name'] for i in v]
        # «открытая планировка»: между подписями на листе нет стены (прямая между точками не пересекает маску стен)
        if 'wall' in res and all(not crosses_wall(res['wall'], gold_rooms[a]['pt'], gold_rooms[b]['pt'])
                                 for k, a in enumerate(req_v) for b in req_v[k + 1:]):
            open_plan.append(names)
        else:
            merged.append(names)
    extra = [rid for rid in res['rooms'] if rid not in hit and res['areas'][rid] >= 1.0 * ppm * ppm]
    return {'gold_rooms': len(req), 'found': len(req) - len(missing), 'missing': missing, 'merged': merged,
            'open_plan': open_plan, 'extra_rooms': len(extra), 'extra_areas_m2': [round(res['areas'][r] / ppm / ppm, 2) for r in extra],
            '_extra_ids': extra,
            '_extra_w': [round(inscribed_width(res['lab'] == r) / ppm, 2) if 'lab' in res else None for r in extra]}


# Обрывок (T-16): безымянный лишний кусок, который не может быть помещением, — меньше FRAG_AREA_M2 или уже FRAG_WIDTH_M
# по вписанной ширине (межстенный зазор, лестничный марш, клетка мебели, водяной знак). Пол его остаётся в выгрузке,
# но в «лишние комнаты» он не идёт — уходит в список fragments_m2 (виден в отчёте).
FRAG_AREA_M2 = 1.5
FRAG_WIDTH_M = 1.0


def inscribed_width(mask):
    """Ширина вписанной окружности куска, пкс (2 × максимум расстояния до края)."""
    m = np.pad(mask.astype(np.uint8), 1)
    return 2.0 * float(cv2.distanceTransform(m, cv2.DIST_L2, 5).max())


def is_fragment(area_m2, width_m):
    return area_m2 < FRAG_AREA_M2 or (width_m is not None and width_m < FRAG_WIDTH_M)


def name_extras(topo, rep_labels):
    """Лишние куски (нет комнаты золота) — с именем помещения от VLM, если его точка в этом куске; без имени —
    «необъяснённый» (критерий этапа 2: лишние — только неподписанные помещения с именем VLM). Безымянный обрывок
    (is_fragment) из лишних снимается в fragments_m2."""
    ids = topo.pop('_extra_ids', [])
    ws = topo.pop('_extra_w', [None] * len(ids))
    by = {}
    for q in rep_labels or []:
        if q.get('room') is not None:
            by.setdefault(q['room'], []).append(q['name'])
    names = [', '.join(by.get(rid, [])) or None for rid in ids]
    keep, frag = [], []
    for a, w, n in zip(topo['extra_areas_m2'], ws, names):
        if n is None and is_fragment(a, w):
            frag.append(a)
        else:
            keep.append((a, w, n))
    topo['extra_rooms'] = len(keep)
    topo['extra_areas_m2'] = [a for a, _, _ in keep]
    topo['extra_named'] = [n for _, _, n in keep]
    topo['extra_unnamed_m2'] = [a for a, _, n in keep if n is None]
    topo['fragments_m2'] = frag
    return topo


def panels_of(final, ppm):
    n, lab, st, _ = cv2.connectedComponentsWithStats(final, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w >= 2.0 * ppm and h >= 2.0 * ppm and a >= 0.5 * ppm * ppm:
            out.append((int(x), int(y), int(w), int(h)))
    # вложенные (стена внутри панели, оторванная) — поглотить
    out.sort(key=lambda b: -b[2] * b[3])
    res = []
    for b in out:
        if any(b[0] >= r[0] - 2 and b[1] >= r[1] - 2 and b[0] + b[2] <= r[0] + r[2] + 2 and b[1] + b[3] <= r[1] + r[3] + 2
               for r in res):
            continue
        res.append(b)
    return res


def gia_px(res, t):
    """Площадь «по внутренней грани наружных стен, с внутренними стенами» (RICS GIA), px²."""
    final, outside = res['final'], res['outside']
    foot = (~outside) & True
    dist_out = cv2.distanceTransform((~outside).astype(np.uint8), cv2.DIST_L2, 5)
    dtw = cv2.distanceTransform(final, cv2.DIST_L2, 5)
    ridge = dtw >= cv2.dilate(dtw, np.ones((3, 3), np.uint8)) - 1e-6        # ось стены (гребень distance transform)
    axis = (final > 0) & ridge & (dtw >= 1.5) & (dist_out <= dtw + 1.5)     # ось НАРУЖНОЙ стены: до наружи — полтолщины
    t_ext = float(2 * np.median(dtw[axis])) if axis.any() else t
    # след здания = найденные комнаты + стены в пределах толщины от них (рамки подписей и мусор вне здания не считаем)
    rooms = np.isin(res['lab'], res['rooms'])
    k = int(2 * t_ext + 3) | 1
    foot = rooms | ((final > 0) & (cv2.dilate(rooms.astype(np.uint8), np.ones((k, k), np.uint8)) > 0))
    ff = foot.astype(np.uint8)
    n_, lab_, out_ = fc.free_components(ff)
    foot = foot | ~out_                                     # залить дыры (колонны, шахты)
    dist_f = cv2.distanceTransform(foot.astype(np.uint8), cv2.DIST_L2, 5)
    ext_wall = foot & (final > 0) & (dist_f <= t_ext + 0.5)
    return float(foot.sum() - ext_wall.sum()), t_ext


def plan_regions(wall, t, fams, max_open=None):
    """Отдельные планы листа/панели (`fpcore.xy_cut` по пустым полосам) — разрывы между ними не закрываются. Обломки стены,
    отрезанные окнами во всю толщину стены, — к ближайшему плану (`fpcore.merge_fragments`, T-20261111-09; FP_FRAG=0 — как до).
    `max_open` — полоса-проём не шире (окно и ворота друг напротив друга) постройку не режет (T-20261111-11, `open_max`)."""
    regions = fc.xy_cut(wall, max(40, int(3 * t)), max_open=max_open)
    if os.environ.get('FP_FRAG', '1') != '0':
        regions = fc.merge_fragments(wall, regions, t, fams)
    return regions


def run_plan(plan, inputs, outdir, gold=None, cfg=None):
    """gold/cfg — для слепого плана (T-04): «золото» собрано из подписей VLM + текста объявления (`blind_gold`),
    маска — `auto_cfg`; иначе — `gold/<план>.json` и CFG стенда."""
    t0 = time.time()
    gold = gold or json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    img = cv2.imread(str(Path(inputs) / gold['image']), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if cfg is None:      # FP_AUTO=1 — A/B/C по общему правилу (как слепые), иначе — настройка стенда CFG
        cfg = auto_cfg(img) if os.environ.get('FP_AUTO', '0') != '0' else dict(CFG[plan])
    wall = build_mask(img, cfg)
    t = sheet_thickness(wall, cfg)
    arrows = sheet_arrows(img, wall, cfg, t)
    fams = fc.angle_families(wall)
    # T-20261111-11: полоса-проём (окно и ворота друг напротив друга) постройку не режет; масштаба ещё нет — предел по толщине
    # стены (OPEN_MAX_T · t ≈ 1,7 м при стене ~0,2 м)
    regions = plan_regions(wall, t, fams, max_open=open_max(int(OPEN_MAX_T * t)))
    log = {'plan': plan, 'thickness_px': round(t, 2), 'families_deg': [round(f, 1) for f in fams], 'regions': regions}
    # 1) перебор гипотез масштаба по всему листу → лучшая по числу инлаеров подписей
    sweep = []
    hyps = [float(os.environ['FP_PPM'])] if os.environ.get('FP_PPM') else [18 * 1.2 ** k for k in range(12)]  # FP_PPM — отладка
    blind = bool(gold.get('blind'))       # выноски — только у подписей VLM (у ручного золота точки уже в комнатах)
    for ppm in hyps:
        r = analyze(img, gray, wall, ppm, fams, t, regions, cfg['thin'], cfg['glaze'])
        gh = [dict(g) for g in gold['rooms']]
        if blind:
            callouts_to_rooms(gh, gray, r, t)
        _, obs = match_gold(r, gh, fams)
        f = fc.fit_scale(obs)
        if f:
            est = 1 / f['s']
            sweep.append({'ppm': ppm, 'est': est, 'inl': len(f['inliers']), 'n': len(obs),
                          'cons': abs(est / ppm - 1)})
    if not sweep:
        raise SystemExit(f'{plan}: масштаб не найден — нет комнат с подписью размера, совпавших с комнатами маски')
    sweep.sort(key=lambda x: (-x['inl'], x['cons']))
    log['sweep'] = [{k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()} for s in sweep[:6]]
    ppm0 = sweep[0]['est']
    base = analyze(img, gray, wall, ppm0, fams, t, regions, cfg['thin'], cfg['glaze'])
    if blind:
        log['callouts'] = callouts_to_rooms(gold['rooms'], gray, base, t)
        moved = {c['name']: c['to'] for c in log['callouts']}
        for q in gold.get('_labels') or []:
            if q['name'] in moved:
                q['pt'] = tuple(moved[q['name']])
    vdir = os.environ.get('FP_VLM')
    vl = load_vlm(plan, vdir, img.shape) if vdir else None
    if vl is not None and gold.get('_labels') is not None:     # слепой: подписи VLM с размерами из текста объявления
        vl['labels'] = [dict(q) for q in gold['_labels']]
        vl['pts'] = [q['pt'] for q in gold['_labels']]
    cfg['dev_sheet'] = log['dev_sheet'] = dev_sheet(cfg, vl)      # T-38/3: правила проёмов листа застройщика — только у него
    log['cfg'] = {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()}
    H_, W_ = wall.shape
    pan = []     # (X0, Y0, X1, Y1, маска панели или None, принадлежность точки)
    pan_title = []
    # источник деления листа (T-27): заголовки этажей (≥ 2, `labels3`) → контуры VLM `panels` (не оборванные) → куски маски;
    # FP_PANELS=vlm|pieces — принудительно (сравнение)
    # T-27/2: целые контуры VLM — геометрия, если заголовки этажей с ними сходятся (`titles_vs_vlm`) или заголовков < 2;
    # не сходятся / контуры оборваны → делёж кусков по заголовкам; одинаковые заголовки контуров — одна панель (`vlm_groups`)
    pmode = os.environ.get('FP_PANELS', 'auto')
    titles = (vl.get('titles') or []) if vl else []
    pflags = log['panel_flags'] = []
    if vl and vl.get('panels_truncated'):
        log['panels_truncated'] = True
    if titles:
        log['titles'] = [{'title': q['title'], 'pt': [round(q['pt'][0], 1), round(q['pt'][1], 1)]} for q in titles]
    use_vlm = bool(vl and vl['panels']) and pmode in ('auto', 'vlm')
    if use_vlm and titles:
        tv = titles_vs_vlm(titles, vl['panels'])
        log['titles_vs_vlm'] = tv
        if pmode == 'auto' and len(titles) >= 2 and any(norm_title(a) != norm_title(b) for a, b in tv):
            use_vlm = False
            pflags.append('vlm_panels_disagree')
    if not use_vlm and vl and pmode in ('auto', 'titles') and len(titles) >= 2:
        pan, pan_title = panels_by_titles(base['final'], ppm0, titles, W_, H_, pflags)
        log['panels_src'] = 'titles'
    if pan:
        pass                                   # поделено по заголовкам
    elif use_vlm:
        log['panels_src'] = 'vlm'
        # панели — контуры VLM (заголовок → здание): стены за контуром (+1 м) режутся; точка — в ближайший контур
        vpolys = [np.ascontiguousarray(q['poly'].reshape(-1, 1, 2), np.float32) for q in vl['panels']]
        groups = vlm_groups(vl['panels'])
        gof = {i: gi for gi, (_, idx) in enumerate(groups) for i in idx}
        log['panels_groups'] = [[t, idx] for t, idx in groups]

        def owner(pt):
            return gof[int(np.argmax([cv2.pointPolygonTest(pp, (float(pt[0]), float(pt[1])), True) for pp in vpolys]))]
        # контур VLM неточен (C: низ дома срезан на ~1.2 м → весь этаж утёк наружу), поэтому
        # пиксель отдаётся ближайшему контуру (знаковое расстояние), но не дальше PANEL_R_M от него
        sds = []
        for q in vl['panels']:
            fm = np.zeros((H_, W_), np.uint8)
            cv2.fillPoly(fm, [q['poly'].astype(np.int32)], 1)
            sds.append(cv2.distanceTransform(1 - fm, cv2.DIST_L2, 5) - cv2.distanceTransform(fm, cv2.DIST_L2, 5))
        sds = np.stack(sds)
        near = np.argmin(sds, axis=0)
        for gi, (gt, idx) in enumerate(groups):
            pm = np.zeros((H_, W_), np.uint8)
            for qi in idx:
                pm |= ((near == qi) & (sds[qi] <= PANEL_R_M * ppm0)).astype(np.uint8)
            if not pm.any():
                continue
            ys_, xs_ = np.nonzero(pm)
            pan.append((int(xs_.min()), int(ys_.min()), int(xs_.max()) + 1, int(ys_.max()) + 1, pm,
                        (lambda pt, gi=gi: owner(pt) == gi)))
            pan_title.append(gt or None)
        log['panels_vlm'] = [{'title': q['title'], 'poly': q['poly'].round(1).tolist()} for q in vl['panels']]
    else:
        log['panels_src'] = 'pieces'
        for (x, y, w, h) in panels_of(base['final'], ppm0):
            pad = int(1.0 * ppm0)
            pan.append((max(0, x - pad), max(0, y - pad), min(W_, x + w + pad), min(H_, y + h + pad), None,
                        (lambda pt, x=x, y=y, w=w, h=h: x <= pt[0] <= x + w and y <= pt[1] <= y + h)))
    log['panels_px'] = [p[:4] for p in pan]
    # 2) по каждой панели: свой масштаб (2 итерации), метрики
    out_panels = []
    for pi, (X0, Y0, X1, Y1, pm, inside) in enumerate(pan):
        groom = [dict(g, pt=[g['pt'][0] - X0, g['pt'][1] - Y0]) for g in gold['rooms'] if inside(g['pt'])]
        gopen = [dict(o, pt=[o['pt'][0] - X0, o['pt'][1] - Y0]) for o in gold.get('openings', [])
                 if X0 <= o['pt'][0] < X1 and Y0 <= o['pt'][1] < Y1 and (pm is None or pm[int(o['pt'][1]), int(o['pt'][0])])]
        vpts = [(px - X0, py - Y0) for px, py in vl['pts'] if inside((px, py))] if vl else []
        sub_img, sub_gray, sub_wall = img[Y0:Y1, X0:X1], gray[Y0:Y1, X0:X1], wall[Y0:Y1, X0:X1].copy()
        if pm is not None:
            sub_wall &= pm[Y0:Y1, X0:X1]
        if not sub_wall.any():
            continue
        sub_wall = np.pad(sub_wall, 2)[2:-2, 2:-2]   # граница кропа — свободна (наружа касается края)
        sub_wall[:2, :] = 0; sub_wall[-2:, :] = 0; sub_wall[:, :2] = 0; sub_wall[:, -2:] = 0
        ppm = ppm0
        fit = None
        # отдельные постройки внутри панели не сшивать; полоса-проём до OPEN_MAX_M — не промежуток (T-20261111-11, гараж bs30)
        sub_regions = plan_regions(sub_wall, t, fams, max_open=open_max(int(OPEN_MAX_M * ppm0)))
        for _ in range(2):
            r = analyze(sub_img, sub_gray, sub_wall, ppm, fams, t, sub_regions, cfg['thin'], cfg['glaze'])
            hit, obs = match_gold(r, groom, fams)
            fit = fc.fit_scale(obs)
            if fit:
                ppm = 1 / fit['s']
        r = analyze(sub_img, sub_gray, sub_wall, ppm, fams, t, sub_regions, cfg['thin'], cfg['glaze'])
        splits = []
        rep_log, rep_labels = [], []
        if vl and os.environ.get('FP_REPAIR', '1') != '0':
            # T-03: круг самопочинки — гипотезы с ценой и откатом вместо прямых слияний/разрезов
            labs = [repair.Label(q['name'], (q['pt'][0] - X0, q['pt'][1] - Y0), q['dims'], 'vlm', q.get('note'),
                                 q.get('area_m2'))
                    for q in vl['labels'] if inside(q['pt'])]
            labs += [repair.Label(q['name'], (q['pt'][0] - X0, q['pt'][1] - Y0), None, 'vlm-space')
                     for q in vl['spaces'] if inside(q['pt'])]
            r, rep_log, rep_labels = do_repair(r, labs, sub_img, sub_gray, cfg, ppm, fams, t)
        elif vpts:     # подписи VLM как опора: куски без подписи за ложной стеной — обратно в комнату с подписью
            r['lab'], r['final'], r['rooms'], splits = fc.merge_false_splits(
                r['lab'], r['rooms'], r['final'], r['wall'], r['add'], vpts, ppm)
            r['lab'], r['rooms'], lsplit = fc.split_by_labels(r['lab'], r['rooms'], vpts, ppm)
            r['label_splits'] = lsplit
            r['areas'] = np.bincount(r['lab'].ravel(), minlength=int(r['lab'].max()) + 1)
        # T-20261110-38: двери в полости — по комнатам ПОСЛЕ починки (до неё комнату дробят мелкие куски у закрытий, и «полостью»
        # оказывался кусок площадки: регресс QFfI3u… терял двери ванной и лестницы). Только лист застройщика (`dev_sheet`)
        if cfg.get('dev_sheet'):
            pocket_doors(r['gaps'], r['lab_g'], r['lab'], r['final'], r['outside'], r['areas'], POCKET_M2 * ppm * ppm,
                         POCKET_W_M * ppm)
        doorless = doorless_doors(r, ppm)              # T-11/3: комнате без дверей — лучшая дверь прежнего правила
        hit, obs = match_gold(r, groom, fams, core=True)
        fit = fc.fit_scale(obs)
        loo = fc.leave_one_out(obs)
        topo = topology(r, groom, hit, ppm)
        if os.environ.get('FP_STATE'):                 # отладка (T-16): состояние панели после починки
            Path(os.environ['FP_STATE']).mkdir(parents=True, exist_ok=True)
            np.savez_compressed(Path(os.environ['FP_STATE']) / f'st-{plan}-{pi}.npz', lab=r['lab'], final=r['final'],
                                wall=r['wall'], outside=r['outside'], rooms=np.array(r['rooms']), gray=sub_gray,
                                extra=np.array(topo['_extra_ids']), ppm=ppm)
        topo = name_extras(topo, rep_labels)
        dims = room_dims(groom, hit, obs, loo, ppm0)
        if gold.get('blind'):
            dims += unlabeled_dims(r, groom, hit, fams, ppm, fit)
        attach_flags(dims, groom, rep_labels, ppm, loo)
        flag_enclosed(dims, rep_log)
        gpx, t_ext = gia_px(r, t)
        # проёмы против ручного счёта
        op = None
        if gopen:
            rad = 0.75 * ppm
            used, hits = set(), 0
            tm = 0
            gaps_o = [g for g in r['gaps'] if g.kind != 'wall']     # зазубрины — стена, не проём (T-36)
            for o in gopen:
                best = None
                for g in gaps_o:
                    d = math.hypot(g.cx - o['pt'][0], g.cy - o['pt'][1])
                    if d <= rad and g.id not in used and (best is None or d < best[0]):
                        best = (d, g)
                if best:
                    used.add(best[1].id); hits += 1
                    tm += int(best[1].kind == o['type'])
            op = {'gold': len(gopen), 'found': hits, 'recall': hits / len(gopen), 'detected': len(gaps_o),
                  'precision': hits / max(1, len(gaps_o)), 'type_ok': tm}
        # углы стен > 1 м: выпрямленная грань против прямой МНК по исходным пикселям
        polys, edges = fc.mask_polygons(r['final'], fams, min_area=4)
        errs = [fc.angdiff(e['ang'], e['raw']) for e in edges if e['len'] >= ppm]
        diag = [e for e in edges if e['len'] >= ppm and all(fc.angdiff(e['raw'], b) > 6 for b in (0, 90))]
        diag_kept = [e for e in diag if fc.angdiff(e['ang'], e['raw']) <= 3]
        angles = {'n': len(errs), 'median': float(np.median(errs)) if errs else None,
                  'p95': float(np.percentile(errs, 95)) if errs else None,
                  'diag_edges': len(diag), 'diag_kept': len(diag_kept)}
        name = (pan_title[pi] if pi < len(pan_title) else None) or most_common([g['panel'] for g in groom]) or f'panel{pi}'
        P = {'panel': name, 'bbox_px': [X0, Y0, X1, Y1], 'ppm': ppm, 'fit': fit and {k: v for k, v in fit.items() if k != 'inliers'},
             'inliers': fit and fit['inliers'], 'loo': loo, 'loo_sum': fc.loo_summary(loo), 'loo_near': fc.loo_summary(loo, 'near'),
             'loo_clean': fc.loo_summary(loo, 'near_clean'), 'label_flags': [l['id'] for l in loo if l.get('flag_label')],
             'topology': topo, 'false_splits': [s for s in splits if s['false']], 'split_checks': len(splits),
             'label_splits': r.get('label_splits', []), 'repairs': rep_log, 'label_report': rep_labels,
             'absorbed': r.get('absorbed', []), 'doorless': doorless,
             'vlm_title': (pan_title[pi] if pi < len(pan_title) else
                           vl['panels'][pi]['title'] if vl and vl['panels'] and log.get('panels_src') == 'vlm' and pi < len(vl['panels']) else None),
             'gia_m2': gpx / ppm / ppm, 't_ext_px': t_ext, 'openings': op, 'angles': angles,
             'gold_panels': sorted({g['panel'] for g in groom}), 'dims': dims,
             'fams_panel': fc.panel_families(r['wall'], 2 * 1.5 * ppm), 'image': str(Path(inputs) / gold['image'])}
        out_panels.append(P)
        if arrows is not None:                          # T-13: стрелки панели — для проёмов (`arrow_doors`)
            r['arrows'], r['arrows_t'] = arrows[Y0:Y1, X0:X1], t
            r['arrows_thin'] = fc.thin_lines(sub_gray, r['wall'], cfg['thin'])     # дуги створок — ширина слитой двери (/3)
            r['arrows_dark'] = (sub_gray < cfg['mask'][1]).astype(np.uint8)       # тёмное листа — проём под дугой (/4)
        export_panel(outdir, plan, pi, P, r, sub_img, sub_wall, fams, groom, gopen)
    # площади против листа
    areas = []
    for a in gold.get('areas', []):
        if a['panel'] == '*':
            got = sum(p['gia_m2'] for p in out_panels)
        else:
            ps = [p for p in out_panels if p['panel'] == a['panel']]
            got = sum(p['gia_m2'] for p in ps) if ps else None
        areas.append({**a, 'got_m2': got, 'diff_rel': (got / a['m2'] - 1) if got else None})
    log['areas'] = areas
    log['panels'] = out_panels
    log['sec'] = round(time.time() - t0, 1)
    (Path(outdir) / f'metrics-{plan}.json').write_text(json.dumps(log, ensure_ascii=False, indent=1, default=float))
    return log


def dark_raw(img, gray, cfg):
    """Тёмное сырого листа по правилу плана, БЕЗ открытия/чистки (для проверки наложением — не та же маска)."""
    k = cfg['mask']
    if k[0] == 'blue':
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        return (hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 50)
    if cfg.get('thin_hi', 0) > k[1]:                 # лист тонких стен: тёмное с гистерезисом, как в маске
        return fc.hysteresis(gray, k[1], cfg['thin_hi']) > 0
    if (cfg.get('grey_info') or {}).get('used'):    # T-38: серые перегородки в маске — и в свидетельстве (иначе починка
        return gray < fc.GREY_HI                     # снимает их как «стену без тёмного под ней»)
    return gray < k[1]


def do_repair(r, labs, img, gray, cfg, ppm, fams, t):
    """Круг починки панели (repair.run): масштаб заморожен (ppm), манера подписи — по подписям VLM этой панели."""
    t_int = repair.inner_thickness(r['final'], r['wall'])
    ctx = repair.Ctx(gray=gray, ev=repair.evidence(dark_raw(img, gray, cfg), t_int), wp=repair.wall_prob(gray), ppm=ppm,
                     t_int=t_int, fams=fams, bay_in=r.get('bay_in'))
    st = repair.State(r['lab'].copy(), r['final'].copy(), list(r['rooms']), r['add'].copy())
    labs_all = labs
    labs, off = repair.on_sheet(labs, st.lab.shape)   # точка за краем листа панели — не в починку (в отчёт — как была)
    topo = repair.topology(st, labs, ppm)
    obs = []
    for i, l in enumerate(labs):
        rid = topo['own'][i]
        if l.dims and rid is not None and sum(1 for j in topo['by'][rid] if labs[j].dims) == 1:
            obs.append({'id': i, 'dims': l.dims, 'ext': repair.room_ext(st, rid, ctx)})
    f = fc.fit_scale(obs)
    if f:
        c, p, share = fc.convention(f)
        ctx.conv = (c, p)
    log0 = {'kind': 'start', 'labels': len([l for l in labs if l.dims]), 'spaces': len([l for l in labs if not l.dims]),
            't_int': round(t_int, 1), 'conv': list(ctx.conv), 'ppm': round(ppm, 2),
            'ppm_vlm': round(1 / f['s'], 2) if f else None, 'pix0_m': round(repair.pixel_cost(st, ctx), 1),
            'topo0': {k: v for k, v in topo.items() if k in ('cost', 'merged')} | {'missing': len(topo['missing']),
                                                                                   'unexplained': len(topo['unexplained'])}}
    # T-20261110-38: лист с подписями площадей — куски без подписи сперва в соседа по площади (`repair.absorb_by_area`)
    st_a, jr_area = repair.absorb_by_area(st, labs, ctx)
    removed_area = (st.final > 0) & ~(st_a.final > 0)
    st2, jr = repair.run(st_a, labs, ctx, r['outside'])
    jr = jr_area + jr
    # снятое кругом закрытие, по обе стороны которого теперь одна комната, — не проём («дверь» посреди коридора Этажей). Снятое
    # с границей min-cut (`st.cut`) между разными комнатами — остаётся проёмом. Только лист застройщика (`dev_sheet`, T-38/3)
    dev = bool(cfg.get('dev_sheet'))
    if dev:
        removed_area = removed_area | same_room_gaps(r['lab_g'], r['gaps'], (st_a.final > 0) & ~(st2.final > 0), st2.lab)
    absorbed, removed = [], (removed_area if removed_area.any() else None)
    if os.environ.get('FP_ABSORB', '1') != '0':
        # T-20261110-19: обрывки за нашими закрытиями — в соседа (`repair.absorb_fragments`); зазубрины и окна — стена, не разрез
        notch = np.isin(r['lab_g'], [g.id for g in r['gaps'] if g.kind in ('wall', 'window')])
        st3, jr_a, absorbed = repair.absorb_fragments(st2, labs, ctx, is_fragment, notch)
        jr += jr_a
        removed = ((st2.final > 0) & ~(st3.final > 0)) | (removed if removed is not None else False)
        st2 = st3
    topo2 = repair.topology(st2, labs, ppm)
    jr.append({'kind': 'end', 'pix_m': round(repair.pixel_cost(st2, ctx), 1), 'topo': topo2['cost'],
               'missing': len(topo2['missing']), 'merged': topo2['merged'], 'unexplained': len(topo2['unexplained'])})
    new_wall = (st2.final > 0) & ~(st2.add > 0) & ~(r['final'] > 0)
    r = dict(r)
    r['wall'] = ((r['wall'] > 0) | new_wall).astype(np.uint8)
    r['add_extra'] = ((st2.add > 0) & ~(r['add'] > 0)).astype(np.uint8)
    r['drawn'] = st2.drawn
    r['cut'] = st2.cut
    # комнаты локального пересчёта лежали «снаружи» (открытая постройка) — теперь внутри: пол, площадь, проёмы
    new_ids = [rid for rid in st2.rooms if rid not in set(r['rooms'])]
    if new_ids and r.get('outside') is not None:
        k = max(3, int(2 * t_int + 1)) | 1
        newm = cv2.dilate(np.isin(st2.lab, new_ids).astype(np.uint8), np.ones((k, k), np.uint8)) > 0
        r['outside'] = (r['outside'] > 0) & ~newm
    r['lab'], r['final'], r['rooms'] = st2.lab, st2.final, st2.rooms
    r['areas'] =np.bincount(r['lab'].ravel(), minlength=int(r['lab'].max()) + 1)
    if removed is not None and removed.any():
        r['add'] = ((r['add'] > 0) & ~removed).astype(np.uint8)
        r['lab_g'], r['gaps'] = shrink_gaps(r['lab_g'], r['gaps'], removed, STUB_M * ppm if dev else 0.0)
    r['absorbed'] = absorbed
    return r, [log0] + off + jr, repair.label_report(st2, labs_all, ctx)


STUB_M = 0.22      # T-20261110-38: остаток снятого закрытия короче — огрызок у стены, не проём (двери 5–7 см на туре Этажей)


def same_room_gaps(lab_g, gaps, run_removed, lab) -> np.ndarray:
    """T-20261110-38: пиксели дверей, чьё закрытие снял круг починки (`run_removed`) и у которых по обе стороны (кольцо 2 px)
    теперь одна комната `lab` → маска для `shrink_gaps`. Двери без снятых пикселей не смотрим."""
    out = np.zeros(lab_g.shape, bool)
    if not run_removed.any():
        return out
    k = np.ones((3, 3), np.uint8)
    for g in gaps:
        if g.kind != 'door' or g.exterior:
            continue
        gm = lab_g == g.id
        if not (gm & run_removed).any():
            continue
        ring = (cv2.dilate(gm.astype(np.uint8), k, iterations=2) > 0) & ~gm
        sides = [int(i) for i in np.unique(lab[ring]) if i > 0]
        if len(sides) == 1:
            out |= gm
    return out


def shrink_gaps(lab_g, gaps, removed, stub_px: float = 0.0):
    """Снятые закрытия (T-19, обрывок влит в соседа) — из проёмов: проём целиком снят — его нет, частично — геометрия по
    оставшимся пикселям (как `fc.gap_components`); остаток короче `stub_px` — не проём (пиксели остаются стеной).
    Остальные проёмы — как были."""
    gone = removed & (lab_g > 0)
    ids = set(int(i) for i in np.unique(lab_g[gone]))
    if not ids:
        return lab_g, gaps
    lab_g = lab_g.copy()
    lab_g[gone] = 0
    out = []
    for g in gaps:
        if g.id not in ids:
            out.append(g)
            continue
        ys, xs = np.nonzero(lab_g == g.id)
        if len(xs) < 3:
            lab_g[lab_g == g.id] = 0
            continue
        (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        if max(w, h) + 1 < stub_px:
            lab_g[lab_g == g.id] = 0
            continue
        out.append(dataclasses.replace(g, cx=float(cx), cy=float(cy), length=float(max(w, h) + 1), depth=float(min(w, h) + 1),
                                       bbox=(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1),
                                             int(ys.max() - ys.min() + 1))))
    return lab_g, out


MISMATCH_FLAGS = ('не сошлось', 'замер ≠ подписи')


def attach_flags(dims, groom, rep_labels, ppm, loo=None):
    """Флаг системы (по подписи, прочитанной VLM, и её комнате) — к строке золота: ближайшая подпись VLM ≤ 1,5 м.
    «Не сошлось» по манере панели, а другая мерка той же комнаты (ядро без ниши/камина, рамка) при масштабе ОСТАЛЬНЫХ комнат
    (`loo` → `near_*`) даёт подпись в норме по обеим сторонам — подпись про эту комнату, агентство мерило иначе: уровень 1
    «ниша/манера?», не 2 (T-20261110-12: Principal Bedroom 4.21 — без ниши у французского окна, Bedroom 4.70 — без камина)."""
    near = {l['id']: l for l in loo or [] if l.get('ok')}
    for row in dims:
        if row.get('status') == 'мерка без подписи':      # флаг уже свой (T-04)
            continue
        g = next((x for x in groom if x['name'] == row['id']), None)
        if g is None:
            continue
        best = None
        for q in rep_labels:
            if q.get('space'):
                continue
            d = math.hypot(q['pt'][0] - g['pt'][0], q['pt'][1] - g['pt'][1])
            if d <= 1.5 * ppm and (best is None or d < best[0]):
                best = (d, q)
        if best is None:
            row['flag'], row['flag_level'] = 'нет подписи VLM', 2
        else:
            row['flag'], row['flag_level'] = best[1].get('flag', ''), best[1].get('level', 0)
            # итоговый замер против чисел подписи, прочитанных VLM (не золота; порядок сторон не важен): замер мог
            # выбрать другую манеру (ниша, эркер), чем сверка стен, — тогда тоже флаг
            vd = best[1].get('dims')
            if vd and 'ours' in row:
                oa, ob = row['ours']
                e = min(max(abs(oa - vd[0]), abs(ob - vd[1])), max(abs(oa - vd[1]), abs(ob - vd[0])))
                lvl = 2 if e > repair.bad_tol(vd) else 1 if e > repair.norm_tol(vd) else 0
                if lvl > row['flag_level']:
                    row['flag'], row['flag_level'] = ('замер ≠ подписи' if lvl == 2 else 'ниша/манера?'), lvl
        n = near.get(row['id'])
        if row.get('flag_level') == 2 and row.get('flag') in MISMATCH_FLAGS and n and n.get('near_err') \
                and max(n['near_err']) <= repair.norm_tol(row['gold']):
            row['flag'], row['flag_level'] = f"ниша/манера? ({n['near_cand']})", 1


def flag_enclosed(dims, rep_log):
    """Комната, замкнутая гипотезой enclose (T-16), — часть её границы проведена не по стене (линия, край заливки,
    продолжение стены): мерка поперёк такой стороны — догадка; без своего флага — флаг 1 «открытая: граница проведена»."""
    opened = {e.get('label') for e in rep_log or [] if e.get('kind') == 'enclose' and e.get('applied')}
    for row in dims:
        if row.get('id') in opened and not row.get('flag_level'):
            row['flag'], row['flag_level'] = 'открытая: граница проведена', 1


def most_common(xs):
    from collections import Counter
    return Counter(xs).most_common(1)[0][0] if xs else None


def poly_m(poly, ppm, off):
    return [[round((float(p[0]) + off[0]) / ppm, 4), round((float(p[1]) + off[1]) / ppm, 4)] for p in poly]


def room_families_map(r, fp, ppm, t_w):
    """Семейства углов по комнате (T-16, `fc.room_families`): у комнаты с длинным прямым ребром не из семейств панели —
    свои; грань стены берёт семейства ближайшей комнаты (≤ 2t+3 px). FP_ROOMFAM=0 — как до T-16 (одно на панель).
    → (комната → семейства, fams_at(участок контура), fams_of(_, p, q) для метрики стен)."""
    if os.environ.get('FP_ROOMFAM', '1') == '0':
        return {}, None, None
    lab = r['lab']
    room_fams = {}
    for rid in r['rooms']:
        ys, xs = np.nonzero(lab == rid)
        if not len(ys):
            continue
        y0, y1, x0, x1 = max(0, ys.min() - 2), ys.max() + 3, max(0, xs.min() - 2), xs.max() + 3
        rf = fc.room_families(lab[y0:y1, x0:x1] == rid, fp, fc.ROOM_FAM_MIN_M * ppm)
        if len(rf) > len(fp):
            room_fams[int(rid)] = rf
    if not room_fams:
        return {}, None, None
    from scipy import ndimage
    R = np.isin(lab, list(room_fams))
    dist, (iy, ix) = ndimage.distance_transform_edt(~R, return_indices=True)
    near = lab[iy, ix].copy()
    near[dist > 2 * t_w + 3] = 0
    H, W = lab.shape

    def at_pts(xs, ys):
        v = near[np.clip(np.round(ys).astype(int), 0, H - 1), np.clip(np.round(xs).astype(int), 0, W - 1)]
        if not v.size:
            return None
        ids, cnt = np.unique(v, return_counts=True)
        k = int(ids[int(np.argmax(cnt))])
        if k == 0 or cnt.max() < 0.5 * v.size:
            return None
        return room_fams.get(k)

    def fams_at(span):
        span = np.asarray(span, float).reshape(-1, 2)
        return at_pts(span[:, 0], span[:, 1])

    def fams_of(_k, p, q):
        t = np.linspace(0.0, 1.0, 9)
        return at_pts(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
    return room_fams, fams_at, fams_of


def split_by_drawn(g, lab_g, drawn):
    """Дверной проём, через который прошла дорисованная перегородка (T-38: общий проём двух слитых спален), — два
    проёма по обе стороны стены. → [(cx, cy, длина px)]; не задет — один исходный."""
    one = [(g.cx, g.cy, g.length)]
    if g.kind != 'door' or drawn is None or not drawn.any():
        return one
    m = lab_g == g.id
    dd = cv2.dilate(drawn.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if not (m & dd).any():
        return one
    n, cl = cv2.connectedComponents((m & ~dd).astype(np.uint8), connectivity=8)
    out = []
    for j in range(1, n):
        ys, xs = np.nonzero(cl == j)
        if len(ys) >= 3:
            c, _, _, L, _ = fc.gap_axes(ys, xs)
            out.append((float(c[0]), float(c[1]), L))
    return out if len(out) >= 2 else one


FLOOR_INTRUDE_M = 0.15   # заход пола комнаты в пол соседа глубже этого — сквозь тонкую перегородку (T-20261110-33/2)


def floor_depth(lab, rooms):
    """Глубина каждого пикселя пола комнаты — расстояние (px) до ближайшего пикселя не её пола (стена, закрытие, другая комната)."""
    dep = np.zeros(lab.shape, np.float32)
    for k in rooms:
        m = lab == k
        dep[m] = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)[m]
    return dep


def room_floor_mask(lab, outside, rooms_m, rid, t_w, depth=None, tol_px=0.0):
    """Пол комнаты для модели: её область, расширенная под всю толщину стены `t_w` (без щели у стен), без «снаружи» и без
    ГЛУБОКОГО ЗАХОДА В ПОЛ ДРУГИХ КОМНАТ (`rooms_m` — маска всех комнат панели, `depth` — `floor_depth`). T-20261110-33/2: толщина
    стен одна на лист, и на листе с толстыми наружными и тонкими перегородками (aRQVC9: 34 px и 8–10 px) пол спальни проходил
    перегородку и вставал на ~25 px в пол соседа — контуры налезали, двери площадки ложились в допуск «наш проём» спальни
    (`trial_room.openings_of`), и ядро резало их у угла (`opening_cut_by_core`). Заход — связный кусок чужого пола под расширением:
    глубже `tol_px` где-либо — снимается целиком (перегородка тоньше стены листа), мельче — остаётся как был: ниши проёмов и углы
    стыков у листов с одной толщиной стен (8–11 см у примера /try) — иначе на контуре зубцы, и ядро спальни ломается."""
    kf = max(3, int(2 * t_w + 1)) | 1
    own = lab == rid
    fm = cv2.dilate(own.astype(np.uint8), np.ones((kf, kf), np.uint8)) & (~outside).astype(np.uint8)
    intr = (fm > 0) & rooms_m & ~own
    if intr.any():
        if depth is None:
            fm[intr] = 0
            return fm
        n, cl = cv2.connectedComponents(intr.astype(np.uint8), connectivity=8)
        deep = np.zeros(n, bool)
        np.logical_or.at(deep, cl[intr], depth[intr] > tol_px)
        fm[intr & deep[cl]] = 0
    return fm


def export_panel(outdir, plan, pi, P, r, img, wall, fams, groom, gopen):
    """Модель панели для рендера (метры) + наложение для глаз."""
    ppm = P['ppm']
    final, add, lab_g = r['final'], r['add'], r['lab_g']
    doors = np.zeros_like(add)
    wins = np.zeros_like(add)
    notch = np.zeros_like(add)
    a_drop, a_merged, a_used = arrow_doors(r['gaps'], lab_g, r.get('arrows'), r.get('arrows_t'), r['wall'], r.get('arrows_thin'),
                                           ppm, r.get('arrows_dark'), P.get('fams_panel') or fams)
    a_cut = np.zeros_like(add)                         # /3: стрелка внутри слитой двери — проём, не столбик стены в 3D
    for *_, quad in a_merged:
        cv2.fillPoly(a_cut, [np.round(quad).astype(np.int32)], 1)
    if a_merged:
        a_cut &= (r['arrows'] > 0).astype(a_cut.dtype)
    for g in r['gaps']:
        if g.id in a_drop:                             # разрыв «стена ↔ стрелка» — не проём, перемычки над ним нет
            continue
        (wins if g.kind == 'window' else notch if g.kind == 'wall' else doors)[lab_g == g.id] = 1
    if r.get('add_extra') is not None:                 # закрытия локального пересчёта (T-03) — как двери
        doors |= r['add_extra']
    doors &= (final > 0)
    wins &= (final > 0)
    solid = (((r['wall'] > 0) | (notch > 0)) & (final > 0)).astype(np.uint8)    # зазубрина/узкий просвет — стена
    if r.get('drawn') is not None:                    # разрез min-cut вдоль нарисованной линии — тонкая стена
        solid |= cv2.dilate(r['drawn'].astype(np.uint8), np.ones((2, 2), np.uint8))
    if r.get('arrows') is not None:                    # /3: стрелка — значок, не стена: в 3D ни столбика в проёме, ни на лестнице
        solid[r['arrows'] > 0] = 0                     # (разбор комнат её по-прежнему видит стеной; пол под ней есть)
    if a_cut.any():                                    # стрелка в проёме: снизу пусто, сверху перемычка, как у двери
        doors[a_cut > 0] = 1
    # стена монолитом на всю высоту; под окном — подоконная часть, над окном и дверью — перемычка (без горизонтальных швов)
    bands = [(0.0, H_WALL, solid), (0.0, SILL, wins & (solid == 0)), (HEAD, H_WALL, (wins | doors) & (solid == 0))]
    off = (0, 0)
    model = {'plan': plan, 'panel': P['panel'], 'ppm': ppm, 'bbox_px': P['bbox_px'], 'bands': [], 'floors': [],
             'openings': [], 'rooms': [], 'image': P.get('image')}
    # T-04: выпрямление — рёбра к семействам углов ПАНЕЛИ, ступени под прямым углом; грани пола — на грани стен.
    # Метрика косых — на тех же масках прежним способом (до) и новым (после).
    fp = P.get('fams_panel') or fams
    straight = os.environ.get('FP_STRAIGHT', '1') != '0'
    min_len = 0.3 * ppm
    st0 = dict(fc.STRAIGHT_STATS)
    t_w = fc.stroke_thickness(r['wall'])
    room_fams, fams_at, wall_fams_of = room_families_map(r, fp, ppm, t_w) if straight else ({}, None, None)
    old_w, new_w = [], []
    for bi, (z0, z1, m) in enumerate(bands):
        polys0, _ = fc.mask_polygons(m, fams, min_area=3)
        if not straight:
            polys = polys0
        elif bi == 0:
            polys = fc.mask_polygons(m, fp, min_area=3, straight=True, short_px=ppm, min_free=0.4 * ppm,
                                     fams_at=fams_at)[0]
        else:                                          # подоконник/перемычка — прямоугольник по семейству
            polys = fc.rect_polygons(m, fp, min_area=3, fams_at=fams_at)
        old_w += polys0; new_w += polys
        model['bands'].append({'z0': z0, 'z1': z1, 'polys': [{'outer': poly_m(o, ppm, off),
                                                             'holes': [poly_m(h, ppm, off) for h in hs]} for o, hs in polys]})
    ref = (fc.polygon_lines(fc.mask_polygons(final, fp, min_area=3, straight=True, short_px=ppm, min_free=0.4 * ppm,
                                             fams_at=fams_at)[0], fp) if straight else None)
    old_f, new_f = [], []
    fl_fams0, fl_fams = [], []
    rooms_m = np.isin(r['lab'], list(r['rooms']))
    depth = floor_depth(r['lab'], r['rooms'])
    for rid in r['rooms']:
        fm = room_floor_mask(r['lab'], r['outside'], rooms_m, rid, t_w, depth, FLOOR_INTRUDE_M * ppm)
        polys0, _ = fc.mask_polygons(fm, fams, min_area=10)
        rf = room_fams.get(rid)
        polys = (fc.mask_polygons(fm, fp, min_area=10, straight=True, ref=ref, ref_d=t_w + 1.5, short_px=ppm,
                                  min_free=0.4 * ppm, fams_at=(lambda span, rf=rf: rf) if rf else None)[0]
                 if straight else polys0)
        old_f += polys0; new_f += polys
        fl_fams0 += [rf or fp] * len(polys0); fl_fams += [rf or fp] * len(polys)
        if os.environ.get('FP_DUMP'):                  # отладка выпрямления: маски полов панели
            Path(os.environ['FP_DUMP']).mkdir(parents=True, exist_ok=True)
            np.save(Path(os.environ['FP_DUMP']) / f'floor-{plan}-{pi}-{rid}.npy', fm)
            np.save(Path(os.environ['FP_DUMP']) / f'final-{plan}-{pi}.npy', final)
            for bi, (_, _, bm) in enumerate(bands):
                np.save(Path(os.environ['FP_DUMP']) / f'band{bi}-{plan}-{pi}.npy', bm)
        names = [g['name'] for g in groom if g.get('_room') == rid]
        for o, hs in polys:
            model['floors'].append({'outer': poly_m(o, ppm, off), 'holes': [poly_m(h, ppm, off) for h in hs], 'room': rid})
        model['rooms'].append({'id': int(rid), 'names': names, 'area_m2': round(float(r['areas'][rid]) / ppm / ppm, 2)})
    # метрика косых: ребро — против семейств своей комнаты (T-16; у комнат без своих — семейства панели)
    P['skew'] = {'fams_panel': [round(f, 1) for f in fp],
                 'fams_rooms': {int(k): [round(f, 1) for f in v[len(fp):]] for k, v in room_fams.items()},
                 'floors_before': fc.skew_stats(old_f, fp, min_len, fams_of=lambda k, p, q: fl_fams0[k]),
                 'floors_after': fc.skew_stats(new_f, fp, min_len, fams_of=lambda k, p, q: fl_fams[k]),
                 'walls_before': fc.skew_stats(old_w, fp, min_len, fams_of=wall_fams_of),
                 'walls_after': fc.skew_stats(new_w, fp, min_len, fams_of=wall_fams_of),
                 'straight': {k: fc.STRAIGHT_STATS[k] - st0[k] for k in st0}}
    model['skew'] = P['skew']
    for cx, cy, L, ext, _ in a_merged:                 # T-13: проём, разделённый стрелкой, — один
        model['openings'].append({'kind': 'door', 'c': [round(cx / ppm, 3), round(cy / ppm, 3)], 'width_m': round(L / ppm, 3),
                                  'glaze': 0.0, 'exterior': ext})
    for g in r['gaps']:
        if g.kind == 'wall' or g.id in a_drop or g.id in a_used:
            continue
        for cx, cy, L in split_by_drawn(g, lab_g, r.get('drawn')):
            model['openings'].append({'kind': g.kind, 'c': [round(cx / ppm, 3), round(cy / ppm, 3)],
                                      'width_m': round(L / ppm, 3), 'glaze': round(g.glaze, 2), 'exterior': g.exterior})
    Path(outdir).mkdir(parents=True, exist_ok=True)
    (Path(outdir) / f'model-{plan}-{pi}.json').write_text(json.dumps(model, ensure_ascii=False))
    # наложение
    ov = (img.astype(float) * 0.35 + 255 * 0.65).astype(np.uint8)
    rng = np.random.default_rng(7)
    for rid in r['rooms']:
        col = rng.integers(120, 240, 3)
        ov[r['lab'] == rid] = (ov[r['lab'] == rid] * 0.4 + col * 0.6).astype(np.uint8)
    ov[solid > 0] = (60, 60, 60)
    ov[doors > 0] = (0, 170, 0)
    ov[wins > 0] = (230, 160, 0)
    if r.get('cut') is not None:                       # границы min-cut (T-03): пурпур
        ov[r['cut']] = (200, 0, 200)
    for g in groom:
        x, y = map(int, g['pt'])
        ok = g.get('_room') is not None
        cv2.circle(ov, (x, y), 5, (0, 0, 255) if not ok else (0, 120, 255), -1)
    for o in gopen:
        x, y = map(int, o['pt'])
        cv2.drawMarker(ov, (x, y), (255, 0, 255), cv2.MARKER_CROSS, 10, 2)
    cv2.imwrite(str(Path(outdir) / f'overlay-{plan}-{pi}.png'), ov)


DARK_THR = 125
BLUE_VS_DARK = 0.75     # синие штрихи — стены, только если не тоньше 0,75 толщины тёмных (T-20261110-08)


def auto_cfg(img) -> dict:
    """Маска стен для нового листа без настройки (T-04, слепые планы): синие стены — если синего (тон 95–135,
    насыщенность ≥ 100) ≥ 1 % листа, это штрихи, а не заливка, и они не тоньше тёмных (≥ BLUE_VS_DARK толщины тёмных:
    A — синие 12 px против текста 6; наш /try — синие обводки комнат и окна 4 px при тёмно-серых стенах 12 px — не стены);
    иначе тёмное: порог 125 (между C 110 и B 135 — водяной знак светлее), открытие 3 px; толстые стены (медиана ≥ 12 px
    после открытия 3: B 22, C 8) — открытие 5 (меньше текста)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 50)
    thr = int(os.environ.get('FP_DARK_THR', DARK_THR))
    m3 = fc.wall_mask_dark(img, thr, 3, 60)
    t3 = fc.stroke_thickness(m3)
    if blue.mean() >= 0.01:
        tb = fc.stroke_thickness(blue.astype(np.uint8))
        if 2.5 <= tb <= 25 and tb >= BLUE_VS_DARK * t3:
            return {'mask': ('blue',), 'min_area': 40, 'thin': 15, 'glaze': 215, 'auto': 'blue'}
    if t3 >= 12:
        return {'mask': ('dark', thr, 5), 'min_area': 120, 'thin': 15, 'glaze': 200, 'auto': f'dark t3={t3:.1f}'}
    return {'mask': ('dark', thr, 3), 'min_area': 60, 'thin': 15, 'glaze': 200, 'auto': f'dark t3={t3:.1f}'}


def blind_gold(plan, image, vdir, listing_path=None) -> dict:
    """Слепой план (T-04): «золото» стенда из подписей VLM (имя, точка, размер, если напечатан) + текст объявления
    (`listing.match`: размер из текста — по имени, флаг при расхождении/повторе/отсутствии). Имена делаются
    уникальными (#2, #3 — у одинаковых), панель подписи — контур VLM, в котором точка (как в run_plan)."""
    import listing
    img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    vl = load_vlm(plan, vdir, img.shape)
    labs = [dict(q) for q in vl['labels']]
    rows, orphans = [], []
    if listing_path and Path(listing_path).exists():
        rows = listing.parse_listing(Path(listing_path).read_text(errors='replace'))
    labs, orphans = listing.match(labs, rows)
    polys = [np.ascontiguousarray(q['poly'].reshape(-1, 1, 2), np.float32) for q in vl['panels']]
    titles = [str(q.get('title') or f'panel{i}') for i, q in enumerate(vl['panels'])]
    seen = {}
    for t in list(titles):                                   # одинаковые заголовки панелей — различать
        seen[t] = seen.get(t, 0) + 1
    cnt = {}
    for i, t in enumerate(titles):
        if seen[t] > 1:
            cnt[t] = cnt.get(t, 0) + 1
            titles[i] = f'{t} {cnt[t]}'
    from collections import Counter
    nn = Counter(q['name'] for q in labs)
    k = Counter()
    rooms = []
    for q in labs:
        k[q['name']] += 1
        name = q['name'] if nn[q['name']] == 1 else f'{q["name"]} #{k[q["name"]]}'
        pan = (titles[int(np.argmax([cv2.pointPolygonTest(pp, (float(q['pt'][0]), float(q['pt'][1])), True)
                                     for pp in polys]))] if polys else 'sheet')
        g = {'name': name, 'name0': q['name'], 'panel': pan, 'pt': [int(round(q['pt'][0])), int(round(q['pt'][1]))],
             'dims_src': q.get('dims_src'), 'text_flags': q.get('text_flags', []), 'unsure': q.get('unsure', False),
             'note': q.get('note')}
        if q.get('text_name'):                               # T-20261110-33: строка текста — имя для неясной подписи листа
            g['text_name'], g['text_match'] = q['text_name'], q.get('text_match')
        for f in ('vtype', 'vtype_src', 'area_m2', 'area_reduced_m2', 'name_src'):   # T-20261110-38: labels4
            if q.get(f) is not None:
                g[f] = q[f]
        if q.get('dims'):
            g['dims_m'] = [float(q['dims'][0]), float(q['dims'][1])]
        rooms.append(g)
        q['name'] = name
    return {'image': str(Path(image).resolve()), 'rooms': rooms, 'openings': [], 'areas': [], '_labels': labs,
            'listing_rows': len(rows), 'listing_orphans': orphans, 'blind': True}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('plan')
    ap.add_argument('out')
    ap.add_argument('--inputs', default='/home/pakar/remlab-logs/floorplan-bench/inputs')
    ap.add_argument('--blind', help='картинка слепого плана (без золота): подписи — VLM (FP_VLM, FP_LABELS), маска — auto_cfg')
    ap.add_argument('--listing', help='текст объявления (по умолчанию <картинка без расширения>-listing.txt, если есть)')
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    if a.blind:
        img_p = Path(a.blind)
        lst = a.listing or str(img_p.with_name(img_p.stem + '-listing.txt'))
        G = blind_gold(a.plan, img_p, os.environ['FP_VLM'], lst)
        C = auto_cfg(cv2.imread(str(img_p), cv2.IMREAD_COLOR))
        (Path(a.out) / f'gold-{a.plan}.json').write_text(json.dumps({k: v for k, v in G.items() if k != '_labels'},
                                                                    ensure_ascii=False, indent=1, default=float))
        print('blind', a.plan, 'labels', len(G['rooms']), 'with dims', sum(1 for g in G['rooms'] if 'dims_m' in g),
              'listing rows', G['listing_rows'], 'orphans', len(G['listing_orphans']), 'cfg', C)
        L = run_plan(a.plan, str(img_p.parent), a.out, gold=G, cfg=C)
    else:
        L = run_plan(a.plan, a.inputs, a.out)
    print(json.dumps({'plan': L['plan'], 't': L['thickness_px'], 'fams': L['families_deg'], 'sweep': L['sweep'][:3],
                      'areas': L['areas'], 'sec': L['sec']}, ensure_ascii=False, default=float))
    for p in L['panels']:
        print(p['panel'], 'near', {k: round(v, 3) for k, v in p['loo_near'].items()}, 'clean',
              {k: round(v, 3) for k, v in p['loo_clean'].items()}, 'flags', p['label_flags'])
        print(p['panel'], 'ppm', round(p['ppm'], 2), 'loo', {k: round(v, 3) if isinstance(v, float) else v for k, v in p['loo_sum'].items()},
              'topo', p['topology'], 'gia', round(p['gia_m2'], 1), 'open', p['openings'],
              'ang', {k: (round(v, 2) if isinstance(v, float) else v) for k, v in p['angles'].items()},
              'fit', p['fit'] and {k: round(v, 4) if isinstance(v, float) else v for k, v in p['fit'].items()})
        for l in p['loo']:
            print('   ', l)
