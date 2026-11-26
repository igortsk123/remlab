"""Два слоя чернил листа для наложения плана на лист (T-98/21, Fable 17 §3).

  чуткий  — всё, что может быть линией, и бледное: по нему решают «под стеной ответа ничего нет»;
  строгий — только то, что точно стена (глубокое, длинное, не подпись): по нему решают «на листе стена, а в ответе нет».

Цепочка — та же, что у разбора листа (cleanup.clean_bgr: ровный фон, сетка, цветная мебель — каждый шаг сам решает, нужен ли листу;
выпрямление ВЫКЛЮЧЕНО — маска должна лежать на тех же пикселях, что и лист), потом деление на местную бумагу + местный порог.
Все размеры — в толщинах штриха самого листа, все уровни — от шума бумаги этого листа; пороги — ink_layers.json (с _why).
Не годен лист (линий почти не видно / сплошное тёмное) — оба слоя пустые и причина в паспорте. $0, без сети."""
import json
import os

import cv2
import numpy as np

import cleanup

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ink_layers.json')


def load_cfg(path=None):
    return json.load(open(path or CFG_PATH, encoding='utf-8'))


def _odd(n):
    return max(3, int(n) | 1)


def passport(gray):
    """→ {'paper': яркость бумаги, 't': тонкий штрих px (10-й процентиль ширин), 'tw': толстая стена px}. Грубая маска — тёмнее середины между бумагой и самым тёмным."""
    paper = float(np.percentile(gray, 70))
    dark = float(np.percentile(gray, 1))
    thr = paper - 0.5 * max(paper - dark, 20.0)
    m = (gray < thr).astype(np.uint8)
    if int(m.sum()) < 50:
        return {'paper': paper, 't': 2.0, 'tw': 4.0, 'rough_px': int(m.sum())}
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    ridge = (dt > 0.5) & (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8)) - 1e-6)
    w = 2.0 * dt[ridge]
    t = float(np.percentile(w, 10))      # тонкий штрих: стены с толстой заливкой не должны задирать «типичный»
    tw = float(np.percentile(w, 90))
    return {'paper': paper, 't': max(t, 1.5), 'tw': max(tw, 2.5 * 1.5, t), 'rough_px': int(m.sum())}


def _components(mask, keep_fn):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        if keep_fn(int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT]), int(st[i, cv2.CC_STAT_AREA])):
            keep[i] = True
    return keep[lab]


def layers_of_bgr(bgr, cfg=None):
    """BGR → (чуткий bool[H,W], строгий bool[H,W], паспорт-dict). Шаги цепочки и их решения — в паспорте['steps']."""
    cfg = cfg or load_cfg()
    H, W = bgr.shape[:2]
    pp = {'sheet_px': [W, H], 'steps': {}}
    cur, ops, info = cleanup.clean_bgr(bgr, rectify=False, background=True, lines=False, grid=True, layers=True)
    pp['steps'] = {'ops': ops, **{k: v for k, v in info.items() if k in ('bg', 'grid', 'layers')}}
    gray = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)
    ps = passport(gray)
    t, tw = ps['t'], ps['tw']
    pp.update({'paper': round(ps['paper'], 1), 't_px': round(t, 2), 'tw_px': round(tw, 2)})
    k = _odd(max(15, cfg['bg_kernel_walls'] * tw))
    bg = cv2.GaussianBlur(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)), (0, 0), k)
    rel = gray.astype(np.float32) / np.maximum(bg.astype(np.float32), 1.0)
    paper_px = rel > 0.9
    if int(paper_px.sum()) < 100:
        pp['годен'] = False
        pp['причина'] = 'нет бумаги (почти весь лист тёмный)'
        z = np.zeros((H, W), bool)
        return z, z.copy(), pp
    med = float(np.median(rel[paper_px]))
    sd = 1.4826 * float(np.median(np.abs(rel[paper_px] - med)))
    pp['paper_noise'] = round(sd, 4)
    d_sens = max(cfg['paper_noise_k'] * sd, cfg['sens_min_depth'])
    glob = rel < (med - d_sens)
    # местный порог: темнее соседей в окне порядка штриха; берём, только если не раздул слой (зерно/штриховка → шаг отказывается)
    sg = max(1.0, cfg['local_sigma_strokes'] * t)
    loc = (cv2.GaussianBlur(rel, (0, 0), sg) - rel) > cfg['local_depth']
    add = loc & ~glob
    use_local = int(glob.sum()) > 0 and int(add.sum()) <= cfg['local_add_max'] * int(glob.sum())
    pp['steps']['local'] = {'использован': bool(use_local), 'добавил_доля': round(float(add.sum() / max(int(glob.sum()), 1)), 3)}
    sens = glob | loc if use_local else glob
    amin = cfg['sens_min_area_strokes2'] * t * t
    sens = _components(sens, lambda w_, h_, a_: a_ >= amin)
    frac = float(sens.mean())
    pp['чуткий_доля'] = round(frac, 4)
    lo, hi = cfg['usable_ink_frac']
    if not (lo <= frac <= hi):
        pp['годен'] = False
        pp['причина'] = f'чернил {frac:.4f} вне {lo}…{hi}: для наложения не годен'
        z = np.zeros((H, W), bool)
        return z, z.copy(), pp
    # строгий: глубже половины типичной глубины линии листа, длинный и не тоньше штриха
    depth = med - float(np.percentile(rel[sens], 100 - cfg['strict_depth_pct']))      # глубина ТЁМНОЙ линии листа (серые заливки — реки, мебель — глубину не занижают)
    d_strict = max(cfg['strict_depth_frac'] * depth, cfg['strict_min_noise_k'] * sd)
    pp.update({'глубина_линии': round(depth, 3), 'порог_строгого': round(d_strict, 3)})
    deep = ((rel < (med - d_strict)) & sens).astype(np.uint8)
    lmin = max(3, int(round(cfg['strict_min_len_strokes'] * t)))
    if tw >= cfg['thick_ratio'] * t:                      # на листе есть толстые стены: строгий = толстое
        wmin = max(cfg['thick_ratio'] * t, cfg['thick_min_frac'] * tw)
        dt = cv2.distanceTransform(deep, cv2.DIST_L2, 3)
        core = (2.0 * dt >= wmin).astype(np.uint8)
        r = max(1, int(round(wmin / 2.0)))
        strict = (cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0) & (deep > 0)
        pp['строгий_вид'] = f'толстое ≥ {wmin:.1f} px'
    else:                                                 # тонкие стены: длинные отрезки по осям листа
        hor = cv2.morphologyEx(deep, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (lmin, 1)))
        ver = cv2.morphologyEx(deep, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, lmin)))
        strict = (hor > 0) | (ver > 0)
        pp['строгий_вид'] = f'длинные по осям ≥ {lmin} px'
    pp['строгий_доля'] = round(float(strict.mean()), 4)
    pp['годен'] = True
    return sens, strict, pp


def layers_of_path(path, cfg=None):
    """файл листа (альфа — на белое) → те же три значения"""
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return layers_of_bgr(cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR), cfg)
