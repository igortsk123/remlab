#!/usr/bin/env python3
"""Стенд OpenCV-пути (T-20261109-02): картинка планировки → панели → стены/проёмы/комнаты → масштаб по подписям →
метрики против золота `gold/<план>.json` → модель для 3D (`model-<план>.json`) и наложения для глаз.

  python tools/floorplan/bench.py <A|B|C> <папка-вывода> [--inputs /home/pakar/remlab-logs/floorplan-bench/inputs]
"""
from __future__ import annotations

import argparse
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
BAY_RECT = 0.85     # эркер — почти прямоугольник по заполнению minAreaRect
ENV_DMAX = float(os.environ.get('FP_ENV_DMAX', '3.0'))   # наибольшая глубина закрытия контура, в толщинах стены (2,5 → 3: C, окно в ступени стены)
FAINT_GRAY = 230  # бледная линия рамы окна (на белом 255 / заливке ~244)
HULL_M = float(os.environ.get('FP_HULL_M', '4.0'))   # грубый контур постройки для снятия перемычек между постройками, м
PANEL_R_M = float(os.environ.get('FP_PANEL_R_M', '2.5'))   # запас контура панели VLM, м (до соседнего контура)
LB_M = float(os.environ.get('FP_LB_M', '6.0'))   # наибольший закрываемый наружный разрыв, м (длиннее 3,6 м — только по раме)


def load_vlm(plan, vdir, shape):
    """Ответы VLM flash (как в продукте): точки подписей и контуры панелей, сетка 0–1000 → px листа."""
    import vlm
    H, W = shape[:2]
    kx, ky = W / 1000.0, H / 1000.0
    out = {'pts': [], 'panels': [], 'labels': [], 'spaces': []}
    p = Path(vdir) / f'raw-{plan}-{os.environ.get("FP_LABELS", "labels")}.txt'   # T-04: слепые — labels2
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        out['pts'] = [(r['pt'][0] * kx, r['pt'][1] * ky) for r in d.get('rooms', []) if r.get('pt')]
        for r in d.get('rooms', []):
            if not r.get('pt'):
                continue
            dm = r.get('dims_m')
            ok = isinstance(dm, list) and len(dm) == 2 and all(isinstance(v, (int, float)) and 0.5 <= v <= 30 for v in dm)
            out['labels'].append({'name': ' '.join(str(r.get('name', '')).split()), 'pt': (r['pt'][0] * kx, r['pt'][1] * ky),
                                  'dims': tuple(float(v) for v in dm) if ok else None,
                                  'unsure': bool(r.get('unsure')), 'note': r.get('note')})
    # T-03: помещения без размеров (имя от VLM) — второй ответ, отдельная папка (FP_VLM2)
    p2 = Path(os.environ.get('FP_VLM2', vdir)) / f'raw-{plan}-unlabeled.txt'
    if p2.exists():
        d = vlm.parse(p2.read_text()) or {}
        out['spaces'] = [{'name': str(s.get('name', '')), 'pt': (s['pt'][0] * kx, s['pt'][1] * ky), 'dims': None}
                         for s in d.get('spaces', []) if s.get('pt')]
    p = Path(vdir) / f'raw-{plan}-panels.txt'
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        for q in d.get('panels', []):
            poly = np.array([[x * kx, y * ky] for x, y in q.get('poly', [])], np.float32)
            if len(poly) >= 3:
                out['panels'].append({'title': q.get('title'), 'poly': poly})
    return out


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
    return m


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
                   glaze_thr)).encode())
    h.update(inspect.getsource(_analyze).encode() + inspect.getsource(bay_windows).encode())
    p = Path(cdir) / f'an-{h.hexdigest()[:20]}.pkl'
    if p.exists():
        return pickle.loads(p.read_bytes())
    r = _analyze(img, gray, wall, ppm, fams, t, regions, thin_thr, glaze_thr)
    Path(cdir).mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps(r))
    return r


