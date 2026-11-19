#!/usr/bin/env python3
"""Только чтение: правило F (`mesh_clean.floaters`, отлетевшие мелкие осколки) по ВСЕМ GLB папки модели — сколько кусков и какую долю площади оно убирает ПОВЕРХ правила E (до F → после F).
  python3 floaters_scan.py <папка модели> [--out файл.json]"""
import glob
import json
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_clean as MC
from slab_probe import load


def pieces(v, f, removed):
    idx = np.nonzero(~removed)[0]
    return int(len(np.unique(MC.label_components(f[idx], len(v))))) if len(idx) else 0


d = sys.argv[1]
rows = []
for p in sorted(glob.glob(os.path.join(d, '*-1024-42-0.glb'))):
    if p.endswith(('.clean.glb', '.audit.glb', '.ai.glb')) or '.clean' in p or '.audit' in p:
        continue
    k = os.path.basename(p).split('-')[0]
    parts, v, f = load(p)
    area = MC.tri_areas(v, f)
    _, keepA = MC.analyse(trimesh.Trimesh(v, f, process=False))
    slab, _ = MC.slab_faces(v, f)
    rem = MC.slab_pieces(v, f, ~keepA) | slab
    if float(area[rem].sum() / area.sum()) >= 0.10:
        rem = rem | MC.slab_dust(v, f, rem)
    fl = MC.floaters(v, f, rem)
    fl0 = MC.floaters(v, f, rem, floor_band=-1e9)          # F без условия «под телом» (подножие)
    rows.append({'sku': k.replace('_', ':', 1), 'pieces_E': pieces(v, f, rem), 'pieces_EF': pieces(v, f, rem | fl), 'tris_F': int(fl.sum()), 'tris_F_no_floor': int(fl0.sum()), 'tris_floor': int((fl & ~fl0).sum()), 'area_floor': round(float(area[fl & ~fl0].sum() / area.sum()), 5), 'area_share_F': round(float(area[fl].sum() / area.sum()), 4)})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
if out:
    json.dump(rows, open(out, 'w'), ensure_ascii=False, indent=1)
