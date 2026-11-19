#!/usr/bin/env python3
"""Только чтение: правило G (`mesh_clean.floor_plate`, «коврик под ножками») по ВСЕМ GLB папки модели ПОВЕРХ E+F — сколько граней и площади снимает и почему (кандидаты ①② с причиной).
  python3 floor_plate_scan.py <папка модели> [--out файл.json]"""
import glob
import json
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_clean as MC
from slab_probe import load

d = sys.argv[1]
rows = []
for p in sorted(glob.glob(os.path.join(d, '*-1024-42-0.glb'))):
    if '.clean' in p or '.audit' in p or p.endswith('.ai.glb'):
        continue
    k = os.path.basename(p).split('-')[0]
    parts, v, f = load(p)
    _, keepA = MC.analyse(trimesh.Trimesh(v, f, process=False))
    info: dict = {}
    rem_ef = MC.slab_rule_e(v, f, ~keepA, use_f=True)
    g, gi = MC.floor_plate(v, f, rem_ef)
    rows.append({'sku': k.replace('_', ':', 1), 'g_tris': int(g.sum()), 'g_area_share': gi['removed_area_share'], 'refused': gi['refused'], 'candidates': gi['candidates'][:8]})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
if out:
    json.dump(rows, open(out, 'w'), ensure_ascii=False, indent=1)
