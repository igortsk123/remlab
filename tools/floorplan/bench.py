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
    out = {'pts': [], 'panels': []}
    p = Path(vdir) / f'raw-{plan}-labels.txt'
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        out['pts'] = [(r['pt'][0] * kx, r['pt'][1] * ky) for r in d.get('rooms', []) if r.get('pt')]
    p = Path(vdir) / f'raw-{plan}-panels.txt'
    if p.exists():
        d = vlm.parse(p.read_text()) or {}
        for q in d.get('panels', []):
            poly = np.array([[x * kx, y * ky] for x, y in q.get('poly', [])], np.float32)
            if len(poly) >= 3:
                out['panels'].append({'title': q.get('title'), 'poly': poly})
    return out


def build_mask(img, cfg):
    k = cfg['mask']
    if k[0] == 'blue':
        return fc.wall_mask_blue(img, cfg['min_area'])
    return fc.wall_mask_dark(img, k[1], k[2], cfg['min_area'])


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
        m = (lab == rid) & ~res.get('bay_in', np.zeros(lab.shape, bool))   # подпись агентства — без эркера
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
            'open_plan': open_plan, 'extra_rooms': len(extra), 'extra_areas_m2': [round(res['areas'][r] / ppm / ppm, 2) for r in extra]}


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


def run_plan(plan, inputs, outdir):
    t0 = time.time()
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    img = cv2.imread(str(Path(inputs) / gold['image']), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cfg = CFG[plan]
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
    sweep.sort(key=lambda x: (-x['inl'], x['cons']))
    log['sweep'] = [{k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()} for s in sweep[:6]]
    ppm0 = sweep[0]['est']
    base = analyze(img, gray, wall, ppm0, fams, t, regions, cfg['thin'], cfg['glaze'])
    vdir = os.environ.get('FP_VLM')
    vl = load_vlm(plan, vdir, img.shape) if vdir else None
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
        if vpts:     # подписи VLM как опора: куски без подписи за ложной стеной — обратно в комнату с подписью
            r['lab'], r['final'], r['rooms'], splits = fc.merge_false_splits(
                r['lab'], r['rooms'], r['final'], r['wall'], r['add'], vpts, ppm)
            r['lab'], r['rooms'], lsplit = fc.split_by_labels(r['lab'], r['rooms'], vpts, ppm)
            r['label_splits'] = lsplit
            r['areas'] = np.bincount(r['lab'].ravel(), minlength=int(r['lab'].max()) + 1)
        hit, obs = match_gold(r, groom, fams, core=True)
        fit = fc.fit_scale(obs)
        loo = fc.leave_one_out(obs)
        topo = topology(r, groom, hit, ppm)
        dims = room_dims(groom, hit, obs, loo, ppm0)
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
             'label_splits': r.get('label_splits', []),
             'vlm_title': vl['panels'][pi]['title'] if vl and vl['panels'] else None,
             'gia_m2': gpx / ppm / ppm, 't_ext_px': t_ext, 'openings': op, 'angles': angles,
             'gold_panels': sorted({g['panel'] for g in groom}), 'dims': dims}
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


def most_common(xs):
    from collections import Counter
    return Counter(xs).most_common(1)[0][0] if xs else None


def poly_m(poly, ppm, off):
    return [[round((float(p[0]) + off[0]) / ppm, 4), round((float(p[1]) + off[1]) / ppm, 4)] for p in poly]


def export_panel(outdir, plan, pi, P, r, img, wall, fams, groom, gopen):
    """Модель панели для рендера (метры) + наложение для глаз."""
    ppm = P['ppm']
    final, add, lab_g = r['final'], r['add'], r['lab_g']
    doors = np.zeros_like(add)
    wins = np.zeros_like(add)
    for g in r['gaps']:
        (wins if g.kind == 'window' else doors)[lab_g == g.id] = 1
    solid = ((r['wall'] > 0) & (final > 0)).astype(np.uint8)
    # стена монолитом на всю высоту; под окном — подоконная часть, над окном и дверью — перемычка (без горизонтальных швов)
    bands = [(0.0, H_WALL, solid), (0.0, SILL, wins & (solid == 0)), (HEAD, H_WALL, (wins | doors) & (solid == 0))]
    off = (0, 0)
    model = {'plan': plan, 'panel': P['panel'], 'ppm': ppm, 'bbox_px': P['bbox_px'], 'bands': [], 'floors': [],
             'openings': [], 'rooms': []}
    for z0, z1, m in bands:
        polys, _ = fc.mask_polygons(m, fams, min_area=3)
        model['bands'].append({'z0': z0, 'z1': z1, 'polys': [{'outer': poly_m(o, ppm, off),
                                                             'holes': [poly_m(h, ppm, off) for h in hs]} for o, hs in polys]})
    for rid in r['rooms']:
        kf = max(3, int(2 * fc.stroke_thickness(r['wall']) + 1)) | 1   # пол заходит под всю толщину стены — без щели
        fm = cv2.dilate((r['lab'] == rid).astype(np.uint8), np.ones((kf, kf), np.uint8)) & (~r['outside']).astype(np.uint8)
        polys, _ = fc.mask_polygons(fm, fams, min_area=10)
        names = [g['name'] for g in groom if g.get('_room') == rid]
        for o, hs in polys:
            model['floors'].append({'outer': poly_m(o, ppm, off), 'holes': [poly_m(h, ppm, off) for h in hs], 'room': rid})
        model['rooms'].append({'id': int(rid), 'names': names, 'area_m2': round(float(r['areas'][rid]) / ppm / ppm, 2)})
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
    for g in groom:
        x, y = map(int, g['pt'])
        ok = g.get('_room') is not None
        cv2.circle(ov, (x, y), 5, (0, 0, 255) if not ok else (0, 120, 255), -1)
    for o in gopen:
        x, y = map(int, o['pt'])
        cv2.drawMarker(ov, (x, y), (255, 0, 255), cv2.MARKER_CROSS, 10, 2)
    cv2.imwrite(str(Path(outdir) / f'overlay-{plan}-{pi}.png'), ov)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('plan')
    ap.add_argument('out')
    ap.add_argument('--inputs', default='/home/pakar/remlab-logs/floorplan-bench/inputs')
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
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
