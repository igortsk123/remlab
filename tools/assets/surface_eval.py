#!/usr/bin/env python3
"""Мерка «по поверхностям» (T-20261124-65, смена объёма 24.11; владелец TG 2697: «свет пока не принципиально — сначала научись дорисовывать»).

Что ловит. Главный брак корпусной мебели — «чужой цвет на боку» (Fable 24.11: 6 из 11 корпусных): бок виден на фото узкой полосой, а красится тоном фасада/ниши/«корпуса». Прежняя автооценка
меряла «рисунок», а чужой материал на боку как таковой не ловила.
Как. БЕЗ света сайта. Для каждой поверхности — перёд / бок / верх / зад — цвет ВСЕЙ поверхности модели (прямо из текстуры, то есть из того, чем её покрасили) сравнивается с цветом её ПОЛОСЫ на фото
(пиксели фото, где в кадре камеры фото видна именно эта поверхность; кромка в `erode_px` отступа). Результат по поверхности: ΔE (Lab, ΔE76), ΔL, ΔC и ЧИСЛО ПИКСЕЛЕЙ в полосе.
  • Поверхность = нормаль граней относительно камеры фото: перёд — смотрит в камеру фото, зад — от неё, бок A/B — вбок (по знаку), верх — вверх. У сеток TRELLIS порядок обхода граней «наружу» не гарантирован,
    поэтому нормаль ориентируется по тому, откуда грань видна: кадр камеры фото (`pose_fit.render_persp`) и кадры модели с пяти сторон (перёд, зад, два бока, верх — камера почти без перспективы).
  • Нет полосы (< min_px) — «не измерено» с причиной; у «зад» (его на фото не бывает) сравнение идёт с полосой бока — правило Fable «зад — тон бока», помечено ref.
  • Регистрация: силуэт кадра камеры фото против силуэта фото (IoU ≥ iou_min), иначе товар «не измерено».
Всё — numpy/OpenCV на процессоре, без браузера и сети; модель не меняется, ничего не чистится. Числа — `data/flat3d/surface-eval.json`; ID товаров в коде нет.

  surface_eval.py batch --items items.json --out ПАПКА [--only id,id] [--repeat 2]
  items.json: [{"id", "glb": «material.glb» (с текстурой), "photo": «фото RGBA», "check06": «06-visible/check.json» (extra.camera), "role": «роль каталога» (для типа в таблице)}]
  → ПАПКА/run<k>/{surface-eval.json (по товарам), summary.json}, ПАПКА/table.md (товар × поверхности: ΔE (px) ⚑), ПАПКА/spread.json (разброс повтора).
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


def delta(a: np.ndarray, b: np.ndarray) -> dict:
    return {'dE': round(float(np.linalg.norm(a - b)), 2), 'dL': round(float(a[0] - b[0]), 2),
            'dC': round(float(math.hypot(a[1], a[2]) - math.hypot(b[1], b[2])), 2)}


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


def measure_item(it: dict, R: dict) -> dict:
    """Одна вещь: полосы поверхностей на фото против цвета поверхностей модели."""
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
        d['flag'] = bool(d['dE'] >= R['flags']['dE'])
        out['surfaces'][name] = d

    back_ref = vis_side if strip[vis_side].get('photo_lab') is not None else None
    fill(1, None, '')
    fill(vis_side, None, '')
    fill(5 - vis_side, vis_side, 'бок')
    fill(0, None, '')
    fill(4, back_ref, R['back_ref'])
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
    copy_s: dict = {'measured': 0, 'flagged': [], 'by_surface': {}}
    unm: dict = {}
    for sid, v in res.items():
        for name, d in v.get('surfaces', {}).items():
            if d['ref'] != 'сама':
                copy_s['measured'] += 1
                copy_s['by_surface'][name] = copy_s['by_surface'].get(name, 0) + 1
                if d['flag']:
                    copy_s['flagged'].append(f'{sid}:{name}')
                continue
            e = by_s.setdefault(name, {'measured': 0, 'flagged': [], 'dE': []})
            e['measured'] += 1
            e['dE'].append(d['dE'])
            if d['flag']:
                e['flagged'].append(sid)
        for u in v.get('unmeasured', []):
            unm.setdefault(u['what'], []).append(sid)
    for name, e in by_s.items():
        e['dE_median'] = round(float(np.median(e['dE'])), 2)
        e['dE_p90'] = round(float(np.quantile(e['dE'], 0.9)), 2)
        e['n_flagged'] = len(e['flagged'])
        del e['dE']
    copy_s['n_flagged'] = len(copy_s['flagged'])
    return {'items': len(res), 'by_surface': by_s, 'copy_of_side': copy_s, 'unmeasured_by_surface': {k: len(v) for k, v in sorted(unm.items())},
            'unmeasured_ids': {k: v for k, v in sorted(unm.items())}, 'flag_dE': R['flags']['dE']}


def spread(a: dict, b: dict) -> dict:
    """Разброс двух прогонов тех же входов: макс. |разность| ΔE по поверхностям (шум самой мерки)."""
    mx, per = 0.0, {}
    for sid in sorted(set(a) & set(b)):
        sa, sb = a[sid].get('surfaces', {}), b[sid].get('surfaces', {})
        row = {n: round(abs(sa[n]['dE'] - sb[n]['dE']), 3) for n in sa if n in sb}
        if row:
            per[sid] = row
            mx = max(mx, max(row.values()))
    return {'max_dE': round(mx, 3), 'per_item': per}


def table_md(res: dict, R: dict, sp: dict | None = None) -> str:
    """Таблица товар × поверхности: «ΔE (px полосы)», ⚑ — ΔE ≥ порога; «= бок (копия)» — своей полосы нет, поверхность сравнена с полосой бока: не отдельная мерка, в ⚑ свода не входит; «—» с причиной — не измерено."""
    cols = R['table_surfaces']
    lines = ['| товар | тип | IoU | ' + ' | '.join(cols) + ' | бок-2 (скрытый) | не измерено |', '|' + '---|' * (len(cols) + 4)]
    for sid, v in res.items():
        def cell(name: str) -> str:
            d = v.get('surfaces', {}).get(name)
            if not d:
                return '—'
            return f"{d['dE']:.1f} ({d['n_strip']})" + (' ⚑' if d['flag'] else '') if d['ref'] == 'сама' else f"= {d['ref']} (копия)"
        un = '; '.join(f"{u['what']}: {u['reason'][:60]}" for u in v.get('unmeasured', []))
        iou = (v.get('registration') or {}).get('iou')
        lines.append(f"| …{sid[-8:]} | {v.get('type') or '?'} | {iou if iou is not None else '—'} | " + ' | '.join(cell(c) for c in cols) + f' | {cell("бок-2")} | {un} |')
    sm = summary(res, R)
    lines += ['', '| поверхность | измерено | ΔE мед. | ΔE p90 | ⚑ |', '|---|---|---|---|---|']
    for name in R['surfaces']:
        e = sm['by_surface'].get(name)
        if e:
            lines.append(f"| {name} | {e['measured']} | {e['dE_median']} | {e['dE_p90']} | {e['n_flagged']} |")
    c = sm['copy_of_side']
    lines.append(f"| копия бока (зад, бок-2 без своей полосы) | {c['measured']} | — | — | {c['n_flagged']} (не отдельные) |")
    if sp:
        lines += ['', f"Разброс повтора: макс. |разность| ΔE двух прогонов = {sp['max_dE']}."]
    return '\n'.join(lines)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('batch')
    b.add_argument('--items', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--only', default='')
    b.add_argument('--repeat', type=int, default=1, help='сколько раз прогнать те же входы (2 — разброс повтора)')
    a = ap.parse_args(argv)
    R = load_rules()
    items = json.load(open(a.items, encoding='utf-8'))
    only = {x for x in a.only.split(',') if x}
    if only:
        items = [x for x in items if x['id'] in only]
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