def _analyze(img, gray, wall, ppm, fams, t, regions=None, thin_thr=210, glaze_thr=215):
    """Один проход при гипотезе масштаба ppm (px на метр): разрывы → комнаты → проёмы."""
    ang = rot_angles(fams)
    Ls, Lb, fl = int(1.7 * ppm), int(LB_M * ppm), max(3, int(round(1.5 * t)))   # Lb: окна/французские двери
    corner = fc.extend_corners(wall, int(0.6 * ppm), fl)
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
                        keep[ys2, xs2] = 1
                continue
            if win or g.glaze >= GLAZE_MIN or ev >= DOOR_EV:
                keep[ys, xs] = 1
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
                keep |= m.astype(np.uint8)
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
            keep[ys, xs] = 1
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
    lab_g, gaps = fc.gap_components(add, dark, outside)
    for g in gaps:
        if bay.any() and bay[lab_g == g.id].any():
            g.kind = 'window'
        elif not g.exterior:
            g.kind = 'door'
        elif g.glaze >= GLAZE_MIN:
            g.kind = 'window'
        else:                                        # наружный без рамы: дуга створки → дверь, иначе окно
            ys, xs = np.nonzero(lab_g == g.id)
            c, u, nrm, L, dpt = fc.gap_axes(ys, xs)
            g.kind = 'door' if fc.door_evidence(thin, c, u, nrm, L, dpt) >= DOOR_EV else 'window'
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
    t = fc.stroke_thickness(wall)
    fams = fc.angle_families(wall)
    regions = fc.xy_cut(wall, max(40, int(3 * t)))
    log = {'plan': plan, 'thickness_px': round(t, 2), 'families_deg': [round(f, 1) for f in fams], 'regions': regions}
    # 1) перебор гипотез масштаба по всему листу → лучшая по числу инлаеров подписей
    sweep = []
    hyps = [float(os.environ['FP_PPM'])] if os.environ.get('FP_PPM') else [18 * 1.2 ** k for k in range(12)]  # FP_PPM — отладка
    for ppm in hyps:
        r = analyze(img, gray, wall, ppm, fams, t, regions, cfg['thin'], cfg['glaze'])
        _, obs = match_gold(r, [dict(g) for g in gold['rooms']], fams)
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
    vdir = os.environ.get('FP_VLM')
    vl = load_vlm(plan, vdir, img.shape) if vdir else None
    if vl is not None and gold.get('_labels') is not None:     # слепой: подписи VLM с размерами из текста объявления
        vl['labels'] = [dict(q) for q in gold['_labels']]
        vl['pts'] = [q['pt'] for q in gold['_labels']]
    log['cfg'] = {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()}
    H_, W_ = wall.shape
    pan = []     # (X0, Y0, X1, Y1, маска панели или None, принадлежность точки)
    if vl and vl['panels']:
        # панели — контуры VLM (заголовок → здание): стены за контуром (+1 м) режутся; точка — в ближайший контур
        vpolys = [np.ascontiguousarray(q['poly'].reshape(-1, 1, 2), np.float32) for q in vl['panels']]

        def owner(pt):
            return int(np.argmax([cv2.pointPolygonTest(pp, (float(pt[0]), float(pt[1])), True) for pp in vpolys]))
        # контур VLM неточен (C: низ дома срезан на ~1.2 м → весь этаж утёк наружу), поэтому
        # пиксель отдаётся ближайшему контуру (знаковое расстояние), но не дальше PANEL_R_M от него
        sds = []
        for q in vl['panels']:
            fm = np.zeros((H_, W_), np.uint8)
            cv2.fillPoly(fm, [q['poly'].astype(np.int32)], 1)
            sds.append(cv2.distanceTransform(1 - fm, cv2.DIST_L2, 5) - cv2.distanceTransform(fm, cv2.DIST_L2, 5))
        sds = np.stack(sds)
        near = np.argmin(sds, axis=0)
        for qi, q in enumerate(vl['panels']):
            pm = ((near == qi) & (sds[qi] <= PANEL_R_M * ppm0)).astype(np.uint8)
            if not pm.any():
                continue
            ys_, xs_ = np.nonzero(pm)
            pan.append((int(xs_.min()), int(ys_.min()), int(xs_.max()) + 1, int(ys_.max()) + 1, pm,
                        (lambda pt, qi=qi: owner(pt) == qi)))
        log['panels_vlm'] = [{'title': q['title'], 'poly': q['poly'].round(1).tolist()} for q in vl['panels']]
    else:
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
        sub_regions = fc.xy_cut(sub_wall, max(40, int(3 * t)))      # отдельные постройки внутри панели не сшивать
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
            labs = [repair.Label(q['name'], (q['pt'][0] - X0, q['pt'][1] - Y0), q['dims'], 'vlm')
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
        attach_flags(dims, groom, rep_labels, ppm)
        flag_enclosed(dims, rep_log)
        gpx, t_ext = gia_px(r, t)
        # проёмы против ручного счёта
        op = None
        if gopen:
            rad = 0.75 * ppm
            used, hits = set(), 0
            tm = 0
            for o in gopen:
                best = None
                for g in r['gaps']:
                    d = math.hypot(g.cx - o['pt'][0], g.cy - o['pt'][1])
                    if d <= rad and g.id not in used and (best is None or d < best[0]):
                        best = (d, g)
                if best:
                    used.add(best[1].id); hits += 1
                    tm += int(best[1].kind == o['type'])
            op = {'gold': len(gopen), 'found': hits, 'recall': hits / len(gopen), 'detected': len(r['gaps']),
                  'precision': hits / max(1, len(r['gaps'])), 'type_ok': tm}
        # углы стен > 1 м: выпрямленная грань против прямой МНК по исходным пикселям
        polys, edges = fc.mask_polygons(r['final'], fams, min_area=4)
        errs = [fc.angdiff(e['ang'], e['raw']) for e in edges if e['len'] >= ppm]
        diag = [e for e in edges if e['len'] >= ppm and all(fc.angdiff(e['raw'], b) > 6 for b in (0, 90))]
        diag_kept = [e for e in diag if fc.angdiff(e['ang'], e['raw']) <= 3]
        angles = {'n': len(errs), 'median': float(np.median(errs)) if errs else None,
                  'p95': float(np.percentile(errs, 95)) if errs else None,
                  'diag_edges': len(diag), 'diag_kept': len(diag_kept)}
        name = most_common([g['panel'] for g in groom]) or f'panel{pi}'
        P = {'panel': name, 'bbox_px': [X0, Y0, X1, Y1], 'ppm': ppm, 'fit': fit and {k: v for k, v in fit.items() if k != 'inliers'},
             'inliers': fit and fit['inliers'], 'loo': loo, 'loo_sum': fc.loo_summary(loo), 'loo_near': fc.loo_summary(loo, 'near'),
             'loo_clean': fc.loo_summary(loo, 'near_clean'), 'label_flags': [l['id'] for l in loo if l.get('flag_label')],
             'topology': topo, 'false_splits': [s for s in splits if s['false']], 'split_checks': len(splits),
             'label_splits': r.get('label_splits', []), 'repairs': rep_log, 'label_report': rep_labels,
             'vlm_title': vl['panels'][pi]['title'] if vl and vl['panels'] else None,
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
    return gray < k[1]


def do_repair(r, labs, img, gray, cfg, ppm, fams, t):
    """Круг починки панели (repair.run): масштаб заморожен (ppm), манера подписи — по подписям VLM этой панели."""
    t_int = repair.inner_thickness(r['final'], r['wall'])
    ctx = repair.Ctx(gray=gray, ev=repair.evidence(dark_raw(img, gray, cfg), t_int), wp=repair.wall_prob(gray), ppm=ppm,
                     t_int=t_int, fams=fams, bay_in=r.get('bay_in'))
    st = repair.State(r['lab'].copy(), r['final'].copy(), list(r['rooms']), r['add'].copy())
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
    st2, jr = repair.run(st, labs, ctx, r['outside'])
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
    return r, [log0] + jr, repair.label_report(st2, labs, ctx)


def attach_flags(dims, groom, rep_labels, ppm):
    """Флаг системы (по подписи, прочитанной VLM, и её комнате) — к строке золота: ближайшая подпись VLM ≤ 1,5 м."""
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


def export_panel(outdir, plan, pi, P, r, img, wall, fams, groom, gopen):
    """Модель панели для рендера (метры) + наложение для глаз."""
    ppm = P['ppm']
    final, add, lab_g = r['final'], r['add'], r['lab_g']
    doors = np.zeros_like(add)
    wins = np.zeros_like(add)
    for g in r['gaps']:
        (wins if g.kind == 'window' else doors)[lab_g == g.id] = 1
    if r.get('add_extra') is not None:                 # закрытия локального пересчёта (T-03) — как двери
        doors |= r['add_extra']
    doors &= (final > 0)
    wins &= (final > 0)
    solid = ((r['wall'] > 0) & (final > 0)).astype(np.uint8)
    if r.get('drawn') is not None:                     # разрез min-cut вдоль нарисованной линии — тонкая стена
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
    for rid in r['rooms']:
        kf = max(3, int(2 * t_w + 1)) | 1   # пол заходит под всю толщину стены — без щели
        fm = cv2.dilate((r['lab'] == rid).astype(np.uint8), np.ones((kf, kf), np.uint8)) & (~r['outside']).astype(np.uint8)
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
        model['openings'].append({'kind': g.kind, 'c': [round(g.cx / ppm, 3), round(g.cy / ppm, 3)],
                                  'width_m': round(g.length / ppm, 3), 'glaze': round(g.glaze, 2), 'exterior': g.exterior})
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


def auto_cfg(img) -> dict:
    """Маска стен для нового листа без настройки (T-04, слепые планы): синие стены — если синего (тон 95–135,
    насыщенность ≥ 100) ≥ 1 % листа и это штрихи, а не заливка; иначе тёмное: порог 125 (между C 110 и B 135 —
    водяной знак светлее), открытие 3 px; толстые стены (медиана ≥ 12 px после открытия 3: B 22, C 8) — открытие 5 (меньше текста)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 50)
    if blue.mean() >= 0.01 and 2.5 <= fc.stroke_thickness(blue.astype(np.uint8)) <= 25:
        return {'mask': ('blue',), 'min_area': 40, 'thin': 15, 'glaze': 215, 'auto': 'blue'}
    thr = int(os.environ.get('FP_DARK_THR', DARK_THR))
    m3 = fc.wall_mask_dark(img, thr, 3, 60)
    t3 = fc.stroke_thickness(m3)
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
