#!/usr/bin/env python3
"""По ВСЕМ GLB папки модели: что старое правило A срезает, а вариант D (куски A только если выступают из-под предмета + B) оставляет = основания/ножки, которые A сносил зря.
  python3 slab_scan.py <папка модели> <set30.json> [--out файл.json]"""
import glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_clean as MC
from slab_probe import load

d, setp = sys.argv[1], sys.argv[2]
S = {c['sku'].replace(':', '_'): c for c in json.load(open(setp, encoding='utf-8'))}
rows = []
for p in sorted(glob.glob(os.path.join(d, '*-1024-42-0.glb'))):
    if p.endswith(('.clean.glb', '.audit.glb', '.ai.glb')):
        continue
    k = os.path.basename(p).split('-')[0]
    parts, v, f = load(p)
    import trimesh
    area = MC.tri_areas(v, f)
    _, keepA = MC.analyse(trimesh.Trimesh(v, f, process=False))
    remA = ~keepA
    slab, _ = MC.slab_faces(v, f)
    remD = MC.slab_pieces(v, f, remA) | slab
    lost = remA & ~remD                                  # A срезает, D оставляет
    rows.append({'sku': k.replace('_', ':', 1), 'role': S.get(k, {}).get('role'), 'A_area_share': round(float(area[remA].sum() / area.sum()), 3), 'D_area_share': round(float(area[remD].sum() / area.sum()), 3),
                 'A_cut_D_keep_tris': int(lost.sum()), 'A_cut_D_keep_area_share': round(float(area[lost].sum() / area.sum()), 4)})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
if out:
    json.dump(rows, open(out, 'w'), ensure_ascii=False, indent=1)
