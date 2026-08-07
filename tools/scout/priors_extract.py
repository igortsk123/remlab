#!/usr/bin/env python3
"""Извлечение дизайнерских priors из датасетов планировок (план layout-priors-from-datasets).

Не обучение: полные ГИСТОГРАММЫ (бины 10 см / 15°) в разрезах room_type × форма комнаты ×
источник. Источники: InstructScene (npz, с полигонами пола) и M3DLayout (json, без границ —
только парные метрики). Родословную не смешиваем: 3dfront-производные, matterport (сканы) и
infinigen (процедурный) агрегируются раздельно.

  ~/venvs/scout/bin/python priors_extract.py            # извлечь всё → priors/ + публикация
  ~/venvs/scout/bin/python priors_extract.py --limit 200  # проба
Выход: ~/scout-scenes/priors/layout-priors.json + index.html (публикуется в /test/priors/).
"""
import glob
import json
import math
import os
import subprocess
import sys

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.affinity import rotate as shp_rotate, translate as shp_translate
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
DS = os.path.expanduser('~/datasets')
OUT = os.path.expanduser('~/scout-scenes/priors')
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0

# датасет-категория → наша роль (только то, что учит наши правила)
CAT = {
    'l_shaped_sofa': 'диван_углов', 'multi_seat_sofa': 'диван', 'loveseat_sofa': 'диван',
    'chaise_longue_sofa': 'диван', 'lazy_sofa': 'кресло', 'armchair': 'кресло',
    'lounge_chair': 'кресло', 'coffee_table': 'столик', 'tv_stand': 'тв-тумба',
    'bookshelf': 'стеллаж', 'shelf': 'стеллаж', 'cabinet': 'комод', 'console_table': 'консоль',
    'corner_side_table': 'приставной', 'dining_table': 'стол обеденный', 'dining_chair': 'стул',
    'chinese_chair': 'стул', 'stool': 'пуф', 'ceiling_lamp': 'люстра', 'pendant_lamp': 'люстра',
    'wine_cabinet': 'витрина', 'desk': 'стол', 'round_end_table': 'приставной',
    # спальня — на будущее (Э8/спальный трек)
    'double_bed': 'кровать', 'kids_bed': 'кровать', 'single_bed': 'кровать',
    'nightstand': 'тумбочка', 'wardrobe': 'шкаф', 'dressing_table': 'туалетный стол',
    'dressing_chair': 'стул', 'tv стенд': 'тв-тумба',
}
PAIRS = [('диван', 'столик'), ('диван', 'тв-тумба'), ('диван', 'кресло'),
         ('столик', 'пуф'), ('стол обеденный', 'стул'), ('кровать', 'тумбочка'),
         ('диван', 'ковёр'), ('кресло', 'столик')]
LAMPS = {'люстра'}
DBIN, ABIN, DMAX = 10, 15, 500          # см / градусы / потолок дистанций


