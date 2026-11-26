#!/usr/bin/env python3
"""Мерка «по поверхностям» (T-20261124-65, смена объёма 24.11; владелец TG 2697: «свет пока не принципиально — сначала научись дорисовывать»).

Что ловит. Главный брак корпусной мебели — «чужой цвет на боку» (Fable 24.11: 6 из 11 корпусных): бок виден на фото узкой полосой, а красится тоном фасада/ниши/«корпуса». Прежняя автооценка
меряла «рисунок», а чужой материал на боку как таковой не ловила.
Как. БЕЗ света сайта. Для каждой поверхности — перёд / бок / верх / зад — цвет ВСЕЙ поверхности модели (прямо из текстуры, то есть из того, чем её покрасили) сравнивается с цветом её ПОЛОСЫ на фото
(пиксели фото, где в кадре камеры фото видна именно эта поверхность; кромка в `erode_px` отступа). Результат по поверхности: угол оттенка Δh и ΔC/C (⚑ — по оттенку, T-20261125-73/2, свод покраски п.4/п.9), ΔE_ab, ΔE (Lab, ΔE76), ΔL, ΔC для сведения и ЧИСЛО ПИКСЕЛЕЙ в полосе.
  • ⚑ (`judge`/`decide`): оба цветные (C ≥ c_min) — Δh ≥ dh_deg; оба нейтральные — по оттенку не судим; цветной против нейтрального — C цветного ≥ c_clear. Насыщенность и яркость в ⚑ не входят
    (на боку фото тень, модель без света; «тем же оттенком вдвое насыщеннее» — тот же материал). ⚑ только если расходятся И вся поверхность модели, И те же пиксели полосы (иначе поверхность из разных
    деталей — сиденье + рама). «Глянец?» — блик на фото (светлее модели, C полосы ≪ C модели): пометка вместо ⚑.
  • Поверхность = нормаль граней относительно камеры фото: перёд — смотрит в камеру фото, зад — от неё, бок A/B — вбок (по знаку), верх — вверх. У сеток TRELLIS порядок обхода граней «наружу» не гарантирован,
    поэтому нормаль ориентируется по тому, откуда грань видна: кадр камеры фото (`pose_fit.render_persp`) и кадры модели с пяти сторон (перёд, зад, два бока, верх — камера почти без перспективы).
  • Нет полосы (< min_px) — «не измерено» с причиной; у «зад» (его на фото не бывает) сравнение идёт с полосой бока — правило Fable «зад — тон бока», помечено ref.
  • Регистрация: силуэт кадра камеры фото против силуэта фото (IoU ≥ iou_min), иначе товар «не измерено».
Всё — numpy/OpenCV на процессоре, без браузера и сети; модель не меняется, ничего не чистится. Числа — `data/flat3d/surface-eval.json`; ID товаров в коде нет.

  surface_eval.py batch --items items.json --out ПАПКА [--only id,id] [--repeat 2]
  items.json: [{"id", "glb": «material.glb» (с текстурой), "photo": «фото RGBA», "check06": «06-visible/check.json» (extra.camera), "role": «роль каталога» (для типа в таблице)}]
  → ПАПКА/run<k>/{surface-eval.json (по товарам), summary.json}, ПАПКА/table.md (товар × поверхности: Δh · ΔC/C · ΔE_ab (px) ⚑ / глянец? + ΔL для сведения), ПАПКА/spread.json (разброс повтора).
  surface_eval.py frames --items items.json --only id,id --out ПАПКА [--surface бок]   — кадры калибровки: фото | модель в той же камере | образцы цвета и числа.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
TRELLIS = os.path.join(ROOT, 'tools', 'scout', 'salad', 'trellis')
RULES_PATH = os.path.join(ROOT, 'data', 'flat3d', 'surface-eval.json')
if TRELLIS not in sys.path:
    sys.path.insert(0, TRELLIS)                      # pose_fit / tex_coverage (под `python -I` каталог скрипта в путь сам не попадает)
CLS = {0: 'верх', 1: 'перёд', 2: 'бок A', 3: 'бок B', 4: 'зад'}


def load_rules(path: str | None = None) -> dict:
    with open(path or RULES_PATH, encoding='utf-8') as f:
        return json.load(f)


# ---------- поверхности по нормали ----------

def classify(nw: np.ndarray, h: np.ndarray, R: dict) -> np.ndarray:
    """Класс по мировой нормали (k, 3), смотрящей В КАМЕРУ: 0 верх, 1 перёд, 2 бок A (угол > 0), 3 бок B, 4 зад, −1 прочее (низ). h — горизонтальное направление на камеру фото (x, z)."""
    ny = nw[:, 1]
    cT = math.cos(math.radians(R['top_tilt_deg']))
    cls = np.full(len(nw), -1, np.int8)
    top = ny >= cT
    wall = np.abs(ny) < cT
    nh = nw[:, [0, 2]]
    nh = nh / np.maximum(np.linalg.norm(nh, axis=1, keepdims=True), 1e-12)
    ang = np.degrees(np.arctan2(h[0] * nh[:, 1] - h[1] * nh[:, 0], h[0] * nh[:, 0] + h[1] * nh[:, 1]))
    a = np.abs(ang)
    cls[wall & (a <= R['front_half_deg'])] = 1
    cls[wall & (a >= R['back_from_deg'])] = 4
    side = wall & (a > R['front_half_deg']) & (a < R['back_from_deg'])
    cls[side & (ang > 0)] = 2
    cls[side & (ang <= 0)] = 3
    cls[top] = 0
    return cls


def load_geo(glb: str) -> dict:
    """GLB (одна геометрия с текстурой) → {V, F, UV, N (сглаженные), tex}."""
    sys.path.insert(0, TRELLIS)
    import tex_coverage as TC
    import pose_fit as PF
    g = TC.load_geoms(glb)
    if len(g) != 1:
        raise ValueError(f'ожидалась одна геометрия, найдено {len(g)}')
    g = g[0]
    return {'V': g['V'], 'F': g['F'], 'UV': g['UV'], 'N': PF.smooth_normals(g['V'], g['F']), 'tex': g['tex']}


def world_normals(r: dict, cam: dict) -> np.ndarray:
    """Мировые нормали пикселей кадра (n, n, 3), ориентированные В КАМЕРУ: nf = ncam·(right, up, −fwd)."""
    import pose_fit as PF
    _C, right, up, fwd = PF.cam_basis(cam['az'], cam['el'], cam['d'])
    nc = r['normal']
    return nc[..., 0:1] * right + nc[..., 1:2] * up - nc[..., 2:3] * fwd


def texel(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """RGB текстуры в точках (u, v_flipped) — как их отдаёт render_persp: строка = v_flipped·H, столбец = u·W."""
    H, W = tex.shape[:2]
    x = np.clip((uv[..., 0] * W).astype(np.int64), 0, W - 1)
    y = np.clip((uv[..., 1] * H).astype(np.int64), 0, H - 1)
    return tex[y, x]


# ---------- фото ----------

def erode(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    from scipy import ndimage as ndi
    return ndi.binary_erosion(mask, iterations=int(px))


def photo_canvas_of(photo_path: str, margin: float) -> dict:
    """Квадрат вокруг силуэта фото (как pose_fit.photo_canvas): {x0, y0, side}."""
    from PIL import Image
    a = np.asarray(Image.open(photo_path).convert('RGBA'))[..., 3] > 127
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        raise ValueError('у фото нет альфы')
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    side = max(bx1 - bx0, by1 - by0) * (1 + 2 * margin)
    return {'x0': float((bx0 + bx1) / 2 - side / 2), 'y0': float((by0 + by1) / 2 - side / 2), 'side': float(side)}


def crop_photo(photo_path: str, cam_cv: dict, n: int) -> tuple:
    """Квадрат вокруг силуэта фото → n×n: (RGB uint8, альфа>127 bool). Вне фото — прозрачно."""
    from PIL import Image
    im = Image.open(photo_path).convert('RGBA')
    box = (cam_cv['x0'], cam_cv['y0'], cam_cv['x0'] + cam_cv['side'], cam_cv['y0'] + cam_cv['side'])
    a = np.asarray(im.transform((n, n), Image.EXTENT, box, Image.BILINEAR))
    return a[..., :3], a[..., 3] > 127


# ---------- цвет ----------

def lab_med(rgb: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    """Медиана Lab (по каналам; со взвешиванием по площади, если дан w) → [L, a, b]."""
    from sides_eval import rgb_to_lab
    lab = rgb_to_lab(np.asarray(rgb, np.float64).reshape(-1, 3))
    if w is None:
        return np.median(lab, axis=0)
    out = []
    for k in range(3):
        o = np.argsort(lab[:, k], kind='stable')
        cw = np.cumsum(w[o])
        out.append(lab[o, k][np.searchsorted(cw, cw[-1] / 2.0)])
    return np.array(out)


def lab_to_rgb(lab: list) -> tuple:
    """Lab (D65, как sides_eval.rgb_to_lab) → sRGB (r, g, b) 0..255 — для образцов цвета на кадрах."""
    fy = (lab[0] + 16) / 116.0
    f = np.array([fy + lab[1] / 500.0, fy, fy - lab[2] / 200.0])
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    c = np.clip(np.linalg.solve(m, xyz), 0.0, 1.0)
    c = np.where(c > 0.0031308, 1.055 * np.power(c, 1 / 2.4) - 0.055, 12.92 * c)
    return tuple(int(round(v * 255)) for v in c)


def delta(a: np.ndarray, b: np.ndarray) -> dict:
    """ΔE76 (с яркостью), ΔE_ab (только цветность a, b — по нему ⚑: тень на боку фото меняет L, а не цвет), ΔL и ΔC — для сведения."""
    return {'dE': round(float(np.linalg.norm(a - b)), 2), 'dEab': round(float(math.hypot(a[1] - b[1], a[2] - b[2])), 2),
            'dL': round(float(a[0] - b[0]), 2), 'dC': round(float(math.hypot(a[1], a[2]) - math.hypot(b[1], b[2])), 2)}


def chroma_hue(lab) -> tuple:
    """(C, h°) по Lab: C = √(a²+b²), h = atan2(b, a) в градусах."""
    return math.hypot(lab[1], lab[2]), math.degrees(math.atan2(lab[2], lab[1]))


def judge(lab_m, lab_p, V: dict) -> dict:
    """Расходится ли ЦВЕТ модели с фото (T-20261125-73/2; свод покраски п.4/п.9: «чужой бок» = угол оттенка, не ΔE; светлоту не судим — на боку фото тень).
    • оба цветные (C ≥ c_min): расходятся, если угол оттенка Δh ≥ dh_deg; насыщенность («вдвое насыщеннее» тем же оттенком) — не повод;
    • оба нейтральные (C < c_min): по оттенку не судим (серое/белое/чёрное — по роли и карточке), не расходятся;
    • один цветной, другой нейтральный: расходятся, если цветной явно цветной (C ≥ c_clear): беж против серо-голубого, серое против тёплого дерева.
    Числа — в data/flat3d/surface-eval.json, `verdict`."""
    cm, hm = chroma_hue(lab_m)
    cp, hp = chroma_hue(lab_p)
    nm, npho = cm < V['c_min'], cp < V['c_min']
    if nm and npho:
        return {'kind': 'нейтр.', 'dh': None, 'mismatch': False}
    if nm or npho:
        return {'kind': 'цвет↔нейтр.', 'dh': None, 'mismatch': bool(max(cm, cp) >= V['c_clear'])}
    dh = abs((hm - hp + 180.0) % 360.0 - 180.0)
    return {'kind': 'цвет', 'dh': round(float(dh), 1), 'mismatch': bool(dh >= V['dh_deg'])}


def decide(lab_whole, lab_photo, lab_vis, V: dict) -> dict:
    """⚑ — только при согласии: расходится И «вся поверхность модели» (lab_whole), И «те же пиксели полосы» (lab_vis — модель там, где на фото полоса; у копии бока их нет — тогда решает вся поверхность).
    Расходится по всей поверхности, но не в пикселях полосы — это не чужой цвет, а поверхность из разных деталей (сиденье + рама): метки нет. «Глянец» — блик на фото вместо цвета (на фото светлее модели
    на gloss.dL_min и C полосы ≤ gloss.c_ratio × C модели): пометка вместо ⚑."""
    cm, _ = chroma_hue(lab_whole)
    cp, _ = chroma_hue(lab_photo)
    jw = judge(lab_whole, lab_photo, V)
    jv = judge(lab_vis, lab_photo, V) if lab_vis is not None else None
    raw = bool(jw['mismatch'] and (jv is None or jv['mismatch']))
    g = V['gloss']
    gloss = bool(raw and (lab_photo[0] - lab_whole[0]) >= g['dL_min'] and cp <= g['c_ratio'] * cm)
    out = {'kind': jw['kind'], 'dh': jw['dh'], 'C_photo': round(float(cp), 1), 'C_model': round(float(cm), 1),
           'dC_rel': round(float((cm - cp) / max(cm, cp, 1e-9)), 2), 'mismatch_whole': jw['mismatch'],
           'gloss': gloss, 'flag': bool(raw and not gloss)}
    if jv is not None:
        out.update({'mismatch_vis': jv['mismatch'], 'dh_vis': jv['dh']})
    return out


# ---------- кадры ----------

def side_cams(cam: dict, R: dict) -> list:
    """Пять камер сторон: почти без перспективы, предмет (куб ≈ 1) занимает ~1/view_fill кадра; углы вокруг азимута фото."""
    base = {'d': float(R['view_d']), 'f': float(R['view_d']) / float(R['view_fill']), 'cx': 0.5, 'cy': 0.5}
    az = float(cam['az'])
    return [dict(base, az=az + a, el=0.0) for a in (0.0, 180.0, 90.0, -90.0)] + [dict(base, az=az, el=89.9)]


def model_colours(geo: dict, cam: dict, R: dict) -> tuple:
    """Цвет ВСЕЙ поверхности модели: {класс: Lab-медиана по площади}, {класс: пикселей} — из кадров с пяти сторон (пиксели, где грань смотрит в камеру кадра не круче view_cos_min)."""
    import pose_fit as PF
    h = np.array([math.sin(math.radians(cam['az'])), math.cos(math.radians(cam['az']))])
    n = int(R['view_px'])
    cols: dict = {c: [] for c in CLS}
    ws: dict = {c: [] for c in CLS}
    for vc in side_cams(cam, R):
        r = PF.render_persp(geo, vc, n)
        m = r['mask'] & (r['cos'] >= R['view_cos_min'])
        cl = classify(world_normals(r, vc)[m], h, R)
        rgb = texel(geo['tex'], r['uv'])[m]
        wt = 1.0 / np.maximum(r['cos'][m], 0.3)                 # площадь поверхности на пиксель ∝ 1/cos
        for c in CLS:
            k = cl == c
            if k.any():
                cols[c].append(rgb[k])
                ws[c].append(wt[k])
    lab, cnt = {}, {}
    for c in CLS:
        if cols[c]:
            rgb, w = np.concatenate(cols[c]), np.concatenate(ws[c])
            lab[c], cnt[c] = lab_med(rgb, w), int(len(rgb))
    return lab, cnt


def measure_item(it: dict, R: dict, keep: dict | None = None) -> dict:
    """Одна вещь: полосы поверхностей на фото против цвета поверхностей модели. keep — словарь, куда складываются кадры и маски полос (для кадра калибровки)."""
    import pose_fit as PF
    cam = json.load(open(it['check06'], encoding='utf-8'))['extra']['camera']
    cam = {k: float(cam[k]) for k in ('az', 'el', 'd', 'f', 'cx', 'cy')}
    geo = load_geo(it['glb'])
    n = int(R['frame_px'])
    cv = photo_canvas_of(it['photo'], float(R['canvas_margin']))
    ph_rgb, ph_a = crop_photo(it['photo'], cv, n)
    r = PF.render_persp(geo, cam, n)
    sil = r['mask']
    inter, union = int((sil & ph_a).sum()), int((sil | ph_a).sum())
    iou = inter / union if union else 0.0
    out: dict = {'registration': {'iou': round(iou, 4), 'ok': bool(iou >= R['registration']['iou_min'])}, 'surfaces': {}, 'unmeasured': []}
    if not out['registration']['ok']:
        out['unmeasured'].append({'what': 'все поверхности', 'reason': f"регистрация: IoU силуэта {iou:.2f} < {R['registration']['iou_min']} — модель и фото не лежат друг на друге"})
        return out
    h = np.array([math.sin(math.radians(cam['az'])), math.cos(math.radians(cam['az']))])
    cl_img = np.full((n, n), -1, np.int8)
    cl_img[sil] = classify(world_normals(r, cam)[sil], h, R)
    mod_rgb = texel(geo['tex'], r['uv'])
    lab_all, cnt_all = model_colours(geo, cam, R)
    er, mn = int(R['regions']['erode_px']), int(R['regions']['min_px'])
    strip: dict = {}
    for c in CLS:
        m = erode(cl_img == c, er) & ph_a
        npx = int(m.sum())
        s = {'n': npx}
        if npx >= mn:
            s['photo_lab'] = lab_med(ph_rgb[m])
            s['model_vis_lab'] = lab_med(mod_rgb[m])
        strip[c] = s
        if keep is not None:
            s['mask'] = m
    sideA, sideB = strip[2], strip[3]
    vis_side = 2 if sideA['n'] >= sideB['n'] else 3                   # «бок» — тот, у которого на фото полоса больше
    names = {0: 'верх', 1: 'перёд', 4: 'зад', vis_side: 'бок', (5 - vis_side): 'бок-2'}

    def fill(c: int, ref_c: int | None, why_ref: str) -> None:
        name = names[c]
        if c not in lab_all:
            out['unmeasured'].append({'what': name, 'reason': 'у модели нет такой поверхности (нет граней этого направления)'})
            return
        own = 'photo_lab' in strip[c]
        src = c if own else ref_c
        if src is None or 'photo_lab' not in strip.get(src, {}):
            out['unmeasured'].append({'what': name, 'reason': f"нет полосы на фото: {strip[c]['n']} px (< {mn})"})
            return
        d = delta(lab_all[c], strip[src]['photo_lab'])
        d.update({'n_strip': strip[src]['n'], 'n_own_strip': strip[c]['n'], 'ref': 'сама' if own else why_ref,
                  'model_px': cnt_all.get(c), 'photo_lab': [round(float(x), 1) for x in strip[src]['photo_lab']], 'model_lab': [round(float(x), 1) for x in lab_all[c]]})
        if own:
            d['dE_vis'] = delta(strip[c]['model_vis_lab'], strip[c]['photo_lab'])['dE']          # модель в тех же пикселях полосы (как нарисовано) против фото
        vis_lab = strip[c]['model_vis_lab'] if own else None
        if own:
            d['model_vis_lab'] = [round(float(x), 1) for x in vis_lab]
        d.update(decide(lab_all[c], strip[src]['photo_lab'], vis_lab, R['verdict']))
        out['surfaces'][name] = d

    back_ref = vis_side if strip[vis_side].get('photo_lab') is not None else None
    fill(1, None, '')
    fill(vis_side, None, '')
    fill(5 - vis_side, vis_side, 'бок')
    fill(0, None, '')
    fill(4, back_ref, R['back_ref'])
    if keep is not None:
        keep.update({'photo': ph_rgb, 'photo_a': ph_a, 'model': mod_rgb, 'sil': sil, 'cls': cl_img, 'strip': strip, 'names': names})
    return out


# ---------- пакет ----------

def type_of(role: str | None) -> str | None:
    if not role:
        return None
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
    import mesh_type_passports as MTP
    return MTP.normalize(role, MTP.load())


def run_once(items: list, out: str, R: dict) -> dict:
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    res: dict = {}
    for it in items:
        sid = it['id']
        base = {'id': sid, 'role': it.get('role'), 'type': type_of(it.get('role'))}
        t1 = time.time()
        try:
            if not (os.path.exists(it['glb']) and os.path.exists(it['photo']) and os.path.exists(it['check06'])):
                raise FileNotFoundError('нет GLB, фото или 06-visible/check.json')
            got = measure_item(it, R)
        except Exception as e:  # noqa: BLE001 — один товар не роняет пакет; причина — в таблице
            got = {'surfaces': {}, 'unmeasured': [{'what': 'все поверхности', 'reason': f'{type(e).__name__}: {str(e)[:140]}'}]}
        got['seconds'] = round(time.time() - t1, 1)
        res[sid] = dict(base, **got)
    summ = summary(res, R)
    summ['seconds'] = round(time.time() - t0, 1)
    json.dump(res, open(os.path.join(out, 'surface-eval.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(summ, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'eval': res, 'summary': summ}


def summary(res: dict, R: dict) -> dict:
    """Свод по поверхностям. «зад» и «бок-2» без своей полосы (ref:бок) — копия бока, не отдельная мерка: считаются отдельной строкой «копия бока», в ⚑ своих поверхностей не входят."""
    by_s: dict = {}
    copy_s: dict = {'measured': 0, 'flagged': [], 'gloss': [], 'by_surface': {}}
    unm: dict = {}
    for sid, v in res.items():
        for name, d in v.get('surfaces', {}).items():
            if d['ref'] != 'сама':
                copy_s['measured'] += 1
                copy_s['by_surface'][name] = copy_s['by_surface'].get(name, 0) + 1
                if d['flag']:
                    copy_s['flagged'].append(f'{sid}:{name}')
                if d['gloss']:
                    copy_s['gloss'].append(f'{sid}:{name}')
                continue
            e = by_s.setdefault(name, {'measured': 0, 'flagged': [], 'gloss': [], 'neutral': [], 'dh': [], 'dC_rel': [], 'dE': [], 'dEab': [], 'dL': []})
            e['measured'] += 1
            for k in ('dE', 'dEab', 'dL', 'dC_rel'):
                e[k].append(d[k])
            if d['dh'] is not None:
                e['dh'].append(d['dh'])
            if d['kind'] == 'нейтр.':
                e['neutral'].append(sid)
            if d['flag']:
                e['flagged'].append(sid)
            if d['gloss']:
                e['gloss'].append(sid)
        for u in v.get('unmeasured', []):
            unm.setdefault(u['what'], []).append(sid)
    for name, e in by_s.items():
        med = lambda xs: round(float(np.median(xs)), 2) if len(xs) else None  # noqa: E731
        e.update({'dh_median': med(e['dh']), 'n_dh': len(e['dh']), 'dC_rel_median': med(e['dC_rel']), 'dEab_median': med(e['dEab']),
                  'dEab_p90': round(float(np.quantile(e['dEab'], 0.9)), 2), 'dE_median': med(e['dE']), 'dL_median': med(e['dL']),
                  'n_flagged': len(e['flagged']), 'n_gloss': len(e['gloss']), 'n_neutral': len(e['neutral'])})
        for k in ('dE', 'dEab', 'dL', 'dC_rel', 'dh'):
            del e[k]
    copy_s['n_flagged'] = len(copy_s['flagged'])
    copy_s['n_gloss'] = len(copy_s['gloss'])
    return {'items': len(res), 'by_surface': by_s, 'copy_of_side': copy_s, 'unmeasured_by_surface': {k: len(v) for k, v in sorted(unm.items())},
            'unmeasured_ids': {k: v for k, v in sorted(unm.items())}, 'verdict': R['verdict']}


def spread(a: dict, b: dict) -> dict:
    """Разброс двух прогонов тех же входов: макс. |разность| ΔE по поверхностям (шум самой мерки)."""
    mx, per = 0.0, {}
    for sid in sorted(set(a) & set(b)):
        sa, sb = a[sid].get('surfaces', {}), b[sid].get('surfaces', {})
        row = {n: round(max(abs(sa[n]['dE'] - sb[n]['dE']), abs(sa[n]['dEab'] - sb[n]['dEab'])), 3) for n in sa if n in sb}
        if row:
            per[sid] = row
            mx = max(mx, max(row.values()))
    return {'max_dE': round(mx, 3), 'per_item': per}


def table_md(res: dict, R: dict, sp: dict | None = None) -> str:
    """Таблица товар × поверхности: «Δh° · ΔC/C · ΔE_ab (px полосы)»; ⚑ — оттенок расходится и по всей поверхности, и по пикселям полосы (`decide`); «глянец?» — блик на фото вместо цвета, не ⚑;
    «(не по полосе)» — по всей поверхности расходится, а по пикселям полосы нет (поверхность из разных деталей), не ⚑; «нейтр.» — оба серые/белые/чёрные, по оттенку не судим.
    «= бок (копия)» — своей полосы нет, поверхность сравнена с полосой бока: не отдельная мерка, в ⚑ свода не входит; «—» с причиной — не измерено.
    Вторая таблица — ΔL по поверхностям «для сведения» (тень/свет на фото, в ⚑ не участвует)."""
    cols = R['table_surfaces']
    names = cols + ['бок-2']

    def cell(v: dict, name: str, what: str) -> str:
        d = v.get('surfaces', {}).get(name)
        if not d:
            return '—'
        if d['ref'] != 'сама':
            return f"= {d['ref']} (копия)"
        if what == 'dL':
            return f"{d['dL']:+.1f}"
        if d['kind'] == 'цвет':
            head = f"Δh {d['dh']:.0f}° · ΔC/C {d['dC_rel']:+.2f}"
        elif d['kind'] == 'нейтр.':
            head = 'нейтр.'
        else:
            head = f"цвет↔нейтр. C {d['C_photo']:.0f}→{d['C_model']:.0f}"
        tail = ' ⚑' if d['flag'] else (' глянец?' if d['gloss'] else (' (не по полосе)' if d['mismatch_whole'] and not d['mismatch_vis'] else ''))
        return f"{head} · ΔE_ab {d['dEab']:.1f} ({d['n_strip']})" + tail

    lines = ['| товар | тип | IoU | ' + ' | '.join(cols) + ' | бок-2 (скрытый) | не измерено |', '|' + '---|' * (len(cols) + 4)]
    for sid, v in res.items():
        un = '; '.join(f"{u['what']}: {u['reason'][:60]}" for u in v.get('unmeasured', []))
        iou = (v.get('registration') or {}).get('iou')
        lines.append(f"| …{sid[-8:]} | {v.get('type') or '?'} | {iou if iou is not None else '—'} | " + ' | '.join(cell(v, c, 'dE') for c in names) + f' | {un} |')
    lines += ['', 'ΔL (модель − фото) по поверхностям — для сведения, в ⚑ не участвует:', '', '| товар | ' + ' | '.join(names) + ' |', '|' + '---|' * (len(names) + 1)]
    for sid, v in res.items():
        lines.append(f"| …{sid[-8:]} | " + ' | '.join(cell(v, c, 'dL') for c in names) + ' |')
    sm = summary(res, R)
    V = R['verdict']
    lines += ['', f"⚑: оттенок расходится (Δh ≥ {V['dh_deg']}° при C ≥ {V['c_min']} у обеих сторон; цветной C ≥ {V['c_clear']} против нейтрального) и по всей поверхности, и по пикселям полосы", '',
              '| поверхность | измерено | Δh мед. (судим) | нейтр. | ΔC/C мед. | ΔE_ab мед. | ΔL мед. | ⚑ | глянец? |', '|---|---|---|---|---|---|---|---|---|']
    for name in R['surfaces']:
        e = sm['by_surface'].get(name)
        if e:
            dh = f"{e['dh_median']:.1f}° ({e['n_dh']})" if e['dh_median'] is not None else '—'
            lines.append(f"| {name} | {e['measured']} | {dh} | {e['n_neutral']} | {e['dC_rel_median']:+.2f} | {e['dEab_median']} | {e['dL_median']:+.1f} | {e['n_flagged']} | {e['n_gloss']} |")
    c = sm['copy_of_side']
    lines.append(f"| копия бока (зад, бок-2 без своей полосы) | {c['measured']} | — | — | — | — | — | {c['n_flagged']} (не отдельные) | {c['n_gloss']} |")
    if sp:
        lines += ['', f"Разброс повтора: макс. |разность| ΔE двух прогонов = {sp['max_dE']}."]
    return '\n'.join(lines)


def cal_frame(it: dict, R: dict, surface: str, path: str, title: str) -> dict:
    """Кадр калибровки: слева — фото, справа — модель в той же камере; вне полосы поверхности кадр притемнён (видно, какие пиксели мерились). Третья часть — три образца цвета
    (полоса на фото / модель в тех же пикселях / вся поверхность модели) и числа Δh, ΔC/C, вердикт по поверхности и по полосе, ΔE_ab, ΔE, ΔL (для сведения), px. Возвращает измерение поверхности."""
    from PIL import Image, ImageDraw, ImageFont
    keep: dict = {}
    got = measure_item(it, R, keep)
    d = got['surfaces'].get(surface)
    if not d or d['ref'] != 'сама':
        raise ValueError(f'поверхность «{surface}» не измерена по своей полосе: {got["unmeasured"]}')
    cid = next(c for c, nm in keep['names'].items() if nm == surface)
    strip = keep['strip'][cid]['mask']
    ys, xs = np.nonzero(keep['sil'] | keep['photo_a'])
    pad = 12
    y0, y1, x0, x1 = max(ys.min() - pad, 0), ys.max() + pad, max(xs.min() - pad, 0), xs.max() + pad
    bg = np.array([236, 236, 236], np.uint8)

    def panel(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
        o = np.where(alpha[..., None], rgb, bg).astype(np.float32)
        o = np.where(strip[..., None], o, o * 0.35 + bg * 0.15)
        edge = erode(strip, 1) ^ strip
        o[edge] = (255, 0, 160)
        return Image.fromarray(o.clip(0, 255).astype(np.uint8)[y0:y1, x0:x1])

    pa, pb = panel(keep['photo'], keep['photo_a']), panel(keep['model'], keep['sil'])
    H = 420
    sc = H / pa.height
    pa, pb = (p.resize((int(p.width * sc), H), Image.BILINEAR) for p in (pa, pb))
    W3 = 560
    canvas = Image.new('RGB', (pa.width + pb.width + W3 + 40, H + 60), (255, 255, 255))
    canvas.paste(pa, (10, 50))
    canvas.paste(pb, (pa.width + 20, 50))
    dr = ImageDraw.Draw(canvas)
    try:
        f1 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
        f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 16)
    except OSError:
        f1 = f2 = ImageFont.load_default()

    def sw(lab: list, x: int, y: int, cap: str) -> None:
        rgb = lab_to_rgb(lab)
        dr.rectangle([x, y, x + 100, y + 70], fill=rgb, outline=(0, 0, 0))
        dr.text((x, y + 74), cap, fill=(0, 0, 0), font=f1)
        dr.text((x, y + 94), f"L {lab[0]:.0f} a {lab[1]:+.0f} b {lab[2]:+.0f}", fill=(60, 60, 60), font=f1)

    dr.text((10, 8), f"{title} — {surface}: фото (слева) | модель в той же камере | образцы цвета", fill=(0, 0, 0), font=f2)
    dr.text((10, 30), 'розовый контур — полоса, по которой меряем; остальное притемнено', fill=(90, 90, 90), font=f1)
    X = pa.width + pb.width + 40
    sw(d['photo_lab'], X, 50, 'фото: полоса')
    sw(d['model_vis_lab'], X + 110, 50, 'модель: полоса')
    sw(d['model_lab'], X + 220, 50, 'модель: вся')
    verdict = '⚑' if d['flag'] else ('глянец? (не ⚑)' if d['gloss'] else 'без ⚑')
    judged = f"Δh {d['dh']:.0f}° (порог {R['verdict']['dh_deg']}°)" if d['dh'] is not None else f"{d['kind']} (C {d['C_photo']:.0f} → {d['C_model']:.0f})"
    y = 190
    for line, fnt in ((verdict, f2), (judged, f2), (f"ΔC/C {d['dC_rel']:+.2f}   (C {d['C_photo']:.0f} → {d['C_model']:.0f})", f1),
                      (f"вся поверхность: {'расходится' if d['mismatch_whole'] else 'нет'};  пиксели полосы: {'расходится' if d['mismatch_vis'] else 'нет'}", f1),
                      (f"ΔE_ab {d['dEab']:.1f}   ΔE {d['dE']:.1f}   ΔL {d['dL']:+.1f}  (для сведения)", f1), (f"полоса {d['n_strip']} px", f1)):
        dr.text((X, y), line, fill=(0, 0, 0), font=fnt)
        y += 26
    canvas.save(path)
    return d


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('batch')
    b.add_argument('--items', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--only', default='')
    b.add_argument('--repeat', type=int, default=1, help='сколько раз прогнать те же входы (2 — разброс повтора)')
    fr = sub.add_parser('frames', help='кадры калибровки: полоса поверхности на фото | та же поверхность модели | образцы и числа')
    fr.add_argument('--items', required=True)
    fr.add_argument('--out', required=True)
    fr.add_argument('--only', required=True)
    fr.add_argument('--surface', default='бок')
    a = ap.parse_args(argv)
    R = load_rules()
    items = json.load(open(a.items, encoding='utf-8'))
    only = {x for x in a.only.split(',') if x}
    if only:
        items = [x for x in items if x['id'] in only]
    if a.cmd == 'frames':
        os.makedirs(a.out, exist_ok=True)
        for it in items:
            d = cal_frame(it, R, a.surface, os.path.join(a.out, f"{it['id']}.png" if a.surface == 'бок' else f"{it['id']}-{a.surface}.png"), '…' + it['id'][-8:])
            print(f"…{it['id'][-8:]} {a.surface}: {d['kind']} Δh {d['dh']} ΔC/C {d['dC_rel']} C {d['C_photo']}→{d['C_model']} | ΔE_ab {d['dEab']} ΔL {d['dL']} | вся {d['mismatch_whole']} полоса {d['mismatch_vis']} | px {d['n_strip']} ⚑ {d['flag']} глянец {d['gloss']}")
        return 0
    runs = []
    for k in range(1, a.repeat + 1):
        runs.append(run_once(items, os.path.join(a.out, f'run{k}'), R))
        s = runs[-1]['summary']
        print(f"прогон {k}: товаров {s['items']}, не измерено по поверхностям {s['unmeasured_by_surface']}, {s['seconds']} с")
    sp = spread(runs[0]['eval'], runs[1]['eval']) if len(runs) > 1 else None
    if sp:
        json.dump(sp, open(os.path.join(a.out, 'spread.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(a.out, 'table.md'), 'w', encoding='utf-8').write(table_md(runs[0]['eval'], R, sp))
    print(f"таблица: {os.path.join(a.out, 'table.md')}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
