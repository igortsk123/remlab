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
SPLIT_DEEP = os.environ.get('FP_SPLIT', '1') != '0'  # T-20261111-09: разрыв глубже ENV_DMAX·t — делить по закрытиям (0 — как до)
PS_TAIL = os.environ.get('FP_PS_TAIL', '1') != '0'   # T-20261111-09: малый разрыв без дуги — срезать хвост-клин и проверить снова


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
                   glaze_thr, ENV_GEO, SPLIT_DEEP, PS_TAIL)).encode())
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
    kid = np.zeros(wall.shape, np.int32)            # номер закрытия (T-20261111-09: делить сросшиеся углами, `fpcore.split_composite`)

    nkid = [0]

    def mark(ys, xs):
        nkid[0] += 1
        kid[ys, xs] = nkid[0]
        keep[ys, xs] = 1
    # малые разрывы: закрываем, только если есть след проёма — рама окна в толщине стены или дуга двери
    for p in ps_s:
        lab_s, gs = fc.gap_components(p, dark, out1)
        for g in gs:
            ys, xs = np.nonzero(lab_s == g.id)
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            win = g.glaze >= GLAZE_MIN and g.exterior and dpt <= 2.2 * t
            if dpt > 2.2 * t:
                continue
            ev = fc.door_evidence(thin, c, u, nrm, L, dpt)
            if dpt > max_depth and not win and ev < DOOR_EV:
                # каморка (шкаф, кладовка) залита перемычкой целиком — проём ищем только в её «устье» у соседа
                mm = fc.mouth_strip(lab_s == g.id, wall, t)
                if mm is not None:
                    ys2, xs2 = mm
                    c2, u2, n2, L2, d2 = fc.gap_axes(ys2, xs2)
                    if d2 <= max_depth and L2 >= 0.4 * ppm and fc.door_evidence(thin, c2, u2, n2, L2, d2) >= DOOR_EV:
                        mark(ys2, xs2)
                continue
            if win or g.glaze >= GLAZE_MIN or ev >= DOOR_EV:
                mark(ys, xs)
            elif PS_TAIL:
                # T-20261111-09: дверь в тонкой стене, чей кусок за проёмом тоньше куска над ним, — перемычка шла и вдоль тонкого
                # куска (щель у его грани), и дуга мерилась по «двери» 1,5 м (TGva…, кухня: 0,73 м двери + 0,77 м щели). Срезать
                # хвост-клин (`fpcore.wedge_tails`, как у классификации T-03) и проверить дугу у остатка
                tail = fc.wedge_tails(wall_drawn, ys, xs, ppm)
                if tail is not None and (~tail).sum() >= 3:
                    ys3, xs3 = ys[~tail], xs[~tail]
                    c3, u3, n3, L3, d3 = fc.gap_axes(ys3, xs3)
                    if d3 <= max_depth and fc.door_evidence(thin, c3, u3, n3, L3, d3) >= DOOR_EV:
                        mark(ys3, xs3)
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
            if fc.DOOR_MIN_M * ppm <= L <= Ls and fc.door_evidence(thin, c, u, nrm, L, dpt) >= DOOR_EV:
                mark(ys, xs)
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
            ev = max(fc.door_evidence(thin, c, u, nrm, L, dpt),
                     fc.door_evidence(thin, (q1 + q2) / 2, ut, np.array([-ut[1], ut[0]]), D, 0.0))
            if ev >= DOOR_EV:
                mark(ys, xs)
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
                    if fc.door_evidence(thin, c, u, nrm, L, dpt) >= DOOR_EV:
                        mark(ys, xs)
                        thin_keep[ys, xs] = 1
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
        lab_g, gaps = fc.split_composite(lab_g, gaps, kid, dark, outside, ENV_DMAX * t)
    tails = []                                     # хвосты-клинья, срезанные с дверей (T-20261111-03)
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
                if fc.door_evidence(thin, c, u, nrm, L, dpt) < DOOR_EV:
                    g.kind = 'wall'
        elif g.glaze >= GLAZE_MIN:
            # наружный с «рамой» — окно. Но створку рисуют и закрытой в линии стены: «рама» есть, а дуга «вогнутая» —
            # касается стены у торца, центр в комнате (наш пример /try, T-20261110-11: входы спальни 1 и санузла 2 были
            # окнами). Прежние рисунки дуги у рам окон ложно доходят до 1,0 (линии рамы, размерные снаружи — листы A, B, T),
            # поэтому здесь проверяется только этот рисунок
            g.kind = 'window'
            if GLAZED_ARC:
                ys, xs = np.nonzero(lab_g == g.id)
                c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
                if fc.door_evidence(thin, c, u, nrm, L, dpt, tangent_only=True) >= DOOR_EV_GLAZED:
                    g.kind = 'door'
        else:                                        # наружный без рамы: дуга створки → дверь, иначе окно
            ys, xs = np.nonzero(lab_g == g.id)
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            g.kind = 'door' if fc.door_evidence(thin, c, u, nrm, L, dpt) >= DOOR_EV else 'window'
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
            'lab_g': lab_g, 'gaps': gaps, 'ppm': ppm, 'bay_in': bay_in}


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
        if fc.door_evidence(thin, kc, ku, kn, kL, kd) >= DOOR_EV:   # проём с дугой створки (дверь) — не эркер
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


def plan_regions(wall, t, fams):
    """Отдельные планы листа/панели (`fpcore.xy_cut` по пустым полосам) — разрывы между ними не закрываются. Обломки стены,
    отрезанные окнами во всю толщину стены, — к ближайшему плану (`fpcore.merge_fragments`, T-20261111-09; FP_FRAG=0 — как до)."""
    regions = fc.xy_cut(wall, max(40, int(3 * t)))
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
    fams = fc.angle_families(wall)
    regions = plan_regions(wall, t, fams)
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
        sub_regions = plan_regions(sub_wall, t, fams)               # отдельные постройки внутри панели не сшивать
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
             'absorbed': r.get('absorbed', []),
             'vlm_title': (pan_title[pi] if pi < len(pan_title) else
                           vl['panels'][pi]['title'] if vl and vl['panels'] and log.get('panels_src') == 'vlm' and pi < len(vl['panels']) else None),
             'gia_m2': gpx / ppm / ppm, 't_ext_px': t_ext, 'openings': op, 'angles': angles,
             'gold_panels': sorted({g['panel'] for g in groom}), 'dims': dims,
             'fams_panel': fc.panel_families(r['wall'], 2 * 1.5 * ppm), 'image': str(Path(inputs) / gold['image'])}
        out_panels.append(P)
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
    for g in r['gaps']:
        (wins if g.kind == 'window' else notch if g.kind == 'wall' else doors)[lab_g == g.id] = 1
    if r.get('add_extra') is not None:                 # закрытия локального пересчёта (T-03) — как двери
        doors |= r['add_extra']
    doors &= (final > 0)
    wins &= (final > 0)
    solid = (((r['wall'] > 0) | (notch > 0)) & (final > 0)).astype(np.uint8)    # зазубрина/узкий просвет — стена
    if r.get('drawn') is not None:                    # разрез min-cut вдоль нарисованной линии — тонкая стена
        solid |= cv2.dilate(r['drawn'].astype(np.uint8), np.ones((2, 2), np.uint8))
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
    for g in r['gaps']:
        if g.kind == 'wall':
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