def hist_add(h: dict, key: str, val: float, step: float, vmax: float) -> None:
    if val is None or not np.isfinite(val):
        return
    b = int(min(max(val, 0), vmax) // step)
    d = h.setdefault(key, {})
    d[b] = d.get(b, 0) + 1


def fp(cx, cz, hw, hd, yaw) -> Polygon:
    """Футпринт: бокс полугабаритов, повёрнутый на yaw вокруг центра (всё в см)."""
    b = box(cx - hw, cz - hd, cx + hw, cz + hd)
    return shp_rotate(b, -math.degrees(yaw), origin=(cx, cz))


def room_shape(poly: Polygon) -> str:
    """rect / L / complex — по упрощённому контуру и заполнению bbox."""
    area = poly.area
    bx = poly.bounds
    bbox_a = (bx[2] - bx[0]) * (bx[3] - bx[1])
    ratio = area / max(bbox_a, 1e-6)
    nv = len(poly.simplify(8).exterior.coords) - 1
    if ratio >= 0.95 and nv <= 6:
        return 'rect'
    if ratio >= 0.60 and nv <= 9:
        return 'L'
    return 'complex'


def scene_metrics(objs: list[dict], poly: Polygon | None, ctx: str, H: dict) -> None:
    """objs: [{role, x, z, hw, hd, hh, yaw, cat}], всё в см. ctx = 'room|shape|source'."""
    by_role: dict[str, list] = {}
    for o in objs:
        o['fp'] = fp(o['x'], o['z'], o['hw'], o['hd'], o['yaw'])
        by_role.setdefault(o['role'], []).append(o)

    def one(role):
        lst = by_role.get(role) or by_role.get(role + '_углов') or []
        return lst[0] if lst else None

    sofa = one('диван')
    sofa_depth = 2 * sofa['hd'] if sofa else None
    if poly is not None:
        ring = poly.exterior
        for o in objs:
            if o['role'] in LAMPS:
                continue
            fx, fz = math.sin(o['yaw']), math.cos(o['yaw'])   # y-up: yaw против часовой от +z
            back = Point(o['x'] - fx * o['hd'], o['z'] - fz * o['hd'])
            d = ring.distance(back)
            hist_add(H, f'wall_gap|{o["role"]}|{ctx}', d, DBIN, DMAX)
            # ориентация спинки к ближайшему ребру (важно для косых стен, Э8)
            t = ring.project(back)
            p1, p2 = ring.interpolate(max(t - 30, 0)), ring.interpolate(t + 30)
            edge_ang = math.degrees(math.atan2(p2.x - p1.x, p2.y - p1.y))
            rel = abs((math.degrees(o['yaw']) - edge_ang + 90) % 180 - 90)
            if d < 80:
                hist_add(H, f'wall_align|{o["role"]}|{ctx}', rel, ABIN, 90)
        corner = (by_role.get('диван_углов') or [None])[0]
        if corner is not None:
            c = corner['fp']
            dists = sorted(Point(v).distance(c) for v in
                           {(poly.bounds[0], poly.bounds[1]), (poly.bounds[0], poly.bounds[3]),
                            (poly.bounds[2], poly.bounds[1]), (poly.bounds[2], poly.bounds[3])})
            hist_add(H, f'corner_sofa_corner_dist|{ctx}', dists[0], DBIN, DMAX)
        if sofa is not None:
            fx, fz = math.sin(sofa['yaw']), math.cos(sofa['yaw'])
            ray = LineString([(sofa['x'] + fx * sofa['hd'], sofa['z'] + fz * sofa['hd']),
                              (sofa['x'] + fx * (sofa['hd'] + 600),
                               sofa['z'] + fz * (sofa['hd'] + 600))])
            hits = [ray.intersection(o2['fp']) for o2 in objs
                    if o2 is not sofa and o2['role'] not in LAMPS]
            hits = [h.distance(Point(ray.coords[0])) for h in hits if not h.is_empty]
            wall_hit = ray.intersection(poly.exterior)
            if not wall_hit.is_empty:
                hits.append(wall_hit.distance(Point(ray.coords[0])))
            if hits:
                hist_add(H, f'sofa_front_clear|{ctx}', min(hits), DBIN, DMAX)
    for ra, rb in PAIRS:
        a, b = one(ra), one(rb)
        if a is None or b is None:
            continue
        g = a['fp'].distance(b['fp'])
        hist_add(H, f'gap|{ra}~{rb}|{ctx}', g, DBIN, DMAX)
        if sofa_depth:
            hist_add(H, f'gapn|{ra}~{rb}|{ctx}', 100 * g / sofa_depth, 10, 300)
        rel = abs((math.degrees(a['yaw'] - b['yaw']) + 180) % 360 - 180)
        hist_add(H, f'ang|{ra}~{rb}|{ctx}', rel, ABIN, 180)
    # симметрия: две тумбочки/два кресла у якоря
    for role, anchor_role in (('тумбочка', 'кровать'), ('кресло', 'диван')):
        pair = by_role.get(role) or []
        anchor = one(anchor_role)
        if len(pair) >= 2 and anchor is not None:
            d1 = anchor['fp'].distance(pair[0]['fp'])
            d2 = anchor['fp'].distance(pair[1]['fp'])
            hist_add(H, f'sym|{role}@{anchor_role}|{ctx}', abs(d1 - d2), DBIN, 200)


def load_instructscene(H: dict, counts: dict) -> None:
    base = os.path.join(DS, 'instructscene', 'InstructScene')
    for room in ('livingroom', 'diningroom', 'bedroom'):
        stats = json.load(open(os.path.join(base, f'threed_front_{room}', 'dataset_stats.txt')))
        labels = stats['class_labels']
        scenes = sorted(glob.glob(os.path.join(base, f'threed_front_{room}', '*', 'boxes.npz')))
        if LIMIT:
            scenes = scenes[:LIMIT]
        for i, p in enumerate(scenes):
            try:
                z = np.load(p)
                v = z['floor_plan_vertices'][:, [0, 2]] * 100
                poly = unary_union([Polygon(v[t]) for t in z['floor_plan_faces']]).buffer(0)
                if poly.geom_type != 'Polygon' or poly.area < 4 * 10_000:
                    continue
                objs = []
                for cl, tr, sz, an in zip(z['class_labels'], z['translations'],
                                          z['sizes'], z['angles']):
                    cat = labels[int(cl.argmax())]
                    role = CAT.get(cat)
                    if not role:
                        continue
                    objs.append(dict(role=role, cat=cat, x=tr[0] * 100, z=tr[2] * 100,
                                     hw=sz[0] * 100, hd=sz[2] * 100, hh=sz[1] * 100,
                                     yaw=float(an[0])))
                if not objs:
                    continue
                shape = room_shape(poly)
                ctx = f'{room}|{shape}|3dfront'
                scene_metrics(objs, poly, ctx, H)
                counts[ctx] = counts.get(ctx, 0) + 1
                hist_add(H, f'room_area|{room}|{shape}', poly.area / 10_000, 2, 80)
            except Exception as e:  # noqa: BLE001 — счётчик, не молчание
                counts['err_is'] = counts.get('err_is', 0) + 1
                if counts['err_is'] <= 3:
                    print(f'  instructscene {p.split("/")[-2][:20]}: {str(e)[:80]}')
            if i and i % 1000 == 0:
                print(f'  {room}: {i}/{len(scenes)}', flush=True)


def load_m3d(H: dict, counts: dict) -> None:
    for p in sorted(glob.glob(os.path.join(DS, 'm3dlayout', 'M3DLayout_json', '*.json'))):
        name = os.path.basename(p).lower()
        source = ('3dfront-m3d' if '3dfront' in name or 'front' in name else
                  'mp3d' if 'mp3d' in name or 'matterport' in name else
                  'infinigen' if 'infinigen' in name else 'm3d-' + name.split('.')[0][:12])
        data = json.load(open(p))
        scenes = data if isinstance(data, list) else data.get('scenes') or list(data.values())
        if LIMIT:
            scenes = scenes[:LIMIT]
        for i, s in enumerate(scenes):
            try:
                objs = []
                for o in (s.get('objects') or []):
                    role = CAT.get(str(o.get('category', '')).lower().replace(' ', '_'))
                    if not role:
                        continue
                    loc, sz = o['location'], o['size']
                    objs.append(dict(role=role, cat=o['category'], x=loc[0] * 100,
                                     z=loc[2] * 100, hw=sz[0] * 100, hd=sz[2] * 100,
                                     hh=sz[1] * 100, yaw=float(o.get('rotation', 0))))
                if len(objs) < 2:
                    continue
                ctx = f'any|nopoly|{source}'
                scene_metrics(objs, None, ctx, H)   # без полигона: только парные метрики
                counts[ctx] = counts.get(ctx, 0) + 1
            except Exception:  # noqa: BLE001
                counts['err_m3d'] = counts.get('err_m3d', 0) + 1
            if i and i % 3000 == 0:
                print(f'  {source}: {i}/{len(scenes)}', flush=True)


def quantiles(h: dict, step: float) -> dict:
    total = sum(h.values())
    acc, out = 0, {}
    for b in sorted(h, key=int):
        acc += h[b]
        for q in (10, 50, 90):
            if f'p{q}' not in out and acc >= total * q / 100:
                out[f'p{q}'] = round((int(b) + 0.5) * step)
    out['n'] = total
    return out


CANON = [('диван↔ТВ (наша шкала 180–300, потолок 400)', 'gap|диван~тв-тумба|livingroom'),
         ('диван↔столик (36–50)', 'gap|диван~столик|livingroom'),
         ('столик↔пуф (≤60)', 'gap|столик~пуф|livingroom'),
         ('диван↔кресло (зона ≤200)', 'gap|диван~кресло|livingroom'),
         ('щель за спинкой: <20 или ≥76', 'wall_gap|диван|livingroom'),
         ('проход перед диваном', 'sofa_front_clear|livingroom')]


def report(H: dict, counts: dict) -> None:
    os.makedirs(OUT, exist_ok=True)
    agg = {k: {'hist': {str(b): c for b, c in v.items()},
               'q': quantiles(v, ABIN if k.startswith(('ang', 'wall_align')) else DBIN)}
           for k, v in H.items()}
    json.dump({'counts': counts, 'metrics': agg},
              open(os.path.join(OUT, 'layout-priors.json'), 'w'), ensure_ascii=False)

    def block(title, keys):
        rows = []
        for k in sorted(keys):
            q = agg[k]['q']
            hist = agg[k]['hist']
            step = ABIN if k.startswith(('ang', 'wall_align')) else DBIN
            mx = max(hist.values())
            bars = ''.join(
                f'<div class="b" style="height:{max(2, 46 * c // mx)}px" title="{int(b) * step}–{(int(b) + 1) * step}: {c}"></div>'
                for b, c in sorted(hist.items(), key=lambda kv: int(kv[0])))
            rows.append(f'<tr><td>{k}</td><td>{q.get("p10", "—")}</td><td><b>{q.get("p50", "—")}</b></td>'
                        f'<td>{q.get("p90", "—")}</td><td>{q["n"]}</td><td><div class="h">{bars}</div></td></tr>')
        return (f'<h2>{title}</h2><table><tr><th>метрика | разрез</th><th>p10</th><th>p50</th>'
                f'<th>p90</th><th>n</th><th>распределение</th></tr>{"".join(rows)}</table>')

    canon_rows = []
    for label, prefix in CANON:
        ks = [k for k in agg if k.startswith(prefix.split('|')[0]) and prefix.split('|')[1] in k
              and '3dfront' in k]
        if not ks:
            continue
        merged: dict = {}
        for k in ks:
            for b, c in agg[k]['hist'].items():
                merged[b] = merged.get(b, 0) + c
        q = quantiles({int(b): c for b, c in merged.items()}, DBIN)
        canon_rows.append(f'<tr><td>{label}</td><td>{q.get("p10")}</td><td><b>{q.get("p50")}</b>'
                          f'</td><td>{q.get("p90")}</td><td>{q["n"]}</td></tr>')
    groups = {
        'Сверка с каноном (дизайнерские 3D-FRONT гостиные, см)': None,
        'Пары: зазоры (см)': [k for k in agg if k.startswith('gap|')],
        'Пары: зазоры, % глубины дивана': [k for k in agg if k.startswith('gapn|')],
        'Пары: взаимные углы (°)': [k for k in agg if k.startswith('ang|')],
        'До стены: зазор спинки (см)': [k for k in agg if k.startswith('wall_gap|')],
        'До стены: ориентация к ребру (°, у стоящих ≤80 см)': [k for k in agg if k.startswith('wall_align|')],
        'Г-диван: до ближайшего угла (см)': [k for k in agg if k.startswith('corner_sofa')],
        'Проход перед диваном (см)': [k for k in agg if k.startswith('sofa_front_clear')],
        'Симметрия пар у якоря (|d1−d2|, см)': [k for k in agg if k.startswith('sym|')],
        'Площади комнат (м², бин 2)': [k for k in agg if k.startswith('room_area|')],
    }
    body = (f'<table><tr><th>наш канон</th><th>p10</th><th>p50</th><th>p90</th><th>n</th></tr>'
            f'{"".join(canon_rows)}</table>')
    for title, keys in groups.items():
        if keys:
            body += block(title, keys)
    n_sc = sum(v for k, v in counts.items() if not k.startswith('err'))
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Priors из датасетов планировок</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}}
table{{border-collapse:collapse;margin:8px 0 20px;background:#fff}}
td,th{{border:1px solid #ddd;padding:3px 8px;font-size:13px;text-align:left}}
.h{{display:flex;align-items:flex-end;gap:1px;height:48px;min-width:220px}}
.b{{width:4px;background:#4a7dbd}}
</style></head><body>
<h1>Дизайнерские priors — {n_sc} сцен (2026-08-07)</h1>
<p>Разрез метрик: тип комнаты | форма (rect/L/complex) | источник. Родословные раздельно:
3dfront (дизайнеры), mp3d (сканы), infinigen (процедурный — в правила не мешать).
Сверка с каноном: канон владельца по умолчанию выигрывает.</p>
<p>Обработано: {json.dumps({k: v for k, v in sorted(counts.items())}, ensure_ascii=False)}</p>
{body}</body></html>"""
    open(os.path.join(OUT, 'index.html'), 'w').write(html)
    print(f'{OUT}/index.html; сцен {n_sc}')
    if LIMIT:
        print('проба (--limit) — не публикуем')
        return
    r = subprocess.run(['rsync', '-a', '--delete', '-e', 'ssh -o ConnectTimeout=15',
                        OUT + '/', 'root@89.167.127.0:/opt/remlab/test/priors/'],
                       capture_output=True, text=True)
    print('опубликовано: https://remont-lab.online/test/priors/' if r.returncode == 0
          else f'ПУБЛИКАЦИЯ НЕ ПРОШЛА: {r.stderr[:200]}')


def main() -> None:
    H: dict = {}
    counts: dict = {}
    load_instructscene(H, counts)
    load_m3d(H, counts)
    report(H, counts)


if __name__ == '__main__':
    main()
